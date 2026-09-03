"""YouTube Data API 串接（§3.1 凍結簽章）。

開發期紀律（§8）：只有 D2 能真的呼叫。沒設 YOUTUBE_API_KEY 就走 stub，
內網開發者不會不小心燒掉當日配額。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import httpx

from app.config import get_settings
from app.services import stub_data
from app.services.http import get_json

log = logging.getLogger("museek.youtube")

API_BASE = "https://www.googleapis.com/youtube/v3"


class PlaylistNotAccessible(Exception):
    """私人／不存在／空的歌單或影片。"""


class QuotaExceeded(Exception):
    """當日配額耗盡（403 quotaExceeded）。"""


def is_live() -> bool:
    return bool(get_settings().youtube_keys)


def status() -> str:
    return "ok" if is_live() else "stub"


def _quota_error(error: httpx.HTTPStatusError) -> bool:
    if error.response is None or error.response.status_code != 403:
        return False
    try:
        reasons = {e.get("reason") for e in error.response.json()["error"]["errors"]}
    except Exception:  # noqa: BLE001
        return False
    return bool(reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"})


async def fetch_playlist_items(playlist_id: str, api_key: Optional[str] = None) -> List[Dict]:
    """回傳 [{raw_title, channel, video_id}]，最多 50 筆。私人／不存在歌單拋 PlaylistNotAccessible。

    api_key 由呼叫端（QuotaTracker）指定；沒給就用清單裡第一把。
    """
    if not is_live():
        return _stub_playlist(playlist_id)

    settings = get_settings()
    api_key = api_key or settings.youtube_keys[0]
    try:
        data = await get_json(
            f"{API_BASE}/playlistItems",
            params={
                "part": "snippet",
                "playlistId": playlist_id,
                "maxResults": 50,
                "key": api_key,
            },
        )
    except httpx.HTTPStatusError as error:
        if _quota_error(error):
            raise QuotaExceeded("YouTube 每日配額已用盡") from error
        # 400 = playlistId 格式無效、403 = 私人、404 = 不存在。
        # 三者對使用者都是同一件事：這份歌單讀不到，給友善提示＋示範歌單退路。
        if error.response is not None and error.response.status_code in (400, 403, 404):
            raise PlaylistNotAccessible(playlist_id) from error
        raise

    items = []
    for entry in data.get("items", []):
        snippet = entry.get("snippet") or {}
        title = snippet.get("title") or ""
        # 已刪除／私人影片在 playlistItems 會保留佔位，必須濾掉
        if title in ("Deleted video", "Private video", "已刪除的影片", "私人影片"):
            continue
        items.append({
            "raw_title": title,
            "channel": (snippet.get("videoOwnerChannelTitle")
                        or snippet.get("channelTitle") or ""),
            "video_id": ((snippet.get("resourceId") or {}).get("videoId") or ""),
        })
    if not items:
        raise PlaylistNotAccessible(playlist_id)
    return items


async def fetch_video_items(video_id: str, api_key: Optional[str] = None) -> List[Dict]:
    """單曲版的 fetch_playlist_items：videos.list 只花 1 點，回傳同樣的 [{raw_title,...}]。

    讀不到（私人／已刪除／年齡限制下架）就拋 PlaylistNotAccessible，錯誤處理與歌單共用。
    """
    if not is_live():
        return _stub_video(video_id)

    settings = get_settings()
    api_key = api_key or settings.youtube_keys[0]
    try:
        data = await get_json(
            f"{API_BASE}/videos",
            params={"part": "snippet", "id": video_id, "key": api_key},
        )
    except httpx.HTTPStatusError as error:
        if _quota_error(error):
            raise QuotaExceeded("YouTube 每日配額已用盡") from error
        if error.response is not None and error.response.status_code in (400, 403, 404):
            raise PlaylistNotAccessible(video_id) from error
        raise

    # videos.list 對讀不到的影片是回空 items，不是 404
    for entry in data.get("items", []):
        snippet = entry.get("snippet") or {}
        title = snippet.get("title") or ""
        if not title:
            continue
        return [{
            "raw_title": title,
            "channel": snippet.get("channelTitle") or "",
            "video_id": entry.get("id") or video_id,
        }]
    raise PlaylistNotAccessible(video_id)


async def search_video(artist: str, title: str, api_key: Optional[str] = None) -> Optional[Dict]:
    """search.list(type=video, videoEmbeddable=true, videoCategoryId=10, maxResults=3)。

    回傳 {video_id, title, channel, thumbnail, embeddable} 或 None；配額耗盡拋 QuotaExceeded。
    這支每次 100 點——呼叫前必須先過 VideoResolver 的快取與配額檢查。
    """
    if not is_live():
        return _stub_search(artist, title)

    settings = get_settings()
    api_key = api_key or settings.youtube_keys[0]
    try:
        data = await get_json(
            f"{API_BASE}/search",
            params={
                "part": "snippet",
                "q": f"{artist} {title}".strip(),
                "type": "video",
                "videoEmbeddable": "true",
                "videoCategoryId": "10",   # Music
                "maxResults": 3,
                "key": api_key,
            },
            retries=0,  # 100 點一次，不重試
        )
    except httpx.HTTPStatusError as error:
        if _quota_error(error):
            raise QuotaExceeded("YouTube 每日配額已用盡") from error
        log.warning("search.list 失敗：%s", error)
        return None

    for item in data.get("items", []):
        video_id = (item.get("id") or {}).get("videoId")
        if not video_id:
            continue
        snippet = item.get("snippet") or {}
        thumbnails = snippet.get("thumbnails") or {}
        thumbnail = (thumbnails.get("medium") or thumbnails.get("high")
                     or thumbnails.get("default") or {}).get("url", "")
        return {
            "video_id": video_id,
            "title": snippet.get("title", title),
            "channel": snippet.get("channelTitle", artist),
            "thumbnail": thumbnail or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "embeddable": True,  # 已用 videoEmbeddable=true 過濾
        }
    return None


# --- stub（內網開發用）------------------------------------------------------

def _stub_playlist(playlist_id: str) -> List[Dict]:
    if "private" in playlist_id.lower():
        raise PlaylistNotAccessible(playlist_id)
    if "empty" in playlist_id.lower():
        raise PlaylistNotAccessible(playlist_id)
    rows = []
    for entry in stub_data.stub_catalog()[:24]:
        rows.append({
            "raw_title": f"{entry['artist']} - {entry['title']} (Official Audio)",
            "channel": f"{entry['artist']} - Topic",
            "video_id": stub_data.stub_video_id(entry["artist"], entry["title"]),
        })
    return rows


def _stub_video(video_id: str) -> List[Dict]:
    if "private" in video_id.lower():
        raise PlaylistNotAccessible(video_id)
    catalog = stub_data.stub_catalog()
    entry = catalog[sum(ord(c) for c in video_id) % len(catalog)]
    return [{
        "raw_title": f"{entry['artist']} - {entry['title']} (Official Audio)",
        "channel": f"{entry['artist']} - Topic",
        "video_id": video_id,
    }]


def _stub_search(artist: str, title: str) -> Optional[Dict]:
    # 讓一部分候選查不到，好讓「丟棄補位」與 dropped 計數在內網也測得到
    video_id = stub_data.stub_video_id(artist, title)
    if stub_data.stub_popularity(artist, title) % 7 == 0:
        return None
    return {
        "video_id": video_id,
        "title": title,
        "channel": artist,
        "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "embeddable": True,
    }
