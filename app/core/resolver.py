"""Video Resolver（§2.2 D1 邏輯部分）。

快取查詢 → 配額檢查 → search.list → 丟棄補位 → 熔斷判斷。
search.list 一次 100 點，因此「不要呼叫」永遠是第一選項。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.config import get_settings
from app.core.normalize import cache_key
from app.core.quota import QuotaTracker
from app.services import youtube

log = logging.getLogger("museek.resolver")


@dataclass
class ResolveReport:
    resolved: List[Dict] = field(default_factory=list)
    dropped: int = 0            # 搜尋不到／不可嵌入而被丟棄（防幻覺機制）
    quota_spent: int = 0
    searches: int = 0
    cache_hits: int = 0
    cache_only: bool = False    # 是否處於熔斷（僅用快取）模式


class VideoResolver:
    def __init__(self, repo, quota: QuotaTracker) -> None:
        self._repo = repo
        self._quota = quota

    async def resolve(
        self,
        ranked: List[Dict],
        want: Optional[int] = None,
        budget: Optional[int] = None,
    ) -> ResolveReport:
        """依排名逐一驗證，湊滿 want 首為止。budget 是本輪最多幾次 search.list。"""
        settings = get_settings()
        want = want or settings.return_per_round
        budget = budget or settings.verify_per_round

        report = ResolveReport(cache_only=await self._quota.cache_only())
        if report.cache_only:
            log.warning("配額熔斷：本輪僅使用快取")

        for candidate in ranked:
            if len(report.resolved) >= want:
                break

            artist = candidate.get("artist", "")
            title = candidate.get("title", "")
            key = cache_key(artist, title)

            cached = await self._repo.get_video(key)
            if cached:
                report.cache_hits += 1
                if not cached.get("embeddable", True):
                    report.dropped += 1
                    continue
                report.resolved.append(self._merge(candidate, cached))
                continue

            # 沒快取：要花 100 點才知道結果
            if report.cache_only or report.searches >= budget:
                continue
            if not await self._quota.can_spend(settings.quota_cost_search):
                report.cache_only = True
                continue

            try:
                found = await youtube.search_video(artist, title)
            except youtube.QuotaExceeded:
                log.warning("YouTube 回報配額耗盡，本輪切換為僅用快取")
                report.cache_only = True
                continue

            report.searches += 1
            if youtube.is_live():
                report.quota_spent += settings.quota_cost_search
                await self._quota.spend(settings.quota_cost_search)

            if not found or not found.get("embeddable", True):
                # 搜尋不到／不可嵌入 → 丟棄並補下一名，使用者完全無感
                report.dropped += 1
                await self._repo.set_video(key, {
                    "video_id": "", "title": title, "channel": artist,
                    "thumbnail": "", "embeddable": False,
                })
                continue

            await self._repo.set_video(key, found)
            report.resolved.append(self._merge(candidate, found))

        return report

    @staticmethod
    def _merge(candidate: Dict, video: Dict) -> Dict:
        merged = dict(candidate)
        merged.update({
            "video_id": video.get("video_id", ""),
            "thumbnail": video.get("thumbnail", ""),
            "youtube_title": video.get("title", ""),
            "channel": video.get("channel", ""),
        })
        return merged


async def preload_from_cache(repo, candidates: List[Dict]) -> Tuple[Dict[str, Dict], int]:
    """批次撈快取，之後 resolve 逐首查時就不會來回打 DB。回傳 (快取表, 命中數)。"""
    keys = [cache_key(c.get("artist", ""), c.get("title", "")) for c in candidates]
    cached = await repo.get_videos(keys)
    return cached, len(cached)
