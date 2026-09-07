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

    # --- 亞洲比重（NOTES #46）---
    # ReccoBeats 的推薦端點實測下來幾乎不看種子，回來的候選是全球長尾的隨機切片，
    # 亞洲發行只佔 3.9%。所以「多推一點亞洲」換種子是換不出來的，只能自己補進候選池。
    # 補幾首其實控不住比重（實測 6／10／15 首的結果都落在同一區間），
    # 真正在控比重的是下面那組名額——上下限都要有，只有下限表達不出一個比例。
    asia_candidates: int = 12        # 每輪從種子池補幾首亞洲候選進候選池（0 = 不補）
    asia_min_per_round: int = 2      # 每輪端出去的五首裡至少幾首亞洲（0 = 不保留名額）
    asia_max_per_round: int = 2      # 至多幾首（-1 = 不設上限）
    seed_asia_min: int = 3           # 五顆種子裡至少幾顆亞洲（LLM 起點歌手與備援池共用）

    # --- Discovery Ranker 參數（Day 5 調校用）---
    band_center: float = 0.88
    band_width: float = 0.08
    weight_band: float = 0.45
    weight_context: float = 0.30
    weight_novelty: float = 0.25
    echo_chamber_penalty: float = 0.55
    hard_filter: bool = True             # §5.4 建議修正 1：排序前先硬過濾

    # --- 曲風（六個數值維度分不出 citypop 與 soft rock，曲風是獨立的一軸）---
    # 曲風不併進那支向量，而是 Discovery Score 裡獨立的一項。使用者沒指定曲風、
    # 或候選查不到標籤時，這一項**連同權重一起被拿掉再正規化**——不然沒有標籤的
    # 候選一律少一截分數，排序會退化成「比誰查得到曲風」。
    weight_genre: float = 0.45
    # 每輪從種子池補幾首「曲風一定對得上」的候選（0 = 不補）。
    #
    # **這是曲風真正的來源，不是權重。** 推薦端點回來的是全球長尾隨機切片，
    # 實測 42 首候選裡只有 2 首對得上使用者的曲風——那種情況下權重調到 1.0、
    # 名額調到 4，前五命中數完全不動（NOTES #49）。排序排不出池子裡沒有的東西，
    # 跟 #46 的亞洲比重是同一個結論。
    genre_candidates: int = 12
    # 前五首至少幾首命中想要的曲風（0 = 不保留名額）。「想要的曲風」可以是
    # 使用者明講的，也可以是從歌單統計出來的——貼一份清一色 R&B 的歌單，
    # 就是用歌單講了「我要 R&B」。
    genre_min_per_round: int = 4
    # 從歌單統計出來的曲風分布最多留幾個。留太多等於沒有偏好。
    genre_profile_top: int = 6
    # 曲風查詢的總開關。關掉的話 genre_fit 一律是 None，那一項連同權重
    # 從 Discovery Score 消失，其餘流程完全不受影響。
    # RECCOBEATS_MODE=stub 時也一律不查——stub 的意思就是完全不對外。
    genre_lookup: bool = True
    # 一輪最多對外查幾位新歌手的曲風（查過的走行程內快取，不算在內；0 = 不限）。
    #
    # **這個數字很小是因為 iTunes 撐不起批量查詢**（實測見 NOTES #49）：
    # 它的量級是每分鐘約 20 次，所以節流是 3 秒一次、不併發。25 位就是 75 秒
    # 掛在使用者的等待上，那不能接受。曲風的覆蓋率要靠**離線預熱**來，
    # 不是靠執行期現查——這裡只留一點額度給「剛好沒預熱到」的情況。
    genre_lookup_max: int = 3
    # 兩次 iTunes 請求之間的最小間隔（秒）。預設照官方量級（每分鐘約 20 次）。
    # 調低會更快，但實測打太快之後整片回 403、冷卻 90 秒都還沒退場——
    # 而且那會連帶把別名與試聽片段那兩條路一起打死。測試設 0。
    itunes_pace_seconds: float = 3.0

    # --- 其他 ---
    # 掃 QR 要開的網址（導覽列的 QR 彈窗與 /install）。設了就固定用它，
    # 本機開發時掃到的也會是線上版；留空則自動判斷：對外網域用自己，
    # localhost 則退回區網 IP。詳見 app/pwa.py。
    public_base_url: str = ""
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
