"""YouTube 配額計數與熔斷（§8）。

每日 10,000 點、太平洋時間午夜重置、不可加購。超過 quota_circuit_breaker 就切
「僅用快取」模式，/api/health 會顯示。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import get_settings

log = logging.getLogger("museek.quota")

try:  # macOS／Linux 有系統 tz database
    from zoneinfo import ZoneInfo
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - 沒有 tzdata 時退回固定 -8（誤差僅在夏令時間切換日）
    _PACIFIC = timezone(timedelta(hours=-8))


def pacific_day() -> str:
    return datetime.now(tz=_PACIFIC).strftime("%Y-%m-%d")


class QuotaTracker:
    """用量寫在 repository（Mongo 或記憶體），程序重啟不會把已用配額歸零。"""

    def __init__(self, repo) -> None:
        self._repo = repo
        self._day: Optional[str] = None
        self._used = 0

    async def _sync(self) -> None:
        today = pacific_day()
        if self._day != today:
            self._day = today
            self._used = await self._repo.get_quota_used(today)

    async def used(self) -> int:
        await self._sync()
        return self._used

    async def spend(self, cost: int) -> int:
        await self._sync()
        self._used += cost
        await self._repo.add_quota_used(self._day, cost)
        return self._used

    async def can_spend(self, cost: int) -> bool:
        settings = get_settings()
        return (await self.used()) + cost <= settings.quota_daily_limit

    async def cache_only(self) -> bool:
        """熔斷：當日用量超過門檻後只回傳快取內已有 videoId 的候選。"""
        settings = get_settings()
        return (await self.used()) >= settings.quota_circuit_breaker
