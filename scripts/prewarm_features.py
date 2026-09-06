"""批次預熱 feature_cache：用歌手一次撈整個曲庫，而不是一首一首搜。

為什麼值得做（實測，見 NOTES #40）：

    每首歌搜一次      1.04 次請求／首   ← 解析歌單時目前的做法
    用歌手一次撈      0.075 次請求／首  ← 這支腳本，效率差 14 倍

一次 artist/{id}/track 就回最多 100 首，audio-features 又能 40 個 id 一批。
歌單進來時只要有歌命中快取，那一首就完全不用對外——解析時間直接少掉。

用法：
    # 用專案內建的種子池歌手（98 位），先看會打幾次請求
    .venv/bin/python scripts/prewarm_features.py --dry-run

    # 實際跑，限制 20 位歌手
    .venv/bin/python scripts/prewarm_features.py --limit 20

    # 自訂歌手清單，一行一位
    .venv/bin/python scripts/prewarm_features.py --file artists.txt

注意：沒設 MONGO_URL／STORAGE_BACKEND 的話快取會落在 data/cache.json，
      腳本結束後仍在，但雲端讀不到——要讓線上受益必須指向線上的儲存。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.normalize import cache_key  # noqa: E402
from app.db.repository import get_repository  # noqa: E402
from app.services import reccobeats, seed_pool  # noqa: E402
from app.services.http import close_client  # noqa: E402

FEATURES_PER_BATCH = 40


def _same_artist(wanted: str, found: str) -> bool:
    """歌手比對。ReccoBeats 的 artist search 是模糊比對，會撈到完全不相干的人
    （實測搜 "Beach House" 回的是 "Sunset Chill"），所以撈回來要再確認一次。"""
    a, b = (wanted or "").strip().lower(), (found or "").strip().lower()
    return bool(a and b and (a in b or b in a))


async def warm_artist(repo, name: str, dry_run: bool) -> tuple:
    """回傳 (寫入首數, 請求次數, 說明)。"""
    artist_id = await reccobeats.search_artist(name)
    requests = 1
    if not artist_id:
        return 0, requests, "查無此歌手"

    tracks = await reccobeats.artist_tracks(artist_id)
    requests += 1
    tracks = [t for t in tracks if t.get("recco_id") and t.get("title")
              and _same_artist(name, t.get("artist", ""))]
    if not tracks:
        return 0, requests, "撈到的曲目對不上這位歌手"

    written = 0
    for start in range(0, len(tracks), FEATURES_PER_BATCH):
        chunk = tracks[start:start + FEATURES_PER_BATCH]
        if dry_run:
            requests += 1
            written += len(chunk)
            continue
        features = await reccobeats.get_audio_features([t["recco_id"] for t in chunk])
        requests += 1
        for track in chunk:
            feature = features.get(track["recco_id"])
            if not feature:
                continue
            await repo.set_features(cache_key(track["artist"], track["title"]), {
                "recco_id": track["recco_id"], "seed_id": None, "features": feature,
                "popularity": track.get("popularity"), "source": "reccobeats",
            })
            written += 1
    return written, requests, ""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="歌手清單，一行一位。預設用專案的種子池")
    parser.add_argument("--limit", type=int, default=0, help="最多處理幾位歌手")
    parser.add_argument("--dry-run", action="store_true", help="只估算請求數，不寫快取")
    args = parser.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as handle:
            names = [l.strip() for l in handle if l.strip() and not l.startswith("#")]
    else:
        names = seed_pool.artists()
    if args.limit:
        names = names[:args.limit]

    repo = await get_repository()
    print(f"儲存後端：{repo.kind}｜歌手 {len(names)} 位"
          f"{'｜dry-run，不寫入' if args.dry_run else ''}\n")

    total_written = total_requests = 0
    for index, name in enumerate(names, start=1):
        try:
            written, requests, note = await warm_artist(repo, name, args.dry_run)
        except Exception as error:  # noqa: BLE001
            print(f"  [{index:>3}/{len(names)}] {name:28s} 失敗：{str(error)[:60]}")
            continue
        total_written += written
        total_requests += requests
        detail = note or f"{written} 首"
        print(f"  [{index:>3}/{len(names)}] {name:28s} {detail}")

    per_track = total_requests / total_written if total_written else 0
    print(f"\n合計：{total_written} 首特徵、{total_requests} 次請求"
          f"（每首 {per_track:.3f} 次）")
    if args.dry_run:
        print("這是 dry-run，沒有寫入任何快取。")
    await close_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
