"""共用 HTTP 客戶端：逾時 4 秒、失敗重試 1 次（§9）。

音訊分析那條路徑（下載試聽片段、上傳給 ReccoBeats）比一般 JSON 請求慢得多，
因此 get_bytes／post_file 都可以個別指定逾時，不受 4 秒的預設值限制。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from app.config import get_settings

log = logging.getLogger("museek.http")
_client: Optional[httpx.AsyncClient] = None


class PayloadTooLarge(Exception):
    """下載內容超過呼叫端給的上限，已中止。"""


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


async def get_bytes(url: str, *, max_bytes: int, timeout: Optional[float] = None) -> bytes:
    """下載二進位內容。邊收邊計量，超過 max_bytes 立刻中止——避免被沒有上限的檔案拖垮。"""
    chunks: list = []
    total = 0
    async with client().stream("GET", url, timeout=timeout, follow_redirects=True) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise PayloadTooLarge(f"{url} 超過 {max_bytes} bytes")
            chunks.append(chunk)
    return b"".join(chunks)


async def post_file(url: str, *, field: str, filename: str, content: bytes,
                    content_type: str, timeout: Optional[float] = None) -> Any:
    """multipart/form-data 上傳單一檔案並回傳 JSON。不重試——重傳幾 MB 的成本太高。"""
    response = await client().post(
        url, files={field: (filename, content, content_type)}, timeout=timeout
    )
    response.raise_for_status()
    return response.json()
