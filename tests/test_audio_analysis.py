"""曲庫查不到時的音訊分析補救路徑（NOTES #38）。

全部用假的 HTTP 與假的服務函式，不對外連線。
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.core import pipeline
from app.core.normalize import same_artist, same_title
from app.db.repository import MemoryRepository
from app.services import itunes, reccobeats


@pytest.fixture
def live_mode(monkeypatch):
    """把 ReccoBeats 切成真實模式——分析路徑在 stub 模式下本來就不會啟動。"""
    monkeypatch.setenv("RECCOBEATS_MODE", "live")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def repo():
    return MemoryRepository(persist=False)


# --- 曲名／歌手比對 ---------------------------------------------------------

def test_same_title_accepts_version_suffix():
    assert same_title("浴室", "浴室 (LP Version)")
    assert same_title("My Jinji", "My Jinji")


def test_same_title_rejects_different_song():
    # 「魚」包含在「魚仔」裡，但那是另一首歌——錯配的特徵比沒有特徵更糟
    assert not same_title("魚", "魚仔")
    assert not same_title("大風吹", "Hip-hop沒有派對")


def test_same_artist_matches_either_script():
    assert same_artist("落日飛車 Sunset Rollercoaster", "Sunset Rollercoaster")
    assert same_artist("落日飛車 Sunset Rollercoaster", "落日飛車")
    assert not same_artist("草東沒有派對", "MC HotDog")


# --- iTunes 認歌與別名 ------------------------------------------------------

def _song(artist: str, title: str, preview: str = "https://audio/x.m4a", track_id: int = 1):
    return {"artistName": artist, "trackName": title,
            "previewUrl": preview, "trackId": track_id}


def _fake_itunes(monkeypatch, per_store, lookups=None):
    """per_store: {商店: [結果]}；lookups: {商店: 結果}（同一個 trackId 的別名）。"""
    seen = []

    async def fake_get_json(url, params=None, **kwargs):
        if url.endswith("/lookup"):
            hit = (lookups or {}).get(params["country"])
            return {"results": [hit] if hit else []}
        seen.append(params["country"])
        return {"results": per_store.get(params["country"], [])}

    monkeypatch.setattr(itunes, "get_json", fake_get_json)
    return seen


async def test_lookup_track_skips_wrong_song_in_same_response(monkeypatch):
    _fake_itunes(monkeypatch, {"TW": [_song("MC HotDog", "Hip-hop沒有派對", "https://audio/wrong.m4a"),
                                      _song("草東沒有派對", "大風吹", "https://audio/right.m4a")]})
    match = await itunes.lookup_track("草東沒有派對", "大風吹")
    assert match.preview_url == "https://audio/right.m4a"
    assert match.store == "TW"


async def test_lookup_track_falls_through_to_next_store(monkeypatch):
    """華語曲名在美國商店查不到，TW 商店才有——所以要逐個商店試。"""
    seen = _fake_itunes(monkeypatch, {"TW": [], "US": [_song("Sunset Rollercoaster", "My Jinji")]})
    match = await itunes.lookup_track("Sunset Rollercoaster", "My Jinji")
    assert match.preview_url == "https://audio/x.m4a"
    assert seen == ["TW", "US"]


async def test_lookup_track_collects_cross_store_aliases(monkeypatch):
    """同一個 trackId 在另一個商店的寫法，就是曲庫要用的那組中英對照。"""
    _fake_itunes(
        monkeypatch,
        {"TW": [_song("茄子蛋", "浪子回頭")]},
        lookups={"US": _song("EggPlantEgg", "Back Here Again")},
    )
    match = await itunes.lookup_track("茄子蛋", "浪子回頭")
    assert match.artist_names == ["茄子蛋", "EggPlantEgg"]
    assert match.titles == ["浪子回頭", "Back Here Again"]


async def test_lookup_track_retries_with_the_other_half_of_a_bilingual_name(monkeypatch):
    """「陳綺貞 Cheer Chen 魚 Fish」整串送出去 iTunes 回 0 筆，「陳綺貞 魚」才查得到。"""
    terms = []

    async def fake_get_json(url, params=None, **kwargs):
        if url.endswith("/lookup"):
            return {"results": []}
        terms.append(params["term"])
        if params["term"] == "陳綺貞 魚":
            return {"results": [_song("陳綺貞", "魚")]}
        return {"results": []}

    monkeypatch.setattr(itunes, "get_json", fake_get_json)
    match = await itunes.lookup_track("陳綺貞 Cheer Chen", "魚 Fish")

    assert match is not None, "並列寫法查不到就完全不會走到音訊分析"
    assert match.titles == ["魚"]
    assert terms[0] == "陳綺貞 Cheer Chen 魚 Fish", "精確的那組要先送"


def test_search_terms_pair_up_each_script():
    assert itunes._search_terms("告五人 Accusefive", "唯一 Only") == [
        "告五人 Accusefive 唯一 Only", "告五人 唯一", "Accusefive Only",
    ]
    # 沒有並列寫法就只有一種送法，不多花請求
    assert itunes._search_terms("Billie Eilish", "BIRDS OF A FEATHER") == [
        "Billie Eilish BIRDS OF A FEATHER",
    ]


async def test_lookup_track_returns_none_when_nothing_matches(monkeypatch):
    _fake_itunes(monkeypatch, {"TW": [_song("Someone Else", "Another Song")],
                               "US": [_song("Someone Else", "Another Song")]})
    assert await itunes.lookup_track("草東沒有派對", "大風吹") is None


async def test_fetch_preview_swallows_errors(monkeypatch):
    async def boom(url, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(itunes, "get_bytes", boom)
    assert await itunes.fetch_preview("https://audio/x.m4a") is None


# --- ReccoBeats 分析端點 ----------------------------------------------------

async def test_extract_audio_features_posts_multipart(live_mode, monkeypatch):
    captured = {}

    async def fake_post_file(url, *, field, filename, content, content_type, timeout=None):
        captured.update(url=url, field=field, filename=filename,
                        content=content, content_type=content_type)
        # 分析端點回的是單一物件，不是曲庫那種 content 陣列
        return {"energy": 0.1397, "valence": 0.1516, "tempo": 103.6992, "key": 0}

    monkeypatch.setattr(reccobeats, "post_file", fake_post_file)
    features = await reccobeats.extract_audio_features(b"fake-audio")

    assert captured["url"].endswith("/v1/analysis/audio-features")
    assert captured["field"] == "audioFile"
    assert captured["content"] == b"fake-audio"
    assert features == {"energy": 0.1397, "valence": 0.1516, "tempo": 103.6992}


async def test_extract_audio_features_is_silent_in_stub_mode(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("stub 模式不該對外連線")

    monkeypatch.setattr(reccobeats, "post_file", boom)
    assert await reccobeats.extract_audio_features(b"fake-audio") == {}


async def test_extract_audio_features_returns_empty_on_failure(live_mode, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("415 unsupported")

    monkeypatch.setattr(reccobeats, "post_file", boom)
    assert await reccobeats.extract_audio_features(b"fake-audio") == {}


# --- pipeline：曲庫 miss → 分析 ---------------------------------------------

ANALYZED = {"energy": 0.14, "valence": 0.15, "tempo": 103.7}


def _match(artist: str, title: str, **over) -> itunes.TrackMatch:
    return itunes.TrackMatch(track_id=1, store="TW", artist_names=[artist],
                             titles=[title], preview_url=f"https://audio/{title}.m4a",
                             **over)


@pytest.fixture
def analysis_stack(monkeypatch):
    """曲庫全 miss（連歌手那條路也 miss）、iTunes 全中。回傳被分析過的曲目清單。"""
    analyzed = []

    async def no_catalog_hit(artist, title, artist_aliases=()):
        return None

    async def no_artist_hit(artist_names, titles):
        return None

    async def no_artist_catalog(artist_names):
        return []

    async def lookup_track(artist, title):
        return _match(artist, title)

    async def fetch_preview(url):
        return b"fake-audio"

    async def extract(audio, filename="preview.m4a", content_type="audio/mp4"):
        analyzed.append(audio)
        return dict(ANALYZED)

    monkeypatch.setattr(reccobeats, "search_track", no_catalog_hit)
    monkeypatch.setattr(reccobeats, "search_track_via_artist", no_artist_hit)
    monkeypatch.setattr(reccobeats, "artist_catalog", no_artist_catalog)
    monkeypatch.setattr(itunes, "lookup_track", lookup_track)
    monkeypatch.setattr(itunes, "fetch_preview", fetch_preview)
    monkeypatch.setattr(reccobeats, "extract_audio_features", extract)
    return analyzed


async def test_features_fall_back_to_analysis(live_mode, repo, analysis_stack):
    result = await pipeline._features_for(repo, "Luci Gang", "HEADLOCK")

    assert result is not None, "曲庫查不到就回 None 的話，前端會看到一整排 0.00"
    assert result["features"] == ANALYZED
    assert result["source"] == "analysis"
    assert result["popularity"] is None      # 分析端點沒有熱門度，不能編一個
    assert len(analysis_stack) == 1


async def test_analysis_result_is_cached(live_mode, repo, analysis_stack):
    await pipeline._features_for(repo, "Luci Gang", "HEADLOCK")
    again = await pipeline._features_for(repo, "Luci Gang", "HEADLOCK")

    assert again["features"] == ANALYZED
    assert len(analysis_stack) == 1, "第二次應該打快取，不該重新分析"


async def test_analysis_budget_caps_the_number_of_calls(live_mode, repo, analysis_stack):
    budget = pipeline.RecoveryBudget(2)
    results = [await pipeline._features_for(repo, "Luci Gang", f"Song {i}", budget)
               for i in range(4)]

    assert len(analysis_stack) == 2
    assert [r is not None for r in results] == [True, True, False, False]


async def test_recovery_can_be_switched_off(live_mode, repo, analysis_stack, monkeypatch):
    monkeypatch.setenv("RECCOBEATS_RECOVERY", "false")
    get_settings.cache_clear()
    assert await pipeline._features_for(repo, "Luci Gang", "HEADLOCK") is None
    assert analysis_stack == []


async def test_missing_preview_leaves_track_unmatched(live_mode, repo, analysis_stack, monkeypatch):
    async def nothing(artist, title):
        return None

    monkeypatch.setattr(itunes, "lookup_track", nothing)
    assert await pipeline._features_for(repo, "Luci Gang", "HEADLOCK") is None


async def test_session_reports_how_many_tracks_were_analyzed(live_mode, analysis_stack):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.post(
                "/api/session",
                json={"playlist_url": "https://www.youtube.com/playlist?list=PLdemo"},
            )

    data = response.json()
    assert response.status_code == 200, response.text
    # 24 首的 stub 歌單全部曲庫 miss，但補救額度只有 recovery_max_per_session 首
    assert data["analyzed"] == get_settings().recovery_max_per_session
    assert data["matched"] == data["analyzed"]
    assert data["profile"]["vector"]["energy"] == pytest.approx(ANALYZED["energy"])


# --- 短曲名不送必定被擋的請求 -----------------------------------------------

async def test_short_title_skips_catalog_search(live_mode, monkeypatch):
    """兩個字的華語曲名送出去一定回 400，還會把 /api/health 打成 degraded。"""
    async def boom(*args, **kwargs):
        raise AssertionError("不該對曲庫送出必定被擋的搜尋")

    monkeypatch.setattr(reccobeats, "get_json", boom)
    monkeypatch.setattr(reccobeats, "_last_call_ok", None)
    assert await reccobeats.search_track("deca joins", "浴室") is None
    assert reccobeats.last_status() == "unknown"


# --- 別名補救：拿回真的 recco_id（也就是推薦種子）---------------------------

CATALOG = {"energy": 0.295, "valence": 0.30, "tempo": 126.5}


@pytest.fixture
def alias_stack(monkeypatch):
    """iTunes 認得這首歌，並給出美國商店的英文寫法。"""
    async def lookup_track(artist, title):
        return itunes.TrackMatch(track_id=1, store="TW",
                                 artist_names=["茄子蛋", "EggPlantEgg"],
                                 titles=["浪子回頭", "Back Here Again"],
                                 preview_url="https://audio/x.m4a")

    async def features(ids):
        return {"catalog-id": dict(CATALOG)}

    monkeypatch.setattr(itunes, "lookup_track", lookup_track)
    monkeypatch.setattr(reccobeats, "get_audio_features", features)


async def test_alias_recovers_catalog_id(live_mode, repo, alias_stack, monkeypatch):
    """曲庫收的是 EggPlantEgg，YouTube 上寫的是茄子蛋——別名對上就查得到。"""
    tried = []

    async def search_track(artist, title, artist_aliases=()):
        tried.append((title, tuple(artist_aliases)))
        return "catalog-id" if "EggPlantEgg" in artist_aliases else None

    monkeypatch.setattr(reccobeats, "search_track", search_track)
    result = await pipeline._features_for(repo, "茄子蛋", "浪子回頭")

    assert result["recco_id"] == "catalog-id", "沒有 recco_id 就當不了推薦種子"
    assert result["source"] == "reccobeats"
    assert result["features"] == CATALOG
    assert tried[0] == ("浪子回頭", ())      # 第一趟不帶別名，命中就不會有第二趟


async def test_short_title_recovered_through_artist_track_list(live_mode, repo, alias_stack,
                                                               monkeypatch):
    """「浴室」兩個字搜不了，只能先找歌手再翻曲目清單。"""
    async def search_track(artist, title, artist_aliases=()):
        return None

    async def via_artist(artist_names, titles):
        assert "浴室" in titles
        return "catalog-id"

    monkeypatch.setattr(reccobeats, "search_track", search_track)
    monkeypatch.setattr(reccobeats, "search_track_via_artist", via_artist)
    result = await pipeline._features_for(repo, "deca joins", "浴室")

    assert result["recco_id"] == "catalog-id"
    assert result["features"] == CATALOG


async def test_analysis_keeps_the_recovered_seed(live_mode, repo, monkeypatch):
    """曲庫有這首歌卻沒有特徵：特徵走分析，recco_id 仍然要留著當種子。"""
    async def lookup_track(artist, title):
        return itunes.TrackMatch(track_id=1, store="TW", artist_names=[artist],
                                 titles=[title], preview_url="https://audio/x.m4a")

    async def search_track(artist, title, artist_aliases=()):
        return None

    async def via_artist(artist_names, titles):
        return "catalog-id"

    async def no_features(ids):
        return {}

    async def fetch_preview(url):
        return b"fake-audio"

    async def extract(audio, filename="preview.m4a", content_type="audio/mp4"):
        return dict(ANALYZED)

    monkeypatch.setattr(itunes, "lookup_track", lookup_track)
    monkeypatch.setattr(itunes, "fetch_preview", fetch_preview)
    monkeypatch.setattr(reccobeats, "search_track", search_track)
    monkeypatch.setattr(reccobeats, "search_track_via_artist", via_artist)
    monkeypatch.setattr(reccobeats, "get_audio_features", no_features)
    monkeypatch.setattr(reccobeats, "extract_audio_features", extract)

    result = await pipeline._features_for(repo, "deca joins", "浴室")
    assert result["source"] == "analysis"
    assert result["features"] == ANALYZED
    assert result["recco_id"] == "catalog-id"


async def test_catalog_id_survives_when_features_are_missing(live_mode, repo, monkeypatch):
    """曲庫認得這首歌卻沒有特徵、也分析不出來：id 還是要留著當推薦種子。

    這裡回 None 的話，單曲入口會連一個種子都沒有，整個 session 直接沒得推薦。
    """
    async def search_track(artist, title, artist_aliases=()):
        return "catalog-id"

    async def no_features(ids):
        return {}

    async def no_itunes(artist, title):
        return None

    monkeypatch.setattr(reccobeats, "search_track", search_track)
    monkeypatch.setattr(reccobeats, "get_audio_features", no_features)
    monkeypatch.setattr(itunes, "lookup_track", no_itunes)

    result = await pipeline._features_for(repo, "deca joins", "浴室")
    assert result["recco_id"] == "catalog-id"
    assert result["features"] == {}
    # 沒有特徵的項目不能寫進快取，否則下次就不會再試著補了
    assert await repo.get_features([pipeline.cache_key("deca joins", "浴室")]) == {}


async def test_track_without_features_is_not_counted_as_matched(live_mode, repo, monkeypatch):
    """有種子不等於有特徵——比對率算錯的話，該提醒的時候不會提醒。"""
    from app.core.quota import QuotaTracker

    async def one_video(quota, kind, source_id):
        return [{"raw_title": "deca joins - 浴室", "channel": "deca joins", "video_id": "v1"}]

    async def features_for(repo_, artist, title, budget=None, searched=None):
        return {"recco_id": "catalog-id", "seed_id": None, "features": {},
                "popularity": None, "source": "reccobeats"}

    monkeypatch.setattr(pipeline, "_fetch_items", one_video)
    monkeypatch.setattr(pipeline, "_features_for", features_for)

    result = await pipeline.create_session(repo, QuotaTracker(repo),
                                           "https://www.youtube.com/watch?v=IwxkGdhkAGU")
    assert result["matched"] == 0
    assert result["profile"]["vector"] == {}
    assert "種子" in result["profile"]["warning"], "有種子時要說得跟完全查不到不一樣"


# --- 一首都對不上時，不能拿假曲庫充數 ---------------------------------------

async def test_no_seeds_reports_an_error_instead_of_stub_catalog(live_mode, repo, monkeypatch):
    """推薦端點的 seeds 是必填的曲目 id，沒有種子就是沒得推薦——要照實說。"""
    from app.core.quota import QuotaTracker

    async def boom(*args, **kwargs):
        raise AssertionError("沒有種子就不該呼叫推薦端點")

    monkeypatch.setattr(reccobeats, "get_json", boom)
    await repo.save_profile({
        "session_id": "s1", "playlist_id": "p", "tracks": [
            {"artist": "Luci Gang", "title": "HEADLOCK", "recco_id": None,
             "features": {"energy": 0.8}, "matched": True},
        ],
        "vector": {"energy": 0.8}, "seen_artists": ["luci gang"],
        "blacklist": [], "down_votes": {}, "last_round": [], "last_prompt": "",
    })

    events = [event async for event in
              pipeline.recommend_stream(repo, QuotaTracker(repo), "s1", "想聽點吵的")]
    names = [name for name, _ in events]
    assert "error" in names
    assert dict(events[names.index("error")][1])["code"] == "no_seeds"
    assert "track" not in names


async def test_stub_mode_still_uses_the_stub_catalog(repo):
    """stub 模式沒有真實種子是正常的，內網端到端流程不能因此斷掉。"""
    assert await reccobeats.get_recommendations([], limit=5)


async def test_analysis_half_can_be_switched_off_alone(live_mode, repo, alias_stack, monkeypatch):
    """只想要別名回查、不想付音訊分析那 3 秒的人，關掉後半段就好。"""
    async def search_track(artist, title, artist_aliases=()):
        return None

    async def via_artist(artist_names, titles):
        return None

    async def boom(*args, **kwargs):
        raise AssertionError("關掉之後不該再做音訊分析")

    monkeypatch.setenv("RECCOBEATS_ANALYSIS", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(reccobeats, "search_track", search_track)
    monkeypatch.setattr(reccobeats, "search_track_via_artist", via_artist)
    monkeypatch.setattr(itunes, "fetch_preview", boom)

    assert await pipeline._features_for(repo, "茄子蛋", "浪子回頭") is None


# --- 代打種子：曲庫沒收那首歌，但歌手還在 -----------------------------------

async def test_proxy_seed_picks_the_closest_track_by_the_analyzed_features(live_mode, repo,
                                                                           monkeypatch):
    """HEADLOCK 不在曲庫，但 Luci Gang 本人有 77 首——挑特徵最接近的那首當種子。"""
    catalog = [
        {"recco_id": "slow", "artist": "Luci Gang", "title": "Take It Slow"},
        {"recco_id": "calm", "artist": "Luci Gang", "title": "OK!"},
    ]
    features = {"slow": {"energy": 0.774, "valence": 0.573, "tempo": 131.9},
                "calm": {"energy": 0.267, "valence": 0.201, "tempo": 82.0}}

    async def lookup_track(artist, title):
        return itunes.TrackMatch(track_id=1, store="TW", artist_names=["Luci Gang"],
                                 titles=[title], preview_url="https://audio/x.m4a")

    async def search_track(artist, title, artist_aliases=()):
        return None

    async def via_artist(artist_names, titles):
        return None

    async def artist_catalog(artist_names):
        return catalog

    async def get_features(ids):
        return {i: features[i] for i in ids if i in features}

    async def fetch_preview(url):
        return b"fake-audio"

    async def extract(audio, filename="preview.m4a", content_type="audio/mp4"):
        return {"energy": 0.8085, "valence": 0.6787, "tempo": 132.6}

    monkeypatch.setattr(itunes, "lookup_track", lookup_track)
    monkeypatch.setattr(itunes, "fetch_preview", fetch_preview)
    monkeypatch.setattr(reccobeats, "search_track", search_track)
    monkeypatch.setattr(reccobeats, "search_track_via_artist", via_artist)
    monkeypatch.setattr(reccobeats, "artist_catalog", artist_catalog)
    monkeypatch.setattr(reccobeats, "get_audio_features", get_features)
    monkeypatch.setattr(reccobeats, "extract_audio_features", extract)

    result = await pipeline._features_for(repo, "Luci Gang", "HEADLOCK")

    assert result["recco_id"] is None, "代打種子不能冒充成這首歌的 id"
    assert result["seed_id"] == "slow"
    assert result["source"] == "analysis"


async def test_proxy_seed_is_used_as_a_recommendation_seed(live_mode, repo, monkeypatch):
    """代打種子要真的送進推薦端點，否則單曲入口還是拿不到候選。"""
    from app.core.quota import QuotaTracker

    seen = {}

    async def recommendations(seed_ids, limit=50):
        seen["seeds"] = list(seed_ids)
        return []

    monkeypatch.setattr(reccobeats, "get_recommendations", recommendations)
    await repo.save_profile({
        "session_id": "s2", "playlist_id": "p", "tracks": [
            {"artist": "Luci Gang", "title": "HEADLOCK", "recco_id": None,
             "seed_id": "slow", "features": {"energy": 0.8}, "matched": True},
        ],
        "vector": {"energy": 0.8}, "seen_artists": ["luci gang"],
        "blacklist": [], "down_votes": {}, "last_round": [], "last_prompt": "",
    })

    events = [e async for e in
              pipeline.recommend_stream(repo, QuotaTracker(repo), "s2", "想聽點吵的")]
    assert seen["seeds"] == ["slow"]
    assert "error" not in [name for name, _ in events]
