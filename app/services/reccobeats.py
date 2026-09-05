"""ReccoBeats 串接（§3.1 凍結簽章）。

實測後修正的三件事（原本是照文件推測寫的）：
  1. 搜尋要「只用歌名」。送「歌手 + 歌名」會回 0 筆——實測
     searchText="Frank Ocean White Ferrari" 是空的，"White Ferrari" 才找得到。
     因此改成用歌名搜、再從回傳的 artists 比對歌手。
  2. 批次查特徵的端點是 /v1/audio-features?ids=a,b，
     不是 /v1/track/{ids}/audio-features（後者只吃單一 id）。
  3. 推薦端點回傳的曲目**不含音訊特徵、也沒有 popularity**，
     必須另外批次補特徵；popularity 則完全拿不到（見 NOTES #34）。
  4. 曲庫查不到的歌還有第二條路：/v1/analysis/audio-features 吃音訊檔直接算特徵。
     曲庫命中率對華語與獨立廠牌並不高，沒有這條路那些歌就是一整排 0.00（NOTES #38）。
  5. searchText 少於 3 個字會被擋下來回 400。兩個字的華語曲名（浴室、唯一、魚）
     一律搜不到——這種歌要走「先找歌手、再翻那位歌手的曲目清單」那條路（NOTES #39）。
  6. 曲庫是 Spotify 血統，歌手名不見得跟 YouTube 上同一套寫法（茄子蛋＝EggPlantEgg、
     草東沒有派對＝No Party For Cao Dong）。查不到時要帶著 iTunes 給的別名再試一次。
  7. 推薦端點的 seeds 只吃曲目 id，但**種子不必是同一首歌**。曲庫沒收那首歌時，
     同一位歌手往往還在（Luci Gang 有 77 首、就是沒有 HEADLOCK），
     挑特徵最接近的那首當代打種子即可（NOTES #40）。

外網不可用或呼叫失敗時自動退回 stub_data，內網端到端流程照樣跑得完。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

from app.config import get_settings
from app.core.normalize import name_key, same_artist, same_title, title_variants
from app.services import stub_data
from app.services.http import get_json, pacer, post_file

log = logging.getLogger("museek.reccobeats")

FEATURE_FIELDS = ["energy", "valence", "danceability", "acousticness",
                  "instrumentalness", "liveness", "loudness", "speechiness", "tempo"]

FEATURES_PER_REQUEST = 40   # ids 太多會讓 URL 過長

_last_call_ok: Optional[bool] = None


def last_status() -> str:
    if get_settings().reccobeats_mode == "stub":
        return "stub"
    if _last_call_ok is None:
        return "unknown"
    return "ok" if _last_call_ok else "degraded"


def _use_stub() -> bool:
    return get_settings().reccobeats_mode == "stub"


def _mark(ok: bool) -> None:
    global _last_call_ok
    _last_call_ok = ok


def _parse_features(payload: Dict) -> Dict[str, float]:
    return {field: float(payload[field]) for field in FEATURE_FIELDS
            if payload.get(field) is not None}


def _parse_track(payload: Dict) -> Dict:
    artists = payload.get("artists") or []
    artist = artists[0].get("name", "") if artists and isinstance(artists[0], dict) else ""
    return {
        "recco_id": payload.get("id") or "",
        "artist": artist,
        "title": payload.get("trackTitle") or payload.get("name") or "",
        # ISRC 前兩碼是發行登記國，是候選池裡唯一現成的地區訊號（core/regions）
        "isrc": payload.get("isrc") or "",
        "features": {},          # 搜尋與推薦端點都不含特徵，要另外查
        "popularity": None,      # ReccoBeats 沒有這個欄位
    }


SEARCH_MIN_CHARS = 3        # 少於這個長度，搜尋端點一律回 400（見檔頭第 5 點）
ARTIST_TRACK_PAGES = 2      # 每頁上限 50，翻兩頁足以涵蓋絕大多數歌手
SEARCH_TITLE_FORMS = 2      # 一首歌最多送幾種曲名寫法（原樣、去掉並列的另一半）


def _matches_any_artist(names: Sequence[str], found: str) -> bool:
    return any(same_artist(name, found) for name in names if name)


async def search_track(artist: str, title: str,
                       artist_aliases: Sequence[str] = ()) -> Optional[str]:
    """用曲名搜尋曲庫，再比對歌手。回傳 recco_id，查不到回 None。

    artist_aliases 是同一位歌手的其他寫法（iTunes 給的中英對照），
    曲庫用的是哪一套寫法事前並不知道，所以任何一種對上就算。
    """
    if _use_stub():
        return stub_data.stub_recco_id(artist, title)

    names = [artist, *artist_aliases]
    forms = [t for t in title_variants(title) if len(t.strip()) >= SEARCH_MIN_CHARS]
    if not forms:
        # 明知會被擋就不要送。送了不只白費一趟，還會讓 /api/health 誤報 degraded。
        log.info("曲名「%s」太短，跳過曲庫搜尋", title.strip())
        return None

    settings = get_settings()
    for form in forms[:SEARCH_TITLE_FORMS]:
        try:
            # 只用歌名搜尋——帶上歌手會查不到任何東西
            data = await get_json(
                f"{settings.reccobeats_base_url}/v1/track/search",
                params={"searchText": form.strip(), "size": 10},
                pace=pacer("reccobeats"),
            )
            _mark(True)
        except Exception as error:  # noqa: BLE001
            log.warning("ReccoBeats search 失敗：%s", error)
            _mark(False)
            return None

        for item in data.get("content") or []:
            track = _parse_track(item)
            if _matches_any_artist(names, track["artist"]):
                return track["recco_id"] or None
    return None      # 找不到同一位歌手就算 miss，不硬湊——錯配會污染品味向量


async def search_artist(name: str) -> Optional[str]:
    """回傳 artist_id，查不到回 None。"""
    if _use_stub() or len(name.strip()) < SEARCH_MIN_CHARS:
        return None

    settings = get_settings()
    try:
        data = await get_json(
            f"{settings.reccobeats_base_url}/v1/artist/search",
            params={"searchText": name.strip(), "size": 5},
            pace=pacer("reccobeats"),
        )
        _mark(True)
    except Exception as error:  # noqa: BLE001
        log.warning("ReccoBeats artist search 失敗：%s", error)
        _mark(False)
        return None

    for item in data.get("content") or []:
        if same_artist(name, item.get("name") or ""):
            return item.get("id") or None
    return None


async def artist_tracks(artist_id: str) -> List[Dict]:
    """那位歌手在曲庫裡的曲目（最多兩頁、100 首）。"""
    if _use_stub() or not artist_id:
        return []

    settings = get_settings()
    tracks: List[Dict] = []
    for page in range(ARTIST_TRACK_PAGES):
        try:
            data = await get_json(
                f"{settings.reccobeats_base_url}/v1/artist/{artist_id}/track",
                params={"size": 50, "page": page},
                pace=pacer("reccobeats"),
            )
            _mark(True)
        except Exception as error:  # noqa: BLE001
            log.warning("ReccoBeats artist track 失敗：%s", error)
            _mark(False)
            break
        items = data.get("content") or []
        tracks.extend(_parse_track(item) for item in items)
        if len(items) < 50 or page + 1 >= (data.get("totalPages") or 1):
            break
    return tracks


_artist_cache: Dict[str, List[Dict]] = {}
ARTIST_CACHE_MAX = 64


def reset_artist_cache() -> None:
    _artist_cache.clear()


async def artist_catalog(artist_names: Sequence[str]) -> List[Dict]:
    """第一個在曲庫裡找得到的歌手，回傳他的曲目清單。

    行程內快取：同一份歌單常有同一位歌手的多首歌，
    而「查不到這位歌手」也要記住，否則每一首都會再問一次。
    """
    if _use_stub():
        return []

    for name in artist_names:
        key = name_key(name or "")
        if not key:
            continue
        tracks = _artist_cache.get(key)
        if tracks is None:
            artist_id = await search_artist(name)
            tracks = await artist_tracks(artist_id) if artist_id else []
            if len(_artist_cache) >= ARTIST_CACHE_MAX:
                _artist_cache.clear()
            _artist_cache[key] = tracks
        if tracks:
            return tracks
    return []


async def search_track_via_artist(artist_names: Sequence[str],
                                  titles: Sequence[str]) -> Optional[str]:
    """先找歌手，再從那位歌手的曲目清單裡比對曲名。

    這條路是「浴室」「唯一」這種兩個字的華語曲名唯一查得到的方式——
    曲名搜尋有 3 字下限，歌手名沒有。順帶也不受曲名翻譯影響：
    曲庫把大風吹收成大風吹、iTunes 的美國商店卻叫它 Simon Says。
    """
    for track in await artist_catalog(artist_names):
        if any(same_title(wanted, track["title"]) for wanted in titles if wanted):
            return track["recco_id"] or None
    return None


async def get_audio_features(recco_ids: List[str]) -> Dict[str, Dict]:
    """回傳 {recco_id: {...features}}；查不到的 id 不出現在回傳 dict 中。"""
    if not recco_ids or _use_stub():
        return {}

    settings = get_settings()
    result: Dict[str, Dict] = {}
    for start in range(0, len(recco_ids), FEATURES_PER_REQUEST):
        chunk = recco_ids[start:start + FEATURES_PER_REQUEST]
        try:
            data = await get_json(
                f"{settings.reccobeats_base_url}/v1/audio-features",
                params={"ids": ",".join(chunk)},
                pace=pacer("reccobeats"),
            )
            _mark(True)
        except Exception as error:  # noqa: BLE001
            log.warning("ReccoBeats audio-features 失敗：%s", error)
            _mark(False)
            continue
        for item in data.get("content") or []:
            key = item.get("id")
            features = _parse_features(item)
            if key and features:
                result[key] = features
    return result


async def get_recommendations(seed_ids: List[str], limit: int = 50) -> List[Dict]:
    """回傳 [{recco_id, artist, title, features, popularity}]。

    推薦端點只給曲目資訊，特徵要再查一次，因此這裡是兩趟請求。
    """
    if _use_stub():
        return stub_data.stub_catalog()[:limit]
    if not seed_ids:
        # 推薦端點的 seeds 是必填（少了直接 400），而且只吃曲目 id——
        # 歌手 id 不算數，音訊特徵也沒有對應的查詢方式（NOTES #39）。
        # 沒有種子就是沒得推薦，真實模式下絕不能拿 stub 假曲庫充數（同 NOTES #35 的原則）。
        log.warning("沒有任何推薦種子，不呼叫推薦端點")
        return []

    settings = get_settings()
    try:
        data = await get_json(
            f"{settings.reccobeats_base_url}/v1/track/recommendation",
            params={"seeds": ",".join(seed_ids[:5]), "size": limit},
            pace=pacer("reccobeats"),
        )
        _mark(True)
    except Exception as error:  # noqa: BLE001
        log.warning("ReccoBeats recommendation 失敗，改用 stub 曲庫：%s", error)
        _mark(False)
        return stub_data.stub_catalog()[:limit]

    tracks = [_parse_track(item) for item in data.get("content") or []]
    tracks = [t for t in tracks if t["recco_id"] and t["title"]]
    if not tracks:
        return []

    features = await get_audio_features([t["recco_id"] for t in tracks])
    enriched = []
    for track in tracks:
        found = features.get(track["recco_id"])
        if found:                      # 沒有特徵就沒辦法排序，直接不列入候選
            enriched.append({**track, "features": found})
    return enriched


async def extract_audio_features(audio: bytes, filename: str = "preview.m4a",
                                 content_type: str = "audio/mp4") -> Dict[str, float]:
    """把音訊檔丟給分析端點算特徵（§ ReccoBeats /v1/analysis/audio-features）。

    上限 5MB／30 秒，超過的部分會被截斷。回傳格式與曲庫的特徵同一個尺度，
    因此兩種來源可以混在同一支品味向量裡。失敗回空 dict。
    """
    if _use_stub() or not audio:
        return {}

    settings = get_settings()
    try:
        data = await post_file(
            f"{settings.reccobeats_base_url}/v1/analysis/audio-features",
            field="audioFile", filename=filename, content=audio,
            content_type=content_type, timeout=settings.analysis_timeout,
        )
        _mark(True)
    except Exception as error:  # noqa: BLE001
        log.warning("ReccoBeats 音訊分析失敗：%s", error)
        _mark(False)
        return {}

    # 分析端點回的是單一物件，不是 content 陣列
    return _parse_features(data if isinstance(data, dict) else {})
