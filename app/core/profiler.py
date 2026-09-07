"""Taste Profiler：把歌單曲目的音訊特徵壓成一支品味向量（§2.2 D1、§6）。純數學。"""
from __future__ import annotations

from statistics import mean
from typing import Dict, List, Optional, Tuple

from app.core import genres
from app.models import FEATURE_KEYS

LOW_MATCH_THRESHOLD = 0.40  # §9：比對率 < 40% 要降級並提示


def build_vector(feature_rows: List[Dict[str, float]]) -> Dict[str, float]:
    """逐維度取平均。某維度全部缺值就不放進向量，之後相似度計算會自動跳過。"""
    vector: Dict[str, float] = {}
    for key in FEATURE_KEYS:
        values = [float(row[key]) for row in feature_rows if row.get(key) is not None]
        if values:
            vector[key] = round(mean(values), 4)
    return vector


def build_profile(tracks: List[Dict]) -> Tuple[Dict[str, float], float, List[str], int, int,
                                              Optional[str], Dict[str, float]]:
    """回傳 (vector, popularity_mean, seen_artists, matched, unmatched, warning, genre_weights)。

    tracks 每筆需含 artist／title／matched，matched=True 者另含 features 與 popularity；
    有查到曲風的另含 genres。

    **曲風分布是向量之外的第二支輪廓，不是向量的一部分。** 六個維度的平均值
    說不出「這個人聽的是 citypop 不是 soft rock」——兩者的 energy／valence／tempo
    可以完全一樣。所以曲風單獨統計成一份分布，排序時當獨立的一項用
    （見 core/genres 與 ranker.score_candidate）。

    統計的母體是 **matched 的曲目**，跟向量同一批：沒查到特徵的那些歌
    連帶也多半沒有曲風標籤，混進來只會讓分母虛胖。
    """
    matched_rows = [t for t in tracks if t.get("matched")]
    matched = len(matched_rows)
    unmatched = len(tracks) - matched

    vector = build_vector([t.get("features") or {} for t in matched_rows])
    popularities = [float(t["popularity"]) for t in matched_rows if t.get("popularity") is not None]
    popularity_mean = round(mean(popularities), 2) if popularities else 50.0

    seen_artists = list(dict.fromkeys(
        (t.get("artist") or "").strip().lower() for t in tracks if (t.get("artist") or "").strip()
    ))

    warning = None
    rate = matched / len(tracks) if tracks else 0.0
    if tracks and rate < LOW_MATCH_THRESHOLD:
        warning = "這份歌單有較多曲目未收錄，推薦可能較發散。"
    return (vector, popularity_mean, seen_artists, matched, unmatched, warning,
            genres.distribution(matched_rows))
