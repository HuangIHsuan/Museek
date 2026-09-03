"""把 data/cache.json 的內容搬進 MongoDB。

記憶體版落檔（video_cache／feature_cache／quota）在切換到 Mongo 時不會自動帶過去。
配額計數尤其重要——不搬的話帳會歸零，之後就低估當日實際用量。

用法：  .venv/bin/python scripts/migrate_cache_to_mongo.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.db.repository import MemoryRepository  # noqa: E402


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.now(tz=timezone.utc)


async def main() -> int:
    settings = get_settings()
    if not settings.mongo_url:
        print("MONGO_URL 是空的，沒有目標可以搬。")
        return 1

    try:
        with open(MemoryRepository.CACHE_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        print(f"找不到 {MemoryRepository.CACHE_FILE}，不需要搬移。")
        return 0

    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(settings.mongo_url, serverSelectionTimeoutMS=3000)
    await client.admin.command("ping")
    db = client[settings.mongo_db]

    videos = data.get("video_cache") or {}
    for key, doc in videos.items():
        doc = {k: v for k, v in doc.items() if k != "_cached_ts"}
        doc["_id"] = key
        doc["cached_at"] = _as_datetime(doc.get("cached_at"))
        await db.video_cache.replace_one({"_id": key}, doc, upsert=True)

    features = data.get("feature_cache") or {}
    for key, doc in features.items():
        doc = dict(doc)
        doc["_id"] = key
        doc["cached_at"] = _as_datetime(doc.get("cached_at"))
        await db.feature_cache.replace_one({"_id": key}, doc, upsert=True)

    # 配額取兩邊較大值，避免重跑這支腳本把已用量洗掉
    quota = data.get("quota") or {}
    for day, used in quota.items():
        existing = await db.quota.find_one({"_id": day})
        current = int(existing.get("used", 0)) if existing else 0
        if int(used) > current:
            await db.quota.update_one({"_id": day}, {"$set": {"used": int(used)}}, upsert=True)

    print(f"已搬移：video_cache {len(videos)} 筆、feature_cache {len(features)} 筆、"
          f"quota {len(quota)} 天")
    print("提醒：實際 Google 端用量請以 GCP Console 為準（見 NOTES.md #2）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
