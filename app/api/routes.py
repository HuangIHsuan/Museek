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

# 私人歌單／解析失敗時給的退路（§9、§12）。正式清單由 T 策展後替換。
DEMO_PLAYLISTS = [
    {"name": "雨天通勤", "url": "https://www.youtube.com/playlist?list=DEMO_RAINY_COMMUTE"},
    {"name": "深夜獨處", "url": "https://www.youtube.com/playlist?list=DEMO_LATE_NIGHT"},
    {"name": "週末公路", "url": "https://www.youtube.com/playlist?list=DEMO_ROAD_TRIP"},
]


def _sse(event: str, data: Dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(source: AsyncGenerator[Tuple[str, Dict], None]) -> AsyncGenerator[str, None]:
    """把 pipeline 的 (event, payload) 轉成 SSE 文字；中途爆掉就送 error 事件收尾。"""
    try:
        async for event, payload in source:
            yield _sse(event, payload)
    except pipeline.SessionNotFound:
        yield _sse("error", {"code": "session_not_found", "message": "這個工作階段已過期，請重新解析歌單。"})
    except youtube.QuotaExceeded:
        yield _sse("error", {"code": "quota_exceeded",
                             "message": "今天的 YouTube 查詢額度已用完，改用快取中的曲目再試一次。"})
    except Exception as error:  # noqa: BLE001
        log.exception("串流過程發生未預期錯誤")
        yield _sse("error", {"code": "internal_error", "message": "服務暫時無法使用，請稍後再試。"})


def _sse_response(source) -> StreamingResponse:
    return StreamingResponse(
        _stream(source),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/session", response_model=SessionResponse)
async def create_session(payload: SessionRequest, request: Request) -> SessionResponse:
    repo = request.app.state.repo
    quota: QuotaTracker = request.app.state.quota
    try:
        result = await pipeline.create_session(repo, quota, payload.playlist_url)
    except InvalidPlaylistUrl as error:
        raise HTTPException(400, detail={"code": "invalid_url", "message": str(error),
                                         "hint": DEMO_PLAYLISTS}) from error
    except youtube.PlaylistNotAccessible as error:
        raise HTTPException(404, detail={
            "code": "playlist_not_accessible",
            "message": "這份歌單讀不到——可能是私人的、已刪除，或網址不完整。"
                       "改為公開，或試試示範歌單。",
            "hint": DEMO_PLAYLISTS,
        }) from error
    except youtube.QuotaExceeded as error:
        raise HTTPException(503, detail={"code": "quota_exceeded",
                                         "message": "今天的 YouTube 查詢額度已用完，請改試示範歌單。",
                                         "hint": DEMO_PLAYLISTS}) from error
    return SessionResponse(**result)


@router.post("/recommend")
async def recommend(payload: RecommendRequest, request: Request) -> StreamingResponse:
    return _sse_response(pipeline.recommend_stream(
        request.app.state.repo, request.app.state.quota, payload.session_id, payload.prompt
    ))


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
        quota_limit=settings.quota_daily_limit,
        cache_only=await quota.cache_only(),
    )


@router.get("/demo-playlists")
async def demo_playlists() -> Dict:
    return {"playlists": DEMO_PLAYLISTS}
