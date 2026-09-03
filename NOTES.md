# 待辦注記

接上 YouTube API 與地端 LLM 之後累積的項目，**目前都沒有改**，之後再處理。
編號無優先順序，但標「⚠️」的是會造成實際損失或風險的。

---

## ⚠️ 1　YouTube API Key 沒有做使用限制

YouTube 金鑰若沒有在 GCP Console 設定使用限制，任何拿到它的人都能用光
每日 10,000 點，而配額不可加購（§8）。**部署前務必確認限制已設定。**

**建議做的事：**
- 到 GCP Console → 憑證 → 這把 key → 「API 限制」只勾 YouTube Data API v3
- 「應用程式限制」設 IP 或 HTTP 參照網址（部署後才知道最終網域）
- 部署時放平台環境變數，不要進版控（`.env` 已在 `.gitignore`）
- 若確定外流，直接重新產生一把

## ⚠️ 2　配額計數器與 Google 實際用量會有落差

`quota_used` 是我們自己算的，只計入經由後端發出的呼叫。今天為了驗證金鑰，
我用 curl 直接打了 `channels.list` ×2、`playlistItems.list` ×1（共 3 點），
這些不在計數器裡。實際用量請以 GCP Console 的配額頁為準，我們的數字只能當下限。

目前後端計數：501 點（1 點歌單 + 5 次搜尋 × 100）。

## 3　換 Azure OpenAI 要改的地方

現在 `LLM_CHANNEL=gateway` 走 OpenAI 相容格式，指向 llm-host 的 vLLM。
換 Azure OpenAI 時 `app/services/llm.py` 的 `_call_gateway` 有三處要動：

| 項目 | 現在（vLLM） | Azure OpenAI |
|---|---|---|
| 認證 | `Authorization: Bearer <key>` | `api-key: <key>` |
| 路徑 | `{base}/chat/completions` | `{base}/openai/deployments/{deployment}/chat/completions?api-version=2024-10-21` |
| 關閉思考 | `chat_template_kwargs.enable_thinking=false` | **不支援，會 400**。設 `GATEWAY_DISABLE_THINKING=false` |

`GATEWAY_MODEL` 在 Azure 是 deployment 名稱而不是模型名稱。

## 4　為什麼一定要關掉模型思考

qwen3.8-27b 預設會先輸出一大段 reasoning。實測 `explain` 在 `max_tokens=1024` 下
**全部 1024 個 token 都花在思考上，`content` 回傳 null**，結果靜靜退回模板理由。
關掉之後 13.7 秒 → 1.3 秒，而且理由品質很好。

這件事的教訓：**「有回傳」不等於「LLM 有在工作」**。降級路徑太安靜會蓋住故障。
現在空回應會寫 WARNING 到 log，但沒有反映到 `/api/health`——值得之後補。

## 5　曲名正規化還沒處理的樣式

用 NPR Music 的歌單實測後發現：

- `歌手: 歌名`（冒號分隔）沒有處理 → 「Mon Rovîa: Tiny Desk Concert」整串被當成歌名
- 頻道上傳型歌單（`UU…` 開頭）的 `videoOwnerChannelTitle` 一律是頻道名，
  導致所有曲目的歌手都變成「NPR Music」
- 非音樂貼文（宣傳、抽獎）沒有濾掉

前兩項對正常的策展歌單影響不大（那類多半是「Artist - Title」），
但 T 的 100 筆測資進來後應該一起處理。

## ~~6　stub 的 ReccoBeats 永遠不會 miss~~（已切真實 API，比對率成為真數字）

`stub_features()` 是用歌手／歌名雜湊生出來的，所以任何字串都「查得到」，
比對率永遠 100%。結果是 **§9 的「歌單比對率 < 40% 就降級」這條路徑，
在 stub 模式下無法驗證**。之後應該讓 stub 依雜湊丟掉一定比例的曲目。

## ~~7　ReccoBeats 真實 API 仍未驗證~~（已驗證並修正三處）

本機網路連不到 `api.reccobeats.com`。端點與欄位是照文件推測寫的，
真實格式不同時只要改 `_parse_track` / `_parse_features` 兩個函式。
**這仍是 Day 1 的 GO/NO-GO 風險項。**

## 8　Mongo 還沒裝，目前是記憶體 + JSON 落檔

`video_cache` / `feature_cache` / `quota` 會寫到 `data/cache.json`，
所以重啟不會重花配額。但：

- `taste_profiles` 不落檔，重啟後既有 session 會失效
- §6 的 TTL 索引（video_cache 30 天、taste_profiles expires_at）**尚未實際驗證過**
- 多人同時開發會各自持有一份快取

本機沒有 mongod，Docker daemon 也沒開。要接真的 Mongo：
`docker run -d -p 27017:27017 --name museek-mongo mongo:7`，程式會自動改用它。

## 9　推薦理由的語氣與長度

- 同一輪裡「您」和「你」混用，需要在 prompt 裡統一
- 規格要求 60 字內，模型常寫到 80–110 字。目前在 110 字處退到最近的句尾標點，
  不會斷在句中，但仍超過規格。要嘛放寬規格，要嘛在 prompt 加強約束
- 有一次把 acousticness 說成「電子感」並和 valence 的數值混在一起講

## 10　5 首理由是逐首序列生成

每首約 1.3 秒，五首約 6–7 秒。序列生成的好處是 SSE 可以一首一首浮出來，
Demo 的「思考感」比較好；要縮短總時間可以改成並行，但會變成五首一起出現。
先維持現狀，Day 5 看演練節奏再決定。

## 11　播放實測尚未完成

前端 iframe 的 src、`playsinline=1`、縮圖網址都確認正確，縮圖也確實載入了
（`naturalWidth=320`），但開發用的預覽窗格不渲染跨網域 iframe，
所以**「能不能真的播」還沒有被眼睛驗證過**。請在自己的瀏覽器開 http://localhost:8765 確認。
iOS standalone 模式的實測則還要另外做（§11 Day 1 項目）。

## 12　示範歌單還是佔位符

`app/api/routes.py` 的 `DEMO_PLAYLISTS` 是三組假 ID，等 T 策展完替換。
前端在歌單解析失敗時已經會跳出一鍵切換按鈕，接上真 ID 就能用。

---

## ⚠️ 13　「開始探索」會忽略使用者填的歌單網址，並撞上 400（後端已修，前端待討論）

**重現：** 在入口頁同時填「公開 YouTube 歌單」與「描述此刻的氛圍」，直接按「開始探索」。

`app/static/index.html` 的 `recommend()` 在沒有 session 時，會拿寫死的
`https://www.youtube.com/playlist?list=DEMO001` 去建 session，
**完全不看使用者剛剛填在上面的網址**：

```js
if (!state.sessionId) {
  await createSession("https://www.youtube.com/playlist?list=DEMO001");
  if (!state.sessionId) return;
}
```

接真實 YouTube API 之後，`DEMO001` 不是合法的 playlistId，
`playlistItems.list` 回的是 **400 Bad Request**（不是 403／404）。
而 `services/youtube.py` 的 `fetch_playlist_items` 只把 403／404 轉成
`PlaylistNotAccessible`，400 直接往上拋 → 500 且回應沒有 body →
前端只顯示「請求失敗」，使用者完全看不出發生什麼事。

**後端已修；前端改動已還原，等與前端同仁討論後統一處理。**

原本提的做法：

1. 前端（**已還原，尚未套用**）：`recommend()` 若還沒有 session，改用使用者填在欄位裡的網址；
   欄位空的時候才跳出對話框給 `/api/demo-playlists` 的清單。
2. 後端（**已套用**）：`fetch_playlist_items` 把 **400** 也歸類為 `PlaylistNotAccessible`
   （400 = playlistId 格式無效、403 = 私人、404 = 不存在，對使用者是同一件事），
   訊息改為「這份歌單讀不到——可能是私人的、已刪除，或網址不完整」＋三組示範歌單。
3. 前端（**已還原**）：「我的品味」按鈕原本也是打 DEMO001，改成有 session 就跳品味頁、沒有就回入口頁。

> 後端這一項留著是刻意的：前端還原後 `DEMO001` 那條路徑又會被走到，
> 沒有 400 的處理就是空 body 的 500，使用者只看得到「請求失敗」。

**仍未處理：** 兩個主要按鈕的視覺權重一樣，畫面上看不出「解析歌單 → 開始探索」的先後。
這是 UI 層的事，之後一併處理。

## 15　看完品味數值後無法輸入情境（改動已還原，待討論）

「我讀到的你」原本只有一顆「開始探索」，用的是寫死的預設提示，
情境輸入只存在於入口頁。**這直接卡住 Demo 腳本 §12**——
10–25 秒「貼歌單顯示我讀到的你」、25–40 秒「輸入下雨天開車想放空」，
原本的畫面做不到這個順序，只能退回上一頁重打。

曾在品味面板加上情境輸入與三顆快捷 chip（留空則沿用預設提示），實測可行：
輸入「被主管罵完，想要安靜一點的」→ 解析為
`低落／放空／energy_max 0.3／valence_max 0.5／acousticness_min 0.5`，
回傳 Cigarettes After Sex、Slowdive、deca joins 浴室。

**但這版已還原**，等與前端同仁討論後統一修正。
改過的版本保留在 `app/static/index.proposed.html`，可直接與 `index.html` 對照：

```bash
diff app/static/index.proposed.html app/static/index.html
```

討論時值得一併決定的：兩顆主要按鈕（解析歌單／開始探索）視覺權重相同，
畫面上看不出先後關係——這是這兩個問題的共同根因。

## 14　配額是以太平洋時間分日記錄（不是 bug）

`data/cache.json` 的 `quota` 會出現 `{"2026-09-01": 502, "2026-09-02": 301}` 這種形狀，
數字看起來「變小」是因為太平洋時間跨日、配額重置（§8）。這是正確行為。
Demo 當天要注意：**台北時間下午 3 點左右會跨日重置**，排練與正式 Demo 若跨過這個點，
配額狀況會不一樣。

## ⚠️ 16　`.env` 曾被 `.env.example` 的內容覆蓋

2026-09-02 17:17 左右，`.env` 變成與 `.env.example` 逐字相同——
真實的 YouTube 金鑰與 LLM 設定全部消失，服務靜靜退回全 stub 模式。
`/api/health` 會顯示 `youtube: stub`、`llm: stub`，但**功能表面上還是正常的**
（規則式解析照樣回結果），不盯著 health 就不會發現。

我無法從現有紀錄判斷是什麼覆蓋的——那個時間點我的編輯是針對
`.env.example`、`README.md`、`NOTES.md`。已重新寫回 `.env`，
並多留一份 `.env.backup`（同樣在 `.gitignore` 裡，權限 600）。

**要注意的兩件事：**
- 這類「降級成 stub」的狀況太安靜。`/api/health` 有正確反映，但沒有任何主動警示。
  可以考慮在啟動 log 之外，讓前端健康檢查角落在 stub 模式時顯示明顯標記。
- 之後如果又發現推薦品質突然變差、理由變成模板句，第一件事就是看 `/api/health`。

## 17　測試會寫進正式的 `logs/recommendations.jsonl`

`_log_round()` 不分環境一律落檔，所以跑 `pytest` 會把測試用的
「放鬆一點的音樂」之類假紀錄混進正式推薦紀錄裡。
分析資料時要記得濾掉，或讓測試把 `LOG_DIR` 指到 tmp。

## ⚠️ 18　多人使用時的隔離狀況（實測結果）

**問題：多人從不同 IP／裝置使用，會看到同一個人的「我的品味」嗎？**

**不會。** 每次 `/api/session` 產生一個新的 `uuid4().hex`，profile 各自存在
`taste_profiles` 裡。實測兩台裝置解析同一份歌單：session_id 不同，
A 按 👎 讓自己的 energy 從 0.5493 → 0.5826，B 仍是 0.5493，互不影響。

但延伸出三個真的要處理的問題：

### 18a　session_id 是純 bearer token，沒有任何綁定

沒有 cookie、沒有認證、沒有 IP 綁定——**拿到 session_id 就等於拿到那個人的品味檔案**，
可讀可改。實測：裝置 B 用裝置 A 的 session_id 打 `/api/feedback`，
成功把 A 的 energy 改成 0.6162。

uuid4 是 128 bit，猜不到，所以實務風險低；但 session_id 會出現在
前端 JS、網路請求、以及後端 log 裡。**Demo 時如果投影畫面開著 DevTools，
或 log 外流，等於把別人的 session 交出去。** 正式上線要綁 HttpOnly cookie。

### ~~18b ⚠️ 多 worker／多實例會隨機掉 session~~（已由 Firestore 解決）

`MemoryRepository` 的 `_repo` 是 module-level 全域變數，
**每個 uvicorn worker 各有一份自己的記憶體**。`taste_profiles` 又沒有落檔
（只有 video_cache／feature_cache／quota 落到 `data/cache.json`）。

實測 `--workers 2`：同一個 session_id 打 6 次 `/api/recommend`，
**5 次找得到、1 次回 session_not_found**——使用者會遇到「時好時壞」的鬼故事。
單一 worker 則 4/4 正常。

**已解決：** 雲端改用 Firestore，session 存在共用的資料庫而不是各自的記憶體，
所有 Cloud Run 執行個體讀的是同一份。雲端實測三台裝置各自獨立、互不影響，
A 按 👎 只動到 A 的向量。

**但本機仍有這個問題**——`STORAGE_BACKEND=memory` 時每個 worker 各一份，
而且多個 worker 會同時讀寫同一個 `data/cache.json` 互相覆蓋。
本機要跑多 worker 就得接 Mongo 或 Firestore。

### 18c ⚠️ 配額是全域共用的（多人測試時最該注意的一項）

10,000 點是整個專案共用，不是每人一份。多人同時試用會一起燒：
未命中快取的話一輪 500 點，**20 輪就見底**。
評審現場如果每個人都貼自己的歌單，很快就會撞到熔斷。
預熱快取（§8）不只是加速，是多人場景下的必要條件。

### 附帶：重新整理就會失去 session

前端把 session_id 放在 JS 的 `state` 物件裡，沒有寫 localStorage，
所以**重新整理頁面 = 品味檔案不見**，要重貼歌單。
後端 profile 也沒落檔，服務重啟同樣全部失效。

## 19　情境標籤會同時顯示「低能量、高能量」

`_intent_label()` 只要 `energy_max` 和 `energy_min` 都有值就會兩個都印，
畫面上出現「理解情境：平靜、放空、低能量、高能量、60–100 BPM」，看起來像壞掉。
應該改成印區間（例如「能量 0.3–0.6」）而不是兩個矛盾的標籤。

## 20　雲端改用 Firestore，不是文件寫的 MongoDB

開發文件 §6 寫的是 MongoDB。GCP 沒有代管的 MongoDB，而 Cloud Run 閒置會縮到零、
記憶體版一死就清空（session 消失、快取沒了要重燒配額），所以雲端版改用 Firestore。

**三種儲存後端目前都在，介面完全一致**，靠 `STORAGE_BACKEND` 切換：

| 值 | 用在哪 | 狀態 |
|---|---|---|
| `memory` | 本機開發、測試 | 落檔到 `data/cache.json` |
| `mongo` | 本機 docker、內網 | **已實測**（TTL 索引 30 天已驗證） |
| `firestore` | Cloud Run | 雲端部署用 |

**交付時要說明的差異：**
- MongoDB 的 TTL 是 `expireAfterSeconds`（建立後 N 秒刪）；
  Firestore 的 TTL 是「`expires_at` 欄位時間到就刪」。
  因此 `firestore_repo.py` 一律寫入明確的 `expires_at`，語意等價但實作不同。
- §13 的「`video_cache` TTL 索引 30 天已建立」在 Firestore 上對應的是
  TTL 政策，可用 `gcloud firestore fields ttls list` 佐證，已 ACTIVE。
- 本機仍可用 MongoDB（`docker run -d -p 27017:27017 mirror.gcr.io/library/mongo:7`），
  §6 的資料模型與索引都已實際驗證過，交付內容不算落空。

## 21　公司網路擋 Docker Hub，要用 mirror.gcr.io

`docker pull mongo:7` 會 TLS handshake timeout。改用 Google 的映像檔 mirror 可以：

```bash
docker pull mirror.gcr.io/library/mongo:7
```

同一類限制：`api.reccobeats.com` 也連不到（NOTES #7）。

## 22　gcloud 需要 Python 3.10+，這台只有 3.9

系統 Python 是 3.9.6，沒有 brew、沒有 pyenv。用 uv 裝了一份免管理員權限的
獨立 Python 3.12，並包了一個 wrapper：

```bash
~/.museek-tools/gcloud   # 已設好 CLOUDSDK_PYTHON
```

專案本身還是跑在 3.9（`.venv`），但 Dockerfile 用的是 python:3.12-slim——
**本機與容器的 Python 版本不一致**，理論上可能出現只在其中一邊發生的問題。
目前沒踩到（程式碼有 `from __future__ import annotations`，相容 3.9），
但值得知道。

## ⚠️ 23　公開的 Cloud Run 端點帶著真實 YouTube 金鑰

部署用 `--allow-unauthenticated`（Demo 掃 QR Code 需要），而服務裡有真實金鑰。
**任何人拿到網址就能透過 `/api/recommend` 燒掉每日 10,000 點配額。**

目前的緩解：
- `--max-instances 3`
- 內建熔斷：當日超過 8,000 點自動切「僅用快取」（§8）

還沒做、建議 Demo 前補上的：
- 金鑰改放 Secret Manager，不要用 `--set-env-vars`（現在在 Cloud Run 設定裡看得到）
- 或加一個簡單的速率限制／請求來源檢查

## ⚠️ 24　現在有「兩個各自獨立的配額計數器」，加起來才是真的

本機（Mongo）和 Cloud Run（Firestore）各記各的，但**兩邊用的是同一把
YouTube 金鑰、同一個 Google 專案配額**。誰也不知道對方花了多少。

今天的實際情況：

| 來源 | 計數器顯示 | 說明 |
|---|---|---|
| 本機 Mongo | 412 | 開發與測試 |
| Cloud Run Firestore | 503 | 部署後的煙霧測試 |
| curl 直接打（驗證金鑰） | 未計入 | 約 3 點 |
| **實際 Google 端用量** | **約 918** | 以 GCP Console 為準 |

也就是說 `/api/health` 顯示的 503 只是雲端那一份，**真實用量將近兩倍**。

**影響：** 熔斷門檻（8,000 點切僅用快取）會失準——兩邊各自跑到 7,999 時，
Google 端其實已經快 16,000，早就超過每日 10,000 上限了。

**Demo 前務必做的：** 只留一個環境在打 YouTube。要嘛本機改用 stub、
要嘛雲端不帶金鑰。或者兩邊都指向同一個 Firestore（本機設
`STORAGE_BACKEND=firestore` 並提供 ADC）。

## ~~25　雲端沒有 LLM，理由會退成模板句~~（已解決：改接 Azure OpenAI）

Cloud Run 連不到 `llm-host`（Tailscale 內網位址），所以線上版 `LLM_CHANNEL=stub`。
同一首歌的理由差異：

| | 理由 |
|---|---|
| 本機（qwen3.8-27b） | 這首歌能量值 0.216 低於你的 0.549，適合雨天開車放空；但快樂度 0.604 高於你的 0.495，帶來不同於平常的明亮氛圍。 |
| 雲端（模板） | 速度 95.30 BPM，與你平常聽的幾乎一致；但律動感 0.06，比你的平均低出一截。 |

兩者都只引用真實音訊特徵（§12 的「每個數字都來自音訊分析」站得住腳），
但模板句明顯生硬、也不會回應使用者的情境描述。

**要補的話**，把 `LLM_CHANNEL=gateway` 指向任何公開的 OpenAI 相容端點即可，
程式不用改。Gemini 有 OpenAI 相容介面
（`https://generativelanguage.googleapis.com/v1beta/openai`），
同一個 GCP 帳號就能開金鑰，但要記得設 `GATEWAY_DISABLE_THINKING=false`。

## 26　Cloud Run 容器內跑 Tailscale 連內網 LLM

**做法：** 容器裡多跑一個 `tailscaled`，用 userspace 模式（Cloud Run 沒有
`/dev/net/tun`，不能用一般模式），它會開一個本機 HTTP proxy；
只有 LLM 的呼叫走那個 proxy，YouTube 與 Firestore 一律直連。

相關檔案：`Dockerfile`（裝 tailscale）、`entrypoint.sh`（啟動 tailscaled 再啟動 uvicorn）、
`app/services/llm.py` 的 `_llm_client()`（依 `LLM_PROXY` 決定走不走 proxy）。

啟用只需要兩個環境變數：

```bash
~/.museek-tools/gcloud run services update museek \
  --region asia-east1 --project <GCP_PROJECT_ID> \
  --update-env-vars "TS_AUTHKEY=<金鑰>,LLM_PROXY=http://localhost:1055,\
LLM_CHANNEL=gateway,GATEWAY_BASE_URL=http://llm-host:8000/v1,GATEWAY_MODEL=qwen3.8-27b,\
GATEWAY_TOKEN=<LLM金鑰>"
```

**沒有 `TS_AUTHKEY` 時 entrypoint 會自動略過**，服務照常啟動、LLM 退回 stub，
所以這個改動不會讓現有部署變得更脆弱。

### auth key 的注意事項

**一定要用 ephemeral + reusable 的金鑰。** Cloud Run 會縮到零，每次冷啟都是
一個新節點；非 ephemeral 金鑰會在 tailnet 上留下一堆殭屍節點。
金鑰本身也應該放 Secret Manager，不要用 `--set-env-vars`（同 #23）。

> 註：這是個人的 side project、外網開發、自用的 tailnet，
> 因此不涉及公司內網合規問題——開發文件 §1.2 的內外網分流是題目設定，
> 不是這個部署的實際限制。

### 替代方案（如果不想讓雲端碰內網）

把 `LLM_CHANNEL` 指向公開的 OpenAI 相容端點就好，完全不用 Tailscale：
Gemini 的相容介面是 `https://generativelanguage.googleapis.com/v1beta/openai`，
同一個 GCP 帳號就能開金鑰，記得 `GATEWAY_DISABLE_THINKING=false`。

## 27　Azure OpenAI 的 gpt-5.x 參數與舊模型不相容

`<AZURE_RESOURCE>` 上有三個 deployment，其中 `gpt-4o-transcribe-diarize`
是語音轉錄用的，不能做 chat。可用的是 `gpt-5.6-luna`（目前採用）與 `gpt-5.6-terra`。

gpt-5.x 拒絕兩個常見參數：

| 參數 | 錯誤 |
|---|---|
| `max_tokens` | `Unsupported parameter: use 'max_completion_tokens' instead` |
| `temperature: 0.2` | `Only the default (1) value is supported` |

`_call_azure()` 因此做了參數風格自動偵測（`AZURE_PARAM_STYLE=auto`）：
先試 modern（`max_completion_tokens`、不帶 temperature），被拒就退 legacy
（`max_tokens` + temperature），並記住結果。之後若改接 gpt-4o 不用改程式。

## ⚠️ 28　推理模型的 token 預算必須涵蓋「思考 + 輸出」

跟 NOTES #4 的 qwen 完全同一個坑，換到 Azure 又中一次：
`explain` 原本傳 `max_tokens=300`，luna 的思考直接吃光，
**HTTP 200 但 `content` 是空字串**，於是每一首理由都靜靜退回模板。

弔詭的是本機實測時 luna 是成功的——思考長度會浮動，300 只是「有時候夠」。

**修法：** modern 風格會把預算抬到 `AZURE_MIN_COMPLETION_TOKENS`（預設 2000）。
這是下限不是上限。

**這個坑會反覆出現**，只要換模型就要重驗一次。判斷方式：
理由如果長得像「速度 95.30 BPM，與你平常聽的幾乎一致；但律動感 0.06，比你的平均低出一截。」
那就是模板，不是模型。

### 現在看得見了

`/api/health` 的 `llm` 欄位新增 `degraded` 狀態：有設定 LLM、但最近一次
explain 實際產不出內容時會顯示。之前這種降級完全無聲（同 #16 的教訓）。

## 29　模型對同一個特徵用了好幾種譯名

同一輪推薦裡出現：樂器性／器樂性（instrumentalness）、原音感／音響性（acousticness）、
舞動性／舞動感（danceability）。使用者會以為是不同指標。
應該在 EXPLAIN_SYSTEM 裡明確給定譯名對照表。

## 30　雲端一輪推薦要 40 秒

5 首理由序列生成，Azure 每則約 7 秒（本機 llm-host 約 1.3 秒）。
加上解析與排序，一輪 41.6 秒——**Demo 腳本 §12 給思考串流的時間是 40–55 秒共 15 秒**，
差距很大。要嘛改成並行生成（會變成五首一起跳出來，少了逐首浮現的效果），
要嘛 Demo 前先跑一輪讓快取熱著。Day 5 演練時要實際計時。

## ~~⚠️ 31　不同情境會給出一模一樣的推薦~~（三個原因已全部修正）

雲端實測：對同一個 session 依序輸入「下雨天開車想放空，不要太吵」、
「健身房想要熱血一點的」、「想聽點沒聽過的冷門音樂」，
**後兩者回傳完全相同的五首歌，順序也一樣**。四次探索總共只出現 8 首不重複的歌。

這不是快取造成的——快取只影響配額，不影響選誰。三個原因疊加：

### 31a　Azure 對很多情境解析不出任何限制

| 輸入 | Azure 解析出的 constraints | 規則式解析出的 |
|---|---|---|
| 下雨天開車想放空，不要太吵 | `{"energy_max": 0.4}` | `{"energy_max": 0.5, "tempo_range": [70,110]}` |
| 健身房想要熱血一點的 | **`{}`** | `{"energy_min": 0.6, "tempo_range": [110,165]}` |
| 想聽點沒聽過的冷門音樂 | **`{}`** | `{}` |

constraints 是空的，硬過濾就沒東西可濾，排序退回「純看品味相似度」，
於是不管使用者說什麼都拿到同一批歌。

**原因在我們自己的提示詞**：`INTENT_SYSTEM` 寫了「無法判斷的欄位給 null，不要臆測」，
模型因此不敢把「熱血」轉成數字。這句話本來是要防幻覺的，結果過度保守。
**規則式解析在這題上比 LLM 準**，這點很反直覺但實測如此。

修法方向：在提示詞裡給幾個對照範例（few-shot），
明確說「熱血／嗨 → energy_min 0.6、tempo 110–165」這類映射。

### 31b　exploration 解析出來就被丟掉

Intent JSON 有 `exploration: high|medium|low`，`prompts.py` 也要求模型輸出，
但**整個排序完全沒有讀它**。「想聽沒聽過的冷門音樂」應該要放寬探索帶、
提高 novelty 權重，現在什麼都不會發生。

### 31c　候選池是固定的 40 首

`RECCOBEATS_MODE=stub`，候選來源是 `stub_data._STUB_LIBRARY` 這個寫死的清單。
**不管換幾次情境、重新探索幾次，都是在同樣 40 首裡重排。**
真實的 ReccoBeats 尚未驗證（NOTES #7），這是那件事的下游影響。

> 對 Demo 的意義：「換個情境會給不一樣的歌」這件事目前**不保證成立**。
> 演練時要挑實際驗證過會產生差異的情境組合，或先把 31a、31c 修掉。

## ~~32　`rank()` 的「已套用硬過濾」旗標會說謊~~（已修）

目前 `rank()` 的行為是「分級」不是「全丟」——違反限制的候選排到後段而不是剔除。
但只要有任何一首違反限制，回傳的旗標就是 `True`，即使**通過的有 0 首**。

pipeline 拿這個旗標去組 SSE 的文字：

```python
filter_note = "（已先濾掉違反情境的曲目）" if hard_filtered else ""
```

於是畫面會顯示「已先濾掉違反情境的曲目」，但實際上一首都沒濾掉、
前五名全是違反限制的候選（實測「睡前想聽安靜的原音」就是 0 首通過）。
**這是會在 Demo 現場被戳破的文案。**

## ⚠️ 33　程式碼檔案在我的編輯之外被改動過

`app/core/ranker.py` 與 `tests/test_ranker.py` 的內容，與我當初寫入的版本不同
（`rank()` 從「全丟」改成「分級」、`min_pool` 預設從 8 變成 5、
測試的斷言也跟著改了）。這是繼 `.env` 被覆蓋（#16）之後第二次。

我無法從現有紀錄判斷是什麼造成的。實務影響：
**我對「程式碼現在長什麼樣」的認知不能只靠記憶**，
牽涉行為的判斷都要當場重讀檔案再下結論。

## 34　ReccoBeats 真實 API 與文件推測的三處落差

實測後修正（`app/services/reccobeats.py` 已改）：

| 項目 | 原本的推測 | 實際 |
|---|---|---|
| 搜尋 | `searchText="歌手 歌名"` | **會回 0 筆**。只能用歌名搜，再從 `artists[].name` 比對歌手 |
| 批次特徵 | `/v1/track/{id1,id2}/audio-features` | 該路徑只吃單一 id。批次要用 **`/v1/audio-features?ids=a,b`** |
| 推薦回傳 | 以為含特徵與 popularity | **兩者都沒有**。特徵要再查一次，popularity 根本不存在 |

### ⚠️ 34a　novelty 失去資料來源

§5.3 的 `novelty = 1 - popularity / 100` 依賴 popularity，而 **ReccoBeats 沒有這個欄位**。
目前缺值時 novelty 固定 0.5，等於權重 0.25 的那一項變成常數、完全不影響排序。

Day 5 調參時要處理：要嘛換一個新鮮度指標，要嘛把那 0.25 重新分配給 band 與 context_fit。

### 34b　推薦結果的文化跨度很大

用 Radiohead 當種子，回傳包含王OK、Cupido、Connie Francis、Barış Manço、Falco。
特徵上合理（energy 都符合限制），但「我聽 Radiohead，你推土耳其老歌」在 Demo 現場不好解釋。
這是 ReccoBeats 推薦引擎本身的行為，不是我們的 bug。

## ⚠️ 35　從 stub 切到真實模式時，舊快取會假裝自己是真的

切換 `RECCOBEATS_MODE` 之後，`feature_cache` 裡 123 筆 stub 時代寫入的假特徵
**仍然會被當成真資料取用**——NPR 歌單因此顯示「收錄 50/50」、向量看起來完全正常，
但那整支向量是雜湊亂數。清掉快取後真相是 **0/50**。

**已修：** 快取項目現在會標記 `source`（stub / reccobeats），
真實模式一律拒用 stub 項目；沒有 source 的舊項目視同 stub。
另外提供 `scripts/purge_stub_cache.py` 實際刪除。

> 這是「假資料看起來比真資料正常」的典型案例。
> 之後任何一次資料來源切換，都要先問一句：舊快取會不會混進來。

## 36　NPR 那份歌單不是合適的測試素材

`UU4eYXhJI4-7wSWc8UNRwD4A` 是 NPR Music 的頻道上傳 feed，內容是
「Mon Rovîa: Tiny Desk Concert」這類影片標題與宣傳貼文，不是歌曲。
真實 ReccoBeats 下比對率 0%。之前一直「正常」純粹是 stub 對任何字串都給得出特徵。

改用藝人頻道的上傳 feed 比較接近真實情境（Radiohead 的 `UUq19-LqvG35A-30oyAiPiqA`
實測 16/50）。**正式的三組示範歌單仍待策展**（§2.2 是 T 的工作）。

順帶已修 NOTES #5 的冒號分隔：「Mon Rovîa: Tiny Desk Concert」現在切得出歌手。
