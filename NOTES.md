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

## 12　示範歌單還是佔位符（已作廢，見 #42）

`app/api/routes.py` 的 `DEMO_PLAYLISTS` 是三組假 ID，等 T 策展完替換。
前端在歌單解析失敗時已經會跳出一鍵切換按鈕，接上真 ID 就能用。

**2026-09-04：整個示範歌單機制已移除，不再策展。** 詳見 #42。

---

## ⚠️ 13　「開始探索」會忽略使用者填的歌單網址，並撞上 400（後端已修，前端已於 #42 處理）

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
實測 16/50）。這只是測試用的歌單，不是產品裡的示範歌單——產品已經沒有示範歌單了（#42）。

順帶已修 NOTES #5 的冒號分隔：「Mon Rovîa: Tiny Desk Concert」現在切得出歌手。

## ⚠️ 37　多金鑰輪替（刻意加入，需要知情使用）

`YOUTUBE_API_KEYS` 支援逗號分隔多把金鑰，一把的當日配額用盡就自動換下一把，
全部用盡才熔斷成「僅用快取」。

**這是專案負責人在知悉風險後的明確決定，不是預設行為。**

### 風險（決定當下已充分討論）

Google 的 API 條款將「一個 API Client 跨多個專案取用配額」視為規避配額。
金鑰分屬不同人的不同帳號**不改變**這個判斷——Google 端看到的是同一個服務
（同一個 Cloud Run 網址、同一組流量特徵）持有多個專案的金鑰。

後果是**清單裡每一把金鑰、以及它們所屬的專案可能一併被撤銷**。
使用多人金鑰時，風險落在每一位擁有者身上，不只是部署者。使用前請確認每個人都知情。

專案原始的開發文件 §8 也獨立提出過同一個限制。

### 沒有風險的替代做法（優先考慮）

| 做法 | 效果 |
|---|---|
| **預熱快取**（§8 第 2 層） | Demo 當天每輪 0 點。`scripts/prewarm_cache.py` |
| 多人各自本機開發、各用自己的金鑰 | 完全正常，不是輪替 |
| 單把金鑰 + 手動故障備援 | 主金鑰被撤時人工換上，正當用途 |

### 實作說明

- 設定：`YOUTUBE_API_KEYS=key1,key2,key3`（設了就取代 `YOUTUBE_API_KEY`）
- 每把金鑰**各自記帳**：儲存的文件 id 是 `<太平洋日期>#<金鑰指紋>`，
  指紋是 sha256 前 8 碼，**金鑰本身不會寫進資料庫**
- 換手時機有兩種：主動（用量達上限）與被動（YouTube 回 403 quotaExceeded
  時呼叫 `mark_exhausted`，把那把直接記到上限，重啟後不會又用它）
- 熔斷條件從「單把過門檻」改成「**每一把都過門檻**」
- `/api/health` 新增 `quota_keys`（每把的用量、是否耗盡、是否使用中）
  與 `active_key`（目前用第幾把）——這件事是刻意做成看得見的

### 順帶修掉的一個舊問題

`QuotaTracker` 原本只在**跨日**時才重讀資料庫，同一天內看不到其他執行個體
寫入的用量。多個 Cloud Run 執行個體會各自以為金鑰還沒用過而一起超花。
現在加了 5 秒 TTL 重讀，漂移有上界。**這個毛病單金鑰時就存在**，
只是多金鑰讓它更容易造成實際損失。

---

## 38　曲庫查不到的歌會讓品味向量整排 0.00（已修）

單曲入口貼一首 Luci Gang 的歌，「我讀到的你」四條長條全部是 0.00。
不是計算錯誤——那首歌 ReccoBeats 曲庫沒有，`search_track` 回 None，
`_features_for` 就跟著回 None，那首歌根本沒有特徵可以平均。

華語與獨立廠牌的曲庫命中率本來就不高，單曲入口又只有一首歌，
一首沒中就是整支向量空白。這在 Demo 現場是會直接被看到的畫面。

### 修法：第二條取得特徵的路

ReccoBeats 除了曲庫查詢，還有一支 `POST /v1/analysis/audio-features`，
吃的是**音訊檔**而不是曲目 id（上限 5MB／30 秒）。所以缺的其實只是音檔來源。

音檔用 iTunes 公開搜尋 API 的 30 秒試聽片段：免金鑰、每首歌都附一段，
長度與大小天生就落在分析端點的限制內。

```
曲庫 search → 有 id 且有特徵 → 用曲庫的（source=reccobeats）
             ↓ 沒有
        iTunes 找試聽片段 → 下載 → POST 分析端點（source=analysis）
             ↓ 還是沒有
        matched=False，維持原本的降級提示
```

### 實測（2026-09-03，真的打了外網）

| 曲目 | 曲庫 | 分析結果 |
|---|---|---|
| Luci Gang – HEADLOCK | miss | energy 0.81／valence 0.68／tempo 132.6 |
| 草東沒有派對 – 大風吹 | miss（曲庫裡是 No Party For Cao Dong，歌手名對不上） | energy 0.48／valence 0.54／tempo 153.3 |
| deca joins – 浴室 | miss（曲名太短，見下） | energy 0.24／valence 0.19／tempo 126.6 |
| Frank Ocean – White Ferrari | hit | 走曲庫，不浪費一次分析 |

兩件實測才知道的事：

1. **分析端點吃 m4a。** 文件只列 MP3／OGG／WAV／AIFF，但 iTunes 給的是
   AAC/m4a，直接送過去回 200。省掉了 ffmpeg 轉檔這整包依賴。
2. **兩種來源的特徵是同一個尺度**，可以混在同一支向量裡。同一首 White Ferrari：
   分析值 energy 0.14／tempo 103.7／loudness -16.4，
   曲庫值 0.096／108.7／-15.6。

### 順帶修掉的一個毛病

`/v1/track/search` 的 `searchText` **少於 3 個字會回 400**。
兩個字的華語曲名（浴室、唯一、魚）永遠搜不到，而且那趟白費的請求
會把 `_last_call_ok` 標成 False，`/api/health` 就誤報 `degraded`。
現在短曲名直接跳過曲庫搜尋，走分析那條路。

### 成本與上限

每首約 3 秒（下載 1s + 分析 2s），而且是序列的。50 首都沒中的歌單
不設上限會讓 `/api/session` 卡好幾分鐘，因此 `ANALYSIS_MAX_PER_SESSION`
預設 8 首。結果一樣寫進 `feature_cache`（`source=analysis`），
同一首歌只會分析一次。

實測 24 首的歌單（stub 歌單、真實 ReccoBeats）：**44 秒**，
matched 從 12 升到 20（曲庫 12 + 分析 8），unmatched 4。
其中約 24 秒是那 8 次分析。`/api/session` 整條流程本來就是序列的
（24 首各自 search + audio-features 兩趟），要再快就得整段改成併發——
這件事還沒做，跟 #30 是同一個題目。

`/api/session` 的回應多了 `analyzed` 欄位，說明 matched 之中有幾首
是靠分析補上的——跟金鑰輪替一樣，這件事刻意做成看得見的。

### 分析出來的曲目沒有 recco_id，當不了推薦種子

見 #39——那才是真正的解法，這一節留著是因為它是問題的入口。

---

## 39　能不能拿分析出來的數值去曲庫「找相似的歌」？不行，但問題有解

#38 留下的洞：分析出來的特徵沒有 recco_id，當不了推薦種子。
直覺的想法是「那就拿那組數值去 ReccoBeats 找相似的歌」——
**這條路 API 不支援**，實測結論如下。

### 實測：推薦端點吃什麼、不吃什麼

`GET /v1/track/recommendation`

| 參數 | 結果 |
|---|---|
| `seeds` | **必填**。沒帶直接 400：`Required request parameter 'seeds' ... is not present` |
| `seeds` = 歌手 id | 400：`seeds need at least one track`。只吃曲目 id |
| `seeds` = Spotify 曲目 id | 可以，等同 ReccoBeats id |
| `tempo` | **有效**。同一顆種子，`tempo=70` 回傳曲目平均 57.8 BPM、`tempo=180` 平均 124.6、不帶是 80.9 |
| `energy`／`valence`／`acousticness`／`danceability` | **送了沒有作用**。0.0 與 1.0 兩組各取 ~85 首，平均 0.353 vs 0.367，最小值也沒有變 |
| `target_energy`／`targetEnergy`／`minEnergy`／`energyMin`／`min_energy` | 同樣沒有作用（未知參數會被安靜忽略，不會報錯） |

端點本身是**隨機的**——同一組參數連打三次回傳的曲目集合都不同，
所以上面每一格都是多次取樣後比平均，不是單次比較。

**結論：品味向量只能用在自家的 Discovery Ranker 排序，取候選還是得靠曲目 id。**

### 那就把 id 拿回來——曲庫其實有那些歌，是我們查法太窄

原本只有一種查法：用曲名搜 `/v1/track/search`，再比對歌手。三個地方會漏：

1. `searchText` **少於 3 個字回 400**（浴室、唯一、群青）。
2. 曲庫是 **Spotify 血統，歌手名不見得同一套寫法**：
   茄子蛋＝EggPlantEgg、草東沒有派對＝No Party For Cao Dong、告五人＝Accusefive。
3. **連曲名都會被換掉**：大風吹在美國商店叫 Simon Says、浪子回頭叫 Back Here Again。

補救的關鍵是 iTunes 的 `/lookup?id=<trackId>&country=<store>`——
同一個 trackId 在另一個商店的中繼資料，等於一組免費的中英對照表。
而且這一趟本來就要打（#38 的試聽片段），沒有多花成本。

補救順序（`pipeline._recover_via_itunes`）：

```
曲名搜尋（原本的）→ 沒中
  ↓ iTunes 認出這首歌，順便拿各商店的寫法
帶著別名重搜曲名 → 沒中
  ↓
歌手搜尋 → /v1/artist/{id}/track 翻曲目清單比對曲名   ← 兩個字的曲名只有這條路
  ↓ 還是沒中
分析試聽片段（#38）——拿得到特徵，拿不到 id
```

歌手曲目清單那條路是最可靠的：`/v1/artist/search` 沒有 3 字下限，
也不受曲名翻譯影響。每頁上限 50，`page` 可翻頁，這裡取兩頁。

### 實測（2026-09-03，真的打了外網）

| 曲目 | 改之前 | 改之後 |
|---|---|---|
| 茄子蛋 – 浪子回頭 | miss | 曲庫 `37993927…`（別名 EggPlantEgg） |
| deca joins – 浴室 | miss（曲名 2 字） | 曲庫 `b315d235…`（歌手曲目清單） |
| 告五人 – 唯一 | miss（曲名 2 字） | 曲庫 `80b6d242…`（別名 Accusefive） |
| 草東沒有派對 – 大風吹 | miss（歌手名對不上） | 曲庫 `f322b86b…`（別名 No Party For Cao Dong） |
| Luci Gang – HEADLOCK | miss | 曲庫真的沒有 → 分析特徵，無 id |
| 落日飛車 – My Jinji | 曲庫 | 曲庫 |
| Frank Ocean – White Ferrari | 曲庫 | 曲庫 |

**可用種子 2/7 → 6/7**，整批 9.1 秒。
24 首的 stub 歌單跑真實 ReccoBeats：matched 12 → 19，其中只有 1 首需要走到音訊分析。

### 真的一首都對不上的時候

`get_recommendations([])` 原本會**退回 stub 假曲庫**——向量是真的、候選是假的，
跟 #35 是同一種錯。現在真實模式下 seeds 為空就回 `[]`，
`/api/recommend` 送出 `error` 事件（`code: no_seeds`）照實說明。
stub 模式維持原樣，內網端到端流程不受影響。

不過在那之前還有一層：**種子不必是同一首歌**，見 #40。

### ⚠️ 順帶觀察到：ReccoBeats 有速率限制

驗證期間密集呼叫（一輪 session 就有 50＋ 趟）吃到 **429 Too Many Requests**，
`search`／`audio-features`／`analysis` 三個端點都會中。
`get_json` 本來就會對 429 退避重試一次，退不過就降級（該首沒有特徵），
所以流程不會斷——但**歌單愈長愈容易踩到**，Demo 前先跑一次預熱比較保險。
確切的門檻沒有文件，也還沒實測出來。

### 兩個開關

`RECCOBEATS_RECOVERY`（整段補救）與 `RECCOBEATS_ANALYSIS`（只關音訊分析那半）。
分開是因為成本差三倍：別名回查約 1 秒且拿得到種子，音訊分析約 3 秒且拿不到。
`RECOVERY_MAX_PER_SESSION` 預設 12。

### 還沒做

`tempo` 是唯一實測有效的參數，而 Intent Parser 本來就會解出 `tempo_range`。
把它接進推薦端點，候選池就會直接貼近使用者講的情境——這也正好是 #31c
（候選池是固定的 40 首）的解法之一。還沒做。

---

## 40　曲庫真的沒有那首歌時，用「代打種子」

#39 的結論是「取候選一定要曲目 id」，於是 #38 的分析路徑看起來是死路：
分析出來的特徵沒有 id，當不了種子。

漏掉的一件事是：**種子不必是同一首歌**。推薦端點要的只是一顆曲目 id，
用來指出「從曲庫的哪個鄰居開始找」。實際挑哪一首由我們決定——
那正好是分析出來的那組數值派得上用場的地方。

### 曲庫沒收那首歌，歌手通常還在

實測 Luci Gang – HEADLOCK：曲目查不到，但 `/v1/artist/search` 找得到 Luci Gang，
底下**有 77 首**。把他的曲目批次查特徵，用 `ranker.similarity`
（跟排序同一支加權歐氏距離，tempo 一樣除以 200）比對分析出來的向量，挑最近的一首：

| 候選 | energy | valence | tempo | 距離 |
|---|---|---|---|---|
| HEADLOCK（分析值，目標） | 0.809 | 0.679 | 132.6 | — |
| Take It Slow | 0.774 | 0.573 | 131.9 | 最近 |
| NORI (Remix) | 0.851 | 0.779 | 140.0 | 次之 |
| OK! | 0.567 | 0.674 | 140.0 | 最遠 |

### 完整的種子取得順序

```
1. 曲目本身在曲庫              → recco_id（最好）
2. 別名／歌手曲目清單找得到      → recco_id（#39）
3. 曲目沒有、歌手還在           → 同一位歌手特徵最近的那首 = seed_id（本節）
4. 歌手也沒有                  → no_seeds 錯誤，不造假
```

代打種子存在 `seed_id`，**不寫進 `recco_id`**——那個欄位的意思是
「這首歌在曲庫裡的 id」，塞別首歌的 id 進去，快取就開始說謊了。
取種子時 `recco_id or seed_id`。

### 實測（2026-09-03，真的打了外網）

單曲入口貼 Luci Gang – HEADLOCK（就是那張四條 0.00 的截圖）：

```
音訊分析補上特徵：energy 0.809 / valence 0.679 / tempo 132.6
代打種子：DUMB（相似度 0.909，原曲不在曲庫）
→ 43 首候選 → 回傳 5 首，全部落在 124–130 BPM、energy 0.63–0.97
```

一首歌的歌單，從「四條 0.00、沒有候選」變成一輪完整的推薦。

### 為什麼這樣是誠實的

代打種子只決定**去曲庫的哪一區撈候選**，最後排序用的仍然是真的品味向量
（Discovery Ranker 那支加權歐氏距離）。所以候選池的鄰居選對了，
排序也還是照使用者的實際口味與情境走——沒有任何一個回傳給使用者的數字是假的。

### 順帶

`artist_catalog()` 有行程內快取（上限 64 位歌手），
同一份歌單常有同一位歌手的多首歌，而且「查不到這位歌手」也要記住，
否則每一首都會再問一次。測試用 `reset_artist_cache()` 清掉。

`tests/conftest.py` 另外加了一道 `no_network` 防線：
任何測試只要真的建了 HTTP client 就失敗。這次就是它抓到
`_proxy_seed` 在測試裡偷偷打了外網（130 個測試從 0.3 秒變成 15 秒）。

---

## 41　單曲貼進來卻「沒有跑分析」——問題出在切歌名，不在分析（已修）

貼一首新的歌進去，回應是「這首歌沒有對應的音訊特徵，推薦會更依賴你描述的氛圍」，
而且 log 裡完全沒有分析的痕跡。#38 那條音訊分析的路是通的（Luci Gang 就是這樣救回來的），
所以問題不在分析本身——**是它根本沒被觸發**。

### 觸發鏈斷在第一步

```
YouTube 標題 → split_artist_title → 曲庫查不到 → iTunes 認歌 → 試聽片段 → 分析端點
                     ↑ 斷在這裡：歌名裡還黏著歌手名，後面每一步都查不到
```

`告五人 Accusefive [ 唯一 Only ] Official Music Video` 切出來的歌名是
**整串「告五人 Accusefive [ 唯一 Only ]」**：方括號不在「括號裡是歌名」那條規則裡，
標題又沒有 ` - ` 分隔符。歌名錯了，曲庫查不到、iTunes 也查不到，
沒有 `previewUrl` 就沒有音檔，分析端點自然一次都沒被呼叫。

### 四個各自獨立的洞

| # | 症狀 | 例子 | 修法 |
|---|---|---|---|
| 1 | 方括號裡的歌名被當成整串歌名 | `告五人 Accusefive [ 唯一 Only ]` | `_TITLE_IN_BRACKET` 收 `[]`／`［］`，並加版本標記防呆（`[Remix]` 不是歌名） |
| 2 | 沒有分隔符時歌手名黏在歌名前 | `【HYBS】Tip Toe` → 歌名 `HYBS Tip Toe` | 退回頻道名當歌手時，把歌名開頭重複的那段拿掉 |
| 3 | 中英並列的歌名整串查不到 | iTunes 上「陳綺貞 Cheer Chen 魚 Fish」0 筆、「陳綺貞 魚」查得到 | `title_variants()`：兩種寫法各送一次，比對時任一種對上就算 |
| 4 | 撇號被清成空白 | `That's What I Like` → `That s What I Like` | 只清成對的引號，字中間的 `'`／`’` 留著 |

順帶修掉的：全形 `［Official Video］` 不在雜訊括號的字元集裡；
`歌手 'Song' M/V`（HYBE／SM／YG 的固定寫法）以前會把頻道名當歌手；
iTunes 的商店譯名（`Official髭男dism` ↔ `Official鬍子男dism`）用包含比不出來，
改成相似度 ≥ 0.85 才算——門檻放低會把「告五人」配到「五月天」身上，錯配比查不到更糟。

### 實測（2026-09-03，真的打了外網）

拿 10 個真實的 YouTube 標題樣式跑完整條鏈：**3/10 → 7/10**。
剩下 3 首（Karencici – Ma Ma Ma、9m88 – 洗澡、持修 – 浪漫的逃亡）是
**Apple Music TW／US 真的沒有收**，翻完那三位歌手的全部曲目都找不到——
沒有音檔就沒有分析，這種只能照實說。

### 有種子沒特徵，不能一起丟掉

`_features_for()` 以前只要沒特徵就回 `None`，連同已經拿到的 `recco_id` 一起丟。
單曲入口只有一首歌，種子丟了就直接是 `no_seeds`。現在特徵補不上、但曲庫認得這首歌時，
會保留 id 當種子（**不寫快取**——特徵下次可能補得上，記下來反而擋住重試），
`matched` 也改成看特徵而不是看有沒有查到東西，否則比對率會算錯。

降級訊息也跟著分成兩種，因為這是兩種不同的處境：

- 有種子沒特徵 → 「以曲庫裡最接近的同名曲目為種子，並更依賴你描述的氛圍」
- 兩者都沒有 → 「ReccoBeats 與 iTunes 都查不到⋯⋯換一首或改貼整份歌單」

### 教訓

跟 #4 是同一件事的另一面：那次是「有回傳不等於 LLM 有在工作」，
這次是**「補救路徑存在，不等於它有被走到」**。降級訊息只說了結果（沒有特徵），
沒說是哪一步斷的，於是看起來像分析失敗，實際上分析連呼叫都沒發生。
曲名正規化是整條鏈的第一步，它錯了，後面每一層的重試都在查一個不存在的東西。

---

## 42　拿掉全部示範歌單，空品味改用「馬上建立」（已改）

**問題：** 首頁一進來按「我的品味」，前端會拿寫死的
`https://www.youtube.com/playlist?list=DEMO001` 去建 session，
接真 API 之後這個 ID 不存在，於是初始狀態就跳「無法解析連結」——
使用者什麼都還沒做，看到的第一個畫面卻是錯誤。#13 講的是同一條路徑，
當時前端改動被還原了，這次一起處理掉。

**改法：** 示範歌單整套移除，不留佔位符也不再策展（#12 作廢）。

- 後端：刪掉 `DEMO_PLAYLISTS`、`GET /api/demo-playlists`、
  以及三個錯誤 detail 裡的 `hint`（`ErrorDetail.hint` 欄位一併移除）。
  解析失敗的訊息改成請對方換公開連結，不再叫人「試試示範歌單」。
- 前端：對話框拿掉示範歌單按鈕清單；`showDialog` 第三個參數改成一顆可自訂的 CTA
  （`{label, run}`），沒帶就還是「知道了」關掉。
- 空品味狀態統一走 `showTasteEmptyDialog()`：標題「尚未建立品味清單」，
  CTA「馬上建立」直接切到入口頁（貼歌單／情境）。首頁與導覽列的「我的品味」
  都改成 `data-go="profile"`，由同一個判斷決定跳品味頁還是跳這個對話框。
- `recommend()` 沒有 session 時不再偷偷建 DEMO session，改為跳同一個對話框。

**教訓：** 「找不到資料時給個假的預設值」在 stub 階段看起來很體貼，
接上真實服務之後它就是一個必定失敗的請求。空狀態該做的是把人帶到能產生資料的地方，
不是替他生一份假資料。

## 43　「只描述情境」的入口：品味不是聽出來的，是推出來的（已做）

原本情境欄位其實是假的：`recommend()` 沒有 session 時會去讀上面那格連結，
連結也空著就跳「尚未建立品味清單」。所以「描述此刻的氛圍」從來不能單獨用。

現在 `POST /api/recommend` 可以不帶 `session_id`。後端要補的是歌單本來提供的兩樣東西：

| 歌單提供的 | 情境入口怎麼補 |
|---|---|
| 品味向量（聽過的歌逐維度平均） | LLM 讀出氛圍的中心值，再收進 Intent 的上下限 |
| 推薦種子（曲目 id） | LLM 給 3～5 位起點歌手，各挑一首最貼近氛圍的（沿用 #40 的代打種子） |

**兩個地方是刻意這樣做的：**

1. **上下限一律壓過中心值**（`ranker.target_vector`）。使用者說「不要太吵」、
   模型卻給 energy 0.8 時，band 會把分數推向硬過濾等一下要砍掉的那一區，
   前段就排滿了隨後被判違規的歌。中心值只在限制沒講到的維度作數。
2. **理由不准提「你常聽的」**。這條路上沒有聆聽紀錄，向量是從情境推出來的目標值。
   `explain(..., mood_only=True)` 會換掉提示詞與模板用詞——這不是措辭問題，
   是不能對使用者宣稱一件沒發生過的事。

**原本的已知落差（#44 已補上）：** LLM 掛掉時規則式給得出氛圍與中心值，
但 `seed_artists` 一律是空的，於是情境入口會直接回 `no_seeds`。

## 44　備援種子池：情境入口找不到起點時的後路（已做）

實測「深夜開車」跳出 `no_seeds`——#43 那個刻意的取捨，在真實環境撞上了。

**第一件事是先分得出兩種故障。** 原本 `_vibe_seeds()` 在「LLM 沒給歌手」那條路
連 log 都沒寫，線上只看得到一個沒有頭緒的 `no_seeds`：

| 實際狀況 | 現在的 log |
|---|---|
| LLM 沒給歌手（降級／格式不對） | `氛圍推薦：LLM 沒有給任何起點歌手` |
| 給了但曲庫一位都沒收 | `氛圍推薦：X、Y、Z 都不在 ReccoBeats 曲庫裡，改用備援種子` |

**為什麼不是「氛圍 → 歌手」對照表。** 一開始想的是那個，但那要我們替
「深夜開車配這五位」這種主張辯護，而且模型本來就答得比我們好——它答不出來
的機率遠低於曲庫沒收的機率。真正缺的不是知識，是**一個保證查得到的起點**。

所以 `services/seed_pool.py` 存的是一份**覆蓋特徵空間**的歌手清單：
安靜↔吵、陰鬱↔明亮、原音↔電子、慢↔快每個方向都有人守著，
挑哪幾首完全由目標向量的距離決定。這樣就不必宣稱任何品味主張，
挑選邏輯也和其他地方是同一套數學。

**三個實作上的決定：**

1. **當備援，不當替代。** 模型給的歌手優先——那是照使用者這一次的情境挑的。
   一位都沒對上才退。
2. **存 `recco_id`，不存名字。** `scripts/verify_vibe_seeds.py` 對真實曲庫跑一輪，
   把清單解析成 `data/vibe_seeds.json`（要進版控）。存名字等於把同一個
   「查不到」的問題再走一次；有這個檔就是零 API 呼叫、每首都保證查得到。
   查不到的歌手會列出來——那份名單就是「清單該換人了」的訊號。
3. **前 12 名之內隨機取 5 首。** 純取 Top 5 的話，備援救回了推薦，
   卻讓所有人的「深夜開車」變成同五首歌。

**這件事要看得見。** `session` 與 `done` 事件都帶 `seed_source`
（`vibe` / `fallback` / `none`），前端在用備援時會明說。推薦的起點被換掉了，
那不是實作細節——#4 的教訓就是降級路徑太安靜會蓋住故障，備援本身也適用同一條。

## ⚠️ 45　配額用完時 Google 回 429，程式把它讀成「每首歌都查不到」（已修）

「熱鬧愉快的氛圍」只推出一首歌。log 顯示 `dropped: 9, quota_spent: 800`——
八次搜尋全部失敗、還全部被記了帳。直接打 API 才看到真正的回應：

```json
{ "error": { "code": 429, "status": "RESOURCE_EXHAUSTED",
  "errors": [{ "reason": "rateLimitExceeded" }],
  "message": "Quota exceeded for quota metric 'Search Queries' ..." } }
```

**是 429，不是 403。** `_quota_error()` 原本只認 403，於是這個回應一路掉到
「search.list 失敗 → 回 None」那條路，而 resolver 對 None 的解讀是
**「這首歌在 YouTube 上不存在」**。三件事同時發生：

1. 熔斷沒跳、金鑰沒換——每一首候選都白打一次已經注定失敗的請求；
2. 每一首都被寫進 `video_cache` 標記 `embeddable: false`，
   **快取 30 天內再也不會推出這些歌**（實際被汙染 15 筆，已清掉）；
3. 配額被記了 800 點假帳——那八次呼叫其實一點都沒花到。

**修法的重點是「查無此曲」與「打不通」必須是兩件事。**
`search_video()` 現在只有真的查完、結果是空的才回 `None`；服務層面的失敗
（非配額的 4xx／5xx／逾時）拋 `SearchUnavailable`，配額類的（403 或 429，
含 `RESOURCE_EXHAUSTED`）拋 `QuotaExceeded`。resolver 收到 `SearchUnavailable`
就本輪轉「僅用快取」：不寫快取、不算 dropped、不記配額，但已經快取過的候選
繼續湊——服務掛了不該連原本拿得到的幾首都一起沒了。

**湊不滿也要說出原因。** `done` 事件補上 `wanted` 與 `search_down`，
前端在少於五首時明說是額度用完還是真的找不到可嵌入的影片。
只給一首又不解釋，看起來就是推薦引擎壞了——這和 #4、#44 是同一條教訓。

**順帶修的第二件事：** 這次的情境「熱鬧愉快」在規則式解析裡一個詞都沒中
（LLM 走的是地端 gateway，當下連不上）。`mood` 是 null、中心值就是中性的
0.5／0.5／0.4，推薦自然不熱鬧。規則式是 LLM 掛掉時的全部理解能力，
同義詞漏一個就等於那個情境不存在——已補上「熱鬧／派對／慶祝／歡樂／有活力」
這一組，並給它們比一般「愉悅」更吵、更好搖擺的中心值。

## ⚠️ 46　「推薦怎麼還是一整排歐美」——問題不在排序，在候選池根本沒有亞洲（已改）

使用者的原話是「可以多一點亞洲音樂的比重嗎，現在還是主要是歐美」。
第一反應是去改起點歌手（提示詞裡本來就寫著「優先寫國際發行的名字」，
備援池 40 位裡也只有 Nujabes 一位不是歐美的）。**改完等於沒改**，
因為在那之前應該先問一個更基本的問題：候選是怎麼來的。

### 先量，再改

直接打 ReccoBeats 的推薦端點，三件事同時成立：

| 實驗 | 結果 |
|---|---|
| 同一顆種子連問兩次 | 20 首裡只有 **3 首**重疊 |
| Jay Chou 的種子 vs Metallica 的種子 | **0 首**重疊，但兩邊都是全球長尾（匈牙利語、僧伽羅語、德語兒童有聲書） |
| 換成 Spotify 曲目 id 當種子 | 一樣 |
| 179 首候選的 ISRC 前兩碼 | US 38、QZ 27、DE 18、SE 11…**亞洲合計 7 首＝ 3.9%** |

**`/v1/track/recommendation` 幾乎不看種子。** 它比較像一台加了輕微條件的
隨機取樣器——這也解釋了為什麼 #40 的「代打種子」在體感上沒有帶來預期的改善。
既然候選池是全球長尾的隨機切片，而長尾裡本來就沒什麼亞洲發行，
那麼**換種子、改提示詞、調權重全都動不了那 3.9%**：排序排不出池子裡沒有的東西。

（順帶量到的：`popularity` 是有效參數，`popularity=90` 回來的全是真的紅的歌；
`energy` 只有很弱的影響（給 0.1 回來平均 0.65，給 0.95 回來 0.79），
`market`／`genre` 完全沒作用。另外**推薦端點其實有回 `popularity` 欄位**，
與 #34 記的「拿不到」不符——novelty 目前對每一首都用 0.5，這是另一件該修的事。）

### 改法：自己把亞洲候選補進池子

`app/services/seed_pool.py` 拆成 `asia` / `west` 兩區，**兩區各自**都要攤開
特徵空間（安靜↔吵、陰鬱↔明亮、原音↔電子、慢↔快）。亞洲那一區的 59 位歌手
全部用 `scripts/verify_vibe_seeds.py` 對真實曲庫驗過：名字要照曲庫的寫法，
`sodagreen` 是全小寫、落日飛車在曲庫裡叫「落日飛車 Sunset Rollercoaster」、
`IU` 兩個字會直接撞上搜尋的 3 字下限。98 位全部解得出來，共 377 首。

推薦時從亞洲那一區抽幾首混進候選池。**補進來的歌不享有任何加分**，
帶著自己的特徵跟其他候選比同一個 Discovery Score——這一步只負責
「池子裡有東西可選」，選不選得上仍然由分數決定。

### 四個踩到的坑（每一個都讓「補進去」變成「補了等於沒補」）

**1. 抽候選不能抽「最像」的。** 第一版照相似度由高到低抽，補了 15 首、
前五名一首都沒有。原因是 Discovery Score 的主項是探索帶：相似度落在
**帶心 0.72 附近**得分最高，太像跟太不像一樣被扣分。照「最像」抽出來的歌
全部擠在帶的外側，注定排不上。改成照「離帶心多遠」抽之後才進得了前段。

**2. 名額要保在會端出去的那五首，不是驗證名單的八首。** 名額原本設在
`verify_per_round`(8)，但驗證名單後三首是備位，前五首都能播時永遠輪不到——
名額擺在那裡等於沒擺。改保在 `return_per_round`(5)。

**3. 抽的時候就要先看情境。** 名額只在同一層裡對調，所以補進來的歌若違反
「不要太吵」，它就永遠待在後段那一層，名額再怎麼保也拉不上來。
補 12 首、前五名只有 1 首亞洲，就是這樣來的。改成先用 `passes_hard_filter`
篩過再抽，合格的湊不滿才拿不合格的補。

**4. 備位也要配名額。** 前段有一首在 YouTube 那關被丟掉時，遞補上來的是
備位的第一首；備位清一色不是亞洲的話，掉一首就少一首（實測掉成 1/5）。
備位那三首照同樣的比例配一次名額，守住的才是使用者真正拿到的那五首。

### 為什麼名額有上限

補 6 首、10 首、15 首，前五名的亞洲佔比都落在 50～65%——**「補幾首」控不住比重**。
挑過的、又是照帶心挑的候選，對上隨機長尾，分數幾乎一面倒。使用者要的是
「多一點」，不是「幾乎全部」，而只有下限的機制表達不出一個比例，
所以 `ASIA_MIN_PER_ROUND` / `ASIA_MAX_PER_ROUND` 一起用。上限設 3 時
實測落在 70%（丟棄補位會讓備位的亞洲再遞補上來），設 **2** 才是 45%——
預設取 2。

名額的兩條紀律寫死在 `ranker.region_quota` 裡：**只在同一層裡對調**
（層＝有沒有通過硬過濾，§5.4 的分級優先於地區名額，說了「不要太吵」
就不會因為某首是亞洲的而被拉到前面）；**讓位的一定是同層裡分數最低的那一個**。

### 地區是怎麼判的

曲庫沒有「地區」欄位，但每首都有 **ISRC**，前兩碼是發行登記國。這是候選池裡
唯一現成、不用再打一趟請求的訊號。它量的是發行地不是國籍，所以會**低估**
亞洲比重（落日飛車掛國際廠牌就是 QZ）——低估是可接受的方向：這個數字
用來確認「至少有這麼多」，不拿它把誰踢出候選池。自己補進來的候選帶著
`region` 欄位，那是我們自己的主張，優先於 ISRC。

### 實測（2026-09-04，真的打了外網）

四個情境（雨天開車放空／重訓最後一組／週日早餐／失戀想靜一靜），
端出去的前五名，亞洲佔比 **15% → 45%**（3/20 → 9/20，每輪 1～3 首），
候選池則從 3.9% 拉到約 25%。這是走完整條流程（含丟棄補位）之後的數字。
`done` 事件帶 `asia`，`thinking` 說出補了幾首——比重是被調過的，
這件事要看得見（同 #4、#44 的教訓）。
