"""亞洲比重：候選注入、地區名額，以及它們不該越過的那條線。

這一整組機制存在的理由只有一個數字：ReccoBeats 推薦端點回來的候選裡，
亞洲發行只佔 3.9%（實測 179 首中 7 首，NOTES #46）。排序改不動這件事——
池子裡沒有的東西，排序排不出來。
"""
from __future__ import annotations

import json

import pytest

from app.config import get_settings
from app.core import pipeline, ranker, regions
from app.core.ranker import region_quota, similarity
from app.models import Constraints, Score
from app.services import seed_pool
from app.services.prompts import vibe_system


# --- 地區判定 -----------------------------------------------------------------

def test_isrc_prefix_decides_the_region():
    """ISRC 前兩碼是發行登記國，是候選池裡唯一現成的地區訊號。"""
    assert regions.is_asia({"isrc": "TWA472500001"})
    assert regions.is_asia({"isrc": "jpb123456789"})      # 大小寫不該影響判定
    assert not regions.is_asia({"isrc": "USUM71703861"})


def test_no_isrc_means_no_claim_not_west():
    """沒有 ISRC 是「沒有證據」，不是「歐美」——空字串才誠實。"""
    assert regions.region_of({}) == ""
    assert not regions.is_asia({"isrc": ""})


def test_our_own_tag_beats_the_isrc():
    """自己補進來的候選帶著 region。那是我們的主張，比發行國準：
    落日飛車掛國際廠牌時 ISRC 是 QZ，照 ISRC 判會把它算成不是亞洲。"""
    assert regions.is_asia({"region": "asia", "isrc": "QZABC2500001"})


# --- 種子池 -------------------------------------------------------------------

def test_pool_covers_both_regions_without_duplicates():
    """重複的名字會讓同一位歌手多佔一個位子，白白壓掉別的角落。"""
    names = seed_pool.artists()
    assert len(names) == len({name.lower() for name in names})
    assert len(seed_pool.artists(seed_pool.ASIA)) >= 30
    assert len(seed_pool.artists(seed_pool.WEST)) >= 30


def test_artists_alternate_between_regions():
    """沒有預解析檔時只會即時解析前幾位。照區塊排的話那幾位全是同一區，
    備援就又變回一面倒——交錯是為了讓「前 8 位」本身就是混的。"""
    head = seed_pool.artists()[:8]
    assert sum(1 for name in head if seed_pool.region_of(name) == seed_pool.ASIA) == 4


def _rows(count: int, region: str, energy=0.5):
    return [{"recco_id": f"{region}-{i}", "artist": f"{region}{i}", "title": "T",
             "region": region, "features": {"energy": energy, "valence": 0.5, "tempo": 100}}
            for i in range(count)]


def test_pick_fills_the_asia_quota_first():
    """asia_min 是下限：先把亞洲的位子填滿，剩下的照相似度全區搶。"""
    pool = _rows(10, seed_pool.ASIA) + _rows(10, seed_pool.WEST)
    picked = seed_pool.pick(pool, {"energy": 0.5}, similarity, limit=5, asia_min=3)
    assert len(picked) == 5
    assert sum(1 for row in picked if row["region"] == seed_pool.ASIA) >= 3
    assert len({row["recco_id"] for row in picked}) == 5      # 不重複挑同一首


def test_pick_does_not_invent_asia_rows_it_does_not_have():
    """亞洲那一區湊不滿就湊多少算多少，不會為了配額去挑不貼近的歌。"""
    picked = seed_pool.pick(_rows(6, seed_pool.WEST), {"energy": 0.5}, similarity,
                            limit=5, asia_min=3)
    assert len(picked) == 5
    assert all(row["region"] == seed_pool.WEST for row in picked)


def test_draw_aims_at_the_band_centre_not_at_the_closest():
    """Discovery Score 的主項是探索帶：相似度落在帶心附近得分最高，太像一樣被扣分。
    照「最像」抽出來的候選會全部擠在帶外，補了也排不上（實測補 15 首、前五名 0 首）。"""
    # energy 0.5 的目標下，這幾列的相似度由高到低是 0.5、0.6、0.75、0.95
    pool = (_rows(1, seed_pool.ASIA, energy=0.50) + _rows(1, seed_pool.ASIA, energy=0.60)
            + _rows(1, seed_pool.ASIA, energy=0.75) + _rows(1, seed_pool.ASIA, energy=0.95))
    for row, tag in zip(pool, "abcd"):
        row["recco_id"] = tag
    target = {"energy": 0.5, "valence": 0.5, "tempo": 100}
    sims = {row["recco_id"]: similarity(target, row["features"]) for row in pool}
    wanted = min(sims, key=lambda key: abs(sims[key] - 0.72))

    picked = seed_pool.draw(pool, target, similarity, want=1, center=0.72, shortlist_factor=1)
    assert picked[0]["recco_id"] == wanted
    # 不給 center 時退回「最像優先」，那是種子挑選在用的
    assert seed_pool.draw(pool, target, similarity, want=1,
                          center=None, shortlist_factor=1)[0]["recco_id"] == "a"


def test_load_backfills_region_from_the_artist_name(tmp_path):
    """舊版檔案沒有 region。回推得到就補上，回推不到就留空——
    空的一律當作不是亞洲，寧可少湊一首也不要把不確定的講成確定的。"""
    path = tmp_path / "seeds.json"
    path.write_text(json.dumps({"seeds": [
        {"recco_id": "a", "artist": "YOASOBI", "title": "T", "features": {"energy": 0.5}},
        {"recco_id": "b", "artist": "查無此人", "title": "T", "features": {"energy": 0.5}},
    ]}), encoding="utf-8")
    rows = {row["recco_id"]: row["region"] for row in seed_pool.load(str(path))}
    assert rows == {"a": seed_pool.ASIA, "b": ""}


# --- 名額 ---------------------------------------------------------------------

def _scored(tag: str, final: float, *, asia: bool, energy: float = 0.3):
    return {"recco_id": tag, "artist": tag, "title": tag,
            "region": seed_pool.ASIA if asia else "",
            "features": {"energy": energy},
            "score": Score(similarity=0.7, band=0.9, context_fit=1.0, novelty=0.5, final=final)}


def test_quota_pulls_asia_into_the_returned_five():
    """補進來的歌一首都擠不進前五的話，補了等於沒補。"""
    ranked = ([_scored(f"w{i}", 0.9 - i / 100, asia=False) for i in range(5)]
              + [_scored("a1", 0.5, asia=True), _scored("a2", 0.4, asia=True)])
    out, have = region_quota(ranked, Constraints(), regions.is_asia, 2, 3, 5)
    assert have == 2
    assert sum(1 for c in out[:5] if regions.is_asia(c)) == 2
    # 讓位的是分數最低的那兩首，不是隨便挑的
    assert {c["recco_id"] for c in out[5:]} == {"w3", "w4"}


def test_quota_caps_the_share_as_well():
    """使用者要的是「多一點」，不是「幾乎全部」。只有下限的機制表達不出一個比例。"""
    ranked = ([_scored(f"a{i}", 0.9 - i / 100, asia=True) for i in range(5)]
              + [_scored("w1", 0.5, asia=False), _scored("w2", 0.3, asia=False)])
    out, have = region_quota(ranked, Constraints(), regions.is_asia, 2, 3, 5)
    assert have == 3
    # 補上來的是後段分數最高的那兩首，不是隨便挑的
    assert {c["recco_id"] for c in out[3:5]} == {"w1", "w2"}


def test_cap_does_the_best_it_can_when_there_is_nothing_to_swap_in():
    """後段沒有非亞洲的候選可換時，超額就超額——不會為了守上限把位子空著。"""
    ranked = [_scored(f"a{i}", 0.9 - i / 100, asia=True) for i in range(5)]
    _, have = region_quota(ranked, Constraints(), regions.is_asia, 2, 3, 5)
    assert have == 5


def test_quota_never_promotes_across_the_hard_filter():
    """§5.4 的分級優先於地區名額：使用者說了「不要太吵」，
    會炸出來的那首不會因為它是亞洲的就被拉到前面。"""
    quiet = Constraints(energy_max=0.4)
    ranked = ([_scored(f"w{i}", 0.9 - i / 100, asia=False, energy=0.2) for i in range(5)]
              + [_scored("loud", 0.8, asia=True, energy=0.95)])
    out, have = region_quota(ranked, quiet, regions.is_asia, 2, 3, 5)
    assert have == 0
    assert out[-1]["recco_id"] == "loud"


def test_quota_is_a_no_op_when_the_head_is_already_in_range():
    ranked = [_scored("a1", 0.9, asia=True), _scored("w1", 0.8, asia=False),
              _scored("a2", 0.7, asia=True), _scored("w2", 0.6, asia=False),
              _scored("w3", 0.5, asia=False)]
    out, have = region_quota(list(ranked), Constraints(), regions.is_asia, 2, 3, 5)
    assert have == 2
    assert [c["recco_id"] for c in out] == [c["recco_id"] for c in ranked]


def test_quota_switched_off_leaves_the_order_alone():
    ranked = [_scored(f"w{i}", 0.9 - i / 100, asia=False) for i in range(3)]
    out, have = region_quota(list(ranked), Constraints(), regions.is_asia, 0, -1, 5)
    assert have == 0 and [c["recco_id"] for c in out] == ["w0", "w1", "w2"]


# --- 接線 ---------------------------------------------------------------------

@pytest.fixture
def pool_file(monkeypatch, tmp_path):
    path = tmp_path / "vibe_seeds.json"
    path.write_text(json.dumps({"seeds": [
        {"recco_id": f"asia-{i}", "artist": f"亞洲歌手{i}", "title": f"曲{i}",
         "region": "asia", "features": {"energy": 0.3 + i / 50, "valence": 0.4, "tempo": 95}}
        for i in range(20)
    ] + [
        {"recco_id": "west-1", "artist": "Bon Iver", "title": "T",
         "region": "west", "features": {"energy": 0.3, "valence": 0.4, "tempo": 95}}
    ]}), encoding="utf-8")
    monkeypatch.setattr(seed_pool, "SEED_FILE", str(path))
    return path


async def test_injected_candidates_are_all_asian(monkeypatch, pool_file):
    monkeypatch.setenv("RECCOBEATS_MODE", "live")
    get_settings.cache_clear()
    rows = await pipeline._asia_candidates({"energy": 0.35, "valence": 0.4, "tempo": 95},
                                           5, 0.72, Constraints())
    assert len(rows) == 5
    assert all(regions.is_asia(row) for row in rows)
    assert all(row["features"] for row in rows), "沒有特徵就排不了序，補進去只是佔位"


async def test_stub_mode_injects_nothing(pool_file):
    """stub 曲庫的 id 是假的，補進去只會在驗證那一關全部落空。"""
    assert await pipeline._asia_candidates({"energy": 0.35}, 5, 0.72, Constraints()) == []


def test_merge_drops_songs_the_api_already_gave_us():
    base = [{"artist": "YOASOBI", "title": "Idol", "features": {"energy": 0.9}}]
    extra = [{"artist": "yoasobi", "title": "IDOL", "features": {"energy": 0.9}, "region": "asia"},
             {"artist": "Ado", "title": "うっせぇわ", "features": {"energy": 0.9}, "region": "asia"}]
    merged = pipeline._merge_candidates(base, extra)
    assert [c["title"] for c in merged] == ["Idol", "うっせぇわ"]


# --- 提示詞 -------------------------------------------------------------------

def test_vibe_prompt_asks_for_asian_seed_artists():
    text = vibe_system(3)
    assert "至少 3 位" in text and "亞洲" in text


def test_vibe_prompt_drops_the_rule_entirely_when_switched_off():
    """留一句「至少 0 位」在提示詞裡，模型會照著那句話去想地區，比沒寫更糟。"""
    text = vibe_system(0)
    assert "亞洲" not in text and "{ASIA_RULE}" not in text


async def test_injection_prefers_candidates_that_fit_the_context(monkeypatch, pool_file):
    """名額只在同一層裡對調，所以補進來的歌違反上下限就等於補了個位子在後段。
    抽的時候就要先看情境——實測沒做這件事時，補 12 首前五名只有 1 首亞洲。"""
    monkeypatch.setenv("RECCOBEATS_MODE", "live")
    get_settings.cache_clear()
    quiet = Constraints(energy_max=0.4)      # 池子裡 energy 0.30~0.68，合格的有 5 首
    rows = await pipeline._asia_candidates({"energy": 0.35, "valence": 0.4, "tempo": 95},
                                           5, 0.72, quiet)
    assert len(rows) == 5
    assert all(ranker.passes_hard_filter(quiet, row["features"]) for row in rows)


async def test_injection_still_fills_up_when_too_few_fit(monkeypatch, pool_file):
    """合格的湊不滿就拿不合格的補。候選多一點總比少一點好，
    而且下一輪向量移動之後它們可能就合格了。"""
    monkeypatch.setenv("RECCOBEATS_MODE", "live")
    get_settings.cache_clear()
    rows = await pipeline._asia_candidates({"energy": 0.35}, 12, 0.72,
                                           Constraints(energy_max=0.32))
    assert len(rows) == 12
    assert len({row["recco_id"] for row in rows}) == 12
