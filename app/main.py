"""Museek 後端進入點。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import get_settings
from app.core.quota import QuotaTracker
from app.db.repository import get_repository
from app.services.http import close_client
from app.services.llm import close_llm_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("museek")

STATIC_DIR = "app/static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.repo = await get_repository()
    app.state.quota = QuotaTracker(app.state.repo)
    log.info(
        "啟動完成｜儲存=%s｜YouTube=%s｜ReccoBeats=%s｜LLM=%s",
        app.state.repo.kind,
        "live" if settings.youtube_api_key else "stub",
        settings.reccobeats_mode,
        settings.llm_channel,
    )
    yield
    await close_client()
    await close_llm_client()


app = FastAPI(title="Museek API", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(f"{STATIC_DIR}/index.html")
