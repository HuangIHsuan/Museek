"""Discovery Ranker（開發文件 §5）。純函式、不呼叫任何 API、不使用任何 YouTube 資料。"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from app.models import FEATURE_KEYS, FEATURE_WEIGHTS, Constraints, Score

TEMPO_SCALE = 200.0

# §3.3 的 exploration 欄位原本解析出來就被丟掉。這裡把它接到探索帶的兩個參數上：
# 想要新鮮感就把帶心往「比較不像」的方向移、並放寬帶寬；想要熟悉感則相反。
EXPLORATION_TUNING = {
    "high":   (-0.08, 1.4),
    "medium": (0.0, 1.0),
    "low":    (0.08, 0.8),
}


def exploration_band(exploration: Optional[str], center: float, width: float):
    """依 exploration 調整探索帶，回傳 (center, width)。"""
    shift, scale = EXPLORATION_TUNING.get(exploration or "medium", EXPLORATION_TUNING["medium"])
    return min(1.0, max(0.0, center + shift)), max(0.02, width * scale)  # §5.1：tempo 必須先除以 200，否則 BPM 量級會壓過其他 0–1 維度


def _normalized(features: Dict[str, float], key: str) -> Optional[float]:
    if key not in features or features[key] is None:
        return None
    value = float(features[key])
    return value / TEMPO_SCALE if key == "tempo" else value


def similarity(user_vector: Dict[str, float], candidate: Dict[str, float]) -> float:
    """§5.1 加權歐氏距離轉相似度。缺值的維度直接跳過，不用 0 頂替。"""
    numerator = 0.0
    denominator = 0.0
    for key in FEATURE_KEYS:
        u = _normalized(user_vector, key)
        c = _normalized(candidate, key)
        if u is None or c is None:
            continue
        weight = FEATURE_WEIGHTS[key]
        numerator += weight * (u - c) ** 2
        denominator += weight
    if denominator == 0:
        return 0.0
    return max(0.0, 1.0 - math.sqrt(numerator / denominator))


def band(sim: float, center: float = 0.72, width: float = 0.12) -> float:
    """§5.2 探索帶。分母的 2 是高斯函數定義的一部分，寫死；center／width 供 Day 5 調校。"""
    return math.exp(-((sim - center) ** 2) / (2 * width ** 2))


def _constraint_checks(constraints: Constraints, features: Dict[str, float]) -> List[bool]:
    """把 Intent 的限制逐條攤成 True／False。特徵缺值視為未滿足。"""
    checks: List[bool] = []

    def bound(field: str, value: Optional[float], is_max: bool) -> None:
        if value is None:
            return
        actual = features.get(field)
        if actual is None:
            checks.append(False)
            return
        checks.append(float(actual) <= value if is_max else float(actual) >= value)

    bound("energy", constraints.energy_max, True)
    bound("energy", constraints.energy_min, False)
    bound("valence", constraints.valence_max, True)
    bound("valence", constraints.valence_min, False)
    bound("acousticness", constraints.acousticness_max, True)
    bound("acousticness", constraints.acousticness_min, False)

    if constraints.tempo_range:
        low, high = constraints.tempo_range[0], constraints.tempo_range[1]
        tempo = features.get("tempo")
        checks.append(tempo is not None and low <= float(tempo) <= high)
    return checks


def context_fit(constraints: Constraints, features: Dict[str, float]) -> float:
    """§5.3 已滿足的限制條件數 ÷ 總限制條件數。沒有任何限制時視為完全符合。"""
    checks = _constraint_checks(constraints, features)
    if not checks:
        return 1.0
    return sum(1 for ok in checks if ok) / len(checks)


def passes_hard_filter(constraints: Constraints, features: Dict[str, float]) -> bool:
    """§5.4 建議修正 1：排序前先剔除違反明確上下限的候選。"""
    return all(_constraint_checks(constraints, features))


def score_candidate(
    user_vector: Dict[str, float],
    candidate: Dict,
    constraints: Constraints,
    seen_artists: Optional[List[str]] = None,
    *,
    center: float = 0.72,
    width: float = 0.12,
    w_band: float = 0.45,
    w_context: float = 0.30,
    w_novelty: float = 0.25,
    penalty: float = 0.55,
) -> Score:
    features = candidate.get("features") or {}
    sim = similarity(user_vector, features)
    band_value = band(sim, center, width)
    fit = context_fit(constraints, features)
    popularity = candidate.get("popularity")
    novelty = 1.0 - (float(popularity) / 100.0) if popularity is not None else 0.5
    novelty = min(1.0, max(0.0, novelty))

    final = w_band * band_value + w_context * fit + w_novelty * novelty
    if seen_artists and _artist_seen(candidate.get("artist", ""), seen_artists):
        final *= penalty  # 同溫層懲罰

    return Score(
        similarity=round(sim, 4),
        band=round(band_value, 4),
        context_fit=round(fit, 4),
        novelty=round(novelty, 4),
        final=round(final, 4),
    )


def _artist_seen(artist: str, seen: List[str]) -> bool:
    key = (artist or "").strip().lower()
    return bool(key) and key in {(a or "").strip().lower() for a in seen}


def rank(
    candidates: List[Dict],
    user_vector: Dict[str, float],
    constraints: Constraints,
    seen_artists: Optional[List[str]] = None,
    blacklist: Optional[List[str]] = None,
    *,
    hard_filter: bool = True,
    min_pool: int = 5,
    **score_kwargs,
) -> Tuple[List[Dict], bool]:
    """回傳 (排序後的候選, 是否有候選因違反情境而被降到後段)。

    §5.4 建議修正 1 的實作，但改成「分級」而不是「全丟」：通過硬過濾的排在前面，
    違反明確上下限的排在後面當備位。候選池太小的時候仍然湊得滿五首，
    而使用者說了「不要太吵」時，會炸出來的那首絕不會排在前段——
    這是硬過濾與「不要交出空清單」兩個需求唯一都能滿足的做法。
    """
    blocked = {(a or "").strip().lower() for a in (blacklist or [])}
    pool = [c for c in candidates if (c.get("artist") or "").strip().lower() not in blocked]

    def scored(items: List[Dict]) -> List[Dict]:
        out = []
        for candidate in items:
            item = dict(candidate)
            item["score"] = score_candidate(
                user_vector, candidate, constraints, seen_artists, **score_kwargs
            )
            out.append(item)
        out.sort(key=lambda c: c["score"].final, reverse=True)
        return out

    if not hard_filter:
        return scored(pool), False

    passing, failing = [], []
    for candidate in pool:
        target = passing if passes_hard_filter(constraints, candidate.get("features") or {}) else failing
        target.append(candidate)

    # 旗標只在「真的有分級效果」時為 True：必須同時有通過者與違反者。
    # 全部通過等於沒篩到東西；全部違反則前段一樣是違反者，
    # 這兩種情況都不能對使用者宣稱「已處理過情境」。
    graded = bool(passing) and bool(failing)
    if not failing:
        return scored(passing), False
    return scored(passing) + scored(failing), graded


# --- §5.5 回饋更新 ---------------------------------------------------------

UP_RATE = 0.15
DOWN_RATE = 0.10


def apply_feedback(
    user_vector: Dict[str, float], candidate_features: Dict[str, float], vote: str
) -> Dict[str, float]:
    """👍 往候選靠攏、👎 往反方向推。各維度 clamp 至 [0,1]，tempo clamp 至 [40,220]。"""
    rate = UP_RATE if vote == "up" else -DOWN_RATE
    updated = dict(user_vector)
    for key in FEATURE_KEYS:
        u = user_vector.get(key)
        c = candidate_features.get(key)
        if u is None or c is None:
            continue
        value = float(u) + rate * (float(c) - float(u))
        low, high = (40.0, 220.0) if key == "tempo" else (0.0, 1.0)
        updated[key] = round(min(high, max(low, value)), 4)
    return updated
