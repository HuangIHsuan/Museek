"""金鑰／專案設定被拒 vs. 連結真的讀不到——兩種 403 不能混為一談。

實際踩到的狀況：專案沒啟用 YouTube Data API v3，Google 對每一支端點都回
403 PERMISSION_DENIED（SERVICE_DISABLED／API_KEY_SERVICE_BLOCKED）。
舊的判斷把 403 一律讀成「私人歌單」，於是貼公開單曲連結會拿到
「這個連結讀不到」——使用者照著提示換連結，換幾次都不會好。
"""
from __future__ import annotations

import httpx
import pytest

from app.services import youtube

REQUEST = httpx.Request("GET", "https://www.googleapis.com/youtube/v3/videos")


def _status_error(status: int, body: dict) -> httpx.HTTPStatusError:
    response = httpx.Response(status, json=body, request=REQUEST)
    return httpx.HTTPStatusError(str(status), request=REQUEST, response=response)


SERVICE_DISABLED = {"error": {
    "code": 403, "status": "PERMISSION_DENIED",
    "message": "YouTube Data API v3 has not been used in project 1 before or it is disabled.",
    "errors": [{"reason": "accessNotConfigured"}],
    "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SERVICE_DISABLED"}],
}}

KEY_BLOCKED = {"error": {
    "code": 403, "status": "PERMISSION_DENIED",
    "message": "Requests to this API youtube method ... are blocked.",
    "errors": [{"reason": "forbidden"}],
    "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                 "reason": "API_KEY_SERVICE_BLOCKED"}],
}}

PRIVATE_PLAYLIST = {"error": {
    "code": 403, "status": "PERMISSION_DENIED",
    "errors": [{"reason": "playlistItemsNotAccessible"}],
}}


def test_key_error_recognises_both_shapes():
    assert youtube._key_error(_status_error(403, SERVICE_DISABLED)) is True
    assert youtube._key_error(_status_error(403, KEY_BLOCKED)) is True


def test_private_playlist_is_not_a_key_error():
    """真正的私人歌單還是要走「換一份連結」那條路，不能被誤判成設定壞掉。"""
    assert youtube._key_error(_status_error(403, PRIVATE_PLAYLIST)) is False
    assert youtube._key_error(_status_error(404, {"error": {"errors": [{"reason": "playlistNotFound"}]}})) is False


def test_key_error_is_not_mistaken_for_quota():
    """配額耗盡要熔斷換金鑰，設定被拒換金鑰沒有用——兩者不能互相誤判。"""
    assert youtube._quota_error(_status_error(403, SERVICE_DISABLED)) is False
    assert youtube._quota_error(_status_error(403, KEY_BLOCKED)) is False


def _live(monkeypatch, error: httpx.HTTPStatusError):
    monkeypatch.setattr(youtube, "is_live", lambda: True)

    class _Settings:
        youtube_keys = ["key-alpha"]

    monkeypatch.setattr(youtube, "get_settings", lambda: _Settings())

    async def _raise(*args, **kwargs):
        raise error

    monkeypatch.setattr(youtube, "get_json", _raise)


async def test_fetch_video_items_raises_api_key_rejected(monkeypatch):
    _live(monkeypatch, _status_error(403, SERVICE_DISABLED))
    with pytest.raises(youtube.ApiKeyRejected):
        await youtube.fetch_video_items("dQw4w9WgXcQ")


async def test_fetch_playlist_items_raises_api_key_rejected(monkeypatch):
    _live(monkeypatch, _status_error(403, KEY_BLOCKED))
    with pytest.raises(youtube.ApiKeyRejected):
        await youtube.fetch_playlist_items("PLreal")


async def test_search_video_raises_api_key_rejected(monkeypatch):
    """search 也一樣：換下一把金鑰撞的是同一道牆，不該被當成暫時性故障。"""
    _live(monkeypatch, _status_error(403, KEY_BLOCKED))
    with pytest.raises(youtube.ApiKeyRejected):
        await youtube.search_video("Rick Astley", "Never Gonna Give You Up")


async def test_private_video_still_raises_playlist_not_accessible(monkeypatch):
    _live(monkeypatch, _status_error(403, PRIVATE_PLAYLIST))
    with pytest.raises(youtube.PlaylistNotAccessible):
        await youtube.fetch_video_items("dQw4w9WgXcQ")


async def test_status_reports_key_rejection_then_recovers(monkeypatch):
    monkeypatch.setattr(youtube, "_last_key_error", None)
    _live(monkeypatch, _status_error(403, SERVICE_DISABLED))
    with pytest.raises(youtube.ApiKeyRejected):
        await youtube.fetch_video_items("dQw4w9WgXcQ")
    assert youtube.status().startswith("key_rejected")

    async def _ok(*args, **kwargs):
        return {"items": [{"id": "dQw4w9WgXcQ",
                           "snippet": {"title": "Rick Astley - Never Gonna Give You Up",
                                       "channelTitle": "Rick Astley"}}]}

    monkeypatch.setattr(youtube, "get_json", _ok)
    await youtube.fetch_video_items("dQw4w9WgXcQ")
    assert youtube.status() == "ok"
