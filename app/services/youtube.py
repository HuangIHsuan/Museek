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
    """當日配額耗盡。403 quotaExceeded，或 search.list 用完當日次數時的 429。"""


class ApiKeyRejected(Exception):
    """金鑰或所屬專案的設定有問題：API 沒啟用、金鑰被限制、金鑰無效。

    這也是 403，但和「歌單是私人的」是完全相反的兩件事：問題出在我們的
    金鑰，不在使用者貼的連結。混為一談的話，公開連結會被回報成
    「這個連結讀不到」，使用者換一百條連結都不會好。
    """


class SearchUnavailable(Exception):
    """search.list 這一趟打不通（逾時、5xx、非配額的 4xx）。

    和「查無此曲」是完全不同的事：查無此曲可以記進快取當結論，
    打不通不行——把服務故障寫成「這首歌沒有影片」，會讓那首歌在快取到期前
    再也不會被推薦。
    """


def is_live() -> bool:
    return bool(get_settings().youtube_keys)


_last_key_error: Optional[str] = None


def status() -> str:
    if not is_live():
        return "stub"
    return f"key_rejected（{_last_key_error}）" if _last_key_error else "ok"


# search.list 把當日次數用完時，Google 回的是 429 + rateLimitExceeded
# （"Quota exceeded for quota metric 'Search Queries'"），不是 403 quotaExceeded。
# 只認 403 的話，配額耗盡會被讀成「每一首都查不到」——熔斷不會跳、金鑰不會換，
# 而且每首歌都被寫進快取當作沒有影片。兩個狀態碼都要認。
_QUOTA_STATUS = (403, 429)
_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}

# 金鑰／專案層級的拒絕。Google 把原因放在 error.details[].reason（ErrorInfo），
# 舊版則放在 error.errors[].reason。兩邊都看。
_KEY_REASONS = {
    "SERVICE_DISABLED",             # 專案沒啟用 YouTube Data API v3
    "API_KEY_SERVICE_BLOCKED",      # 金鑰的「API 限制」沒勾到 YouTube Data API
    "API_KEY_INVALID",
    "API_KEY_HTTP_REFERRER_BLOCKED",
    "API_KEY_IP_ADDRESS_BLOCKED",
    "API_KEY_ANDROID_APP_BLOCKED",
    "API_KEY_IOS_APP_BLOCKED",
    "accessNotConfigured",
    "keyInvalid",
    "ipRefererBlocked",
}


def _error_body(error: httpx.HTTPStatusError) -> dict:
    if error.response is None:
        return {}
    try:
        body = error.response.json()["error"]
    except Exception:  # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}


def _reasons(error: httpx.HTTPStatusError) -> set:
    body = _error_body(error)
    found = {str(d.get("reason", "")) for d in body.get("details", []) if isinstance(d, dict)}
    return found | {str(e.get("reason", "")) for e in body.get("errors", []) if isinstance(e, dict)}


def _key_error(error: httpx.HTTPStatusError) -> bool:
    """403 是「我們的金鑰不能打這支 API」還是「這份歌單讀不到」？"""
    if error.response is None or error.response.status_code not in (400, 403):
        return False
    return bool(_reasons(error) & _KEY_REASONS)


def _key_reason(error: httpx.HTTPStatusError) -> str:
    """記下 Google 給的原因並回傳，之後 /api/health 與日誌都指得出是哪一種設定沒做。"""
    global _last_key_error
    reason = ", ".join(sorted(_reasons(error) & _KEY_REASONS)) or "forbidden"
    _last_key_error = reason
    log.error("YouTube 金鑰被拒（%s）：請確認專案已啟用 YouTube Data API v3，"
              "且金鑰的 API 限制有勾選它", reason)
    return reason


def _note_key_ok() -> None:
    """打得通就把上一次的拒絕清掉——設定改好之後 /api/health 要跟著恢復。"""
    global _last_key_error
    _last_key_error = None


def _quota_error(error: httpx.HTTPStatusError) -> bool:
    if error.response is None or error.response.status_code not in _QUOTA_STATUS:
        return False
    body = _error_body(error)
    if not body:
        return False
    if str(body.get("status", "")) == "RESOURCE_EXHAUSTED":
        return True
    reasons = {e.get("reason") for e in body.get("errors", [])}
    return bool(reasons & _QUOTA_REASONS)


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
        if _key_error(error):
            raise ApiKeyRejected(_key_reason(error)) from error
        # 400 = playlistId 格式無效、403 = 私人、404 = 不存在。
        # 三者對使用者都是同一件事：這份歌單讀不到，給友善提示請對方換連結。
        if error.response is not None and error.response.status_code in (400, 403, 404):
            raise PlaylistNotAccessible(playlist_id) from error
        raise
    _note_key_ok()

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
        if _key_error(error):
            raise ApiKeyRejected(_key_reason(error)) from error
        if error.response is not None and error.response.status_code in (400, 403, 404):
            raise PlaylistNotAccessible(video_id) from error
        raise
    _note_key_ok()

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

    回傳 {video_id, title, channel, thumbnail, embeddable}；查無此曲回 None。
    配額耗盡拋 QuotaExceeded，服務打不通拋 SearchUnavailable——None 只代表「真的查不到」。
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
        if _key_error(error):
            # 換金鑰救不了：設定沒改好，每一把都會撞同一道牆。直接往上拋。
            raise ApiKeyRejected(_key_reason(error)) from error
        log.warning("search.list 失敗：%s", error)
        raise SearchUnavailable(str(error)) from error
    except httpx.HTTPError as error:
        # 逾時、連線中斷同理：這是服務問題，不是「這首歌沒有影片」
        log.warning("search.list 連不上：%s", error)
        raise SearchUnavailable(str(error)) from error
    _note_key_ok()

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
