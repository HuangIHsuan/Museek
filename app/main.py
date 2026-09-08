"""Museek 後端進入點。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import get_settings
from app.core.quota import QuotaTracker
from app.db.repository import get_repository
from app.pwa import guess_install_url, qr_svg, render_install_page
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


@app.get("/sw.js", include_in_schema=False)
async def service_worker() -> FileResponse:
    """Service Worker 一定要從根路徑供應，否則管轄範圍只有 /static/。"""
    return FileResponse(
        f"{STATIC_DIR}/sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/install", include_in_schema=False)
async def install(request: Request, url: str | None = None) -> HTMLResponse:
    """掃 QR 把 Museek 加到 iPhone 主畫面的說明頁（app/pwa.py）。"""
    target, source = _install_target(request, url)
    return HTMLResponse(render_install_page(target, source))


def _install_target(request: Request, override: str | None) -> tuple[str, str]:
    """手機該連的網址。Cloud Run 之類的反向代理只在標頭裡講真正的 scheme。"""
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return guess_install_url(
        host=request.headers.get("host", ""),
        scheme=forwarded or request.url.scheme,
        override=override,
        configured=get_settings().public_base_url,
    )


# 掛在 /api/ 底下是刻意的：Service Worker 一律不快取 /api/，
# 換了網路、IP 變了也不會掃到上一次的舊網址（app/static/sw.js）。
@app.get("/api/install", include_in_schema=False)
async def install_info(request: Request, url: str | None = None) -> JSONResponse:
    """導覽列的 QR 彈窗要的東西：網址、來源、畫好的 SVG。"""
    target, source = _install_target(request, url)
    return JSONResponse(
        {"url": target, "source": source, "qr_svg": qr_svg(target) if target else None},
        headers={"Cache-Control": "no-store"},
    )
