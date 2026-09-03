"""Taste Profiler：把歌單曲目的音訊特徵壓成一支品味向量（§2.2 D1、§6）。純數學。"""
from __future__ import annotations

from statistics import mean
from typing import Dict, List, Optional, Tuple

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


def build_profile(tracks: List[Dict]) -> Tuple[Dict[str, float], float, List[str], int, int, Optional[str]]:
    """回傳 (vector, popularity_mean, seen_artists, matched, unmatched, warning)。

    tracks 每筆需含 artist／title／matched，matched=True 者另含 features 與 popularity。
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
    return vector, popularity_mean, seen_artists, matched, unmatched, warning
