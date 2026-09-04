"""候選是不是亞洲發行。純函式，不呼叫任何 API。

曲庫沒有「地區」這個欄位，但每一首都有 **ISRC**，而 ISRC 的前兩碼是
**發行登記國**（`TWA472500001` → TW）。這是候選池裡唯一一個現成、
每首都有、而且不用再打一趟請求的地區訊號。

**它量的是發行地，不是歌手國籍。** 落日飛車掛在國際廠牌底下就會拿到
QZ 或 US 的碼，被這裡判成「不是亞洲」——所以這個判斷會**低估**亞洲比重，
不會高估。低估是可以接受的方向：我們用它來確認「至少有這麼多亞洲」，
而不是用它去把誰踢出候選池。

自己補進來的候選（services/seed_pool）帶著 `region` 欄位，那是我們自己的主張，
比 ISRC 準，所以優先採用；沒有那個欄位才退回讀 ISRC。
"""
from __future__ import annotations

from typing import Dict

ASIA = "asia"

# 東亞、東南亞、南亞的 ISRC 國碼。中東與中亞不列入——使用者說「亞洲音樂」時
# 指的是這一圈的華語／日韓／東南亞流行樂，把範圍畫得比實際主張更大，
# 只會讓「亞洲佔比」這個數字失去意義。
ASIA_ISRC = frozenset({
    "TW", "JP", "KR", "HK", "CN", "MO", "SG", "MY", "TH", "ID", "PH", "VN",
    "KH", "LA", "MM", "BN", "IN", "BD", "LK", "NP", "PK", "MN",
})


def region_of(candidate: Dict) -> str:
    """回傳 "asia" 或空字串。空字串是「沒有證據」，不是「歐美」。"""
    tagged = (candidate.get("region") or "").strip().lower()
    if tagged:
        return tagged
    return ASIA if (candidate.get("isrc") or "")[:2].upper() in ASIA_ISRC else ""


def is_asia(candidate: Dict) -> bool:
    return region_of(candidate) == ASIA


def count_asia(candidates) -> int:
    return sum(1 for candidate in candidates if is_asia(candidate))
