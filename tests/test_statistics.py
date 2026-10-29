"""Unit tests for miconte.statistics — the deterministic statistical engine.

All tests use synthetic data only; no credentials, network, database,
FastAPI or LLM dependency is required to run this file.

Coverage:
  - MetricEnvelope structure validation
  - CTR: nominal, zero impressions, None impressions, negative inputs
  - APV: nominal, zero duration, None inputs
  - ER / ER_public: with/without shares, None values, zero views
  - NSC_1k: positive, negative, zero views
  - Velocity: sufficient baseline, insufficient sample, zero median
  - describe(): normal population, empty, N < 10
  - test_normality(): Shapiro-Wilk path (N<50), KS path (N>=50), non-normal
  - compute_ci_95(): N<10 returns None, normal path, non-normal bootstrap path
  - compare_two_groups(): parametric, non-parametric, insufficient N
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from miconte.statistics import (
    ComparisonResult,
    MetricEnvelope,
    compare_two_groups,
    compute_apv,
    compute_ci_95,
    compute_ctr,
    compute_engagement_rate,
    compute_nsc_1k,
    compute_public_engagement_rate,
    compute_velocity,
    describe,
)
from miconte.statistics import (
    test_normality as check_normality,
)

_D1 = date(2026, 1, 1)
_D2 = date(2026, 1, 31)


# ---------------------------------------------------------------------------
# MetricEnvelope structural tests
# ---------------------------------------------------------------------------


def test_metric_envelope_defaults() -> None:
    env = MetricEnvelope(
        metric_key="test",
        value=1.0,
        unit="ratio",
        source="derived_deterministic",
        visibility="private_oauth",
        period_start=_D1,
        period_end=_D2,
        sample_size=10,
    )
    assert env.ci_95 is None
    assert env.incomplete_observation_window is False
    assert env.is_right_censored is False
    assert env.data_suppressed is False
    assert env.limitations == []


# ---------------------------------------------------------------------------
# CTR
# ---------------------------------------------------------------------------


def test_ctr_nominal() -> None:
    result = compute_ctr(200, 1000, period_start=_D1, period_end=_D2)
    assert isinstance(result, MetricEnvelope)
    assert result.metric_key == "click_through_rate"
    assert result.value == pytest.approx(0.2)
    assert result.unit == "ratio"
    assert result.data_suppressed is False


def test_ctr_zero_impressions_returns_zero_not_error() -> None:
    result = compute_ctr(0, 0, period_start=_D1, period_end=_D2)
    assert result.value == 0.0
    assert result.data_suppressed is False


def test_ctr_none_impressions_returns_none_with_suppressed_flag() -> None:
    result = compute_ctr(100, None, period_start=_D1, period_end=_D2)
    assert result.value is None
    assert result.data_suppressed is True
    assert len(result.limitations) > 0


def test_ctr_negative_values_returns_none() -> None:
    result = compute_ctr(-5, 100, period_start=_D1, period_end=_D2)
    assert result.value is None


def test_ctr_none_clicks_treated_as_zero() -> None:
    result = compute_ctr(None, 1000, period_start=_D1, period_end=_D2)
    assert result.value == 0.0
    assert any("Clics" in lim for lim in result.limitations)


def test_ctr_perfect_ctr() -> None:
    result = compute_ctr(1000, 1000, period_start=_D1, period_end=_D2)
    assert result.value == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# APV
# ---------------------------------------------------------------------------


def test_apv_nominal() -> None:
    result = compute_apv(240, 480, period_start=_D1, period_end=_D2)
    assert result.value == pytest.approx(0.5)
    assert result.metric_key == "average_percentage_viewed"


def test_apv_zero_duration_returns_zero() -> None:
    result = compute_apv(100, 0, period_start=_D1, period_end=_D2)
    assert result.value == 0.0
    assert any("Duración <= 0" in lim for lim in result.limitations)


def test_apv_negative_duration_returns_zero() -> None:
    result = compute_apv(100, -30, period_start=_D1, period_end=_D2)
    assert result.value == 0.0


def test_apv_none_inputs_returns_none_suppressed() -> None:
    result = compute_apv(None, 300, period_start=_D1, period_end=_D2)
    assert result.value is None
    assert result.data_suppressed is True


def test_apv_above_one_allowed_short_loop_video() -> None:
    # avg_watch_time > duration is valid (loop/replay behavior)
    result = compute_apv(600, 300, period_start=_D1, period_end=_D2)
    assert result.value == pytest.approx(2.0)


def test_apv_incomplete_window_flag_propagated() -> None:
    result = compute_apv(
        200, 400,
        period_start=_D1, period_end=_D2,
        incomplete_observation_window=True,
    )
    assert result.incomplete_observation_window is True


# ---------------------------------------------------------------------------
# Engagement Rate
# ---------------------------------------------------------------------------


def test_er_full_nominal() -> None:
    result = compute_engagement_rate(100, 50, 25, 5000, period_start=_D1, period_end=_D2)
    assert result.value == pytest.approx((100 + 50 + 25) / 5000)
    assert result.metric_key == "engagement_rate"


def test_er_zero_views_uses_max_1() -> None:
    result = compute_engagement_rate(10, 5, 2, 0, period_start=_D1, period_end=_D2)
    assert result.value == pytest.approx(17.0)  # (10+5+2)/1


def test_er_none_components_treated_as_zero() -> None:
    result = compute_engagement_rate(None, None, None, 1000, period_start=_D1, period_end=_D2)
    assert result.value == 0.0
    assert len(result.limitations) == 3  # one per None field


def test_er_public_no_shares() -> None:
    result = compute_public_engagement_rate(100, 50, 5000, period_start=_D1, period_end=_D2)
    assert result.metric_key == "public_engagement_rate"
    assert result.value == pytest.approx(150 / 5000)
    assert any("shares" in lim.lower() for lim in result.limitations)


def test_er_public_visibility_is_public() -> None:
    result = compute_public_engagement_rate(50, 20, 1000, period_start=_D1, period_end=_D2)
    assert result.visibility == "public"


# ---------------------------------------------------------------------------
# NSC_1k
# ---------------------------------------------------------------------------


def test_nsc_1k_positive_net() -> None:
    result = compute_nsc_1k(500, 100, 10000, period_start=_D1, period_end=_D2)
    assert result.value == pytest.approx(40.0)  # (500-100)/10000 * 1000
    assert result.unit == "subscribers_per_1k_views"


def test_nsc_1k_negative_net_allowed() -> None:
    result = compute_nsc_1k(50, 200, 5000, period_start=_D1, period_end=_D2)
    assert result.value == pytest.approx(-30.0)


def test_nsc_1k_zero_views_uses_max_1() -> None:
    result = compute_nsc_1k(10, 5, 0, period_start=_D1, period_end=_D2)
    assert result.value == pytest.approx(5000.0)  # 5/1 * 1000


# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------


def test_velocity_nominal() -> None:
    baseline = [1000.0] * 15
    result = compute_velocity(1500, baseline, period_start=_D1, period_end=_D2)
    assert result.value == pytest.approx(1.5)
    assert result.unit == "dimensionless"
    assert result.sample_size == 15
    assert any("asociación observacional" in lim for lim in result.limitations)


def test_velocity_insufficient_baseline_returns_none() -> None:
    result = compute_velocity(1000, [100, 200, 300], period_start=_D1, period_end=_D2)
    assert result.value is None
    assert any("insuficiente" in lim for lim in result.limitations)


def test_velocity_zero_median_returns_none() -> None:
    baseline = [0.0] * 15
    result = compute_velocity(1000, baseline, period_start=_D1, period_end=_D2)
    assert result.value is None


def test_velocity_custom_horizon_label() -> None:
    baseline = [float(x) for x in range(50, 61)]  # 11 values
    result = compute_velocity(500, baseline, period_start=_D1, period_end=_D2, horizon_label="7d")
    assert result.metric_key == "velocity_7d"
    assert result.value is not None


def test_velocity_equal_to_median_returns_one() -> None:
    baseline = [200.0] * 10
    result = compute_velocity(200, baseline, period_start=_D1, period_end=_D2)
    assert result.value == pytest.approx(1.0)


def test_velocity_custom_min_baseline_n() -> None:
    baseline = [500.0] * 5
    result = compute_velocity(
        1000, baseline,
        period_start=_D1, period_end=_D2,
        min_baseline_n=5,
    )
    assert result.value == pytest.approx(2.0)


def test_velocity_nan_values_in_baseline_excluded() -> None:
    baseline = [1000.0, float("nan"), 1000.0] + [1000.0] * 8
    result = compute_velocity(2000, baseline, period_start=_D1, period_end=_D2)
    assert result.value == pytest.approx(2.0)
    assert result.sample_size == 10  # NaN excluded


# ---------------------------------------------------------------------------
# describe()
# ---------------------------------------------------------------------------


def test_describe_empty_sample() -> None:
    stats = describe([])
    assert stats.n == 0
    assert stats.mean is None
    assert any("vacía" in lim for lim in stats.limitations)


def test_describe_single_element() -> None:
    stats = describe([42.0])
    assert stats.n == 1
    assert stats.mean == pytest.approx(42.0)
    assert stats.median == pytest.approx(42.0)
    assert stats.std is None  # ddof=1 undefined for N=1


def test_describe_below_min_n_has_limitation() -> None:
    stats = describe([1, 2, 3])
    assert stats.n == 3
    assert any("N=3" in lim for lim in stats.limitations)


def test_describe_nominal_25_values() -> None:
    rng = np.random.default_rng(0)
    data = rng.normal(100, 15, 25)
    stats = describe(data)
    assert stats.n == 25
    assert stats.std is not None
    assert stats.q1 is not None and stats.q3 is not None
    assert stats.min_val < stats.mean < stats.max_val  # type: ignore[operator]
    assert stats.limitations == []


def test_describe_ignores_nan() -> None:
    data = [10.0, float("nan"), 20.0, 30.0]
    stats = describe(data)
    assert stats.n == 3
    assert stats.mean == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# test_normality()
# ---------------------------------------------------------------------------


def test_normality_shapiro_path_normal_distribution() -> None:
    rng = np.random.default_rng(1)
    data = rng.normal(50, 10, 30)
    result = check_normality(data)
    assert result.test_name == "shapiro-wilk"
    assert result.n == 30
    assert isinstance(result.is_normal, bool)


def test_normality_lilliefors_path_used_for_large_sample() -> None:
    rng = np.random.default_rng(2)
    data = rng.normal(100, 20, 100)
    result = check_normality(data)
    # N>=50 must use Lilliefors, not raw KS: raw KS p-values are invalid
    # when loc/scale are estimated from the same sample.
    assert result.test_name == "lilliefors-ks"


def test_normality_clearly_non_normal_exponential() -> None:
    rng = np.random.default_rng(3)
    # Exponential distribution is skewed — very different from normal
    data = rng.exponential(scale=5.0, size=200)
    result = check_normality(data)
    assert result.test_name == "lilliefors-ks"
    assert result.is_normal is False


def test_normality_insufficient_sample_returns_false() -> None:
    result = check_normality([1.0, 2.0])
    assert result.is_normal is False
    assert any("insuficiente" in lim for lim in result.limitations)


def test_normality_constant_array_degeneracy() -> None:
    data = [5.0] * 60
    result = check_normality(data)
    assert result.test_name == "lilliefors-ks"
    assert result.is_normal is True  # std=0 early return, no Lilliefors call


# ---------------------------------------------------------------------------
# compute_ci_95()
# ---------------------------------------------------------------------------


def test_ci_95_insufficient_n_returns_none() -> None:
    ci = compute_ci_95([1.0, 2.0, 3.0])
    assert ci is None


def test_ci_95_normal_sample_returns_ordered_tuple() -> None:
    rng = np.random.default_rng(4)
    data = rng.normal(50, 5, 40)
    ci = compute_ci_95(data)
    assert ci is not None
    lo, hi = ci
    assert lo < hi
    assert lo < np.mean(data) < hi


def test_ci_95_parametric_bounds_match_t_interval() -> None:
    """Both bounds of the t-interval CI match scipy.stats.t.interval exactly.

    Uses a fixed hard-coded array (N=20, Shapiro-Wilk p=0.187 > 0.05) so the
    normality branch and both CI bounds are fully deterministic — no pytest.skip
    or random seed dependence.

    Expected bounds were pre-computed once from the same scipy.stats.t.interval
    formula and are verified here to floating-point precision.
    """
    from scipy.stats import sem as _sem
    from scipy.stats import t as _t

    # Fixed array: N=20, Shapiro-Wilk p≈0.187 (is_normal=True, deterministic)
    data = np.array([
        51.523585398772155, 44.80007946879752, 53.752255979032284,
        54.70282358195607,  40.24482405673082, 43.48910246568841,
        50.639202015836425, 48.41878703828209, 49.91599421247856,
        45.7347803621321,   54.396989874314144, 53.88895967714474,
        50.33015348780608,  55.636206034840164, 52.33754671126023,
        45.70353768558381,  51.843753920412496, 45.20558699585501,
        54.39225150653636,  49.75037044506873,
    ])
    # Verify normality branch deterministically (Shapiro-Wilk on fixed input)
    norm_result = check_normality(data)
    assert norm_result.is_normal, (
        f"This fixed array must pass Shapiro-Wilk (p={norm_result.p_value:.4f}); "
        "if this assertion fails, statsmodels or scipy changed their test implementation"
    )
    # Compute expected bounds from the same formula the implementation uses
    n = len(data)
    expected_lo, expected_hi = _t.interval(
        0.95, df=n - 1, loc=float(np.mean(data)), scale=float(_sem(data))
    )
    ci = compute_ci_95(data)
    assert ci is not None
    assert ci[0] == pytest.approx(expected_lo, rel=1e-9), (
        f"Lower bound {ci[0]:.10f} ≠ expected {expected_lo:.10f}"
    )
    assert ci[1] == pytest.approx(expected_hi, rel=1e-9), (
        f"Upper bound {ci[1]:.10f} ≠ expected {expected_hi:.10f}"
    )


def test_ci_95_non_normal_returns_bootstrap_ci() -> None:
    rng = np.random.default_rng(6)
    # Heavy-tailed Pareto: very non-normal
    data = rng.pareto(1.5, 60) * 100
    ci = compute_ci_95(data)
    assert ci is not None
    lo, hi = ci
    assert lo < hi


# ---------------------------------------------------------------------------
# compare_two_groups()
# ---------------------------------------------------------------------------


def test_compare_insufficient_n_returns_sentinel() -> None:
    result = compare_two_groups([1, 2, 3], [4, 5, 6])
    assert result.test_name == "insufficient_sample"
    assert np.isnan(result.p_value)
    assert result.effect_size is None


def test_compare_parametric_normal_groups() -> None:
    rng = np.random.default_rng(7)
    a = rng.normal(50, 5, 30)
    b = rng.normal(50, 5, 30)
    result = compare_two_groups(a, b)
    assert isinstance(result, ComparisonResult)
    assert result.test_name == "welch-t-test"
    assert result.n_a == 30 and result.n_b == 30
    assert result.effect_size is not None
    assert result.effect_size_name == "cohen_d"
    assert 0.0 <= result.p_value <= 1.0
    assert any("asociaciones observacionales" in lim for lim in result.limitations)


def test_compare_non_parametric_skewed_groups() -> None:
    rng = np.random.default_rng(8)
    # Exponential: non-normal
    a = rng.exponential(5, 40)
    b = rng.exponential(10, 40)
    result = compare_two_groups(a, b)
    assert result.test_name == "mann-whitney-u"
    assert result.effect_size_name == "rank_biserial_r"
    assert result.effect_size is not None
    assert -1.0 <= result.effect_size <= 1.0


def test_compare_identical_groups_effect_near_zero() -> None:
    rng = np.random.default_rng(9)
    data = rng.normal(100, 10, 50)
    result = compare_two_groups(data, data)
    assert result.effect_size is not None
    assert abs(result.effect_size) < 1e-10


def test_compare_clearly_different_groups_large_effect() -> None:
    rng = np.random.default_rng(10)
    a = rng.normal(100, 5, 50)
    b = rng.normal(200, 5, 50)
    result = compare_two_groups(a, b)
    assert result.p_value < 0.001
    assert result.effect_size is not None
    assert abs(result.effect_size) > 1.0  # Cohen's d for 20-sigma separation


def test_compare_ci_effect_ordered() -> None:
    rng = np.random.default_rng(11)
    a = rng.normal(50, 5, 30)
    b = rng.normal(60, 5, 30)
    result = compare_two_groups(a, b)
    if result.ci_95_effect is not None:
        lo, hi = result.ci_95_effect
        assert lo < hi


def test_compare_no_causal_claim_in_limitations() -> None:
    rng = np.random.default_rng(12)
    a = rng.normal(50, 5, 30)
    b = rng.normal(55, 5, 30)
    result = compare_two_groups(a, b)
    all_lim = " ".join(result.limitations).lower()
    assert "observacional" in all_lim or "asociacion" in all_lim or "asociación" in all_lim


# ---------------------------------------------------------------------------
# No infrastructure dependency guard
# ---------------------------------------------------------------------------


def test_statistics_module_has_no_fastapi_dependency() -> None:
    import importlib.util

    spec = importlib.util.find_spec("miconte.statistics")
    assert spec is not None
    # fastapi is in sys.modules because main.py imported it earlier in the session,
    # but miconte.statistics itself must not import it
    import ast
    import pathlib

    # miconte.statistics must not pull fastapi into the module namespace
    import miconte.statistics  # noqa: F401

    stats_dir = pathlib.Path(spec.origin).parent  # type: ignore[arg-type]
    for py_file in stats_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    names = [node.module or ""]
                for name in names:
                    assert not name.startswith("fastapi"), (
                        f"{py_file.name} imports fastapi: {name}"
                    )
                    assert not name.startswith("sqlalchemy"), (
                        f"{py_file.name} imports sqlalchemy: {name}"
                    )
