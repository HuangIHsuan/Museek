"""Day 1 凍結的 JSON 契約（開發文件 §3）。改這裡等於改契約，需經專案窗口同意。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# --- 品味向量的六個維度（§5.1）---
FEATURE_KEYS = ["energy", "valence", "danceability", "acousticness", "instrumentalness", "tempo"]
FEATURE_WEIGHTS = {
    "energy": 1.0,
    "valence": 1.0,
    "danceability": 0.8,
    "acousticness": 0.8,
    "instrumentalness": 0.5,
    "tempo": 0.6,
}


class Constraints(BaseModel):
    energy_max: Optional[float] = None
    energy_min: Optional[float] = None
    valence_max: Optional[float] = None
    valence_min: Optional[float] = None
    tempo_range: Optional[List[float]] = None
    acousticness_min: Optional[float] = None
    acousticness_max: Optional[float] = None


class Intent(BaseModel):
    """§3.3 Intent JSON。無法判斷的欄位給 None，不臆測。"""
    mood: Optional[str] = None
    activity: Optional[str] = None
    constraints: Constraints = Field(default_factory=Constraints)
    reference_artists: List[str] = Field(default_factory=list)
    avoid: List[str] = Field(default_factory=list)
    exploration: Optional[str] = None


class Score(BaseModel):
    similarity: float
    band: float
    context_fit: float
    novelty: float
    final: float


class TrackResult(BaseModel):
    """§3.2 推薦結果 JSON（前端契約，凍結）"""
    video_id: str
    title: str
    artist: str
    thumbnail: str
    reason: str
    features: Dict[str, float]
    score: Score


# --- API 端點的輸入輸出（§4）---

class SessionRequest(BaseModel):
    playlist_url: str


class ProfilePayload(BaseModel):
    vector: Dict[str, float]
    popularity_mean: float = 0.0
    warning: Optional[str] = None
    top_artists: List[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    session_id: str
    profile: ProfilePayload
    matched: int
    unmatched: int


class RecommendRequest(BaseModel):
    session_id: str
    prompt: str


class FeedbackRequest(BaseModel):
    session_id: str
    video_id: str
    vote: str  # "up" | "down"


class HealthResponse(BaseModel):
    youtube: str
    reccobeats: str
    llm: str
    mongo: str          # 前端契約沿用這個欄位名，實際後端看 storage
    storage: str = "memory"
    quota_used: int
    quota_limit: int
    cache_only: bool


class ErrorDetail(BaseModel):
    code: str
    message: str
    hint: Optional[Any] = None
