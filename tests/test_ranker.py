"""Discovery Ranker 單元測試。對照開發文件 §5.2 的驗證表。"""
from __future__ import annotations

import math

import pytest

from app.core.ranker import (
    apply_feedback,
    band,
    context_fit,
    passes_hard_filter,
    rank,
    score_candidate,
    similarity,
    target_vector,
)
from app.models import FEATURE_KEYS, Constraints

# 文件 §5.2 的對照表。實際計算值與文件列出的數字在 0.98／0.85／0.30 三格有落差，
# 高斯公式本身沒有歧義，因此以計算值為準、對表格放寬到 0.03（已回報 P 修訂文件）。
SPEC_TABLE = [(0.98, 0.100), (0.92, 0.249), (0.85, 0.579), (0.72, 1.000),
              (0.60, 0.607), (0.54, 0.324), (0.30, 0.005)]


@pytest.mark.parametrize("sim,expected", SPEC_TABLE)
def test_band_matches_spec_table(sim, expected):
    assert band(sim) == pytest.approx(expected, abs=0.03)


def test_band_peaks_at_center():
    assert band(0.72) == 1.0


def test_band_is_symmetric_around_center():
    assert band(0.60) == pytest.approx(band(0.84), abs=1e-9)


def test_band_center_and_width_are_tunable():
    assert band(0.5, center=0.5) == 1.0
    assert band(0.6, center=0.5, width=0.2) > band(0.6, center=0.5, width=0.1)


def test_similarity_identical_vectors_is_one():
    vector = {"energy": 0.4, "valence": 0.5, "danceability": 0.6,
              "acousticness": 0.3, "instrumentalness": 0.1, "tempo": 90}
    assert similarity(vector, vector) == pytest.approx(1.0)


def test_similarity_normalizes_tempo():
    """tempo 差 40 BPM 不該把相似度壓垮——沒除以 200 的話會直接掉到 0。"""
    base = {"energy": 0.5, "tempo": 80}
    other = {"energy": 0.5, "tempo": 120}
    assert 0.85 < similarity(base, other) < 1.0


def test_similarity_skips_missing_dimensions():
    assert similarity({"energy": 0.5}, {"energy": 0.5, "valence": 0.9}) == pytest.approx(1.0)


def test_context_fit_counts_satisfied_constraints():
    constraints = Constraints(energy_max=0.5, tempo_range=[70, 100], acousticness_min=0.3)
    assert context_fit(constraints, {"energy": 0.4, "tempo": 85, "acousticness": 0.5}) == 1.0
    assert context_fit(constraints, {"energy": 0.9, "tempo": 85, "acousticness": 0.5}) == pytest.approx(2 / 3)
    assert context_fit(Constraints(), {"energy": 0.9}) == 1.0


def test_hard_filter_rejects_explicit_violations():
    constraints = Constraints(energy_max=0.5, tempo_range=[70, 100])
    assert passes_hard_filter(constraints, {"energy": 0.4, "tempo": 88})
    assert not passes_hard_filter(constraints, {"energy": 0.85, "tempo": 140})


def test_echo_chamber_penalty_applies_to_seen_artists():
    candidate = {"artist": "Frank Ocean", "features": {"energy": 0.4}, "popularity": 50}
    vector = {"energy": 0.4}
    clean = score_candidate(vector, candidate, Constraints())
    penalised = score_candidate(vector, candidate, Constraints(), seen_artists=["frank ocean"])
    assert penalised.final == pytest.approx(clean.final * 0.55, abs=1e-3)


def test_hard_filter_removes_the_loud_candidate_from_the_spec_example():
    """§5.4 的實例：energy 0.85 / tempo 140 只過 1/4 條限制，卻靠 band 滿分排到第二。"""
    constraints = Constraints(energy_max=0.5, tempo_range=[70, 100],
                              valence_min=0.3, acousticness_min=0.3)
    vector = {"energy": 0.40, "valence": 0.50, "acousticness": 0.50, "tempo": 85}
    loud = {"artist": "Loud Band", "popularity": 20,
            "features": {"energy": 0.85, "valence": 0.6, "acousticness": 0.2, "tempo": 140}}
    quiet = [
        {"artist": f"Quiet {i}", "popularity": 30,
         "features": {"energy": 0.35 + i * 0.01, "valence": 0.5, "acousticness": 0.6, "tempo": 80}}
        for i in range(8)
    ]

    soft, applied_soft = rank(quiet + [loud], vector, constraints, hard_filter=False)
    assert applied_soft is False
    assert any(c["artist"] == "Loud Band" for c in soft)

    strict, applied_strict = rank(quiet + [loud], vector, constraints, hard_filter=True)
    assert applied_strict is True
    # 違反情境的那首不會被丟掉，但只能待在備位區，絕不進 Top 5
    assert all(c["artist"] != "Loud Band" for c in strict[:5])
    assert strict[-1]["artist"] == "Loud Band"


def test_hard_filter_keeps_backups_when_nothing_passes():
    """全部都違反限制時仍要交得出清單——寧可解釋得費力，也不要空手。

    但旗標必須是 False：一首都沒通過的時候，前段一樣是違反情境的曲目，
    不能對使用者宣稱「違反情境的已排到後段」。
    """
    constraints = Constraints(energy_max=0.1)
    candidates = [{"artist": f"A{i}", "popularity": 50, "features": {"energy": 0.8}} for i in range(6)]
    ranked, applied = rank(candidates, {"energy": 0.5}, constraints, hard_filter=True)
    assert applied is False
    assert len(ranked) == 6


def test_flag_is_false_when_every_candidate_passes():
    """全部都通過也等於沒篩到東西，同樣不該宣稱做了分級。"""
    candidates = [{"artist": f"A{i}", "popularity": 50, "features": {"energy": 0.3}} for i in range(6)]
    _, applied = rank(candidates, {"energy": 0.3}, Constraints(energy_max=0.5), hard_filter=True)
    assert applied is False


def test_exploration_widens_or_narrows_the_band():
    """§3.3 的 exploration 原本解析出來就丟掉，現在要真的影響探索帶。"""
    high_c, high_w = ranker_exploration("high")
    med_c, med_w = ranker_exploration("medium")
    low_c, low_w = ranker_exploration("low")

    assert high_c < med_c < low_c      # 想要新鮮感 → 帶心往「比較不像」移
    assert high_w > med_w > low_w      # 想要新鮮感 → 帶寬放寬
    assert (med_c, med_w) == (0.72, 0.12)


def ranker_exploration(value):
    from app.core.ranker import exploration_band
    return exploration_band(value, 0.72, 0.12)


def test_passing_candidates_always_outrank_violating_ones():
    """就算違規者的 Discovery Score 比較高，也不能排到通過者前面。"""
    constraints = Constraints(energy_max=0.5)
    passing = {"artist": "Quiet", "popularity": 95, "features": {"energy": 0.45}}
    violating = {"artist": "Loud", "popularity": 0, "features": {"energy": 0.95}}
    ranked, applied = rank([violating, passing], {"energy": 0.45}, constraints, hard_filter=True)
    assert applied is True
    assert [c["artist"] for c in ranked] == ["Quiet", "Loud"]


def test_blacklisted_artists_never_appear():
    candidates = [{"artist": "Banned", "popularity": 10, "features": {"energy": 0.4}},
                  {"artist": "Fine", "popularity": 10, "features": {"energy": 0.4}}]
    ranked, _ = rank(candidates, {"energy": 0.4}, Constraints(), blacklist=["banned"], hard_filter=False)
    assert [c["artist"] for c in ranked] == ["Fine"]


def test_ranked_output_is_sorted_by_final_score():
    candidates = [{"artist": f"A{i}", "popularity": p, "features": {"energy": 0.4}}
                  for i, p in enumerate([90, 10, 50])]
    ranked, _ = rank(candidates, {"energy": 0.4}, Constraints(), hard_filter=False)
    finals = [c["score"].final for c in ranked]
    assert finals == sorted(finals, reverse=True)


def test_feedback_up_moves_towards_candidate():
    updated = apply_feedback({"energy": 0.4}, {"energy": 0.8}, "up")
    assert updated["energy"] == pytest.approx(0.46)


def test_feedback_down_moves_away_from_candidate():
    updated = apply_feedback({"energy": 0.4}, {"energy": 0.8}, "down")
    assert updated["energy"] == pytest.approx(0.36)


def test_feedback_clamps_each_dimension():
    updated = apply_feedback({"energy": 0.02, "tempo": 45},
                             {"energy": 0.9, "tempo": 200}, "down")
    assert updated["energy"] == 0.0
    assert updated["tempo"] >= 40.0


def test_feedback_ignores_dimensions_the_candidate_lacks():
    updated = apply_feedback({"energy": 0.4, "valence": 0.5}, {"energy": 0.8}, "up")
    assert updated["valence"] == 0.5


# --- 沒有歌單時的目標向量 -----------------------------------------------------

def test_target_vector_clamps_the_llm_centre_into_the_stated_bounds():
    """使用者說「不要太吵」，模型卻給了 0.8——上下限一律優先，否則前段會排滿等著被砍的歌。"""
    vector = target_vector({"energy": 0.8, "valence": 0.7},
                           Constraints(energy_max=0.45, tempo_range=[70, 110]))
    assert vector["energy"] == 0.45
    assert vector["valence"] == 0.7        # 沒被限制到的維度照模型給的走
    assert 70 <= vector["tempo"] <= 110


def test_target_vector_fills_every_scoring_dimension():
    """相似度會跳過缺值的維度。目標向量缺一格，那一格就等於沒有意見。"""
    vector = target_vector(None, Constraints())
    assert set(vector) == set(FEATURE_KEYS)
    assert all(0.0 <= vector[key] <= 1.0 for key in FEATURE_KEYS if key != "tempo")
    assert 40.0 <= vector["tempo"] <= 220.0
