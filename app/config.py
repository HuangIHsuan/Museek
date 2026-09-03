"""集中管理環境變數。所有金鑰只存在後端，前端一律只打自家 /api/*。"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- 外部服務金鑰（沒填就自動走 stub，內網開發用） ---
    youtube_api_key: Optional[str] = None
    # 多把金鑰輪替（逗號分隔）。一把的當日配額用盡就換下一把。
    #
    # ⚠️ 這是刻意加入的、跨多個 GCP 專案取用配額的機制。Google 的 API 條款
    #    將此視為規避配額，可能導致相關金鑰一併被撤銷——包含清單裡每一把、
    #    以及它們所屬的專案。使用前請確認每把金鑰的擁有者都知情並同意。
    #    詳見 NOTES.md #37。
    #
    # 設了這一項就會取代 YOUTUBE_API_KEY。留空則維持單金鑰行為。
    youtube_api_keys: str = ""
    reccobeats_base_url: str = "https://api.reccobeats.com"
    # auto = 先打真的、失敗自動退 stub；stub = 完全不對外（內網開發用）；live = 只打真的
    # ReccoBeats 是公開 API、不需要金鑰，因此預設就打真的。
    # auto 在連不上時會自動退 stub，所以離線也不會壞——但要知道那時拿到的是假特徵。
    reccobeats_mode: Literal["auto", "stub", "live"] = "auto"
    # 曲庫第一趟查不到時的補救（NOTES #38、#39）。關掉的話那些歌完全沒有特徵，
    # 品味向量會出現一整排 0.00。補救分兩段，各有一個開關：
    #   1. 別名回查——用 iTunes 的中英對照再查一次曲庫，拿得到真的 recco_id
    #      （＝推薦種子），成本約 1 秒
    #   2. 音訊分析——曲庫真的沒有這首歌時，抓 30 秒試聽片段直接算特徵，
    #      拿不到 id，成本約 3 秒
    reccobeats_recovery: bool = True
    reccobeats_analysis: bool = True
    # 試聽片段與別名來源：iTunes 公開搜尋 API，免金鑰。依序試這幾個商店，
    # TW 在前是因為華語曲名在美國商店只查得到羅馬拼音（甚至意譯）版本。
    itunes_base_url: str = "https://itunes.apple.com"
    itunes_countries: str = "TW,US"
    # 一次 session 最多補救幾首。50 首全沒中的歌單若不設上限，
    # /api/session 會卡好幾分鐘。
    recovery_max_per_session: int = 12
    analysis_timeout: float = 20.0       # 下載與分析都比 JSON 請求慢，不能用 http_timeout

    # --- LLM 通道（開發文件 §1.2）---
    # external = 外部 LLM API（選項 A，建議）
    # gateway  = 公司內部 LLM Gateway（選項 B）
    # stub     = 規則式解析，不打任何 LLM，內網也能端到端跑通
    llm_channel: Literal["external", "gateway", "azure", "stub"] = "stub"
    anthropic_api_key: Optional[str] = None
    anthropic_base_url: Optional[str] = None
    anthropic_model: str = "claude-opus-5"
    # 內部／地端 LLM：OpenAI 相容端點（目前是 llm-host 上的 vLLM，之後換 Azure OpenAI）
    gateway_base_url: Optional[str] = None      # 例：http://llm-host:8000/v1
    gateway_model: str = "qwen3.8-27b"
    gateway_token: Optional[str] = None
    llm_timeout: float = 60.0                   # 地端模型比雲端慢，給寬一點
    # qwen3 這類推理模型預設會先輸出一大段思考，把 max_tokens 燒光導致 content 為空。
    # Intent／Explainer 都是結構化小任務，不需要 CoT，關掉之後快十倍。
    # 換 Azure OpenAI 時要設成 false——它不吃 chat_template_kwargs。
    gateway_disable_thinking: bool = True
    # 只有 LLM 呼叫要走這個 proxy（Cloud Run 上是容器內的 tailscaled userspace proxy）。
    # YouTube／Google 一律直連，不繞 Tailscale。
    llm_proxy: Optional[str] = None

    # --- Azure OpenAI ---
    # 與 gateway 通道的三個差異：api-key 標頭（不是 Bearer）、
    # 路徑帶 deployment 與 api-version、不吃 chat_template_kwargs。
    azure_endpoint: Optional[str] = None      # 例：https://<resource>.openai.azure.com
    azure_deployment: Optional[str] = None    # 部署名稱，不是模型名稱
    azure_api_key: Optional[str] = None
    azure_api_version: str = "2024-12-01-preview"
    # 參數風格：modern = max_completion_tokens 且不帶 temperature（gpt-5.x 等推理模型）；
    # legacy = max_tokens + temperature（gpt-4o 等）；auto = 先試 modern，被拒再退 legacy。
    azure_param_style: Literal["auto", "modern", "legacy"] = "auto"
    # 推理模型的 max_completion_tokens 要涵蓋「思考 + 輸出」。給 300 會讓思考
    # 吃光預算、content 回空字串（實測 gpt-5.6-luna 每次都中）。這是下限，不是上限。
    azure_min_completion_tokens: int = 2000

    # --- 資料庫 ---
    # auto = 依設定自動挑（firestore > mongo > memory）
    storage_backend: Literal["auto", "memory", "mongo", "firestore"] = "auto"
    gcp_project: Optional[str] = None          # Firestore 用；Cloud Run 上會自動帶入
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "museek"
    # Mongo 連不上時是否自動退到記憶體儲存（本機沒裝 Mongo 也能開發）
    allow_memory_fallback: bool = True

    # --- 配額控管（開發文件 §8）---
    quota_daily_limit: int = 10_000          # 每把金鑰各自的每日上限
    quota_circuit_breaker: int = 8_000   # 超過此值切「僅用快取」模式
    quota_cost_search: int = 100
    quota_cost_playlist_items: int = 1
    quota_cost_videos: int = 1       # 單曲入口：videos.list 同樣 1 點
    verify_per_round: int = 8            # 單輪最多驗證 8 首（Top 5 + 3 備位）
    return_per_round: int = 5

    # --- Discovery Ranker 參數（Day 5 調校用）---
    band_center: float = 0.72
    band_width: float = 0.12
    weight_band: float = 0.45
    weight_context: float = 0.30
    weight_novelty: float = 0.25
    echo_chamber_penalty: float = 0.55
    hard_filter: bool = True             # §5.4 建議修正 1：排序前先硬過濾

    # --- 其他 ---
    http_timeout: float = 4.0            # ReccoBeats 逾時 4s，重試 1 次
    log_dir: str = "logs"

    @property
    def youtube_keys(self) -> List[str]:
        """實際可用的金鑰清單，保序去重。空清單代表走 stub。"""
        raw = self.youtube_api_keys or self.youtube_api_key or ""
        keys, seen = [], set()
        for part in raw.split(","):
            key = part.strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
        return keys

    @property
    def itunes_stores(self) -> List[str]:
        """要依序搜尋的 iTunes 商店代碼，保序去重。"""
        stores, seen = [], set()
        for part in (self.itunes_countries or "").split(","):
            code = part.strip().upper()
            if code and code not in seen:
                seen.add(code)
                stores.append(code)
        return stores or ["US"]

    @property
    def llm_ready(self) -> bool:
        if self.llm_channel == "external":
            return bool(self.anthropic_api_key)
        if self.llm_channel == "gateway":
            return bool(self.gateway_base_url)
        if self.llm_channel == "azure":
            return bool(self.azure_endpoint and self.azure_deployment and self.azure_api_key)
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
