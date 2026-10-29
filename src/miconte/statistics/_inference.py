"""Statistical inference module for miConte.

Provides normality testing, descriptive statistics, confidence intervals and
two-group comparisons following the methodological rules in
docs/data-dictionary.md §4:

  - N < 10:  descriptive statistics only; no CI, no p-values.
  - N < 50:  Shapiro-Wilk for normality (scipy.stats.shapiro).
  - N >= 50: Lilliefors test (statsmodels), which corrects p-values for the
             case where loc and scale are estimated from the same sample.
             Raw KS against a fitted normal is invalid here: estimated
             parameters make the KS statistic stochastically smaller under H₀,
             inflating p-values and reducing power.
  - Both groups N1, N2 >= 20 required for two-group comparisons.
  - Parametric path (t-test, Cohen's d):  both groups normal.
  - Non-parametric path (Mann-Whitney U, rank-biserial r):  otherwise.
  - CI_95% for mean:  t.interval (parametric, validated normal only).
  - CI_95% non-parametric:  bootstrap percentile via scipy.

No FastAPI, SQLAlchemy, network or LLM dependencies are permitted here.
"""

from __future__ import annotations

import warnings

import numpy as np
from scipy import stats as _sts
from statsmodels.stats.diagnostic import lilliefors as _lilliefors

from miconte.statistics._models import ComparisonResult, NormalityResult, SampleStats

# Minimum sample sizes (docs/data-dictionary.md §4.1)
_MIN_N_INFERENCE = 10    # CI and estimates
_MIN_N_COMPARISON = 20   # two-sample tests
_ALPHA_NORMALITY = 0.05
_N_BOOTSTRAP = 2000


def describe(data: list[float | int] | np.ndarray) -> SampleStats:
    """Compute descriptive statistics for a numeric sample.

    When N < 10 only the observational measures are populated; mean/std are
    still computed but callers must respect the limitations list.
    """
    arr = np.asarray(data, dtype=float)
    valid = arr[~np.isnan(arr)]
    n = int(valid.size)
    limitations: list[str] = []

    if n == 0:
        return SampleStats(
            n=0, mean=None, median=None, std=None,
            q1=None, q3=None, min_val=None, max_val=None,
            limitations=["Muestra vacía; no es posible calcular estadísticas"],
        )

    if n < _MIN_N_INFERENCE:
        limitations.append(
            f"N={n} < {_MIN_N_INFERENCE}; solo estadística descriptiva básica disponible "
            "(sin intervalos de confianza ni pruebas de hipótesis)"
        )

    return SampleStats(
        n=n,
        mean=float(np.mean(valid)),
        median=float(np.median(valid)),
        std=float(np.std(valid, ddof=1)) if n > 1 else None,
        q1=float(np.percentile(valid, 25)) if n >= 4 else None,
        q3=float(np.percentile(valid, 75)) if n >= 4 else None,
        min_val=float(np.min(valid)),
        max_val=float(np.max(valid)),
        limitations=limitations,
    )


def test_normality(data: list[float | int] | np.ndarray) -> NormalityResult:
    """Test whether a sample is consistent with a normal distribution.

    Selects:
      - Shapiro-Wilk (N < 50) — scipy.stats.shapiro.
      - Lilliefors (N >= 50)  — statsmodels, corrected for estimated parameters.
        Raw KS against a normal with estimated loc/scale is invalid: the KS
        p-value assumes known parameters, inflating the null p-value when
        parameters come from the same sample. Lilliefors uses simulated critical
        values that account for this estimation step.

    The result's is_normal flag reflects p > alpha (0.05).  Failing to reject
    the null does not prove normality — it only means the evidence against it
    is weak at this sample size.
    """
    arr = np.asarray(data, dtype=float)
    valid = arr[~np.isnan(arr)]
    n = int(valid.size)
    limitations: list[str] = []

    if n < 3:
        return NormalityResult(
            test_name="none",
            statistic=float("nan"),
            p_value=float("nan"),
            is_normal=False,
            n=n,
            limitations=[f"N={n} insuficiente para test de normalidad (mínimo 3)"],
        )

    if n < 50:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stat, p = _sts.shapiro(valid)
        test_name = "shapiro-wilk"
    else:
        if float(np.std(valid, ddof=1)) == 0.0:
            return NormalityResult(
                test_name="lilliefors-ks",
                statistic=0.0,
                p_value=1.0,
                is_normal=True,
                n=n,
                limitations=["Desviación estándar = 0; distribución degenerada (constante)"],
            )
        stat, p = _lilliefors(valid, dist="norm")
        test_name = "lilliefors-ks"
        limitations.append(
            "Lilliefors (statsmodels 0.15, método 'table', 10 M simulaciones); "
            "valor p acotado en [0.001, 0.990] — valores fuera del rango se devuelven "
            "como cotas"
        )

    if n < _MIN_N_INFERENCE:
        limitations.append(
            f"N={n} muy pequeño; el test de normalidad tiene baja potencia estadística"
        )

    return NormalityResult(
        test_name=test_name,
        statistic=float(stat),
        p_value=float(p),
        is_normal=bool(p > _ALPHA_NORMALITY),
        n=n,
        limitations=limitations,
    )


def compute_ci_95(
    data: list[float | int] | np.ndarray,
) -> tuple[float, float] | None:
    """Compute 95% confidence interval for the mean.

    - If N < 10: returns None (insufficient sample).
    - If the sample is normally distributed: uses Student's t-interval.
    - Otherwise: uses bootstrap percentile CI (n_resamples=2000).

    Returns None when CI cannot be computed reliably.
    """
    arr = np.asarray(data, dtype=float)
    valid = arr[~np.isnan(arr)]
    n = int(valid.size)

    if n < _MIN_N_INFERENCE:
        return None

    norm_result = test_normality(valid)
    if norm_result.is_normal:
        lo, hi = _sts.t.interval(
            0.95,
            df=n - 1,
            loc=float(np.mean(valid)),
            scale=_sts.sem(valid),
        )
        return (float(lo), float(hi))

    # Bootstrap percentile CI
    try:
        res = _sts.bootstrap(
            (valid,),
            np.mean,
            n_resamples=_N_BOOTSTRAP,
            confidence_level=0.95,
            method="percentile",
            random_state=42,
        )
        return (float(res.confidence_interval.low), float(res.confidence_interval.high))
    except Exception:
        return None


def compare_two_groups(
    group_a: list[float | int] | np.ndarray,
    group_b: list[float | int] | np.ndarray,
) -> ComparisonResult:
    """Compare two independent groups and select the appropriate statistical test.

    Selection logic (docs/data-dictionary.md §4.2):
      - Both groups must have N >= 20 for any inferential test.
      - If both pass normality: independent t-test + Cohen's d.
      - Otherwise: Mann-Whitney U + rank-biserial correlation r.

    Effect sizes and their 95% CI (bootstrap) are always reported.
    Results express ASSOCIATIONS ONLY — never causal conclusions.
    """
    a = np.asarray(group_a, dtype=float)
    b = np.asarray(group_b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    na, nb = int(a.size), int(b.size)
    limitations: list[str] = [
        "Los resultados expresan asociaciones observacionales; no implican causalidad"
    ]

    if na < _MIN_N_COMPARISON or nb < _MIN_N_COMPARISON:
        return ComparisonResult(
            test_name="insufficient_sample",
            statistic=float("nan"),
            p_value=float("nan"),
            effect_size=None,
            effect_size_name=None,
            ci_95_effect=None,
            is_normal_a=None,
            is_normal_b=None,
            n_a=na,
            n_b=nb,
            limitations=limitations + [
                f"Muestra insuficiente para comparación: N_a={na}, N_b={nb}; "
                f"se requieren N1, N2 >= {_MIN_N_COMPARISON}"
            ],
        )

    norm_a = test_normality(a)
    norm_b = test_normality(b)
    both_normal = norm_a.is_normal and norm_b.is_normal

    if both_normal:
        stat, p = _sts.ttest_ind(a, b, equal_var=False)
        test_name = "welch-t-test"
        # Cohen's d (pooled std)
        pooled_std = float(
            np.sqrt(((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2))
        )
        effect_size = (
            (float(np.mean(a)) - float(np.mean(b))) / pooled_std if pooled_std > 0 else 0.0
        )
        effect_size_name = "cohen_d"

        def _cohen_d(a_: np.ndarray, b_: np.ndarray) -> np.floating:
            ps = np.sqrt(
                ((len(a_) - 1) * np.var(a_, ddof=1) + (len(b_) - 1) * np.var(b_, ddof=1))
                / (len(a_) + len(b_) - 2)
            )
            return (np.mean(a_) - np.mean(b_)) / ps if ps > 0 else np.float64(0.0)

        try:
            bs = _sts.bootstrap(
                (a, b), _cohen_d, n_resamples=_N_BOOTSTRAP,
                confidence_level=0.95, method="percentile", random_state=42,
            )
            ci_effect: tuple[float, float] | None = (
                float(bs.confidence_interval.low),
                float(bs.confidence_interval.high),
            )
        except Exception:
            ci_effect = None

    else:
        stat, p = _sts.mannwhitneyu(a, b, alternative="two-sided")
        test_name = "mann-whitney-u"
        # Rank-biserial correlation r = 1 - 2U / (na * nb)
        effect_size = float(1.0 - (2.0 * float(stat)) / (na * nb))
        effect_size_name = "rank_biserial_r"

        def _rbc(a_: np.ndarray, b_: np.ndarray) -> np.floating:
            u, _ = _sts.mannwhitneyu(a_, b_, alternative="two-sided")
            return np.float64(1.0 - (2.0 * float(u)) / (len(a_) * len(b_)))

        try:
            bs = _sts.bootstrap(
                (a, b), _rbc, n_resamples=_N_BOOTSTRAP,
                confidence_level=0.95, method="percentile", random_state=42,
            )
            ci_effect = (
                float(bs.confidence_interval.low),
                float(bs.confidence_interval.high),
            )
        except Exception:
            ci_effect = None

        if not norm_a.is_normal or not norm_b.is_normal:
            limitations.append(
                "Una o ambas distribuciones no son normales; se usa Mann-Whitney U "
                "(no paramétrico)"
            )

    return ComparisonResult(
        test_name=test_name,
        statistic=float(stat),
        p_value=float(p),
        effect_size=effect_size,
        effect_size_name=effect_size_name,
        ci_95_effect=ci_effect,
        is_normal_a=norm_a.is_normal,
        is_normal_b=norm_b.is_normal,
        n_a=na,
        n_b=nb,
        limitations=limitations,
    )
