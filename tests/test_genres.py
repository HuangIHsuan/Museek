"""曲風這一軸：分類、相似度、排序、名額、回饋。

對照的問題是「數值差不多但曲風不一樣」——六個音訊維度分不出 citypop 與
soft rock，所以曲風是獨立的一軸。這裡要守住的性質有四條，少一條這個功能
就會用一種很安靜的方式失效：

  1. 使用者要的那一側**不補上位曲風**，否則「想聽 citypop」＝「想聽任何流行樂」；
  2. 候選那一側**要補上位曲風**，否則「想聽搖滾」對不上一首標成 shoegaze 的歌；
  3. 查不到曲風的候選**不受罰**，否則排序退化成「比誰查得到曲風」；
  4. 曲風名額與地區名額**不互相拆台**。
"""
from __future__ import annotations

import pytest

from app.core import genres, regions
from app.core.ranker import (
    apply_genre_feedback,
    rank,
    region_quota,
    score_candidate,
    tier_of,
)
from app.models import Constraints
from app.services import itunes

QUIET = {"energy": 0.3, "valence": 0.4, "danceability": 0.5,
         "acousticness": 0.6, "instrumentalness": 0.1, "tempo": 90}


def _candidate(name: str, *, tags=(), features=None, popularity=None, **extra):
    return {"recco_id": name, "artist": name, "title": f"{name} 的歌",
            "features": dict(features or QUIET), "genres": list(tags),
            "popularity": popularity, **extra}


# --- 分類與正規化 -----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (["R&B/Soul"], {"rnb", "soul"}),                       # iTunes US 商店
    (["R&B/靈魂樂"], {"rnb", "soul"}),                      # iTunes TW 商店，同一個概念
    (["Hip-Hop/Rap"], {"hip_hop"}),
    (["嘻哈/饒舌"], {"hip_hop"}),
    (["華語流行樂"], {"mandopop", "pop"}),
    (["另類音樂"], {"indie_rock", "rock"}),
    (["城市流行"], {"city_pop", "pop"}),                    # 使用者打的中文
    (["Worldwide"], set()),                                # 認不出來就是空的，不硬湊
])
def test_normalize_reads_every_source(raw, expected):
    assert genres.normalize(raw) == expected


def test_trap_is_not_matched_as_rap():
    """整詞比對：`trap` 裡面有 `rap`，子字串比對會錯得很安靜。"""
    assert genres.normalize(["trap"]) == {"trap", "hip_hop"}
    assert "hip_hop" in genres.normalize(["rap"])


def test_candidate_side_gets_the_whole_parent_chain():
    """一首 shoegaze 就是 indie rock、也就是 rock——三層都是事實。"""
    assert genres.normalize(["shoegaze"]) == {"shoegaze", "indie_rock", "rock"}


def test_wanted_side_never_expands_to_parents():
    """展開了的話，「想聽 citypop」會被任何一首泛泛的流行歌滿分命中。"""
    assert genres.coerce(["citypop"]) == ["city_pop"]
    assert genres.normalize(["citypop"], parents=False) == {"city_pop"}


# --- 相似度 -----------------------------------------------------------------

def test_affinity_is_not_binary():
    assert genres.affinity("rnb", "rnb") == 1.0
    assert genres.affinity("rnb", "neo_soul") == pytest.approx(0.85)
    assert genres.affinity("rnb", "metal") == 0.0


def test_asking_broad_matches_narrow_but_not_the_reverse():
    """「想聽搖滾」拿到 shoegaze 是命中；「想聽 citypop」拿到泛 pop 只是沾邊。"""
    assert genres.genre_fit({"rock": 1.0}, genres.normalize(["shoegaze"])) == 1.0
    assert genres.genre_fit({"city_pop": 1.0}, genres.normalize(["pop"])) == pytest.approx(0.4)


def test_genre_fit_takes_the_best_match_not_the_average():
    """說「citypop 或 R&B」時，一首漂亮的 citypop 就該滿分，不該因為它不是 R&B 被打對折。"""
    assert genres.genre_fit({"city_pop": 1.0, "rnb": 1.0}, ["city_pop"]) == 1.0


def test_genre_fit_is_none_when_either_side_is_empty():
    """None 是「無從判斷」，不是 0 分——兩者在 ranker 的處置完全不同。"""
    assert genres.genre_fit({}, ["city_pop"]) is None
    assert genres.genre_fit({"city_pop": 1.0}, []) is None


def test_profile_weights_scale_the_match():
    """歌單的主要曲風命中＝1.0，邊緣曲風按比重遞減。"""
    weights = genres.distribution([{"genres": ["rnb"]}, {"genres": ["rnb"]}, {"genres": ["jazz"]}])
    assert weights["rnb"] == 1.0 and weights["jazz"] == 0.5
    assert genres.genre_fit(weights, ["rnb"]) == 1.0
    assert genres.genre_fit(weights, ["jazz"]) == pytest.approx(0.5)


def test_blocked_does_not_spill_over_to_related_genres():
    """「不要嘻哈」把 lo-fi 一起排掉是過度解讀，候選池會安靜地少一大塊。"""
    assert genres.blocked(["hip_hop"], ["hip_hop"])
    assert not genres.blocked(["hip_hop"], genres.normalize(["lofi"]) - {"hip_hop"})
    # 「不要 trap」不該連整個嘻哈一起封掉
    assert not genres.blocked(["trap"], ["hip_hop"])


# --- 排序 -------------------------------------------------------------------

def test_untagged_candidates_are_not_punished():
    """這一條是整個設計的關鍵：沒有標籤 ≠ 曲風不合。

    把 None 當 0 分的話，iTunes 查不到的候選一律先扣掉 w_genre 那一截，
    排序會退化成「比誰有標籤」——而有沒有標籤跟好不好聽完全無關。
    """
    wanted = {"city_pop": 1.0}
    untagged = score_candidate(QUIET, _candidate("A"), Constraints(), wanted_genres=wanted)
    no_request = score_candidate(QUIET, _candidate("A"), Constraints())
    assert untagged.genre_fit is None
    assert untagged.final == no_request.final


def test_genre_moves_the_score_when_both_sides_are_known():
    wanted = {"city_pop": 1.0}
    hit = score_candidate(QUIET, _candidate("A", tags=["city_pop"]), Constraints(),
                          wanted_genres=wanted)
    miss = score_candidate(QUIET, _candidate("B", tags=["metal"]), Constraints(),
                           wanted_genres=wanted)
    assert hit.genre_fit == 1.0 and miss.genre_fit == 0.0
    assert hit.final > miss.final


def test_same_numbers_different_genre_now_separate():
    """症狀本身：兩首歌的六個數值一模一樣，只有曲風不同。"""
    wanted = {"city_pop": 1.0}
    same_features = dict(QUIET)
    city = score_candidate(QUIET, _candidate("A", tags=["city_pop"], features=same_features),
                           Constraints(), wanted_genres=wanted)
    soft = score_candidate(QUIET, _candidate("B", tags=["country"], features=same_features),
                           Constraints(), wanted_genres=wanted)
    assert city.similarity == soft.similarity      # 數值分不出來
    assert city.final > soft.final                 # 曲風分得出來


def test_avoided_genre_is_graded_down_not_dropped():
    """§5.4 的紀律是分級不是全丟——候選池太小時仍然要湊得滿。"""
    pool = [_candidate("hiphop", tags=["hip_hop"]), _candidate("folk", tags=["folk"])]
    ranked, _ = rank(pool, QUIET, Constraints(), avoid_genres=["hip_hop"])
    assert [c["artist"] for c in ranked] == ["folk", "hiphop"]
    assert not tier_of(Constraints(), pool[0], ["hip_hop"])


# --- 名額 -------------------------------------------------------------------

def _ranked(rows):
    scored = []
    for row in rows:
        row = dict(row)
        row["score"] = score_candidate(QUIET, row, Constraints())
        scored.append(row)
    return sorted(scored, key=lambda c: c["score"].final, reverse=True)


def test_genre_quota_pulls_a_match_into_the_head():
    head = [_candidate(f"w{i}", tags=["metal"], popularity=i) for i in range(5)]
    tail = [_candidate("city", tags=["city_pop"], popularity=99)]     # 分數最低
    ranked = _ranked(head) + _ranked(tail)

    def hits(candidate):
        return "city_pop" in candidate.get("genres", [])

    out, have = region_quota(ranked, Constraints(), hits, 1, -1, 5)
    assert have == 1
    assert any(hits(c) for c in out[:5])


def test_the_second_quota_does_not_undo_the_first():
    """曲風名額先跑、地區名額後跑；沒有 prefer_keep 的話後者會把前者擠出去。"""
    head = [_candidate(f"w{i}", tags=["metal"], popularity=i) for i in range(5)]
    tail = [_candidate("city", tags=["city_pop"], popularity=98),
            _candidate("asia", tags=["mandopop"], popularity=99, region=regions.ASIA)]
    ranked = _ranked(head) + _ranked(tail)

    def hits(candidate):
        return "city_pop" in candidate.get("genres", [])

    ranked, genre_have = region_quota(ranked, Constraints(), hits, 1, -1, 5)
    ranked, asia_have = region_quota(ranked, Constraints(), regions.is_asia, 1, -1, 5,
                                     prefer_keep=hits)
    assert genre_have == 1 and asia_have == 1
    # 兩個下限要同時成立，這才是「兩個名額都有作用」
    assert any(hits(c) for c in ranked[:5])
    assert any(regions.is_asia(c) for c in ranked[:5])


# --- 回饋 -------------------------------------------------------------------

def test_thumbs_up_raises_that_genre():
    weights = apply_genre_feedback({"rnb": 1.0}, ["city_pop"], "up")
    assert "city_pop" in weights
    after = apply_genre_feedback(weights, ["city_pop"], "up")
    assert after["city_pop"] >= weights["city_pop"]


def test_thumbs_down_can_remove_a_genre_entirely():
    weights = apply_genre_feedback({"metal": 0.1, "folk": 1.0}, ["metal"], "down")
    assert "metal" not in weights, "降到 0 以下還留著沒有意義"
    assert weights["folk"] == 1.0


def test_feedback_renormalises_to_one():
    weights = apply_genre_feedback({"rnb": 1.0, "jazz": 0.5}, ["jazz"], "up")
    assert max(weights.values()) == 1.0


# --- iTunes 這條資料線 -------------------------------------------------------

def _result(artist, genre, title="某首歌"):
    return {"artistName": artist, "trackName": title, "primaryGenreName": genre}


async def test_genres_come_only_from_verified_artist_matches(monkeypatch):
    """iTunes 的搜尋是模糊的：搜 Anri 會混進另一位同名歌手的龐克曲目。

    不驗證歌手名的話，標到的曲風會是**別人的**——那比沒有曲風更糟，
    因為它會被當成事實拿去排序、還會佔掉曲風名額。
    """
    async def fake_search(term, store):
        return [_result("Some Punk Band", "Punk"), _result("Anri", "J-Pop")]

    monkeypatch.setattr(itunes, "_search", fake_search)
    assert await itunes._genres_for_artist("Anri") == {"jpop", "pop"}


async def test_store_order_stops_at_the_first_hit(monkeypatch):
    """TW 商店同時收國際發行，多數歌手一趟就夠——不必每位都打兩趟。"""
    asked = []

    async def fake_search(term, store):
        asked.append(store)
        return [_result("deca joins", "獨立搖滾")]

    monkeypatch.setattr(itunes, "_search", fake_search)
    assert await itunes._genres_for_artist("deca joins") == {"indie_rock", "rock"}
    assert asked == ["TW"], "第一個商店就給得出曲風，不該再問下一個"


async def test_the_other_store_is_tried_when_the_first_has_nothing(monkeypatch):
    asked = []

    async def fake_search(term, store):
        asked.append(store)
        return [] if store == "TW" else [_result("SZA", "R&B/Soul")]

    monkeypatch.setattr(itunes, "_search", fake_search)
    assert await itunes._genres_for_artist("SZA") == {"rnb", "soul"}
    assert asked == ["TW", "US"]


async def test_each_artist_is_only_looked_up_once(monkeypatch):
    """一池候選裡同一位歌手有好幾首——曲風查歌手就是為了省下這些趟。"""
    calls = []

    async def fake_search(term, store):
        calls.append(term)
        return [_result("9m88", "當代 R&B")]

    monkeypatch.setattr(itunes, "_search", fake_search)
    rows = [_candidate("9m88"), _candidate("9m88"), _candidate("9m88")]
    for row in rows:
        row["artist"] = "9m88"

    assert await itunes.tag_candidates(rows) == 3
    assert calls == ["9m88"], "三首同一位歌手只該查一趟"
    assert rows[0]["genres"] == ["rnb"]


async def test_artists_without_a_genre_are_remembered_as_such(monkeypatch):
    """「查過、沒有曲風」也要記住，否則每一輪都會把同一位重問一次。"""
    calls = []

    async def fake_search(term, store):
        calls.append(store)
        return []

    monkeypatch.setattr(itunes, "_search", fake_search)
    await itunes.artist_genres(["Nobody"])
    await itunes.artist_genres(["Nobody"])
    assert len(calls) == len(itunes.get_settings().itunes_stores), "第二次不該再對外查"


async def test_lookup_budget_caps_outbound_requests(monkeypatch):
    """一輪 50 首全是新歌手時，沒有上限就是 50 趟循序請求掛在推薦流程上。

    寧可這一輪少幾首有曲風——查不到曲風的候選在排序時本來就不受罰。
    """
    async def fake_search(term, store):
        return [_result(term, "Pop")]

    monkeypatch.setattr(itunes, "_search", fake_search)
    rows = [_candidate(f"artist{i}") for i in range(10)]
    for i, row in enumerate(rows):
        row["artist"] = f"artist{i}"

    tagged = await itunes.tag_candidates(rows, limit=3)
    assert tagged == 3, "超過額度的那幾位這一輪就是沒有曲風"


# --- 品味輪廓只算最具體的那一層 --------------------------------------------

def test_profile_counts_only_the_most_specific_genre():
    """候選身上的上位曲風是我們自己補的，它是推論不是觀察。

    照單全收的話，一份清一色獨立搖滾的歌單會統計出 `{indie_rock: 1, rock: 1}`
    ——而 metal 的上位也是 rock，於是**一首 metal 拿到滿分命中**。
    這是「數值對但曲風不對」最後殘留的那一塊，實測抓到的。
    """
    playlist = [{"genres": ["indie_rock", "rock"]}] * 10
    assert genres.distribution(playlist) == {"indie_rock": 1.0}


def test_metal_is_no_longer_a_perfect_match_for_an_indie_listener():
    weights = genres.distribution([{"genres": ["indie_rock", "rock"]}] * 10)
    assert genres.genre_fit(weights, genres.normalize(["metal"])) == pytest.approx(0.4)
    # 但 shoegaze 仍然滿分——它**就是**獨立搖滾，不是隔壁的曲風
    assert genres.genre_fit(weights, genres.normalize(["shoegaze"])) == 1.0


def test_leaves_keeps_genres_that_are_not_related():
    """`R&B/Soul` 是兩件事都講了，不是一個蘊含另一個。"""
    assert genres.leaves({"rnb", "soul"}) == {"rnb", "soul"}
    assert genres.leaves({"shoegaze", "indie_rock", "rock"}) == {"shoegaze"}


def test_explicit_affinity_wins_over_the_parent_default():
    """手寫的那張表是針對某一對寫的，父子關係給的只是通則。

    反過來的話，哪天在 RELATED 裡替一對父子寫了數字，會被通則無聲蓋掉。
    """
    original = genres.RELATED.get("lofi", {}).get("hip_hop")
    genres.RELATED.setdefault("lofi", {})["hip_hop"] = 0.7
    try:
        assert genres.affinity("lofi", "hip_hop") == pytest.approx(0.7)
    finally:
        if original is None:
            genres.RELATED["lofi"].pop("hip_hop", None)
        else:
            genres.RELATED["lofi"]["hip_hop"] = original
    # 沒有明寫的父子對仍然吃通則
    assert genres.affinity("trap", "hip_hop") == pytest.approx(genres.PARENT_AFFINITY)


# --- 種子池的曲風 ------------------------------------------------------------

def test_every_seed_artist_has_a_hand_written_genre():
    """補進來的候選要湊得進曲風名額，就得每一位都標到。"""
    from app.services import seed_pool

    missing = [n for n in seed_pool.artists() if not seed_pool.genres_of(n)]
    assert not missing, f"這幾位還沒標曲風：{missing}"


def test_seed_genres_are_all_real_slugs():
    """標了一個分類表上沒有的 slug，等於這位歌手永遠命中不了任何請求。"""
    from app.services import seed_pool

    unknown = {g for slugs in seed_pool.GENRES.values() for g in slugs
               if g not in genres.ALIASES}
    assert not unknown, f"不在分類表裡的 slug：{unknown}"


def test_the_seed_pool_can_express_city_pop():
    """iTunes 給不出 citypop（山下達郎回 J-Pop、落日飛車回「成人當代」）。

    手工標的這份清單是候選池裡唯一標得出來的地方——而 citypop 正是這個功能
    最初要解的那個例子。這條沒過就表示「想聽 citypop」又只能靠鄰居曲風命中。
    """
    from app.services import seed_pool

    city = [n for n in seed_pool.artists() if "city_pop" in seed_pool.genres_of(n)]
    assert city, "沒有任何一位歌手標成 city_pop"


def test_injected_candidates_are_one_per_artist():
    """實測「聽 lo-fi 的人」前五拿到三首 STUTS——注入是分好幾次抽的，跨次要去重。"""
    from app.core.pipeline import _one_artist_each

    rows = [{"artist": "STUTS", "title": "a"}, {"artist": "STUTS", "title": "b"},
            {"artist": "stuts", "title": "c"}, {"artist": "Nujabes", "title": "d"}]
    assert [r["title"] for r in _one_artist_each(rows)] == ["a", "d"]


# --- pipeline：這一輪照哪些曲風排 --------------------------------------------

def test_prompt_genres_replace_the_playlist_profile():
    """「今天想聽 citypop」是一句覆寫的話，不是追加。

    跟歌單既有的曲風分布混在一起，等於告訴使用者「你說了，但我只聽一半」。
    """
    from app.core.pipeline import _wanted_genres

    profile = {"genre_weights": {"rnb": 1.0, "jazz": 0.5}}
    wanted, source = _wanted_genres({"genres": ["city_pop"]}, profile)
    assert wanted == {"city_pop": 1.0} and source == "prompt"


def test_playlist_profile_is_used_when_nothing_was_said():
    """使用者沒明講曲風時，才輪到歌單統計出來的分布——這是「數值像但曲風不像」的預設解。"""
    from app.core.pipeline import _wanted_genres

    profile = {"genre_weights": {"rnb": 1.0, "jazz": 0.5}}
    wanted, source = _wanted_genres({"genres": []}, profile)
    assert wanted == {"rnb": 1.0, "jazz": 0.5} and source == "profile"

    assert _wanted_genres({}, {}) == ({}, "")
