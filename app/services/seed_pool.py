"""備援種子池：情境入口的起點歌手，以及候選池裡那一份「一定是亞洲」的名額。

**這份清單不是策展，是覆蓋率。** 它要回答的問題不是「深夜開車該聽誰」——
那是模型的工作，而且模型答得比我們好——而是「曲庫裡有沒有一首歌，
在特徵空間的這個角落，可以拿來當推薦的起點」。因此挑選標準只有兩條：

  1. 曲庫裡真的查得到（查不到就毫無用處，名字全部用 scripts/verify_vibe_seeds.py 驗過）；
  2. 每個區域各自要把特徵空間攤開——安靜↔吵、陰鬱↔明亮、原音↔電子、慢↔快
     每個方向都有人守著。

實際挑哪幾首**不看曲風標籤，看特徵距離**：把目標向量丟進來，挑最貼近的那幾首。
所以這裡不需要「氛圍 → 歌手」的對照表，也就不必替「深夜開車配這五位」
這種主張辯護——那個判斷交給數字。

## 為什麼分 asia／west 兩區

ReccoBeats 的推薦端點實測下來幾乎不看種子（NOTES #46），候選池是全球長尾的
隨機切片，亞洲發行只佔 3.9%。所以「多推一點亞洲」沒辦法靠換種子達成，
只能自己把亞洲候選補進池子裡——`asia` 這一區就是那份補給的來源。
兩區各自都要攤開特徵空間，否則補進來的亞洲候選只會擠在某一個角落，
情境一換就全部落選。

`data/vibe_seeds.json` 是這份清單解析過後的結果（scripts/verify_vibe_seeds.py 產生）。
有這個檔就是零 API 呼叫、而且每一首都保證查得到；沒有的話 pipeline 會退回即時解析。
"""
from __future__ import annotations

import json
import logging
import os
import random
from typing import Callable, Dict, List, Optional

log = logging.getLogger("museek.seed_pool")

SEED_FILE = os.path.join("data", "vibe_seeds.json")

ASIA = "asia"
WEST = "west"

# 每個區塊守住特徵空間的一個角落。名字是手挑的，位置由 verify 腳本量出來的特徵決定。
# 寫法一律照曲庫（Spotify 血統）自己的寫法，例如 sodagreen 全小寫、
# 落日飛車在曲庫裡叫「落日飛車 Sunset Rollercoaster」——寫錯就是查不到。
POOL: Dict[str, List[str]] = {
    ASIA: [
        # 極安靜、原音為主、慢
        "Ichiko Aoba", "Ryuichi Sakamoto", "Crowd Lu", "Prateek Kuhad", "Cheer Chen",
        # 安靜但偏電子／空間感
        "LÜCY", "deca joins", "Susumu Yokota", "Hikaru Utada", "落日飛車 Sunset Rollercoaster",
        # 中性、律動明確
        "Phum Viphurit", "9m88", "HYUKOH", "SIRUP", "Zion.T", "toe",
        # 明亮、流行
        "Fujii Kaze", "NewJeans", "Wonder Girls", "Leo王", "Vaundy", "Jolin Tsai", "告五人",
        # 高能量、吉他
        "ONE OK ROCK", "tricot", "Fire EX.", "Elephant Gym", "King Gnu", "SE SO NEON",
        "sakanaction",
        # 高能量、電子／舞曲
        "YOASOBI", "Ado", "BLACKPINK", "Mondo Grosso", "Ritviz", "Yaeji",
        # 低情緒、密集
        "No Party For Cao Dong", "Silica Gel", "Younha", "Kenshi Yonezu", "Tizzy Bac", "Waa Wei",
        # 器樂／取樣／嘻哈
        "Nujabes", "Cornelius", "STUTS", "Epik High", "Rich Brian",
        # 華語主流（曲庫收得最齊的那一群，情境偏大眾時靠這幾位）
        "Jay Chou", "Eason Chan", "JJ Lin", "Mayday", "sodagreen", "Hebe Tien", "EggPlantEgg",
        # 東南亞
        "Hindia", "Ben&Ben", "IV Of Spades", "Reality Club", "Safeplanet",
    ],
    WEST: [
        # 極安靜、原音為主、慢
        "Bon Iver", "Sufjan Stevens", "Nick Drake", "José González", "Agnes Obel",
        # 安靜但偏電子／空間感
        "Cigarettes After Sex", "Beach House", "Boards of Canada", "Bonobo", "Tycho",
        # 中性、律動明確
        "Khruangbin", "Men I Trust", "Mac DeMarco", "Tom Misch", "Rex Orange County",
        # 明亮、流行
        "Dua Lipa", "Harry Styles", "Lizzo", "Jungle", "Vampire Weekend",
        # 高能量、吉他
        "Foo Fighters", "Arctic Monkeys", "Queens of the Stone Age", "Muse", "Paramore",
        # 高能量、電子
        "The Chemical Brothers", "Justice", "Fred again..", "Skrillex", "Daft Punk",
        # 低情緒、密集
        "Radiohead", "The National", "Joy Division", "Massive Attack", "Portishead",
        # 器樂／取樣
        "GoGo Penguin", "Kamasi Washington", "Explosions in the Sky", "Ólafur Arnalds",
    ],
}


def _dedup(names: List[str]) -> List[str]:
    out, seen = [], set()
    for name in names:
        key = (name or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(name.strip())
    return out


def artists(region: Optional[str] = None) -> List[str]:
    """保序去重後的歌手名單。不指定 region 時兩區交錯排。

    交錯不是排版偏好：沒有預解析檔時 pipeline 只會即時解析前幾位，
    照區塊排的話那幾位會全部來自同一區，備援就又變回一面倒。
    """
    if region:
        return _dedup(POOL.get(region, []))
    asia, west = _dedup(POOL[ASIA]), _dedup(POOL[WEST])
    mixed: List[str] = []
    for index in range(max(len(asia), len(west))):
        if index < len(asia):
            mixed.append(asia[index])
        if index < len(west):
            mixed.append(west[index])
    return mixed


def region_of(name: str) -> str:
    """歌手屬於哪一區。不在清單裡回空字串——不知道就說不知道，不要猜成 west。"""
    key = (name or "").strip().lower()
    for region, names in POOL.items():
        if any(key == n.strip().lower() for n in names):
            return region
    return ""


def load(path: Optional[str] = None) -> List[Dict]:
    """讀取解析過的種子池。檔案不在、壞掉、或格式不對都回空清單。

    回不出東西不是錯誤——pipeline 還有即時解析那條路。
    這裡安靜地失敗，但呼叫端要把「用了備援」這件事講出來。
    """
    target = path or SEED_FILE
    try:
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return []
    except Exception as error:  # noqa: BLE001
        log.warning("備援種子池讀取失敗（%s）：%s", target, error)
        return []

    rows = data.get("seeds") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        log.warning("備援種子池格式不符：%s", target)
        return []

    out = []
    for row in rows:
        if not (isinstance(row, dict) and row.get("recco_id") and (row.get("features") or {})):
            continue
        row = dict(row)
        # 舊版檔案沒有 region。用歌手名回推，回推不到就留空——
        # 空的一律當作「不是亞洲」，寧可少湊一首，也不要把不確定的東西講成確定的。
        if not row.get("region"):
            row["region"] = region_of(row.get("artist", ""))
        out.append(row)
    if out and not any(row["region"] for row in out):
        log.warning("種子池沒有任何 region 標記，亞洲名額會湊不滿"
                    "（重跑 scripts/verify_vibe_seeds.py 就會補上）")
    return out


def _ranked(pool: List[Dict], target: Dict[str, float], similarity: Callable) -> List[Dict]:
    return sorted(pool, key=lambda row: similarity(target, row.get("features") or {}), reverse=True)


def _sample(ranked: List[Dict], want: int, shortlist: int) -> List[Dict]:
    """在最貼近的前 shortlist 名之內隨機取 want 首。"""
    if want <= 0 or not ranked:
        return []
    window = ranked[:max(want, shortlist)]
    return random.sample(window, min(want, len(window)))


def pick(pool: List[Dict], target: Dict[str, float], similarity, *,
         limit: int = 5, shortlist: int = 12, asia_min: int = 0) -> List[Dict]:
    """挑最貼近目標向量的幾首，但在前 shortlist 名之內隨機取。

    純取 Top N 的話，所有人的「深夜開車」會是同五首歌——備援救回了推薦，
    卻讓每個人拿到一模一樣的結果。先用相似度把範圍收到真的貼近的那一段，
    再在裡面擲骰子：既不會挑到不相干的歌，也不會全世界都一樣。

    asia_min 是**下限不是上限**：先把亞洲的名額填滿，剩下的位子照相似度全區搶。
    亞洲那一區湊不滿就湊多少算多少，不會為了配額去挑不貼近的歌。

    similarity 由呼叫端傳進來（ranker.similarity），這個模組不依賴排序邏輯。
    """
    if not pool or limit <= 0:
        return []
    reserved = _sample(_ranked([r for r in pool if r.get("region") == ASIA], target, similarity),
                       min(asia_min, limit), shortlist)
    taken = {row["recco_id"] for row in reserved}
    rest = _sample(_ranked([r for r in pool if r["recco_id"] not in taken], target, similarity),
                   limit - len(reserved), shortlist)
    return reserved + rest


def draw(pool: List[Dict], target: Dict[str, float], similarity, *,
         want: int, region: str = ASIA, center: Optional[float] = None,
         shortlist_factor: int = 3) -> List[Dict]:
    """從某一區抽 want 首當候選（不是候選的種子，是候選本身）。

    **candidate 要挑的不是「最像」，是「像到剛好」。** Discovery Score 的主項是
    探索帶（ranker.band）：相似度落在 center（預設 0.72）附近的得分最高，
    太像跟太不像一樣被扣分。照相似度由高到低抽出來的歌會全部擠在帶的外側，
    補進候選池之後一首也排不上——實測過，補了 15 首、前五名一首都沒有。

    所以有 center 時就照「離帶心多遠」排。沒給 center 才退回「最像優先」，
    那是給不做排序的呼叫端（例如種子挑選）用的。
    """
    rows = [row for row in pool if not region or row.get("region") == region]
    if center is None:
        ranked = _ranked(rows, target, similarity)
    else:
        ranked = sorted(rows, key=lambda row: abs(
            similarity(target, row.get("features") or {}) - center))
    return _sample(ranked, want, want * max(1, shortlist_factor))
