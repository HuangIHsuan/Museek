"""Firestore 儲存層（GCP 原生，Cloud Run 部署用）。

介面與 MongoRepository、MemoryRepository 完全一致，因此 pipeline 與 API 層不需要
知道底下是哪一種。開發文件 §6 寫的是 MongoDB；改用 Firestore 的取捨見 NOTES.md #20。

TTL：Firestore 的 TTL 政策是「欄位時間到就刪」，跟 Mongo 的 expireAfterSeconds
語意不同，所以這裡一律寫入明確的 expires_at 欄位，再由 TTL 政策掃除。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

log = logging.getLogger("museek.firestore")

VIDEO_CACHE_TTL_DAYS = 30      # YouTube 政策要求
PROFILE_TTL_DAYS = 30

COL_PROFILES = "taste_profiles"
COL_VIDEO = "video_cache"
COL_FEATURES = "feature_cache"
COL_QUOTA = "quota"


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class FirestoreRepository:
    kind = "firestore"

    def __init__(self, client) -> None:
        self.db = client

    # --- 生命週期 ---
    async def ensure_indexes(self) -> None:
        """Firestore 的 TTL 政策要用 gcloud／Console 設定，不能從 client SDK 建立。
        部署腳本 scripts/setup_firestore_ttl.sh 會處理，這裡只記錄狀態。"""
        log.info("Firestore TTL 政策由 scripts/setup_firestore_ttl.sh 設定")

    async def ping(self) -> bool:
        try:
            # 讀一個一定不存在的文件，能回應就代表連線正常。
            # 注意：Firestore 不接受雙底線開頭的文件 ID（保留字），不能用 __ping__
            await self.db.collection(COL_QUOTA).document("healthcheck").get()
            return True
        except Exception as error:  # noqa: BLE001
            log.warning("Firestore ping 失敗：%s", error)
            return False

    # --- taste_profiles ---
    async def save_profile(self, doc: Dict) -> None:
        payload = dict(doc)
        payload["expires_at"] = payload.get("expires_at") or (_utcnow() + timedelta(days=PROFILE_TTL_DAYS))
        await self.db.collection(COL_PROFILES).document(doc["session_id"]).set(_clean(payload))

    async def get_profile(self, session_id: str) -> Optional[Dict]:
        snapshot = await self.db.collection(COL_PROFILES).document(session_id).get()
        if not snapshot.exists:
            return None
        doc = snapshot.to_dict()
        expires = doc.get("expires_at")
        if isinstance(expires, datetime) and expires < _utcnow():
            return None      # TTL 掃除前先自行擋掉，避免回傳過期資料
        return doc

    async def update_profile(self, session_id: str, fields: Dict) -> None:
        await self.db.collection(COL_PROFILES).document(session_id).set(_clean(fields), merge=True)

    # --- video_cache ---
    async def get_video(self, key: str) -> Optional[Dict]:
        snapshot = await self.db.collection(COL_VIDEO).document(_doc_id(key)).get()
        return snapshot.to_dict() if snapshot.exists else None

    async def get_videos(self, keys: List[str]) -> Dict[str, Dict]:
        if not keys:
            return {}
        refs = [self.db.collection(COL_VIDEO).document(_doc_id(k)) for k in keys]
        result: Dict[str, Dict] = {}
        # AsyncClient.get_all() 回傳 async generator，不是 awaitable
        async for snapshot in self.db.get_all(refs):
            if snapshot.exists:
                doc = snapshot.to_dict()
                result[doc.get("_id", snapshot.id)] = doc
        return result

    async def set_video(self, key: str, doc: Dict) -> None:
        now = _utcnow()
        payload = {**doc, "_id": key, "cached_at": now,
                   "expires_at": now + timedelta(days=VIDEO_CACHE_TTL_DAYS)}
        await self.db.collection(COL_VIDEO).document(_doc_id(key)).set(_clean(payload))

    # --- feature_cache（非 YouTube 來源，長期保留，不設 TTL）---
    async def get_features(self, keys: List[str]) -> Dict[str, Dict]:
        if not keys:
            return {}
        refs = [self.db.collection(COL_FEATURES).document(_doc_id(k)) for k in keys]
        result: Dict[str, Dict] = {}
        async for snapshot in self.db.get_all(refs):
            if snapshot.exists:
                doc = snapshot.to_dict()
                result[doc.get("_id", snapshot.id)] = doc
        return result

    async def set_features(self, key: str, doc: Dict) -> None:
        payload = {**doc, "_id": key, "cached_at": _utcnow()}
        await self.db.collection(COL_FEATURES).document(_doc_id(key)).set(_clean(payload))

    # --- quota ---
    async def get_quota_used(self, day: str) -> int:
        snapshot = await self.db.collection(COL_QUOTA).document(day).get()
        return int((snapshot.to_dict() or {}).get("used", 0)) if snapshot.exists else 0

    async def add_quota_used(self, day: str, cost: int) -> None:
        from google.cloud.firestore_v1 import Increment

        await self.db.collection(COL_QUOTA).document(day).set(
            {"used": Increment(cost)}, merge=True
        )


def _doc_id(key: str) -> str:
    """Firestore 文件 ID 不能含 '/'，長度上限 1500 bytes。

    cache_key() 已經濾掉非文字字元，但外部來源難保，這裡再擋一次。
    """
    safe = (key or "_").replace("/", "_")
    if safe in (".", ".."):
        safe = "_"
    if safe.startswith("__"):
        safe = "u" + safe        # 雙底線開頭是 Firestore 保留字
    encoded = safe.encode("utf-8")[:1400]
    return encoded.decode("utf-8", errors="ignore") or "_"


def _clean(doc: Dict) -> Dict:
    """Firestore 不接受 None 以外的一些型別；datetime 要帶時區。"""
    cleaned = {}
    for key, value in doc.items():
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        cleaned[key] = value
    return cleaned


async def create_client(project_id: Optional[str] = None):
    from google.cloud.firestore import AsyncClient

    return AsyncClient(project=project_id) if project_id else AsyncClient()
