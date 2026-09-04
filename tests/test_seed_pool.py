"""備援種子池，以及它在 pipeline 的接線：起點歌手一位都沒對上時的後路。"""
from __future__ import annotations

import json

import pytest

from app.config import get_settings
from app.core import pipeline
from app.core.ranker import similarity
from app.db.repository import MemoryRepository
from app.services import llm, reccobeats, seed_pool


def test_pool_has_no_duplicate_artists():
    """重複的名字會讓同一位歌手在挑選時多佔一個位子，白白壓掉別的角落。"""
    names = seed_pool.artists()
    assert len(names) == len({name.lower() for name in names})
    assert len(names) >= 30      # 太少就攤不開特徵空間，備援等於沒有備援


def test_load_returns_nothing_when_the_file_is_absent(tmp_path):
    """沒跑過 verify 腳本不是錯誤——pipeline 還有即時解析那條路。"""
    assert seed_pool.load(str(tmp_path / "nope.json")) == []


def test_load_drops_rows_without_an_id_or_features(tmp_path):
    path = tmp_path / "vibe_seeds.json"
    path.write_text(json.dumps({"seeds": [
        {"recco_id": "ok", "artist": "A", "title": "T", "features": {"energy": 0.3}},
        {"recco_id": "", "artist": "B", "title": "T", "features": {"energy": 0.3}},
        {"recco_id": "no-features", "artist": "C", "title": "T", "features": {}},
    ]}), encoding="utf-8")
    rows = seed_pool.load(str(path))
    assert [row["recco_id"] for row in rows] == ["ok"]


def test_load_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "vibe_seeds.json"
    path.write_text("{ 這不是 JSON", encoding="utf-8")
    assert seed_pool.load(str(path)) == []


def test_pick_stays_inside_the_closest_shortlist():
    """隨機是為了不讓所有人拿到同五首，但不能隨機到不相干的歌上。"""
    pool = [{"recco_id": f"id{i}", "artist": "A", "title": f"T{i}",
             "features": {"energy": i / 20, "valence": 0.5, "tempo": 100}}
            for i in range(20)]
    target = {"energy": 0.05, "valence": 0.5, "tempo": 100}

    seen = set()
    for _ in range(30):
        picked = seed_pool.pick(pool, target, similarity, limit=3, shortlist=6)
        assert len(picked) == 3
        assert len({row["recco_id"] for row in picked}) == 3   # 不重複挑同一首
        seen.update(row["recco_id"] for row in picked)
    # 低 energy 的目標只該挑到 energy 最低那幾首，前 6 名以外的不該出現
    assert seen <= {f"id{i}" for i in range(6)}
    assert len(seen) > 3      # 而且每次不該都一樣


def test_pick_copes_with_a_pool_smaller_than_the_limit():
    pool = [{"recco_id": "only", "features": {"energy": 0.5}}]
    assert len(seed_pool.pick(pool, {"energy": 0.5}, similarity, limit=5)) == 1
    assert seed_pool.pick([], {"energy": 0.5}, similarity, limit=5) == []


# --- 接線：三種 seed 來源 -----------------------------------------------------

@pytest.fixture
def live_catalog(monkeypatch, tmp_path):
    """真實曲庫模式，但所有對外呼叫都換成假的。回傳一個可調整命中與否的開關。"""
    monkeypatch.setenv("RECCOBEATS_MODE", "live")
    get_settings.cache_clear()
    state = {"hit": True}

    async def artist_catalog(names):
        if not state["hit"]:
            return []
        return [{"recco_id": f"live-{names[0]}", "artist": names[0], "title": "曲庫有的歌"}]

    async def audio_features(ids):
        return {i: {"energy": 0.31, "valence": 0.36, "tempo": 96} for i in ids}

    monkeypatch.setattr(reccobeats, "artist_catalog", artist_catalog)
    monkeypatch.setattr(reccobeats, "get_audio_features", audio_features)
    monkeypatch.setattr(seed_pool, "SEED_FILE", str(tmp_path / "vibe_seeds.json"))
    return state


def _vibe(artists):
    async def analyze(_text):
        return {"vibe": "空無一人的高架橋",
                "target": {"energy": 0.3, "valence": 0.35, "tempo": 95},
                "seed_artists": artists}
    return analyze


async def test_model_artists_win_when_the_catalogue_has_them(monkeypatch, live_catalog):
    """模型是照著這一次的情境挑的，比寫死的池子貼近——有得用就不該動備援。"""
    monkeypatch.setattr(llm, "analyze_vibe", _vibe(["Bon Iver", "Khruangbin"]))
    session = await pipeline.create_vibe_session(MemoryRepository(), "深夜開車")
    assert session["seed_source"] == "vibe"
    assert session["seeds"] == 2


async def test_falls_back_when_the_catalogue_has_none_of_the_model_artists(monkeypatch, live_catalog, tmp_path):
    """使用者原本看到的就是這一格：模型答得出來，曲庫卻一位都沒收。"""
    path = tmp_path / "vibe_seeds.json"
    path.write_text(json.dumps({"seeds": [
        {"recco_id": "pool-quiet", "artist": "Nick Drake", "title": "Pink Moon",
         "features": {"energy": 0.12, "valence": 0.30, "tempo": 88}},
        {"recco_id": "pool-loud", "artist": "Muse", "title": "Hysteria",
         "features": {"energy": 0.95, "valence": 0.60, "tempo": 150}},
    ]}), encoding="utf-8")
    monkeypatch.setattr(llm, "analyze_vibe", _vibe(["查無此人", "也查無此人"]))
    live_catalog["hit"] = False

    repo = MemoryRepository()
    session = await pipeline.create_vibe_session(repo, "深夜開車")
    assert session["seed_source"] == "fallback"
    profile = await repo.get_profile(session["session_id"])
    assert profile["seed_ids"], "備援必須真的接住，否則使用者還是看到 no_seeds"


async def test_falls_back_when_the_model_names_nobody(monkeypatch, live_catalog, tmp_path):
    """LLM 降級時規則式給不出歌手。這條路以前直接死在 no_seeds。"""
    (tmp_path / "vibe_seeds.json").write_text(json.dumps({"seeds": [
        {"recco_id": "pool-quiet", "artist": "Nick Drake", "title": "Pink Moon",
         "features": {"energy": 0.12, "valence": 0.30, "tempo": 88}},
    ]}), encoding="utf-8")
    monkeypatch.setattr(llm, "analyze_vibe", _vibe([]))
    session = await pipeline.create_vibe_session(MemoryRepository(), "深夜開車")
    assert session["seed_source"] == "fallback"


async def test_reports_none_when_even_the_fallback_cannot_resolve(monkeypatch, live_catalog):
    """曲庫整個連不上時要照實說 none，不能假裝有起點。"""
    monkeypatch.setattr(llm, "analyze_vibe", _vibe(["查無此人"]))
    live_catalog["hit"] = False
    session = await pipeline.create_vibe_session(MemoryRepository(), "深夜開車")
    assert session["seed_source"] == "none"
    assert session["seeds"] == 0
