"""Demo 前的快取預熱（§8 三層控管第 2 層）。

把熱門候選的 videoId 先查進 video_cache，Demo 當天每輪推薦就是 0 點配額。

用法：
    # 先看要花多少點，不真的呼叫
    python scripts/prewarm_cache.py --file data/prewarm.txt --dry-run
    # 實際執行，本批最多 80 次搜尋（8,000 點）
    python scripts/prewarm_cache.py --file data/prewarm.txt --limit 80

輸入檔一行一首，格式「歌手|歌名」，# 開頭為註解。

注意：
  * 分兩天跑（Day 5、Day 6），單日別超過 8,000 點，留 2,000 點給當天測試。
  * 沒設 MONGO_URL 的話快取只在記憶體裡，腳本一結束就沒了——預熱必須連真的 Mongo。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.core.normalize import cache_key
from app.core.quota import QuotaTracker
from app.db.repository import get_repository
from app.services import youtube
from app.services.http import close_client


def load_pairs(path: str):
    pairs = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" not in line:
                print(f"  ! 第 {line_number} 行格式不對，略過：{line}")
                continue
            artist, title = (part.strip() for part in line.split("|", 1))
            if artist and title:
                pairs.append((artist, title))
    return pairs


async def run(path: str, limit: int, dry_run: bool) -> int:
    settings = get_settings()
    pairs = load_pairs(path)
    repo = await get_repository()
    quota = QuotaTracker(repo)

    if repo.kind != "mongo":
        print("！儲存是記憶體版，預熱結果不會保留。請先設定 MONGO_URL 再跑。")
        if not dry_run:
            return 1
    if not youtube.is_live() and not dry_run:
        print("！沒有設定 YOUTUBE_API_KEY，這樣預熱到的是 stub 假資料。")
        return 1

    cached = await repo.get_videos([cache_key(a, t) for a, t in pairs])
    todo = [(a, t) for a, t in pairs if cache_key(a, t) not in cached]

    print(f"清單 {len(pairs)} 首｜已快取 {len(cached)} 首｜待查 {len(todo)} 首")
    planned = min(len(todo), limit)
    print(f"本批預計查 {planned} 首，約 {planned * settings.quota_cost_search} 點"
          f"（當日已用 {await quota.used()} / {settings.quota_daily_limit}）")
    if dry_run:
        print("dry-run，沒有實際呼叫。")
        return 0

    found = missing = 0
    for artist, title in todo[:planned]:
        if not await quota.can_spend(settings.quota_cost_search):
            print("！配額不足，提前結束。")
            break
        try:
            video = await youtube.search_video(artist, title)
        except youtube.QuotaExceeded:
            print("！YouTube 回報配額耗盡，停止。")
            break
        await quota.spend(settings.quota_cost_search)
        key = cache_key(artist, title)
        if video:
            await repo.set_video(key, video)
            found += 1
            print(f"  ✓ {artist} - {title} → {video['video_id']}")
        else:
            await repo.set_video(key, {"video_id": "", "title": title, "channel": artist,
                                       "thumbnail": "", "embeddable": False})
            missing += 1
            print(f"  ✗ {artist} - {title}（查無可嵌入結果）")

    print(f"\n完成：命中 {found} 首、查無 {missing} 首，"
          f"當日累計 {await quota.used()} / {settings.quota_daily_limit} 點")
    await close_client()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Museek 快取預熱")
    parser.add_argument("--file", required=True, help="候選清單檔，一行一首「歌手|歌名」")
    parser.add_argument("--limit", type=int, default=80, help="本批最多查幾首（預設 80 = 8,000 點）")
    parser.add_argument("--dry-run", action="store_true", help="只估算配額，不實際呼叫")
    args = parser.parse_args()
    return asyncio.run(run(args.file, args.limit, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
