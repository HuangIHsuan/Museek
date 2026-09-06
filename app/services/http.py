"""共用 HTTP 客戶端：逾時 4 秒、失敗重試 1 次（§9）。

音訊分析那條路徑（下載試聽片段、上傳給 ReccoBeats）比一般 JSON 請求慢得多，
因此 get_bytes／post_file 都可以個別指定逾時，不受 4 秒的預設值限制。"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from app.config import get_settings

log = logging.getLogger("museek.http")


class Pacer:
    """限制對單一服務的送出速度。

    ReccoBeats 的限制數字不公開，但實測結果很明確：**瞬間併發才是問題，
    不是每秒總量**。同時丟 4 個就開始收 429，丟 8 個全滅；
    但均勻間隔的話 8 req/s 也全數通過。

    因此這裡管兩件事：兩次送出之間的最小間隔，以及同時在飛的上限。
    """

    def __init__(self, min_interval: float, max_inflight: int) -> None:
        self._min_interval = min_interval
        self._sem = asyncio.Semaphore(max_inflight)
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def __aenter__(self):
        await self._sem.acquire()
        async with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_at = now + self._min_interval
        return self

    async def __aexit__(self, *_exc) -> None:
        self._sem.release()

    async def back_off(self, seconds: float) -> None:
        """收到 429 之後，把所有後續請求往後推。"""
        async with self._lock:
            self._next_at = max(self._next_at, time.monotonic() + seconds)


# ReccoBeats 專用。保守值：5 req/s、最多 2 個同時在飛（實測 8 req/s 才開始有風險）
_pacers: dict = {}


def pacer(name: str, min_interval: float = 0.3, max_inflight: int = 2) -> Pacer:
    if name not in _pacers:
        _pacers[name] = Pacer(min_interval, max_inflight)
    return _pacers[name]
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


async def get_json(url: str, *, params: Any = None, headers: Any = None, retries: int = 1,
                   pace: Optional[Pacer] = None) -> Any:
    """GET 並回傳 JSON。逾時／5xx／429 重試指定次數，仍失敗就往上拋。

    pace 給定時，送出會受該服務的節流器管制；收到 429 會照 Retry-After 退避，
    並把後續請求一起往後推（ReccoBeats 文件明確要求這樣做）。
    """
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            if pace is not None:
                async with pace:
                    response = await client().get(url, params=params, headers=headers)
            else:
                response = await client().get(url, params=params, headers=headers)
            if response.status_code == 429:
                delay = _retry_after(response, attempt)
                if pace is not None:
                    await pace.back_off(delay)
                log.warning("%s 回 429，等待 %.1f 秒後重試", url, delay)
                last_error = httpx.HTTPStatusError(
                    "429", request=response.request, response=response)
                if attempt < retries:
                    await asyncio.sleep(delay)
                    continue
                raise last_error
            if response.status_code in (500, 502, 503, 504):
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


def _retry_after(response: "httpx.Response", attempt: int) -> float:
    """優先照 Retry-After，沒有才退回遞增退避。上限 30 秒，避免整條流程卡死。"""
    raw = response.headers.get("retry-after")
    if raw:
        try:
            return min(30.0, max(0.5, float(raw)))
        except ValueError:
            pass
    return min(30.0, 1.0 * (attempt + 1))


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
