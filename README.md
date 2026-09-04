# Museek 後端

AI 音樂探索 Agent。規格見 `deck/Museek_系統開發文件.md`（以下章節編號皆指該文件）。

## 現在跑得起來的東西

整條流程端到端可跑，**不需要任何金鑰、不需要 Mongo、不會燒任何配額**：
貼歌單（或單一首歌）→ 品味向量 → 自然語言情境 → Discovery 排序 → 驗證可播放 → SSE 串流 → 👍👎 重排。

兩個入口共用後半段，差別只在「品味從哪裡來」：

| 入口 | 品味向量 | 推薦種子 |
|---|---|---|
| 貼歌單／單曲 | 聽過的歌逐維度取平均 | 歌單曲目在曲庫裡的 id |
| 只描述情境 | LLM 讀出氛圍，換算成「典型的那一首」，再收進情境的上下限 | LLM 給的起點歌手，各挑一首最貼近氛圍的歌 |

情境入口是 `POST /api/recommend` 不帶 `session_id`：後端自己建工作階段，
並在第一首歌之前用 `session` 事件把 id 與讀到的氛圍交還前端（👍👎 要用）。

### 備援種子（`seed_source`）

模型給的歌手曲庫一位都沒收、或模型根本沒給（降級）時，會退到
`app/services/seed_pool.py` 的人工清單——那份清單挑的是**特徵空間的覆蓋率**，
不是「什麼氛圍配什麼歌手」，實際挑哪幾首由目標向量的距離決定。
`session` 與 `done` 事件都會帶 `seed_source`（`vibe` / `fallback` / `none`），
前端在用了備援時會明說，不讓起點被安靜換掉。

```bash
# 把清單解析成 data/vibe_seeds.json：之後零 API 呼叫，且每首都保證查得到。
# 這個檔要進版控——正式環境不該在第一個請求時才即時解析。曲庫收錄會變，記得定期重跑。
RECCOBEATS_MODE=live .venv/bin/python scripts/verify_vibe_seeds.py
```

### 亞洲比重

推薦端點回來的候選**跟種子幾乎無關**：同一顆種子連問兩次，20 首裡只有 3 首重疊；
Jay Chou 與 Metallica 的結果 0 首重疊，兩邊都是全球長尾的隨機切片。
實測 179 首候選裡，亞洲發行（看 ISRC 前兩碼）只有 7 首＝ **3.9%**。
換種子、改提示詞都動不了這個數字——池子裡沒有的東西，排序排不出來。

所以亞洲曲目是**後端自己補進候選池的**：從 `data/vibe_seeds.json` 的亞洲那一區
挑幾首特徵貼近這次情境的歌，混進候選池。補進來的歌**不享有任何加分**，
一樣要跟其他候選比 Discovery Score；`done` 事件會帶 `asia`，說出這一輪
實際端出幾首亞洲曲目。實測前五名的亞洲佔比從 15% 變成 45%（`ASIA_*` 可調，見 `.env.example`）。

外部服務預設全部走 stub，因此在公司內網也跑得動（§1.1）。要接真實資料只需改 `.env`。

## 啟動

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload --port 8000
```

開 http://localhost:8000 。跑測試：

```bash
.venv/bin/python -m pytest -q
```

## 專案結構

```
app/
  main.py              FastAPI 進入點、靜態檔掛載
  config.py            所有環境變數（Ranker 參數也在這，Day 5 調校不用改程式）
  models.py            §3 凍結的 JSON 契約
  api/routes.py        §4 五支端點、SSE 事件格式
  core/
    normalize.py       網址白名單、曲名正規化、快取 key   ← 純字串，內網可測
    profiler.py        Taste Profiler 向量                ← 純數學
    ranker.py          Discovery Ranker §5、沒有歌單時的目標向量、地區名額 ← 純數學，不碰 YouTube 資料
    regions.py         候選是不是亞洲發行（讀 ISRC 前兩碼）      ← 純函式
    resolver.py        Video Resolver：快取→配額→丟棄補位→熔斷
    quota.py           配額計數與熔斷 §8
    pipeline.py        把上面串成 session／recommend／feedback 三條流程
  services/
    youtube.py         playlistItems.list、search.list（無金鑰→stub）
    reccobeats.py      search / audio-features / recommendation / 音訊分析（失敗→stub）
    itunes.py          曲庫查不到時，抓 30 秒試聽片段餵給分析端點 ← 免金鑰
    llm.py             Intent Parser、Vibe Analyzer、Explainer，三通道可切換
    prompts.py         提示詞與 <user_data> 包裝 §10
    seed_pool.py       種子池：情境入口的起點，以及候選池裡那份「一定是亞洲」的名額
    stub_data.py       可重現的假曲庫（雜湊決定特徵，同一首歌永遠同一組數字）
  db/repository.py     Mongo 四個 collection + TTL 索引；連不上自動退記憶體版
  static/              單頁 PWA
scripts/
  prewarm_cache.py     Demo 前快取預熱 §8
  generate_icons.py    PWA 圖示產生器（不依賴 Pillow）
  verify_vibe_seeds.py 把備援種子池解析成 data/vibe_seeds.json（只打 ReccoBeats）
tests/                 200 個測試，全程 stub，不對外連線
```

## 三個開關（`.env`）

| 變數 | 預設 | 說明 |
|---|---|---|
| `YOUTUBE_API_KEY` | 空 | **空 = stub，一點配額都不燒。§8 規定只有 D2 該填這格。** |
| `RECCOBEATS_MODE` | `stub` | `auto` 打真的、失敗自動退 stub；`live` 只打真的 |
| `LLM_CHANNEL` | `stub` | `stub` 規則式解析；`external` Anthropic API；`gateway` OpenAI 相容端點 |

填了 `YOUTUBE_API_KEY` 之後，金鑰所屬的 Google Cloud 專案還要做兩件事，
少一件每個連結都會失敗：

1. 在該專案**啟用 YouTube Data API v3**（沒啟用會回 403 `SERVICE_DISABLED`）。
2. 金鑰若設了「API 限制」，清單裡要**勾選 YouTube Data API v3**
   （沒勾會回 403 `API_KEY_SERVICE_BLOCKED`）。

這兩種都是 403，和「歌單是私人的」同一個狀態碼但完全不同的原因，
所以 `/api/session` 會回 `youtube_key_rejected`（503）而不是
`playlist_not_accessible`（404），`/api/health` 的 `youtube` 欄位也會顯示
`key_rejected（原因）`。看到公開連結被說成「讀不到」，先看這一欄。

ReccoBeats 打真的時，曲庫第一趟查不到的歌（華語、獨立廠牌很常見）會走兩段補救：

1. **別名回查**——曲庫是 Spotify 血統，茄子蛋在裡面叫 EggPlantEgg、
   草東沒有派對叫 No Party For Cao Dong。用 iTunes 的中英對照再查一次曲庫，
   多半查得到，而且拿到的是真的 `recco_id`，可以當推薦種子。
2. **音訊分析**——曲庫真的沒有這首歌時，抓 iTunes 的 30 秒試聽片段丟進
   ReccoBeats 的分析端點直接算特徵。拿不到 id，只補得了特徵。

沒有這兩段，那些歌的品味向量會是一整排 0.00（NOTES #38、#39）。
用 `RECCOBEATS_RECOVERY=false` 全關、`RECCOBEATS_ANALYSIS=false` 只關第 2 段，
`RECOVERY_MAX_PER_SESSION` 調每次最多補救幾首。

曲庫**連那位歌手都沒有**才算真的沒辦法；只是那首歌沒收的話，還有第三段：
用分析出來的特徵，在同一位歌手的曲目裡挑最接近的一首當**代打種子**——
推薦端點要的只是一顆曲目 id，種子不必是同一首歌（NOTES #40）。

實測 7 首華語／獨立曲目：可用種子從 2 首變成 6 首；
單曲入口貼一首曲庫沒收的歌（Luci Gang – HEADLOCK），
也能靠代打種子撈到 43 首候選、跑完一輪推薦。

目前本機 `.env` 的實際設定：YouTube **已啟用真實金鑰**、ReccoBeats 走 stub、
LLM 走 `gateway` 指向地端 llm-host（vLLM / qwen3.8-27b），之後換 Azure OpenAI。

LLM 三條通道的介面都是「純文字進、JSON 出」，切換只改這一個變數，其他模組完全不動——
這就是簡報要講的「可切換性」，程式上已經是事實而不是宣稱（§1.2）。

`LLM_CHANNEL=stub` 不是佔位符：規則式解析器認得中文情境詞，
「下雨天開車想放空，類似我平常聽的但不要太吵」會解析成
`平靜／開車／energy_max 0.5／70–110 BPM`，理由句則由音訊特徵套模板生成，
引用的每個數字都真的來自特徵值。**LLM 掛掉時走的也是這條，Demo 有保底。**

> **跑測試不會燒配額。** `tests/conftest.py` 會把每個對外設定強制蓋成安全值——
> 因為 `.env` 現在有真的金鑰，少了這道防線跑一次 `pytest` 就會花掉配額。


## 部署（GCP Cloud Run）

線上位址：https://<CLOUD_RUN_URL>
專案：`<GCP_PROJECT_ID>`（asia-east1）｜儲存：Firestore｜帳號：<部署帳號>

```bash
# gcloud 需要 Python 3.10+，本機系統只有 3.9，因此用這個 wrapper
~/.museek-tools/gcloud run deploy museek \
  --source . --region asia-east1 --project <GCP_PROJECT_ID> \
  --allow-unauthenticated --max-instances 3 --memory 512Mi --timeout 300 \
  --set-env-vars "STORAGE_BACKEND=firestore,GCP_PROJECT=<GCP_PROJECT_ID>,RECCOBEATS_MODE=stub,\
LLM_CHANNEL=azure,AZURE_ENDPOINT=https://<AZURE_RESOURCE>.cognitiveservices.azure.com/,\
AZURE_DEPLOYMENT=gpt-5.6-luna,AZURE_API_VERSION=2024-12-01-preview,LLM_TIMEOUT=60" \
  --set-secrets "AZURE_API_KEY=azure-api-key:latest,YOUTUBE_API_KEY=youtube-api-key:latest"
```

部署後驗證：

```bash
.venv/bin/python scripts/smoke_test.py https://<CLOUD_RUN_URL>
```

### 雲端與本機的差異

| | 本機 | Cloud Run |
|---|---|---|
| 儲存 | Mongo（docker）或記憶體＋落檔 | Firestore |
| LLM | 地端 llm-host（qwen3.8-27b） | Azure OpenAI（gpt-5.6-luna） |
| YouTube | 真實金鑰 | 真實金鑰 |
| ReccoBeats | stub | stub |

金鑰存在 Secret Manager（`azure-api-key`、`youtube-api-key`），不用明文環境變數。

判斷 LLM 有沒有真的在工作：看 `/api/health` 的 `llm` 欄位——
`configured` 正常、`degraded` 表示有設定但產不出內容、理由已退回模板（NOTES #28）。

### 三種儲存後端

`STORAGE_BACKEND` 可設 `memory` / `mongo` / `firestore`，介面完全一致：

```bash
# 本機起 Mongo（公司網路擋 Docker Hub，要用 Google 的 mirror）
docker run -d --name museek-mongo -p 27017:27017 mirror.gcr.io/library/mongo:7

# 從記憶體落檔搬進 Mongo（含配額計數，不搬會低估用量）
.venv/bin/python scripts/migrate_cache_to_mongo.py
```

## 待辦注記

接上真實服務後發現的項目集中在 [NOTES.md](NOTES.md)，其中兩項有實際風險：
**YouTube 金鑰尚未在 GCP 設使用限制**、**配額計數器會低估實際用量**。

## 已知落差與決策

1. **§5.2 驗證表有三格與高斯公式對不上**：`sim=0.98` 應為 0.096（文件寫 0.100）、
   `0.85` 應為 0.556（文件寫 0.579）、`0.30` 應為 0.002（文件寫 0.005）。
   公式本身沒有歧義，程式以計算值為準，測試對文件表格放寬到 ±0.03。請 P 修訂文件。

2. **§5.4 硬過濾改成「分級」而非「全丟」**：通過硬過濾的排前面，違反上下限的排後面當備位。
   原本的「全丟」寫法在候選池小於 8 首時會整批放行，實測就出現了文件警告的那個情境——
   使用者說「不要太吵」，第 4 首卻是 156 BPM。分級之後兩個需求都滿足：
   前段永遠不會出現違反情境的曲目，候選再少也交得出五首。

3. **ReccoBeats 推薦端點沒有「照著一支向量找相似曲目」的用法**：
   `seeds` 是必填的曲目 id，少了直接 400；歌手 id 不算數；
   實測 `energy`／`valence`／`acousticness`／`danceability` 這些參數送了沒有作用，
   只有 `tempo` 真的會改變結果（NOTES #39）。所以品味向量只能用在自家的
   Discovery Ranker 排序，取候選還是得靠曲目 id——這就是別名回查與代打種子存在的理由。
   連那位歌手都找不到時，回一個 `no_seeds` 錯誤，不拿 stub 假曲庫充數（NOTES #40）。

4. **前端的假曲風標籤已移除**：原型寫死「Indie / City Pop / R&B」，
   但後端沒有曲風資料。改成從歌單統計出的「常聽歌手」，是真的數字。

5. **沒有示範歌單**：整個專案不提供任何預設／示範歌單。私人歌單或網址錯誤時
   只給友善錯誤請對方換連結；還沒建立品味時，「我的品味」會跳「尚未建立品味清單」
   並用「馬上建立」把人帶到貼歌單／情境那一頁。

## 還沒做的

- [ ] 把已驗證有效的 `tempo` 參數接進推薦端點（NOTES #39 末段，候選池會更貼近情境）
- [ ] YouTube API Key 申請與 `playlistItems.list` 實測（只能一個人做，§8）
- [ ] 曲名正規化測資補到 100 筆真實樣本（T；目前 10 筆涵蓋華／英／日／韓）
- [ ] iOS standalone 模式下的 IFrame 內嵌實測（外網 + 實機）
- [ ] 部署與 HTTPS（PWA 的硬前提）
- [ ] Day 5 參數調校：`BAND_CENTER` / `BAND_WIDTH` / 權重 / 懲罰係數（全在 `.env`）

## 合規檢核（§13）現況

已在程式裡落實：`video_cache` TTL 30 天索引、Discovery Score 完全不使用 YouTube 資料、
播放器無外框裝飾且可視區 ≥200×200、縮圖 ≥120×70、`playsinline=1`、
未實作 OAuth、API Key 只在後端、歌單／單曲網址限 youtube.com／youtu.be、
外部文字以 `<user_data>` 包裝且中和內層偽造標籤、referrer 設為 `strict-origin-when-cross-origin`。

尚待外部條件：全站 HTTPS（等部署）、備援影片、預熱、演練。
