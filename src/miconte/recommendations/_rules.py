"""Deterministic recommendation rules for miConte.

Each rule is a pure function:  RecommendationSignal -> RecommendationResult.

Rules are auditable: the threshold, the direction of comparison, the baseline
source, and the sample-size requirement are all hard-coded constants visible
here.  No LLM, no network, no random state.

Threshold documentation (reproducibility contract):
  APV_THRESHOLD_RATIO   = 0.85  — video APV < 85 % of channel median APV
  CTR_THRESHOLD_RATIO   = 0.85  — video CTR < 85 % of channel median CTR
  ER_THRESHOLD_RATIO    = 0.85  — video ER  < 85 % of channel median ER
  VELOCITY_THRESHOLD    = 0.70  — velocity_24h < 70 % of channel median velocity
  MIN_BASELINE_N        = 10    — minimum videos in baseline for rules R01-R05
  NSC_NEGATIVE_THRESHOLD = 0.0  — nsc_1k < 0 triggers R04 regardless of baseline
  VIEWS_THRESHOLD_RATIO = 0.50  — snapshot views < 50 % of channel median views (R07)
  ER_HIGH_OUTLIER_RATIO = 1.50  — snapshot ER > 150 % of channel median ER (R08)

Language contract: descriptions use associative language only.
Causal claims are strictly prohibited.
"""

from __future__ import annotations

from miconte.recommendations._models import RecommendationResult, RecommendationSignal

# ─── Threshold constants ────────────────────────────────────────────────────
APV_THRESHOLD_RATIO: float = 0.85
CTR_THRESHOLD_RATIO: float = 0.85
ER_THRESHOLD_RATIO: float = 0.85
VELOCITY_THRESHOLD: float = 0.70
MIN_BASELINE_N: int = 10
VIEWS_THRESHOLD_RATIO: float = 0.50
ER_HIGH_OUTLIER_RATIO: float = 1.50


# ─── Individual rules ───────────────────────────────────────────────────────

def r06_insufficient_data(signal: RecommendationSignal) -> RecommendationResult:
    """R06 — Baseline insuficiente para análisis comparativo.

    Fires when fewer than MIN_BASELINE_N videos are in the baseline, or when
    no core metrics could be computed for the video.  This rule is evaluated
    before the comparison rules so callers can decide whether to surface R06
    instead of R01-R05.
    """
    no_metrics = signal.apv is None and signal.ctr is None and signal.er is None
    thin_baseline = signal.n_videos_baseline < MIN_BASELINE_N

    triggered = no_metrics or thin_baseline

    evidence: dict[str, object] = {
        "n_videos_baseline": signal.n_videos_baseline,
        "min_required": MIN_BASELINE_N,
        "has_apv": signal.apv is not None,
        "has_ctr": signal.ctr is not None,
        "has_er": signal.er is not None,
    }

    if not triggered:
        return RecommendationResult(
            rule_code="R06_INSUFFICIENT_DATA",
            triggered=False,
            priority="info",
            title="Datos suficientes para análisis",
            description=(
                f"El canal tiene {signal.n_videos_baseline} videos con datos en la línea base, "
                f"superando el mínimo requerido de {MIN_BASELINE_N}."
            ),
            metrics_evidence=evidence,
        )

    reasons: list[str] = []
    if thin_baseline:
        reasons.append(
            f"La línea base del canal contiene {signal.n_videos_baseline} video(s), "
            f"por debajo del mínimo de {MIN_BASELINE_N} requerido para comparaciones "
            "estadísticamente informativas."
        )
    if no_metrics:
        reasons.append(
            "No se pudieron calcular métricas para este video en el período analizado "
            "(sin datos de visualizaciones diarias disponibles)."
        )

    return RecommendationResult(
        rule_code="R06_INSUFFICIENT_DATA",
        triggered=True,
        priority="info",
        title="Datos insuficientes para análisis comparativo",
        description=" ".join(reasons),
        metrics_evidence=evidence,
        limitations=[
            "Este aviso no implica ningún problema de rendimiento; "
            "se requiere más historial de datos para evaluaciones comparativas.",
            f"Umbral mínimo de línea base: {MIN_BASELINE_N} videos con métricas.",
        ],
    )


def r01_apv_below_median(signal: RecommendationSignal) -> RecommendationResult:
    """R01 — Retención media del video por debajo de la mediana del canal.

    Fires when the video's APV is below APV_THRESHOLD_RATIO × channel_apv_median
    and the baseline has at least MIN_BASELINE_N videos.
    """
    code = "R01_APV_BELOW_MEDIAN"

    if (
        signal.n_videos_baseline < MIN_BASELINE_N
        or signal.apv is None
        or signal.channel_apv_median is None
        or signal.channel_apv_median <= 0.0
    ):
        return RecommendationResult(
            rule_code=code, triggered=False, priority="medium",
            title="Retención media: datos insuficientes",
            description="No se pudo evaluar R01 por falta de datos.",
            metrics_evidence={"reason": "insufficient_data"},
        )

    threshold = APV_THRESHOLD_RATIO * signal.channel_apv_median
    triggered = signal.apv < threshold

    evidence = {
        "video_apv": round(signal.apv, 4),
        "channel_apv_median": round(signal.channel_apv_median, 4),
        "threshold_ratio": APV_THRESHOLD_RATIO,
        "threshold_value": round(threshold, 4),
        "n_videos_baseline": signal.n_videos_baseline,
        "period_start": str(signal.period_start),
        "period_end": str(signal.period_end),
    }

    if not triggered:
        return RecommendationResult(
            rule_code=code, triggered=False, priority="medium",
            title="Retención media dentro del rango del canal",
            description=(
                f"La retención promedio del video ({signal.apv:.1%}) se observa en o por encima "
                f"del {APV_THRESHOLD_RATIO:.0%} de la mediana del canal "
                f"({signal.channel_apv_median:.1%})."
            ),
            metrics_evidence=evidence,
        )

    return RecommendationResult(
        rule_code=code,
        triggered=True,
        priority="medium",
        title="Retención media del video por debajo de la mediana del canal",
        description=(
            f"La retención promedio de este video ({signal.apv:.1%}) se observa por debajo del "
            f"{APV_THRESHOLD_RATIO:.0%} de la mediana del canal ({signal.channel_apv_median:.1%}), "
            f"correspondiente a un umbral de {threshold:.1%}. "
            f"Este patrón se identificó en una base de {signal.n_videos_baseline} videos con datos "
            f"en el período analizado. Esta observación es asociativa y no implica causalidad."
        ),
        metrics_evidence=evidence,
        limitations=[
            "APV es un promedio diario ponderado por visualizaciones en el período; "
            "puede subestimar la retención real si el video acumuló vistas fuera del período.",
            "Comparación basada en mediana del canal — no en distribución completa.",
        ],
    )


def r02_ctr_below_median(signal: RecommendationSignal) -> RecommendationResult:
    """R02 — CTR del thumbnail por debajo de la mediana del canal.

    Fires when the video's CTR is below CTR_THRESHOLD_RATIO × channel_ctr_median
    and the baseline has at least MIN_BASELINE_N videos.
    """
    code = "R02_CTR_BELOW_MEDIAN"

    if (
        signal.n_videos_baseline < MIN_BASELINE_N
        or signal.ctr is None
        or signal.channel_ctr_median is None
        or signal.channel_ctr_median <= 0.0
    ):
        return RecommendationResult(
            rule_code=code, triggered=False, priority="medium",
            title="CTR: datos insuficientes",
            description="No se pudo evaluar R02 por falta de datos de CTR o línea base.",
            metrics_evidence={"reason": "insufficient_data"},
        )

    threshold = CTR_THRESHOLD_RATIO * signal.channel_ctr_median
    triggered = signal.ctr < threshold

    evidence = {
        "video_ctr": round(signal.ctr, 4),
        "channel_ctr_median": round(signal.channel_ctr_median, 4),
        "threshold_ratio": CTR_THRESHOLD_RATIO,
        "threshold_value": round(threshold, 4),
        "n_videos_baseline": signal.n_videos_baseline,
        "period_start": str(signal.period_start),
        "period_end": str(signal.period_end),
    }

    if not triggered:
        return RecommendationResult(
            rule_code=code, triggered=False, priority="medium",
            title="CTR del thumbnail dentro del rango del canal",
            description=(
                f"El CTR del video ({signal.ctr:.2%}) se observa en o por encima del "
                f"{CTR_THRESHOLD_RATIO:.0%} de la mediana del canal "
                f"({signal.channel_ctr_median:.2%})."
            ),
            metrics_evidence=evidence,
        )

    return RecommendationResult(
        rule_code=code,
        triggered=True,
        priority="medium",
        title="CTR del thumbnail por debajo de la mediana del canal",
        description=(
            f"El CTR del thumbnail de este video ({signal.ctr:.2%}) se observa por debajo del "
            f"{CTR_THRESHOLD_RATIO:.0%} de la mediana del canal ({signal.channel_ctr_median:.2%}), "
            f"con un umbral de {threshold:.2%}. "
            f"Análisis sobre {signal.n_videos_baseline} videos con datos de impresiones "
            "disponibles. Esta observación es asociativa y no implica causalidad."
        ),
        metrics_evidence=evidence,
        limitations=[
            "CTR promediado sobre los días con datos de impresiones disponibles en el período; "
            "días sin datos de Reporting API quedan excluidos.",
            "El CTR puede variar significativamente según la fuente de tráfico "
            "y la fecha de publicación.",
        ],
    )


def r03_velocity_low_24h(signal: RecommendationSignal) -> RecommendationResult:
    """R03 — Velocidad de primeras 24 h por debajo del 70 % de la mediana del canal.

    Fires when velocity_24h < VELOCITY_THRESHOLD × channel_velocity_median.
    velocity_24h is the normalized value: video_day1_views / median(channel_day1_views).
    A value of 1.0 means the video matched the channel's median first-day velocity.
    """
    code = "R03_VELOCITY_LOW_24H"

    if (
        signal.n_videos_baseline < MIN_BASELINE_N
        or signal.velocity_24h is None
        or signal.channel_velocity_median is None
        or signal.channel_velocity_median <= 0.0
    ):
        return RecommendationResult(
            rule_code=code, triggered=False, priority="high",
            title="Velocidad 24 h: datos insuficientes",
            description="No se pudo evaluar R03 por falta de datos de velocidad o línea base.",
            metrics_evidence={"reason": "insufficient_data"},
        )

    threshold = VELOCITY_THRESHOLD * signal.channel_velocity_median
    triggered = signal.velocity_24h < threshold

    evidence = {
        "video_velocity_24h": round(signal.velocity_24h, 4),
        "channel_velocity_median": round(signal.channel_velocity_median, 4),
        "velocity_threshold_pct": VELOCITY_THRESHOLD,
        "threshold_value": round(threshold, 4),
        "n_videos_baseline": signal.n_videos_baseline,
        "period_start": str(signal.period_start),
        "period_end": str(signal.period_end),
    }

    if not triggered:
        return RecommendationResult(
            rule_code=code, triggered=False, priority="high",
            title="Velocidad inicial dentro del rango del canal",
            description=(
                f"La velocidad normalizada en primeras 24 h ({signal.velocity_24h:.2f}) "
                f"se observa en o por encima del {VELOCITY_THRESHOLD:.0%} de la mediana del canal."
            ),
            metrics_evidence=evidence,
        )

    return RecommendationResult(
        rule_code=code,
        triggered=True,
        priority="high",
        title="Velocidad de primeras 24 h por debajo del umbral del canal",
        description=(
            f"La velocidad normalizada en primeras 24 h de este video ({signal.velocity_24h:.2f}) "
            f"se observa por debajo del {VELOCITY_THRESHOLD:.0%} de la mediana histórica del canal "
            f"({signal.channel_velocity_median:.2f}), con un umbral de {threshold:.2f}. "
            f"Patrón identificado sobre {signal.n_videos_baseline} videos comparados. "
            "Esta observación es asociativa y no implica causalidad sobre el rendimiento futuro."
        ),
        metrics_evidence=evidence,
        limitations=[
            "La velocidad normalizada compara el día de mayor actividad inicial disponible "
            "en los datos diarios; puede no reflejar exactamente las primeras 24 h del lanzamiento "
            "si los datos de ese día no están sincronizados.",
            "El algoritmo de recomendación de YouTube puede amplificar o reducir las diferencias "
            "de velocidad inicial de forma no lineal.",
        ],
    )


def r04_nsc_negative(signal: RecommendationSignal) -> RecommendationResult:
    """R04 — Conversión neta de suscriptores negativa.

    Fires when nsc_1k < 0 (the video is associated with more unsubscribes
    than new subscriptions per 1 000 views, in the analyzed period).
    No baseline required — the condition is absolute.
    """
    code = "R04_NSC_NEGATIVE"

    if signal.nsc_1k is None:
        return RecommendationResult(
            rule_code=code, triggered=False, priority="medium",
            title="NSC_1k: datos insuficientes",
            description="No se pudo evaluar R04: datos de suscriptores no disponibles.",
            metrics_evidence={"reason": "no_subscriber_data"},
        )

    triggered = signal.nsc_1k < 0.0

    evidence = {
        "video_nsc_1k": round(signal.nsc_1k, 4),
        "threshold": 0.0,
        "period_start": str(signal.period_start),
        "period_end": str(signal.period_end),
    }

    if not triggered:
        return RecommendationResult(
            rule_code=code, triggered=False, priority="medium",
            title="Conversión neta de suscriptores positiva o neutra",
            description=(
                f"La conversión neta de suscriptores por 1 000 vistas (NSC_1k = "
                f"{signal.nsc_1k:.2f}) es no negativa en el período analizado."
            ),
            metrics_evidence=evidence,
        )

    return RecommendationResult(
        rule_code=code,
        triggered=True,
        priority="medium",
        title="Conversión neta de suscriptores negativa en el período",
        description=(
            f"En el período analizado, este video se asocia con una conversión neta de "
            f"suscriptores de {signal.nsc_1k:.2f} por cada 1 000 vistas (NSC_1k), lo que "
            f"indica que las bajas superaron las altas en este período. "
            "Esta observación es asociativa y no implica que el video sea la causa directa "
            "de las bajas."
        ),
        metrics_evidence=evidence,
        limitations=[
            "NSC_1k es un indicador a nivel de video; las bajas de suscriptores pueden "
            "originarse en el canal completo y no estar relacionadas con este video específico.",
            "Un valor negativo en un período corto puede deberse a fluctuaciones normales.",
        ],
    )


def r05_er_below_median(signal: RecommendationSignal) -> RecommendationResult:
    """R05 — Tasa de engagement por debajo de la mediana del canal.

    Fires when the video's ER is below ER_THRESHOLD_RATIO × channel_er_median
    and the baseline has at least MIN_BASELINE_N videos.
    """
    code = "R05_ER_BELOW_MEDIAN"

    if (
        signal.n_videos_baseline < MIN_BASELINE_N
        or signal.er is None
        or signal.channel_er_median is None
        or signal.channel_er_median <= 0.0
    ):
        return RecommendationResult(
            rule_code=code, triggered=False, priority="low",
            title="Engagement rate: datos insuficientes",
            description="No se pudo evaluar R05 por falta de datos de engagement o línea base.",
            metrics_evidence={"reason": "insufficient_data"},
        )

    threshold = ER_THRESHOLD_RATIO * signal.channel_er_median
    triggered = signal.er < threshold

    evidence = {
        "video_er": round(signal.er, 4),
        "channel_er_median": round(signal.channel_er_median, 4),
        "threshold_ratio": ER_THRESHOLD_RATIO,
        "threshold_value": round(threshold, 4),
        "n_videos_baseline": signal.n_videos_baseline,
        "period_start": str(signal.period_start),
        "period_end": str(signal.period_end),
    }

    if not triggered:
        return RecommendationResult(
            rule_code=code, triggered=False, priority="low",
            title="Engagement rate dentro del rango del canal",
            description=(
                f"La tasa de engagement del video ({signal.er:.3%}) se observa en o por encima del "
                f"{ER_THRESHOLD_RATIO:.0%} de la mediana del canal "
                f"({signal.channel_er_median:.3%})."
            ),
            metrics_evidence=evidence,
        )

    return RecommendationResult(
        rule_code=code,
        triggered=True,
        priority="low",
        title="Tasa de engagement por debajo de la mediana del canal",
        description=(
            f"La tasa de engagement de este video ({signal.er:.3%}) se observa por debajo del "
            f"{ER_THRESHOLD_RATIO:.0%} de la mediana del canal ({signal.channel_er_median:.3%}), "
            f"con un umbral de {threshold:.3%}. "
            f"Evaluado sobre {signal.n_videos_baseline} videos comparados. "
            "Esta observación es asociativa y no implica causalidad."
        ),
        metrics_evidence=evidence,
        limitations=[
            "Engagement rate incluye likes, comentarios y shares; shares pueden no estar "
            "disponibles en la API pública y se asumen 0 cuando faltan.",
            "La tasa de engagement varía según el nicho y el formato del video.",
        ],
    )


def r07_views_below_channel_median(signal: RecommendationSignal) -> RecommendationResult:
    """R07 — Visualizaciones acumuladas por debajo de la mediana del canal (snapshot).

    Fires when the video's cumulative view count from public snapshots is below
    VIEWS_THRESHOLD_RATIO × channel_view_count_median and the baseline has at
    least MIN_BASELINE_N videos.  This rule is designed for Path A (snapshot-based
    analysis) and only evaluates when snapshot_view_count is populated.
    """
    code = "R07_VIEWS_BELOW_CHANNEL_MEDIAN"

    if (
        signal.snapshot_view_count is None
        or signal.channel_view_count_median is None
        or signal.channel_view_count_median <= 0.0
        or signal.n_videos_baseline < MIN_BASELINE_N
    ):
        return RecommendationResult(
            rule_code=code, triggered=False, priority="medium",
            title="Visualizaciones acumuladas: datos insuficientes",
            description="No se pudo evaluar R07 por falta de datos de snapshots o línea base.",
            metrics_evidence={"reason": "insufficient_data"},
        )

    threshold = VIEWS_THRESHOLD_RATIO * signal.channel_view_count_median
    triggered = signal.snapshot_view_count < threshold

    evidence = {
        "video_view_count": signal.snapshot_view_count,
        "channel_view_count_median": round(signal.channel_view_count_median, 1),
        "threshold_ratio": VIEWS_THRESHOLD_RATIO,
        "threshold_value": round(threshold, 1),
        "n_videos_baseline": signal.n_videos_baseline,
        "data_source": signal.data_source,
    }

    if not triggered:
        return RecommendationResult(
            rule_code=code, triggered=False, priority="medium",
            title="Visualizaciones acumuladas dentro del rango del canal",
            description=(
                f"Las visualizaciones acumuladas del video ({signal.snapshot_view_count:,}) "
                f"se observan en o por encima del {VIEWS_THRESHOLD_RATIO:.0%} de la mediana "
                f"del canal ({signal.channel_view_count_median:,.0f})."
            ),
            metrics_evidence=evidence,
        )

    return RecommendationResult(
        rule_code=code,
        triggered=True,
        priority="medium",
        title="Visualizaciones acumuladas significativamente por debajo de la mediana del canal",
        description=(
            f"Las visualizaciones acumuladas de este video ({signal.snapshot_view_count:,}) "
            f"se observan por debajo del {VIEWS_THRESHOLD_RATIO:.0%} de la mediana del canal "
            f"({signal.channel_view_count_median:,.0f}), correspondiente a un umbral de "
            f"{threshold:,.0f} visualizaciones. "
            f"Evaluado sobre {signal.n_videos_baseline} videos comparados con datos públicos. "
            "Esta observación es asociativa y no implica causalidad; las visualizaciones "
            "acumuladas dependen de la antigüedad del video y factores externos."
        ),
        metrics_evidence=evidence,
        limitations=[
            "Las visualizaciones acumuladas reflejan el total histórico, no un período "
            "fijo; videos más recientes tienen naturalmente menos visualizaciones.",
            "La comparación con la mediana del canal no ajusta por antigüedad ni "
            "por cambios en el algoritmo de recomendación de YouTube.",
        ],
    )


def r08_high_engagement_outlier(signal: RecommendationSignal) -> RecommendationResult:
    """R08 — Tasa de engagement significativamente por encima de la mediana del canal.

    Fires when the video's ER is above ER_HIGH_OUTLIER_RATIO × channel_er_median.
    This is a POSITIVE insight — it surfaces content that resonated with the audience.
    Works with both Path A (snapshot ER) and Path B (daily ER).
    """
    code = "R08_HIGH_ENGAGEMENT_OUTLIER"

    if (
        signal.n_videos_baseline < MIN_BASELINE_N
        or signal.er is None
        or signal.channel_er_median is None
        or signal.channel_er_median <= 0.0
    ):
        return RecommendationResult(
            rule_code=code, triggered=False, priority="info",
            title="Engagement destacado: datos insuficientes",
            description="No se pudo evaluar R08 por falta de datos de engagement o línea base.",
            metrics_evidence={"reason": "insufficient_data"},
        )

    threshold = ER_HIGH_OUTLIER_RATIO * signal.channel_er_median
    triggered = signal.er > threshold

    evidence = {
        "video_er": round(signal.er, 4),
        "channel_er_median": round(signal.channel_er_median, 4),
        "outlier_ratio": ER_HIGH_OUTLIER_RATIO,
        "threshold_value": round(threshold, 4),
        "n_videos_baseline": signal.n_videos_baseline,
        "data_source": signal.data_source,
    }

    if not triggered:
        return RecommendationResult(
            rule_code=code, triggered=False, priority="info",
            title="Engagement dentro del rango habitual del canal",
            description=(
                f"La tasa de engagement del video ({signal.er:.3%}) no supera "
                f"el {ER_HIGH_OUTLIER_RATIO:.0%} de la mediana del canal "
                f"({signal.channel_er_median:.3%})."
            ),
            metrics_evidence=evidence,
        )

    return RecommendationResult(
        rule_code=code,
        triggered=True,
        priority="info",
        title="Engagement significativamente por encima de la mediana del canal",
        description=(
            f"La tasa de engagement de este video ({signal.er:.3%}) se observa por encima del "
            f"{ER_HIGH_OUTLIER_RATIO:.0%} de la mediana del canal "
            f"({signal.channel_er_median:.3%}), "
            f"superando el umbral de {threshold:.3%}. "
            f"Este patrón sugiere que el contenido se asocia con mayor interacción relativa "
            f"dentro del canal. Evaluado sobre {signal.n_videos_baseline} videos comparados. "
            "Esta observación es asociativa y no implica causalidad."
        ),
        metrics_evidence=evidence,
        limitations=[
            "Un engagement rate alto puede estar influenciado por factores externos "
            "(tendencias, colaboraciones, eventos) y no refleja necesariamente la "
            "calidad intrínseca del contenido.",
            "La tasa de engagement varía según el nicho, el formato y la antigüedad del video.",
        ],
    )


# ─── Ordered rule registry ────────────────────────────────────────────────────
# R06 is always evaluated first so callers can detect the no-data case early.
# R07 and R08 are snapshot-aware rules; they silently return triggered=False
# when snapshot fields are not populated (Path B / daily metrics).
_ALL_RULES = [
    r06_insufficient_data,
    r01_apv_below_median,
    r02_ctr_below_median,
    r03_velocity_low_24h,
    r04_nsc_negative,
    r05_er_below_median,
    r07_views_below_channel_median,
    r08_high_engagement_outlier,
]
