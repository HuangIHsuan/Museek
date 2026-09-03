"""ReccoBeats 串接（§3.1 凍結簽章）。

實測後修正的三件事（原本是照文件推測寫的）：
  1. 搜尋要「只用歌名」。送「歌手 + 歌名」會回 0 筆——實測
     searchText="Frank Ocean White Ferrari" 是空的，"White Ferrari" 才找得到。
     因此改成用歌名搜、再從回傳的 artists 比對歌手。
  2. 批次查特徵的端點是 /v1/audio-features?ids=a,b，
     不是 /v1/track/{ids}/audio-features（後者只吃單一 id）。
  3. 推薦端點回傳的曲目**不含音訊特徵、也沒有 popularity**，
     必須另外批次補特徵；popularity 則完全拿不到（見 NOTES #34）。

外網不可用或呼叫失敗時自動退回 stub_data，內網端到端流程照樣跑得完。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.config import get_settings
from app.core.normalize import artist_variants
from app.services import stub_data
from app.services.http import get_json

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
        "features": {},          # 搜尋與推薦端點都不含特徵，要另外查
        "popularity": None,      # ReccoBeats 沒有這個欄位
    }


def _same_artist(wanted: str, found: str) -> bool:
    """歌手比對。中英並列（周杰倫 Jay Chou）任一種寫法對上就算。"""
    found_key = (found or "").strip().lower()
    if not found_key:
        return False
    for variant in artist_variants(wanted):
        key = variant.strip().lower()
        if key and (key in found_key or found_key in key):
            return True
    return False


async def search_track(artist: str, title: str) -> Optional[str]:
    """回傳 recco_id，查不到回 None。"""
    if _use_stub():
        return stub_data.stub_recco_id(artist, title)

    settings = get_settings()
    try:
        # 只用歌名搜尋——帶上歌手會查不到任何東西
        data = await get_json(
            f"{settings.reccobeats_base_url}/v1/track/search",
            params={"searchText": title.strip(), "size": 10},
        )
        _mark(True)
    except Exception as error:  # noqa: BLE001
        log.warning("ReccoBeats search 失敗：%s", error)
        _mark(False)
        return None

    items = data.get("content") or []
    for item in items:
        track = _parse_track(item)
        if _same_artist(artist, track["artist"]):
            return track["recco_id"] or None
    return None      # 找不到同一位歌手就算 miss，不硬湊——錯配會污染品味向量


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
    if _use_stub() or not seed_ids:
        return stub_data.stub_catalog()[:limit]

    settings = get_settings()
    try:
        data = await get_json(
            f"{settings.reccobeats_base_url}/v1/track/recommendation",
            params={"seeds": ",".join(seed_ids[:5]), "size": limit},
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
