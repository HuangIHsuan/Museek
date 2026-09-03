"""MongoDB 資料存取（§6）。

本機沒有 Mongo 時自動退到記憶體實作，內網開發者不會被環境卡住；
退場時 /api/health 的 mongo 欄位會顯示 memory，不會假裝一切正常。
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.config import get_settings

log = logging.getLogger("museek.db")

VIDEO_CACHE_TTL_SECONDS = 30 * 24 * 3600  # YouTube 政策要求：快取最長 30 天


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class MemoryRepository:
    """記憶體版：介面與 MongoRepository 完全一致。

    video_cache 與 quota 會落檔到 data/cache.json——YouTube 配額每天只有 10,000 點
    且不可加購（§8），若每次重啟都要重新花 100 點/首去搜同一批歌，開發兩天就沒了。
    taste_profiles 不落檔（session 本來就是短命的）。
    """

    kind = "memory"
    CACHE_FILE = os.path.join("data", "cache.json")

    def __init__(self, persist: bool = True) -> None:
        self.profiles: Dict[str, Dict] = {}
        self.video_cache: Dict[str, Dict] = {}
        self.feature_cache: Dict[str, Dict] = {}
        self.quota: Dict[str, int] = {}
        self._persist = persist
        if persist:
            self._load()

    def _load(self) -> None:
        try:
            with open(self.CACHE_FILE, encoding="utf-8") as handle:
                data = json.load(handle)
            self.video_cache = data.get("video_cache") or {}
            self.feature_cache = data.get("feature_cache") or {}
            self.quota = data.get("quota") or {}
            log.info("已載入本機快取：%d 首影片、%d 首特徵",
                     len(self.video_cache), len(self.feature_cache))
        except FileNotFoundError:
            pass
        except Exception as error:  # noqa: BLE001 — 快取壞掉不該讓服務起不來
            log.warning("本機快取讀取失敗，改用空快取：%s", error)

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
            payload = {"video_cache": self.video_cache,
                       "feature_cache": self.feature_cache,
                       "quota": self.quota}
            temp = self.CACHE_FILE + ".tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, default=str)
            os.replace(temp, self.CACHE_FILE)
        except Exception as error:  # noqa: BLE001
            log.warning("本機快取寫入失敗：%s", error)

    async def ensure_indexes(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    # --- taste_profiles ---
    async def save_profile(self, doc: Dict) -> None:
        self.profiles[doc["session_id"]] = doc

    async def get_profile(self, session_id: str) -> Optional[Dict]:
        doc = self.profiles.get(session_id)
        if doc and doc.get("expires_at") and doc["expires_at"] < _utcnow():
            self.profiles.pop(session_id, None)
            return None
        return doc

    async def update_profile(self, session_id: str, fields: Dict) -> None:
        if session_id in self.profiles:
            self.profiles[session_id].update(fields)

    # --- video_cache ---
    async def get_video(self, key: str) -> Optional[Dict]:
        doc = self.video_cache.get(key)
        if doc and time.time() - doc.get("_cached_ts", 0) > VIDEO_CACHE_TTL_SECONDS:
            self.video_cache.pop(key, None)
            return None
        return doc

    async def get_videos(self, keys: List[str]) -> Dict[str, Dict]:
        result = {}
        for key in keys:
            doc = await self.get_video(key)
            if doc:
                result[key] = doc
        return result

    async def set_video(self, key: str, doc: Dict) -> None:
        self.video_cache[key] = {**doc, "_id": key, "cached_at": _utcnow(), "_cached_ts": time.time()}
        self._save()

    # --- feature_cache（非 YouTube 來源，長期保留）---
    async def get_features(self, keys: List[str]) -> Dict[str, Dict]:
        return {k: self.feature_cache[k] for k in keys if k in self.feature_cache}

    async def set_features(self, key: str, doc: Dict) -> None:
        self.feature_cache[key] = {**doc, "_id": key, "cached_at": _utcnow()}
        self._save()

    # --- quota ---
    async def get_quota_used(self, day: str) -> int:
        return self.quota.get(day, 0)

    async def add_quota_used(self, day: str, cost: int) -> None:
        self.quota[day] = self.quota.get(day, 0) + cost
        self._save()


class MongoRepository:
    kind = "mongo"

    def __init__(self, client, db_name: str) -> None:
        self._client = client
        self.db = client[db_name]

    async def ensure_indexes(self) -> None:
        # §6 索引
        await self.db.video_cache.create_index("cached_at", expireAfterSeconds=VIDEO_CACHE_TTL_SECONDS)
        await self.db.taste_profiles.create_index("expires_at", expireAfterSeconds=0)
        await self.db.taste_profiles.create_index("session_id", unique=True)

    async def ping(self) -> bool:
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def save_profile(self, doc: Dict) -> None:
        await self.db.taste_profiles.replace_one({"session_id": doc["session_id"]}, doc, upsert=True)

    async def get_profile(self, session_id: str) -> Optional[Dict]:
        return await self.db.taste_profiles.find_one({"session_id": session_id})

    async def update_profile(self, session_id: str, fields: Dict) -> None:
        await self.db.taste_profiles.update_one({"session_id": session_id}, {"$set": fields})

    async def get_video(self, key: str) -> Optional[Dict]:
        return await self.db.video_cache.find_one({"_id": key})

    async def get_videos(self, keys: List[str]) -> Dict[str, Dict]:
        cursor = self.db.video_cache.find({"_id": {"$in": keys}})
        return {doc["_id"]: doc async for doc in cursor}

    async def set_video(self, key: str, doc: Dict) -> None:
        await self.db.video_cache.replace_one(
            {"_id": key}, {**doc, "_id": key, "cached_at": _utcnow()}, upsert=True
        )

    async def get_features(self, keys: List[str]) -> Dict[str, Dict]:
        cursor = self.db.feature_cache.find({"_id": {"$in": keys}})
        return {doc["_id"]: doc async for doc in cursor}

    async def set_features(self, key: str, doc: Dict) -> None:
        await self.db.feature_cache.replace_one(
            {"_id": key}, {**doc, "_id": key, "cached_at": _utcnow()}, upsert=True
        )

    async def get_quota_used(self, day: str) -> int:
        doc = await self.db.quota.find_one({"_id": day})
        return int(doc.get("used", 0)) if doc else 0

    async def add_quota_used(self, day: str, cost: int) -> None:
        await self.db.quota.update_one({"_id": day}, {"$inc": {"used": cost}}, upsert=True)


_repo = None


async def get_repository():
    """啟動時呼叫一次。連不上 Mongo 且允許降級時回記憶體版。"""
    global _repo
    if _repo is not None:
        return _repo

    settings = get_settings()

    if settings.storage_backend == "firestore":
        from app.db.firestore_repo import FirestoreRepository, create_client

        client = await create_client(settings.gcp_project)
        repo = FirestoreRepository(client)
        await repo.ensure_indexes()
        log.info("使用 Firestore（專案 %s）", settings.gcp_project or "<預設>")
        _repo = repo
        return _repo

    if settings.storage_backend == "memory" or not settings.mongo_url:
        log.info("MONGO_URL 為空，直接使用記憶體儲存。")
        _repo = MemoryRepository()
        return _repo
    try:
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(settings.mongo_url, serverSelectionTimeoutMS=1500)
        await client.admin.command("ping")
        repo = MongoRepository(client, settings.mongo_db)
        await repo.ensure_indexes()
        log.info("已連上 MongoDB：%s/%s", settings.mongo_url, settings.mongo_db)
        _repo = repo
    except Exception as error:  # noqa: BLE001
        if not settings.allow_memory_fallback:
            raise
        log.warning("連不上 MongoDB（%s），改用記憶體儲存。快取不會跨重啟保留。", error)
        _repo = MemoryRepository()
    return _repo


def reset_repository() -> None:
    """測試用。"""
    global _repo
    _repo = None


def profile_expiry() -> datetime:
    return _utcnow() + timedelta(days=30)  # TTL 30 天
