"""Deterministic derived metric calculations for miConte.

Implements the formulas defined in docs/data-dictionary.md §3.
All functions are pure (no side effects, no I/O) and produce identical output for
identical inputs. Inputs are plain Python scalars or NumPy arrays; outputs are
MetricEnvelope instances.

Metric formulas (LaTeX):
    CTR      = clicks / impressions              (impressions > 0; else 0.0)
    APV      = avg_watch_time_s / duration_s     (duration_s > 0; else 0.0)
    ER       = (likes + comments + shares) / max(views, 1)
    ER_pub   = (likes + comments) / max(views, 1)    [public-only variant]
    NSC_1k   = (subs_gained - subs_lost) / max(views, 1) * 1000
    V_kd     = video_views / median(baseline_views)  [N_baseline >= 10]
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np

from miconte.statistics._models import MetricEnvelope

_DERIVED = "derived_deterministic"
_PRIVATE = "private_oauth"
_PUBLIC = "public"


def compute_ctr(
    clicks: int | float | None,
    impressions: int | float | None,
    *,
    period_start: date | datetime,
    period_end: date | datetime,
) -> MetricEnvelope:
    """Click-Through Rate: CTR = clicks / impressions.

    Returns 0.0 when impressions == 0 (never ZeroDivisionError).
    Returns None value when impressions is None (data unavailable from source).
    """
    limitations: list[str] = []

    if impressions is None:
        return MetricEnvelope(
            metric_key="click_through_rate",
            value=None,
            unit="ratio",
            source=_DERIVED,
            visibility=_PRIVATE,
            period_start=period_start,
            period_end=period_end,
            sample_size=0,
            data_suppressed=True,
            limitations=["Impresiones no disponibles para este periodo/fuente"],
        )

    if clicks is None:
        clicks = 0.0
        limitations.append("Clics no disponibles; se asume 0 para el cálculo")

    impressions_f = float(impressions)
    clicks_f = float(clicks)

    if impressions_f < 0 or clicks_f < 0:
        return MetricEnvelope(
            metric_key="click_through_rate",
            value=None,
            unit="ratio",
            source=_DERIVED,
            visibility=_PRIVATE,
            period_start=period_start,
            period_end=period_end,
            sample_size=0,
            limitations=["Valor negativo en impressiones o clics; CTR no calculable"],
        )

    value = 0.0 if impressions_f == 0.0 else clicks_f / impressions_f
    return MetricEnvelope(
        metric_key="click_through_rate",
        value=value,
        unit="ratio",
        source=_DERIVED,
        visibility=_PRIVATE,
        period_start=period_start,
        period_end=period_end,
        sample_size=1,
        limitations=limitations,
    )


def compute_apv(
    avg_watch_time_s: int | float | None,
    duration_s: int | float | None,
    *,
    period_start: date | datetime,
    period_end: date | datetime,
    incomplete_observation_window: bool = False,
) -> MetricEnvelope:
    """Average Percentage Viewed (relative retention):
    APV = avg_watch_time_s / duration_s.

    Returns 0.0 when duration_s <= 0 (e.g., live streams not yet processed).
    """
    limitations: list[str] = []

    if duration_s is None or avg_watch_time_s is None:
        return MetricEnvelope(
            metric_key="average_percentage_viewed",
            value=None,
            unit="ratio",
            source=_DERIVED,
            visibility=_PRIVATE,
            period_start=period_start,
            period_end=period_end,
            sample_size=0,
            data_suppressed=True,
            limitations=["Duración del video o tiempo medio de visualización no disponible"],
        )

    dur = float(duration_s)
    awt = float(avg_watch_time_s)

    if dur <= 0:
        limitations.append(
            "Duración <= 0 (posible transmisión en vivo no procesada); APV fijado a 0.0"
        )
        value: float = 0.0
    else:
        value = awt / dur

    return MetricEnvelope(
        metric_key="average_percentage_viewed",
        value=value,
        unit="ratio",
        source=_DERIVED,
        visibility=_PRIVATE,
        period_start=period_start,
        period_end=period_end,
        sample_size=1,
        incomplete_observation_window=incomplete_observation_window,
        limitations=limitations,
    )


def compute_engagement_rate(
    likes: int | float | None,
    comments: int | float | None,
    shares: int | float | None,
    views: int | float,
    *,
    period_start: date | datetime,
    period_end: date | datetime,
) -> MetricEnvelope:
    """Full Engagement Rate: ER = (likes + comments + shares) / max(views, 1).

    None values for likes/comments/shares are treated as 0 with a limitation note.
    Use compute_public_engagement_rate when shares are not available.
    """
    limitations: list[str] = []

    def _coerce(v: int | float | None, name: str) -> float:
        if v is None:
            limitations.append(f"{name} no disponible; se asume 0 para el cálculo de ER")
            return 0.0
        return float(v)

    l_ = _coerce(likes, "likes")
    c_ = _coerce(comments, "comentarios")
    s_ = _coerce(shares, "shares")
    v_ = max(float(views), 1.0)

    return MetricEnvelope(
        metric_key="engagement_rate",
        value=(l_ + c_ + s_) / v_,
        unit="ratio",
        source=_DERIVED,
        visibility=_PRIVATE,
        period_start=period_start,
        period_end=period_end,
        sample_size=1,
        limitations=limitations,
    )


def compute_public_engagement_rate(
    likes: int | float | None,
    comments: int | float | None,
    views: int | float,
    *,
    period_start: date | datetime,
    period_end: date | datetime,
) -> MetricEnvelope:
    """Public Engagement Rate (no shares): ER_pub = (likes + comments) / max(views, 1).

    Uses a distinct metric_key ("public_engagement_rate") so it is never confused
    with the full ER that includes shares.
    """
    limitations: list[str] = ["Shares no disponibles (Data API v3); ER calculado sin shares"]

    def _coerce(v: int | float | None, name: str) -> float:
        if v is None:
            limitations.append(f"{name} no disponible; se asume 0 para el cálculo de ER público")
            return 0.0
        return float(v)

    l_ = _coerce(likes, "likes")
    c_ = _coerce(comments, "comentarios")
    v_ = max(float(views), 1.0)

    return MetricEnvelope(
        metric_key="public_engagement_rate",
        value=(l_ + c_) / v_,
        unit="ratio",
        source=_DERIVED,
        visibility=_PUBLIC,
        period_start=period_start,
        period_end=period_end,
        sample_size=1,
        limitations=limitations,
    )


def compute_nsc_1k(
    subscribers_gained: int | float,
    subscribers_lost: int | float,
    views: int | float,
    *,
    period_start: date | datetime,
    period_end: date | datetime,
) -> MetricEnvelope:
    """Net Subscriber Conversion per 1k views:
    NSC_1k = (subs_gained - subs_lost) / max(views, 1) * 1000.
    """
    sg = float(subscribers_gained)
    sl = float(subscribers_lost)
    v_ = max(float(views), 1.0)
    value = (sg - sl) / v_ * 1000.0

    return MetricEnvelope(
        metric_key="net_subscriber_conversion_per_1k",
        value=value,
        unit="subscribers_per_1k_views",
        source=_DERIVED,
        visibility=_PRIVATE,
        period_start=period_start,
        period_end=period_end,
        sample_size=1,
    )


def compute_velocity(
    video_views: int | float,
    baseline_series: list[int | float] | np.ndarray,
    *,
    period_start: date | datetime,
    period_end: date | datetime,
    horizon_label: str = "24h",
    min_baseline_n: int = 10,
) -> MetricEnvelope:
    """Normalized velocity: V_kd = video_views / median(baseline_series).

    Requires at least min_baseline_n (default 10) values in baseline_series and
    a strictly positive median. Returns None when sample is insufficient.

    A value of 1.5 means the video performed 50% above the channel's historical
    median for the same time horizon — this is an observed association, not causal.
    """
    limitations: list[str] = []
    arr = np.asarray(baseline_series, dtype=float)
    valid = arr[~np.isnan(arr)]
    n = int(valid.size)

    if n < min_baseline_n:
        return MetricEnvelope(
            metric_key=f"velocity_{horizon_label}",
            value=None,
            unit="dimensionless",
            source=_DERIVED,
            visibility=_PRIVATE,
            period_start=period_start,
            period_end=period_end,
            sample_size=n,
            limitations=[
                f"Muestra insuficiente para velocidad normalizada: N={n} < {min_baseline_n}; "
                "se requieren al menos 10 videos con captura en la misma ventana temporal"
            ],
        )

    median_baseline = float(np.median(valid))
    if median_baseline <= 0:
        return MetricEnvelope(
            metric_key=f"velocity_{horizon_label}",
            value=None,
            unit="dimensionless",
            source=_DERIVED,
            visibility=_PRIVATE,
            period_start=period_start,
            period_end=period_end,
            sample_size=n,
            limitations=[
                "Mediana de línea base es <= 0; velocidad normalizada no calculable"
            ],
        )

    value = float(video_views) / median_baseline
    if np.isnan(value) or np.isinf(value):
        return MetricEnvelope(
            metric_key=f"velocity_{horizon_label}",
            value=None,
            unit="dimensionless",
            source=_DERIVED,
            visibility=_PRIVATE,
            period_start=period_start,
            period_end=period_end,
            sample_size=n,
            limitations=["Resultado numérico inválido (NaN/Inf) en velocidad normalizada"],
        )

    limitations.append(
        "Velocidad es una asociación observacional normalizada respecto a la mediana histórica "
        "del canal; no implica causalidad ni predice rendimiento futuro"
    )
    return MetricEnvelope(
        metric_key=f"velocity_{horizon_label}",
        value=value,
        unit="dimensionless",
        source=_DERIVED,
        visibility=_PRIVATE,
        period_start=period_start,
        period_end=period_end,
        sample_size=n,
        limitations=limitations,
    )
