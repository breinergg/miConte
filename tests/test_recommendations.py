"""Unit tests for the miconte.recommendations pure rules engine.

All tests use synthetic data only — no database, no network, no LLM.
Each test verifies a specific rule's threshold logic, edge cases, and
that descriptions use associative language only.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from miconte.recommendations import (
    APV_THRESHOLD_RATIO,
    MIN_BASELINE_N,
    VELOCITY_THRESHOLD,
    evaluate_rules,
)
from miconte.recommendations._models import RecommendationResult, RecommendationSignal
from miconte.recommendations._rules import (
    r01_apv_below_median,
    r02_ctr_below_median,
    r03_velocity_low_24h,
    r04_nsc_negative,
    r05_er_below_median,
    r06_insufficient_data,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _signal(
    *,
    n: int = 15,
    apv: float | None = 0.5,
    ctr: float | None = 0.05,
    er: float | None = 0.04,
    nsc_1k: float | None = 1.0,
    velocity_24h: float | None = 1.0,
    channel_apv_median: float | None = 0.5,
    channel_ctr_median: float | None = 0.05,
    channel_er_median: float | None = 0.04,
    channel_velocity_median: float | None = 1.0,
) -> RecommendationSignal:
    """Build a RecommendationSignal with overridable defaults."""
    return RecommendationSignal(
        channel_id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        apv=apv,
        ctr=ctr,
        er=er,
        nsc_1k=nsc_1k,
        velocity_24h=velocity_24h,
        channel_apv_median=channel_apv_median,
        channel_ctr_median=channel_ctr_median,
        channel_er_median=channel_er_median,
        channel_velocity_median=channel_velocity_median,
        n_videos_baseline=n,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
    )


# ─── R06 — Insufficient data ──────────────────────────────────────────────────

class TestR06InsufficientData:
    def test_fires_when_baseline_below_minimum(self) -> None:
        signal = _signal(n=MIN_BASELINE_N - 1)
        result = r06_insufficient_data(signal)
        assert result.triggered
        assert result.rule_code == "R06_INSUFFICIENT_DATA"
        assert result.priority == "info"

    def test_fires_when_no_metrics_available(self) -> None:
        signal = _signal(n=0, apv=None, ctr=None, er=None)
        result = r06_insufficient_data(signal)
        assert result.triggered

    def test_does_not_fire_with_sufficient_data(self) -> None:
        signal = _signal(n=MIN_BASELINE_N)
        result = r06_insufficient_data(signal)
        assert not result.triggered

    def test_fires_when_baseline_exactly_at_minimum_minus_one(self) -> None:
        signal = _signal(n=MIN_BASELINE_N - 1, apv=0.5)
        result = r06_insufficient_data(signal)
        assert result.triggered

    def test_does_not_fire_with_exactly_minimum_n(self) -> None:
        signal = _signal(n=MIN_BASELINE_N, apv=0.5)
        result = r06_insufficient_data(signal)
        assert not result.triggered

    def test_evidence_contains_baseline_counts(self) -> None:
        signal = _signal(n=5)
        result = r06_insufficient_data(signal)
        assert result.metrics_evidence["n_videos_baseline"] == 5
        assert result.metrics_evidence["min_required"] == MIN_BASELINE_N


# ─── R01 — APV below median ───────────────────────────────────────────────────

class TestR01APVBelowMedian:
    def test_fires_when_apv_below_threshold(self) -> None:
        median = 0.60
        # 80% of median = 0.48, which is below threshold (85% = 0.51)
        signal = _signal(apv=0.48, channel_apv_median=median)
        result = r01_apv_below_median(signal)
        assert result.triggered
        assert result.rule_code == "R01_APV_BELOW_MEDIAN"

    def test_does_not_fire_when_apv_at_threshold(self) -> None:
        median = 0.60
        threshold = APV_THRESHOLD_RATIO * median  # 0.51
        signal = _signal(apv=threshold, channel_apv_median=median)
        result = r01_apv_below_median(signal)
        assert not result.triggered

    def test_does_not_fire_when_apv_above_threshold(self) -> None:
        median = 0.50
        signal = _signal(apv=0.55, channel_apv_median=median)  # above threshold
        result = r01_apv_below_median(signal)
        assert not result.triggered

    def test_does_not_fire_when_insufficient_baseline(self) -> None:
        signal = _signal(n=MIN_BASELINE_N - 1, apv=0.1, channel_apv_median=0.9)
        result = r01_apv_below_median(signal)
        assert not result.triggered

    def test_does_not_fire_when_apv_is_none(self) -> None:
        signal = _signal(apv=None, channel_apv_median=0.5)
        result = r01_apv_below_median(signal)
        assert not result.triggered

    def test_does_not_fire_when_channel_median_is_zero(self) -> None:
        signal = _signal(apv=0.0, channel_apv_median=0.0)
        result = r01_apv_below_median(signal)
        assert not result.triggered

    def test_evidence_contains_threshold_value(self) -> None:
        median = 0.60
        signal = _signal(apv=0.48, channel_apv_median=median)
        result = r01_apv_below_median(signal)
        assert result.triggered
        assert "threshold_value" in result.metrics_evidence
        assert abs(result.metrics_evidence["threshold_value"] - APV_THRESHOLD_RATIO * median) < 1e-9

    def test_description_uses_associative_language(self) -> None:
        signal = _signal(apv=0.40, channel_apv_median=0.60)
        result = r01_apv_below_median(signal)
        assert result.triggered
        desc = result.description.lower()
        # Must not contain causal verbs (note: "causalidad" / "causa directa" in disclaimers are OK)
        assert "causó que" not in desc
        assert "causa que" not in desc
        assert "provoca" not in desc
        assert "leads to" not in desc
        # Must contain associative language
        assert "observa" in desc or "asocia" in desc or "observación" in desc


# ─── R02 — CTR below median ───────────────────────────────────────────────────

class TestR02CTRBelowMedian:
    def test_fires_when_ctr_below_threshold(self) -> None:
        median = 0.06
        signal = _signal(ctr=0.04, channel_ctr_median=median)  # 0.04 < 0.85 * 0.06 = 0.051
        result = r02_ctr_below_median(signal)
        assert result.triggered
        assert result.rule_code == "R02_CTR_BELOW_MEDIAN"

    def test_does_not_fire_when_ctr_above_threshold(self) -> None:
        median = 0.05
        signal = _signal(ctr=0.06, channel_ctr_median=median)
        result = r02_ctr_below_median(signal)
        assert not result.triggered

    def test_does_not_fire_when_ctr_is_none(self) -> None:
        signal = _signal(ctr=None, channel_ctr_median=0.05)
        result = r02_ctr_below_median(signal)
        assert not result.triggered

    def test_does_not_fire_with_thin_baseline(self) -> None:
        signal = _signal(n=3, ctr=0.01, channel_ctr_median=0.06)
        result = r02_ctr_below_median(signal)
        assert not result.triggered

    def test_evidence_contains_video_ctr(self) -> None:
        signal = _signal(ctr=0.03, channel_ctr_median=0.06)
        result = r02_ctr_below_median(signal)
        assert result.triggered
        assert result.metrics_evidence["video_ctr"] == pytest.approx(0.03, abs=1e-6)


# ─── R03 — Velocity low 24h ───────────────────────────────────────────────────

class TestR03VelocityLow24H:
    def test_fires_when_velocity_below_threshold(self) -> None:
        # velocity_24h = 0.5, channel_velocity_median = 1.0 → threshold = 0.70 → 0.5 < 0.7 ✓
        signal = _signal(velocity_24h=0.5, channel_velocity_median=1.0)
        result = r03_velocity_low_24h(signal)
        assert result.triggered
        assert result.rule_code == "R03_VELOCITY_LOW_24H"

    def test_does_not_fire_when_velocity_at_threshold(self) -> None:
        median = 1.0
        threshold = VELOCITY_THRESHOLD * median
        signal = _signal(velocity_24h=threshold, channel_velocity_median=median)
        result = r03_velocity_low_24h(signal)
        assert not result.triggered

    def test_does_not_fire_when_velocity_above_threshold(self) -> None:
        signal = _signal(velocity_24h=1.5, channel_velocity_median=1.0)
        result = r03_velocity_low_24h(signal)
        assert not result.triggered

    def test_does_not_fire_when_velocity_none(self) -> None:
        signal = _signal(velocity_24h=None, channel_velocity_median=1.0)
        result = r03_velocity_low_24h(signal)
        assert not result.triggered

    def test_priority_is_high(self) -> None:
        signal = _signal(velocity_24h=0.3, channel_velocity_median=1.0)
        result = r03_velocity_low_24h(signal)
        assert result.triggered
        assert result.priority == "high"

    def test_does_not_fire_with_thin_baseline(self) -> None:
        signal = _signal(n=5, velocity_24h=0.1, channel_velocity_median=1.0)
        result = r03_velocity_low_24h(signal)
        assert not result.triggered


# ─── R04 — NSC negative ──────────────────────────────────────────────────────

class TestR04NSCNegative:
    def test_fires_when_nsc_negative(self) -> None:
        signal = _signal(nsc_1k=-0.5)
        result = r04_nsc_negative(signal)
        assert result.triggered
        assert result.rule_code == "R04_NSC_NEGATIVE"

    def test_does_not_fire_when_nsc_zero(self) -> None:
        signal = _signal(nsc_1k=0.0)
        result = r04_nsc_negative(signal)
        assert not result.triggered

    def test_does_not_fire_when_nsc_positive(self) -> None:
        signal = _signal(nsc_1k=2.5)
        result = r04_nsc_negative(signal)
        assert not result.triggered

    def test_does_not_fire_when_nsc_is_none(self) -> None:
        signal = _signal(nsc_1k=None)
        result = r04_nsc_negative(signal)
        assert not result.triggered

    def test_fires_even_with_thin_baseline(self) -> None:
        """R04 has no baseline requirement — it is absolute."""
        signal = _signal(n=2, nsc_1k=-1.0)
        result = r04_nsc_negative(signal)
        assert result.triggered

    def test_evidence_contains_nsc_value(self) -> None:
        signal = _signal(nsc_1k=-3.2)
        result = r04_nsc_negative(signal)
        assert result.triggered
        assert result.metrics_evidence["video_nsc_1k"] == pytest.approx(-3.2, abs=1e-4)

    def test_description_is_associative(self) -> None:
        signal = _signal(nsc_1k=-1.0)
        result = r04_nsc_negative(signal)
        assert result.triggered
        desc = result.description.lower()
        # Causal verbs must not appear (disclaimers referencing "la causa directa" are OK)
        assert "causó que" not in desc
        assert "causa que" not in desc
        assert "provoca" not in desc
        assert "asocia" in desc or "asociación" in desc or "indica" in desc


# ─── R05 — ER below median ───────────────────────────────────────────────────

class TestR05ERBelowMedian:
    def test_fires_when_er_below_threshold(self) -> None:
        median = 0.05
        signal = _signal(er=0.03, channel_er_median=median)  # 0.03 < 0.85 * 0.05 = 0.0425
        result = r05_er_below_median(signal)
        assert result.triggered
        assert result.rule_code == "R05_ER_BELOW_MEDIAN"

    def test_does_not_fire_when_er_above_threshold(self) -> None:
        median = 0.04
        signal = _signal(er=0.05, channel_er_median=median)
        result = r05_er_below_median(signal)
        assert not result.triggered

    def test_does_not_fire_when_er_is_none(self) -> None:
        signal = _signal(er=None, channel_er_median=0.04)
        result = r05_er_below_median(signal)
        assert not result.triggered

    def test_priority_is_low(self) -> None:
        signal = _signal(er=0.01, channel_er_median=0.05)
        result = r05_er_below_median(signal)
        assert result.triggered
        assert result.priority == "low"


# ─── evaluate_rules — engine ─────────────────────────────────────────────────

class TestEvaluateRules:
    def test_returns_one_result_per_rule(self) -> None:
        signal = _signal()
        results = evaluate_rules(signal)
        codes = [r.rule_code for r in results]
        assert "R06_INSUFFICIENT_DATA" in codes
        assert "R01_APV_BELOW_MEDIAN" in codes
        assert "R02_CTR_BELOW_MEDIAN" in codes
        assert "R03_VELOCITY_LOW_24H" in codes
        assert "R04_NSC_NEGATIVE" in codes
        assert "R05_ER_BELOW_MEDIAN" in codes
        assert len(results) == 6  # one per rule

    def test_healthy_signal_triggers_only_r06_as_not_triggered(self) -> None:
        """A well-performing video should trigger no rules."""
        signal = _signal(
            n=20,
            apv=0.70, channel_apv_median=0.60,      # above threshold
            ctr=0.08, channel_ctr_median=0.05,      # above threshold
            er=0.06, channel_er_median=0.04,        # above threshold
            nsc_1k=2.0,                             # positive
            velocity_24h=1.5, channel_velocity_median=1.0,  # above threshold
        )
        results = evaluate_rules(signal)
        triggered = [r for r in results if r.triggered]
        assert triggered == [], f"Unexpected triggers: {[r.rule_code for r in triggered]}"

    def test_poorly_performing_video_triggers_multiple_rules(self) -> None:
        signal = _signal(
            n=20,
            apv=0.30, channel_apv_median=0.60,       # below threshold
            ctr=0.02, channel_ctr_median=0.05,       # below threshold
            er=0.01, channel_er_median=0.04,         # below threshold
            nsc_1k=-2.0,                             # negative
            velocity_24h=0.3, channel_velocity_median=1.0,  # below threshold
        )
        results = evaluate_rules(signal)
        triggered_codes = {r.rule_code for r in results if r.triggered}
        assert "R01_APV_BELOW_MEDIAN" in triggered_codes
        assert "R02_CTR_BELOW_MEDIAN" in triggered_codes
        assert "R03_VELOCITY_LOW_24H" in triggered_codes
        assert "R04_NSC_NEGATIVE" in triggered_codes
        assert "R05_ER_BELOW_MEDIAN" in triggered_codes

    def test_thin_baseline_triggers_r06_and_suppresses_comparison_rules(self) -> None:
        signal = _signal(
            n=MIN_BASELINE_N - 1,
            apv=0.10, channel_apv_median=0.60,  # would trigger R01 if baseline was OK
        )
        results = evaluate_rules(signal)
        triggered = {r.rule_code for r in results if r.triggered}
        assert "R06_INSUFFICIENT_DATA" in triggered
        # With thin baseline, comparison rules return triggered=False even when metric is bad
        assert "R01_APV_BELOW_MEDIAN" not in triggered

    def test_r04_independent_of_baseline(self) -> None:
        """R04 fires regardless of baseline size."""
        signal = _signal(n=2, nsc_1k=-5.0)
        results = evaluate_rules(signal)
        triggered = {r.rule_code for r in results if r.triggered}
        assert "R04_NSC_NEGATIVE" in triggered
        assert "R06_INSUFFICIENT_DATA" in triggered

    def test_all_results_have_required_fields(self) -> None:
        signal = _signal()
        for result in evaluate_rules(signal):
            assert isinstance(result, RecommendationResult)
            assert result.rule_code
            assert isinstance(result.triggered, bool)
            assert result.priority in ("high", "medium", "low", "info")
            assert result.title
            assert result.description
            assert isinstance(result.metrics_evidence, dict)
            assert isinstance(result.limitations, list)

    def test_no_causal_language_in_any_description(self) -> None:
        """All triggered rule descriptions must avoid causal claims."""
        signal = _signal(
            n=20,
            apv=0.10, channel_apv_median=0.60,
            ctr=0.01, channel_ctr_median=0.05,
            er=0.005, channel_er_median=0.04,
            nsc_1k=-10.0,
            velocity_24h=0.1, channel_velocity_median=1.0,
        )
        # Causal VERBS/CLAIMS: "causó que", "causa que", "provoca", "leads to"
        # Note: "causalidad" and "la causa directa" appear in disclaimers (correct use)
        forbidden = [
            "causó que", "causa que", "provoca",
            "leads to", "will result", "resultó directamente",
        ]
        for result in evaluate_rules(signal):
            if result.triggered:
                for phrase in forbidden:
                    assert phrase not in result.description.lower(), (
                        f"Rule {result.rule_code} description contains causal language: "
                        f"'{phrase}' in '{result.description}'"
                    )

    def test_r06_is_first_result(self) -> None:
        """R06 must be the first result returned (evaluated before comparison rules)."""
        signal = _signal(n=0)
        results = evaluate_rules(signal)
        assert results[0].rule_code == "R06_INSUFFICIENT_DATA"
