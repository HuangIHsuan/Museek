"""YouTube 配額計數、金鑰輪替與熔斷（§8）。

每把金鑰各自有每日 10,000 點、太平洋時間午夜重置、不可加購。
設定多把金鑰時，一把用盡就換下一把；全部用盡才熔斷成「僅用快取」。

⚠️ 多金鑰輪替是跨多個 GCP 專案取用配額。Google 的 API 條款將此視為規避配額，
   可能導致清單裡每一把金鑰、以及它們所屬的專案一併被撤銷。
   這個模組把每把的用量分開記錄並顯示在 /api/health，讓這件事是看得見的。
   詳見 NOTES.md #37。
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.config import get_settings

log = logging.getLogger("museek.quota")

try:  # macOS／Linux 有系統 tz database
    from zoneinfo import ZoneInfo
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - 沒有 tzdata 時退回固定 -8
    _PACIFIC = timezone(timedelta(hours=-8))


def pacific_day() -> str:
    return datetime.now(tz=_PACIFIC).strftime("%Y-%m-%d")


def key_id(key: str) -> str:
    """金鑰的短指紋。用它當儲存的 key，不要把金鑰本身寫進資料庫。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


class QuotaTracker:
    """用量寫在 repository，程序重啟不會把已用配額歸零。

    儲存的文件 id 是 "<太平洋日期>#<金鑰指紋>"，因此每把金鑰各記各的，
    也不需要改動 repository 的介面。
    """

    # 用量快取的存活秒數。設 0 等於每次都重讀。
    #
    # 為什麼需要這個：多個 Cloud Run 執行個體各自持有一份用量快取，
    # 只在跨日時重讀的話，彼此看不到對方花掉的配額，會一起超花。
    # 短 TTL 讓漂移有上界，又不必每次呼叫都打資料庫。
    REFRESH_SECONDS = 5.0

    def __init__(self, repo, keys: Optional[List[str]] = None) -> None:
        self._repo = repo
        self._keys = keys if keys is not None else get_settings().youtube_keys
        self._day: Optional[str] = None
        self._used: Dict[str, int] = {}
        self._synced_at = 0.0

    # --- 內部 ---

    def _doc_id(self, key: str) -> str:
        return f"{self._day}#{key_id(key)}"

    async def _sync(self, force: bool = False) -> None:
        today = pacific_day()
        fresh = (self._day == today
                 and time.monotonic() - self._synced_at < self.REFRESH_SECONDS)
        if fresh and not force:
            return
        self._day = today
        self._synced_at = time.monotonic()
        for key in self._keys:
            self._used[key] = await self._repo.get_quota_used(self._doc_id(key))

    async def refresh(self) -> None:
        """強制重讀用量。測試與需要精確數字的地方用。"""
        await self._sync(force=True)

    # --- 對外 ---

    async def active_key(self) -> Optional[str]:
        """回傳目前該用的金鑰：第一把還有餘額的。全部用盡回 None。"""
        await self._sync()
        limit = get_settings().quota_daily_limit
        for key in self._keys:
            if self._used.get(key, 0) < limit:
                return key
        return None

    async def active_index(self) -> int:
        """目前用第幾把（從 1 開始）。全部用盡回 0。"""
        key = await self.active_key()
        return self._keys.index(key) + 1 if key else 0

    async def used(self) -> int:
        """所有金鑰的當日用量總和。"""
        await self._sync()
        return sum(self._used.values())

    async def limit(self) -> int:
        """所有金鑰的當日上限總和。"""
        return get_settings().quota_daily_limit * max(1, len(self._keys))

    async def breakdown(self) -> List[Dict]:
        """每把金鑰的用量明細，供 /api/health 顯示。"""
        await self._sync()
        limit = get_settings().quota_daily_limit
        active = await self.active_key()
        return [
            {
                "key": key_id(key),          # 只顯示指紋，不顯示金鑰本身
                "used": self._used.get(key, 0),
                "limit": limit,
                "exhausted": self._used.get(key, 0) >= limit,
                "active": key == active,
            }
            for key in self._keys
        ]

    async def spend(self, cost: int, key: Optional[str] = None) -> int:
        """記錄用量。沒指定 key 就記在目前使用中的那一把上。"""
        await self._sync()
        target = key or await self.active_key()
        if target is None:
            return await self.used()
        self._used[target] = self._used.get(target, 0) + cost
        await self._repo.add_quota_used(self._doc_id(target), cost)
        return sum(self._used.values())

    async def mark_exhausted(self, key: str) -> None:
        """YouTube 回報某把金鑰配額耗盡時呼叫，直接把它記到上限，換下一把。"""
        await self._sync()
        limit = get_settings().quota_daily_limit
        already = self._used.get(key, 0)
        if already < limit:
            await self._repo.add_quota_used(self._doc_id(key), limit - already)
            self._used[key] = limit
        remaining = len(self._keys) - await self._exhausted_count()
        log.warning("金鑰 %s 配額耗盡，剩餘可用金鑰 %d 把", key_id(key), remaining)

    async def _exhausted_count(self) -> int:
        limit = get_settings().quota_daily_limit
        return sum(1 for k in self._keys if self._used.get(k, 0) >= limit)

    async def can_spend(self, cost: int) -> bool:
        """還有沒有金鑰付得起這筆。沒有設定任何金鑰時代表走 stub，不消耗配額。"""
        await self._sync()
        if not self._keys:
            return True
        limit = get_settings().quota_daily_limit
        key = await self.active_key()
        return key is not None and self._used.get(key, 0) + cost <= limit

    async def cache_only(self) -> bool:
        """熔斷：所有金鑰都越過門檻後，只回傳快取內已有 videoId 的候選。

        單金鑰時等同原本的行為；多金鑰時要每一把都過門檻才熔斷。
        """
        await self._sync()
        if not self._keys:
            return False
        breaker = get_settings().quota_circuit_breaker
        return all(self._used.get(k, 0) >= breaker for k in self._keys)
