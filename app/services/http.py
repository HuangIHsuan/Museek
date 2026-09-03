"""共用 HTTP 客戶端：逾時 4 秒、失敗重試 1 次（§9）。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from app.config import get_settings

log = logging.getLogger("museek.http")
_client: Optional[httpx.AsyncClient] = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=get_settings().http_timeout)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def get_json(url: str, *, params: Any = None, headers: Any = None, retries: int = 1) -> Any:
    """GET 並回傳 JSON。逾時／5xx／429 重試指定次數，仍失敗就往上拋。"""
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            response = await client().get(url, params=params, headers=headers)
            if response.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(
                    f"{response.status_code} from {url}", request=response.request, response=response
                )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status is not None and status not in (429, 500, 502, 503, 504):
                raise  # 4xx 重試沒有意義
            last_error = error
            if attempt < retries:
                await asyncio.sleep(0.4 * (attempt + 1))
    assert last_error is not None
    raise last_error
