# Museek 後端

AI 音樂探索 Agent。規格見 `deck/Museek_系統開發文件.md`（以下章節編號皆指該文件）。

## 現在跑得起來的東西

整條流程端到端可跑，**不需要任何金鑰、不需要 Mongo、不會燒任何配額**：
貼歌單 → 品味向量 → 自然語言情境 → Discovery 排序 → 驗證可播放 → SSE 串流 → 👍👎 重排。

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
    ranker.py          Discovery Ranker §5                ← 純數學，不碰 YouTube 資料
    resolver.py        Video Resolver：快取→配額→丟棄補位→熔斷
    quota.py           配額計數與熔斷 §8
    pipeline.py        把上面串成 session／recommend／feedback 三條流程
  services/
    youtube.py         playlistItems.list、search.list（無金鑰→stub）
    reccobeats.py      search / audio-features / recommendation（失敗→stub）
    llm.py             Intent Parser、Explainer，三通道可切換
    prompts.py         提示詞與 <user_data> 包裝 §10
    stub_data.py       可重現的假曲庫（雜湊決定特徵，同一首歌永遠同一組數字）
  db/repository.py     Mongo 四個 collection + TTL 索引；連不上自動退記憶體版
  static/              單頁 PWA
scripts/
  prewarm_cache.py     Demo 前快取預熱 §8
  generate_icons.py    PWA 圖示產生器（不依賴 Pillow）
tests/                 55 個測試，全程 stub，不對外連線
```

## 三個開關（`.env`）

| 變數 | 預設 | 說明 |
|---|---|---|
| `YOUTUBE_API_KEY` | 空 | **空 = stub，一點配額都不燒。§8 規定只有 D2 該填這格。** |
| `RECCOBEATS_MODE` | `stub` | `auto` 打真的、失敗自動退 stub；`live` 只打真的 |
| `LLM_CHANNEL` | `stub` | `stub` 規則式解析；`external` Anthropic API；`gateway` OpenAI 相容端點 |

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

3. **ReccoBeats 真實 API 尚未驗證**：本機網路連不到 `api.reccobeats.com`，
   端點參數與回傳欄位是照文件推測寫的。**這仍是 Day 1 的 GO/NO-GO 風險項。**
   真實格式若不同，只需改 `services/reccobeats.py` 的 `_parse_track` / `_parse_features` 兩個函式，
   其餘模組不受影響。

4. **前端的假曲風標籤已移除**：原型寫死「Indie / City Pop / R&B」，
   但後端沒有曲風資料。改成從歌單統計出的「常聽歌手」，是真的數字。

5. **示範歌單是佔位符**：`app/api/routes.py` 的 `DEMO_PLAYLISTS` 目前是假 ID，
   等 T 策展完三組歌單後替換。私人歌單／網址錯誤時前端已經會跳出一鍵切換按鈕。

## 還沒做的

- [ ] ReccoBeats 真實端點驗證（外網，Day 1 風險項）
- [ ] YouTube API Key 申請與 `playlistItems.list` 實測（只能一個人做，§8）
- [ ] 三組示範歌單策展 + `DEMO_PLAYLISTS` 替換（T）
- [ ] 曲名正規化測資補到 100 筆真實樣本（T；目前 10 筆涵蓋華／英／日／韓）
- [ ] iOS standalone 模式下的 IFrame 內嵌實測（外網 + 實機）
- [ ] 部署與 HTTPS（PWA 的硬前提）
- [ ] Day 5 參數調校：`BAND_CENTER` / `BAND_WIDTH` / 權重 / 懲罰係數（全在 `.env`）

## 合規檢核（§13）現況

已在程式裡落實：`video_cache` TTL 30 天索引、Discovery Score 完全不使用 YouTube 資料、
播放器無外框裝飾且可視區 ≥200×200、縮圖 ≥120×70、`playsinline=1`、
未實作 OAuth、API Key 只在後端、歌單網址限 youtube.com／youtu.be、
外部文字以 `<user_data>` 包裝且中和內層偽造標籤、referrer 設為 `strict-origin-when-cross-origin`。

尚待外部條件：全站 HTTPS（等部署）、備援影片、預熱、演練。
