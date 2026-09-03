# Museek 預告片分鏡

**約 70 秒｜Veo 3 生成 + 實機錄影｜16:9 主版 + 9:16 直式**
分鏡對應《Museek 系統開發文件》§12 Demo 腳本

---

## 敘事主張

整支片只講一件事：

> **推薦系統很懂你——懂到只敢給你一樣的東西。**
> 太像的，你早就聽膩了。太不像的，你根本不會按下播放。
> 真正會留下來的，在中間那一格。
>
> Museek 讀的是聲音本身：能量、情緒、原音比例。
> 推薦理由裡的每個數字都來自音訊分析，不是猜的。

這正是 `band()` 那條高斯曲線在做的事（開發文件 §5.2），講出來比講「AI 推薦」有力得多。

---

## 分鏡表

| # | 時間 | 長度 | 來源 | 內容 |
|---|---|---|---|---|
| S1 | 0:00 | 8s | **Veo** | 雨夜車內，手指一直滑掉歌 |
| S2 | 0:08 | 6s | 實錄 | 貼歌單 →「我讀到的你」四條數值長出來 |
| S3 | 0:14 | 8s | **Veo** | 被念完，走進電梯戴耳機 |
| S4 | 0:22 | 8s | 實錄 | 打字「被主管罵完，想要安靜一點的」→ 五個步驟依序點亮 |
| S5 | 0:30 | 7s | 實錄 | 推薦理由特寫，圈出兩個數值 |
| S6 | 0:37 | 8s | **Veo** | 走出大樓，那首歌接住他 |
| S7 | 0:45 | 8s | 實錄 | 按略過 → taste 條位移 + 重排 |
| S8 | 0:53 | 6s | 實錄 | 系統健康角落的 dropped |
| S9 | 0:59 | 10s | 實錄 | 掃 QR → 加入主畫面 → 沒有網址列 |

**分界原則：情境交給 AI，產品畫面一律實錄。** 三個高光（思考串流、taste 條位移、dropped 攔截）都在實錄那邊——Veo 生的假介面跟真實 UI 對不起來，評審發現落差反而扣分。

---

## Veo 3 Prompts

### S1 · 雨夜車內

```text
Close-up, 50mm lens, shallow depth of field. Interior of a parked car at night,
heavy rain streaking down the windshield. A young woman's hand holds a phone low
in her lap; the screen glow is the only warm light on her face. Her thumb flicks
upward through a music list again and again, skipping track after track — five
quick, tired flicks. Her jaw tightens slightly. Camera static, then a slow rack
focus from the phone screen to her eyes. Cool blue-teal night grade with magenta
neon bleeding through the wet glass from off-screen. Audio: heavy rain drumming
on the car roof, a muffled song fragment cutting off abruptly with each skip, no
music score, no dialogue. No subtitles, no on-screen text, no captions.
```

> 手機螢幕保持過曝或失焦，不要出現任何可辨識的 App 介面。

### S3 · 走進電梯

```text
Medium tracking shot from behind, 35mm lens, handheld with a subtle float. A man
in his late twenties walks away from a glass-walled meeting room down a long
fluorescent-lit office corridor, badge lanyard swinging, shoulders low, eyes
fixed straight ahead. Without breaking stride he pulls white earbuds from his
jacket pocket and steps into a lift. The doors begin to close on him and the
camera stops. Cold green-grey office grade, harsh overhead fluorescents, late
evening darkness in the windows behind him. Audio: distant keyboard clatter, a
printer cycling, low air-conditioning hum, the soft chime of the lift doors. No
music score, no dialogue. No subtitles, no on-screen text, no captions.
```

> S3 與 S6 是同一個人。Veo 沒有角色記憶，外型描述逐字照抄，或乾脆讓 S3 全程只拍背影。

### S6 · 走出大樓

```text
Low-angle medium shot, 28mm lens, very slow push-in. A man in his late twenties
in a dark jacket with white earbuds steps out of an office building's revolving
door onto a rainy city street at night. He raises his hood, takes three steps,
then slows and stops. The tension leaves his shoulders as he listens; his
expression softens, and he tilts his head back slightly. Neon signage and passing
headlights reflect across the wet pavement around him. Deep blue night grade with
warm magenta and lime-green neon accents. Rain falls visibly through the
streetlight beams. Audio: city rain, tyres hissing on wet asphalt, traffic
muffled as if heard through earbuds. No dialogue, no music score. No subtitles,
no on-screen text, no captions.
```

> 全片唯一放配樂進來的地方，讓音樂在這一顆長出來。

### 備用開場 · 深夜捷運

想換掉 S1 的話用這顆。

```text
Static medium shot, 40mm lens. A tired commuter sits alone in a near-empty
late-night metro carriage, forehead resting against the dark window, earbuds in,
phone held loosely. The carriage lights flicker as the train passes through a
tunnel; her reflection appears and disappears in the glass. She thumbs the screen
once, then lets her hand drop without choosing anything. Cool fluorescent
interior against black tunnel windows. Audio: the rhythmic rumble of the train on
the tracks, a distant automated announcement, no music score, no dialogue. No
subtitles, no on-screen text, no captions.
```

---

## 實機錄影規格

### S2 · 貼一份歌單，數值長出來

1. 入口頁貼上公開歌單網址，按「解析歌單」
2. 錄下「我讀到的你」四條 meter 的成長動畫（ENERGY／VALENCE／DANCEABILITY／ACOUSTICNESS）
3. 再補一顆 200% 放大的 meter 特寫，剪接時疊在寬鏡頭之後

### S4 · 打一句話，五個步驟依序點亮

1. 在品味頁的情境欄**逐字打出**「被主管罵完，想要安靜一點的」（錄真實打字節奏，不要貼上）
2. 完整錄下「正在為你探索」五個步驟由上而下點亮
3. **不要剪掉等待時間**——這是真的在跑，那個延遲就是證據

### S5 · 理由裡的每個數字

1. 特寫推薦理由句。實際產出範例：
   > 這首 Men I Trust 的 Numb 能量值 0.216 低於你的 0.549，適合雨天放空；但快樂度 0.604 略高於你的 0.495，帶來些許暖意。
2. 後製把 `0.216` 與 `0.549` 用洋紅圈記，兩者之間拉一條線

### S7 · 按下略過，taste 條就位移

1. 對第一首按「略過」
2. 錄下右上角 taste 條的數字變化，位移的維度會轉成洋紅
3. 同一顆鏡頭要帶到右側清單重新排序
4. **只示範略過，不要示範喜歡**——band 在 sim 過高時會扣分，按喜歡可能讓同類型的歌名次下降，那個解釋成本預告片放不下

### S8 · 被丟掉的那幾首

1. 點開右下角「系統健康」，特寫 `DROPPED` 那一行
2. `dropped` **不保證大於 0**，候選全查得到就是 0。先跑幾輪，挑一輪有數字的來錄

### S9 · 掃碼，加到主畫面，收尾

1. 真的用手機拍：掃 QR Code → Safari 分享選單 →「加入主畫面」
2. 從主畫面點開，鏡頭帶到**沒有網址列**那一瞬間
3. 畫面收黑，打上 `Museek — Seek Your Next Sound.`

> 這顆絕對不要用 AI 生成。Veo 畫不出正確的 iOS 分享選單與你們的 App 圖示，而這顆的全部說服力就在「這是真的裝好了」。

---

## 字卡文案

建議走字卡不配旁白：七天內找不到穩定配音，AI 中文語調在安靜的片子裡容易出戲。字體直接沿用產品的 Arial Black + Noto Sans TC 900，看起來會像同一件作品。

| 時間 | 文案 | 疊在哪 |
|---|---|---|
| 0:04 | 你的播放清單，越聽越窄。 | S1 後半 |
| 0:10 | 演算法很懂你——懂到只敢給你一樣的東西。 | S2 |
| 0:19 | 你想聽什麼，取決於你剛剛經歷了什麼。 | S3 尾 |
| 0:27 | **這些不是動畫。** | S4 思考串流 |
| 0:33 | 每個數字都來自音訊分析，不是語言模型猜的。 | S5 特寫 |
| 0:41 | **熟悉，但不是重複。** | S6 情緒點 |
| 0:49 | 回饋不是裝飾，下一輪就會不一樣。 | S7 重排 |
| 0:55 | 送到你面前之前，我們先丟掉了幾首。 | S8 |
| 1:04 | **貼一份歌單。說一句話。** | S9 收尾前 |
| 1:08 | **Museek — Seek Your Next Sound.** | 黑底結尾卡 |

---

## 拍攝與後製規格

### 螢幕錄影

- 60 fps，解析度至少 2560×1440，剪接降到 1080p 才有裁切空間
- 瀏覽器全螢幕，隱藏書籤列與分頁列
- 關閉所有系統通知（macOS 專注模式）
- 滑鼠游標加高亮或事後遮掉，不要讓游標亂晃
- 直式版本用 Chrome 裝置模擬 iPhone 15 Pro 重錄一次，不要橫式硬裁

### 音樂與版權

- **片中不要放任何推薦到的實際歌曲**——那是商業錄音，銀行的公開場合尤其不能冒險
- 配樂用授權曲庫或 YouTube Audio Library 的 instrumental
- S1、S3 用 Veo 生成的環境音就好，配樂從 S6 才進來
- 片尾留 2 秒純黑，方便接到簡報

---

## Veo 3 常見失敗

| 症狀 | 原因 | 修法 |
|---|---|---|
| 畫面自己長出英文字幕 | prompt 有音訊或對白描述時，模型傾向補字幕 | 每段結尾保留 `No subtitles, no on-screen text, no captions.` |
| 跨鏡頭同一個人長得不一樣 | Veo 每次生成獨立，沒有角色記憶 | 外型描述逐字照抄；或只出現背影、手部、側臉 |
| 生成的中文字全是亂碼 | 模型對中文字形處理不穩 | 絕不讓 AI 生成任何中文畫面文字，字卡一律後製疊上 |
| 生成的手機介面很像但不是你們的 | 模型會自行腦補 UI | 螢幕寫成過曝、失焦或背對鏡頭；產品畫面一律實錄 |
| 一段塞太多動作，每個都做半套 | 8 秒放不下三個以上的節拍 | 一段一個動作。S1 只有「滑掉」、S6 只有「停下來」 |

---

## ⚠️ 開拍前必須先處理

**現在錄會錄到假畫面。**

- `.env` 目前是 stub 模式，**YouTube 金鑰與地端 LLM 設定都不在了**，需要先寫回去
- stub 模式下 videoId 是假的，**播放器會顯示「無法播放這部影片」**——S5、S7 會直接穿幫
- stub 模式下推薦理由走模板，不是模型生成的句子，說服力差很多
- ReccoBeats 仍是 stub，候選來自內建的 40 首曲庫，不是真實推薦結果
- 快取只有 10 首影片，錄影時每跑一輪新提示詞就花 500 點配額，**當日上限 10,000 點且不可加購**——先把要錄的提示詞跑順讓快取熱起來，再正式開錄

---

*Museek ｜ 智能應用科 Agent 黑客松 第二組*
