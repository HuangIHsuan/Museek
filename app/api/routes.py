"""五支 API 端點（§4）。SSE 事件格式與文件逐字對齊。"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Dict, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.core import pipeline
from app.core.normalize import InvalidPlaylistUrl
from app.core.quota import QuotaTracker
from app.models import (
    FeedbackRequest,
    HealthResponse,
    RecommendRequest,
    SessionRequest,
    SessionResponse,
)
from app.services import llm, reccobeats, youtube

log = logging.getLogger("museek.api")
router = APIRouter(prefix="/api")

_KEY_REJECTED_MESSAGE = (
    "伺服器的 YouTube 金鑰被 Google 拒絕，目前讀不到任何連結。這不是你貼的連結的問題——"
    "請管理員到 Google Cloud 主控台確認專案已啟用 YouTube Data API v3，"
    "且金鑰的「API 限制」有勾選它。"
)


def _sse(event: str, data: Dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(source: AsyncGenerator[Tuple[str, Dict], None]) -> AsyncGenerator[str, None]:
    """把 pipeline 的 (event, payload) 轉成 SSE 文字；中途爆掉就送 error 事件收尾。"""
    try:
        async for event, payload in source:
            yield _sse(event, payload)
    except pipeline.SessionNotFound:
        yield _sse("error", {"code": "session_not_found", "message": "這個工作階段已過期，請重新解析連結。"})
    except youtube.QuotaExceeded:
        yield _sse("error", {"code": "quota_exceeded",
                             "message": "今天的 YouTube 查詢額度已用完，改用快取中的曲目再試一次。"})
    except youtube.ApiKeyRejected as error:
        log.error("YouTube 金鑰被拒，串流中止：%s", error)
        yield _sse("error", {"code": "youtube_key_rejected", "message": _KEY_REJECTED_MESSAGE})
    except Exception as error:  # noqa: BLE001
        log.exception("串流過程發生未預期錯誤")
        yield _sse("error", {"code": "internal_error", "message": "服務暫時無法使用，請稍後再試。"})


def _sse_response(source) -> StreamingResponse:
    return StreamingResponse(
        _stream(source),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# 解析歌單要逐首查音訊特徵，50 首實測 70 秒以上。帶 Accept: text/event-stream
# 的呼叫端會收到逐首的進度事件；其餘呼叫端維持原本的一次性 JSON，契約不變。
_SESSION_ERRORS = {
    InvalidPlaylistUrl: (400, "invalid_url", None),
    youtube.PlaylistNotAccessible: (
        404, "playlist_not_accessible",
        "這個連結讀不到——歌單或影片可能是私人的、已刪除，或網址不完整。"
        "請改為公開連結，或換一份歌單／一首歌再試。"),
    youtube.ApiKeyRejected: (503, "youtube_key_rejected", _KEY_REJECTED_MESSAGE),
    youtube.QuotaExceeded: (503, "quota_exceeded", "今天的 YouTube 查詢額度已用完，請稍後再試。"),
}


async def _session_progress(source) -> AsyncGenerator[str, None]:
    """把建立工作階段的過程轉成 SSE。錯誤改用 error 事件送，不能再拋 HTTP 狀態碼。"""
    try:
        async for event, data in source:
            yield _sse(event, data)
    except tuple(_SESSION_ERRORS) as error:
        _status, code, message = _SESSION_ERRORS[type(error)]
        yield _sse("error", {"code": code, "message": message or str(error)})
    except Exception:  # noqa: BLE001
        log.exception("建立工作階段時發生未預期錯誤")
        yield _sse("error", {"code": "internal_error", "message": "服務暫時無法使用，請稍後再試。"})


@router.post("/session")
async def create_session(payload: SessionRequest, request: Request):
    repo = request.app.state.repo
    quota: QuotaTracker = request.app.state.quota

    if "text/event-stream" in (request.headers.get("accept") or ""):
        return StreamingResponse(
            _session_progress(pipeline.create_session_stream(repo, quota, payload.playlist_url)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                     "X-Accel-Buffering": "no"},
        )

    try:
        result = await pipeline.create_session(repo, quota, payload.playlist_url)
    except InvalidPlaylistUrl as error:
        raise HTTPException(400, detail={"code": "invalid_url", "message": str(error)}) from error
    except youtube.PlaylistNotAccessible as error:
        raise HTTPException(404, detail={
            "code": "playlist_not_accessible",
            "message": "這個連結讀不到——歌單或影片可能是私人的、已刪除，或網址不完整。"
                       "請改為公開連結，或換一份歌單／一首歌再試。",
        }) from error
    except youtube.ApiKeyRejected as error:
        # 這也是 403，但和「歌單是私人的」正好相反：問題在我們的金鑰，
        # 使用者換多少條公開連結都不會好。訊息要說清楚是哪一邊壞掉。
        raise HTTPException(503, detail={"code": "youtube_key_rejected",
                                         "message": _KEY_REJECTED_MESSAGE}) from error
    except youtube.QuotaExceeded as error:
        raise HTTPException(503, detail={"code": "quota_exceeded",
                                         "message": "今天的 YouTube 查詢額度已用完，請稍後再試。"}) from error
    return SessionResponse(**result)


@router.post("/recommend")
async def recommend(payload: RecommendRequest, request: Request) -> StreamingResponse:
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(400, detail={"code": "empty_prompt", "message": "請描述你現在想聽的氛圍。"})
    repo, quota = request.app.state.repo, request.app.state.quota
    if not payload.session_id:
        # 沒有歌單也推得動：情境交給 LLM 讀出氛圍，再從那裡找起點
        return _sse_response(pipeline.vibe_recommend_stream(repo, quota, prompt))
    return _sse_response(pipeline.recommend_stream(repo, quota, payload.session_id, prompt))


@router.post("/feedback")
async def feedback(payload: FeedbackRequest, request: Request) -> StreamingResponse:
    if payload.vote not in ("up", "down"):
        raise HTTPException(400, detail={"code": "bad_vote", "message": "vote 只能是 up 或 down。"})
    return _sse_response(pipeline.feedback_stream(
        request.app.state.repo, request.app.state.quota,
        payload.session_id, payload.video_id, payload.vote
    ))


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = get_settings()
    repo = request.app.state.repo
    quota: QuotaTracker = request.app.state.quota
    storage_ok = await repo.ping()
    return HealthResponse(
        youtube=youtube.status(),
        reccobeats=reccobeats.last_status(),
        llm=llm.status(),
        # mongo 欄位是前端凍結契約的一部分，這裡回報「目前儲存後端健不健康」，
        # 實際用的是哪一種看 storage 欄位（memory／mongo／firestore）。
        mongo=("ok" if storage_ok else "down") if repo.kind != "memory" else "memory",
        storage=repo.kind,
        quota_used=await quota.used(),
        quota_limit=await quota.limit(),
        cache_only=await quota.cache_only(),
        quota_keys=await quota.breakdown(),
        active_key=await quota.active_index(),
    )
