"""Day 1 凍結的 JSON 契約（開發文件 §3）。改這裡等於改契約，需經專案窗口同意。

曲風那幾個欄位（Intent.genres／avoid_genres、Score.genre_fit、TrackResult.genres、
ProfilePayload.genres）是**新增**的，都有預設值：舊的前端不讀就當沒有，
既有欄位一個都沒動。加它們的理由是六個數值維度分不出 citypop 與 soft rock，
曲風是獨立的一軸而不是第七個維度（見 core/genres 的檔頭）。"""
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
    # 曲風（core/genres 的標準 slug）。六個數值維度分不出 citypop 與 soft rock，
    # 所以「想聽什麼曲風」要獨立收，不能指望 constraints 表達得出來。
    # 沒點名就是空清單——空清單代表「沒指定」，這時曲風那一項分數會退回
    # 用歌單統計出來的分布（歌單入口）或整個消失（都沒有時）。
    genres: List[str] = Field(default_factory=list)
    avoid_genres: List[str] = Field(default_factory=list)


class Score(BaseModel):
    similarity: float
    band: float
    context_fit: float
    novelty: float
    # 曲風有多合，[0,1]。**None 代表無從判斷**（使用者沒指定曲風，或這首查不到
    # 標籤），此時 ranker 會把這一項連同權重一起拿掉再正規化——不是當成 0 分。
    genre_fit: Optional[float] = None
    final: float


class TrackResult(BaseModel):
    """§3.2 推薦結果 JSON（前端契約，凍結）"""
    video_id: str
    title: str
    artist: str
    thumbnail: str
    reason: str
    features: Dict[str, float]
    # 這首的曲風標籤（標準 slug）。前端拿來顯示，也讓「為什麼推這首」看得見
    # ——數值都對但曲風不對的時候，使用者要能一眼看出是哪裡不對。
    genres: List[str] = Field(default_factory=list)
    score: Score


# --- API 端點的輸入輸出（§4）---

class SessionRequest(BaseModel):
    playlist_url: str


class ProfilePayload(BaseModel):
    vector: Dict[str, float]
    popularity_mean: float = 0.0
    warning: Optional[str] = None
    top_artists: List[str] = Field(default_factory=list)
    # 這份歌單的曲風分布（slug → 權重，最大值正規化為 1）。平均向量說不出
    # 「這個人聽的是 citypop 不是 soft rock」，這份分布可以。
    genres: Dict[str, float] = Field(default_factory=dict)
    # 只有單曲入口才有值：分析偵測到的歌名，讓前端能寫「來自《歌名》的品味輪廓」
    track_title: Optional[str] = None


class SessionResponse(BaseModel):
    session_id: str
    profile: ProfilePayload
    matched: int
    unmatched: int
    # matched 之中有幾首的特徵是靠 30 秒試聽片段分析出來的（曲庫查不到）
    analyzed: int = 0


class RecommendRequest(BaseModel):
    # 沒有 session_id 就是「只給情境」的入口：後端讀出氛圍、自己建一個工作階段，
    # 並在第一首歌之前用 session 事件把 id 交還前端（回饋要用）。
    session_id: Optional[str] = None
    prompt: str


class FeedbackRequest(BaseModel):
    session_id: str
    video_id: str
    vote: str  # "up" | "down"


class HealthResponse(BaseModel):
    youtube: str
    reccobeats: str
    llm: str
    # 曲風標籤來源（iTunes）。unknown = 這個行程還沒查過任何一位歌手
    genres: str = "unknown"
    mongo: str          # 前端契約沿用這個欄位名，實際後端看 storage
    storage: str = "memory"
    quota_used: int          # 所有金鑰的當日用量總和
    quota_limit: int         # 所有金鑰的當日上限總和
    cache_only: bool
    # 多金鑰輪替時的每把明細（NOTES #37）。單金鑰時只有一筆。
    quota_keys: List[Dict[str, Any]] = Field(default_factory=list)
    active_key: int = 0      # 目前用第幾把（從 1 開始），全部用盡為 0


class ErrorDetail(BaseModel):
    code: str
    message: str
