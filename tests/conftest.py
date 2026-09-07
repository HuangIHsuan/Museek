"""測試環境隔離。

pydantic-settings 會讀取 .env，而環境變數優先於 .env——因此這裡把每一個
「會對外連線」的設定都明確設成安全值。少設一個，跑一次 pytest 就可能燒掉
真實 YouTube 配額或打到地端 LLM。這個檔案是那道防線。
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.services import http
from app.db.repository import MemoryRepository, reset_repository
from app.services.reccobeats import reset_artist_cache
from app.services.itunes import reset_genre_cache

SAFE_ENV = {
    "YOUTUBE_API_KEY": "",        # 空字串 = stub。不能用 delenv，那會讓 .env 的值浮上來
    "RECCOBEATS_MODE": "stub",
    "LLM_CHANNEL": "stub",
    "GATEWAY_BASE_URL": "",
    "GATEWAY_TOKEN": "",
    "ANTHROPIC_API_KEY": "",
    "GENRE_LOOKUP": "false",      # 曲風查詢會打 iTunes，測試一律關掉
    "ITUNES_PACE_SECONDS": "0",   # 直接呼叫 itunes 的測試不必等真實節流
    "MONGO_URL": "",              # 空 = 直接用記憶體版，不去連 Mongo
    "PUBLIC_BASE_URL": "",        # 空 = 讓 /install 自己判斷，不吃 .env 裡的正式網址
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """任何一個測試只要真的建了 HTTP client 就直接失敗。

    少擋一條路徑，測試就會安靜地打到外網——慢、不穩，而且會吃到對方的速率限制。
    """
    def refuse() -> None:
        raise AssertionError("測試不該對外連線：請把對應的服務函式 monkeypatch 掉")

    monkeypatch.setattr(http, "client", refuse)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    # 測試絕不能寫到真的 data/cache.json
    monkeypatch.setattr(MemoryRepository, "CACHE_FILE", str(tmp_path / "cache.json"))
    for key, value in SAFE_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    http.reset_pacers()       # 節流器把間隔記死在建立當下，換設定要重建
    reset_repository()
    reset_artist_cache()      # 歌手曲目清單是行程內快取，不清會跨測試污染
    reset_genre_cache()       # 曲風快取（依歌手名）同理
    yield
    get_settings.cache_clear()
    reset_repository()
    reset_artist_cache()
    reset_genre_cache()
