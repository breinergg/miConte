---
name: miconte-statistical-validation
description: Guidelines and procedures for documenting formulas, validating sample sizes, handling missing or censored data, and preventing unjustified causal claims in miConte statistical and analytics services. Use when writing, modifying, or reviewing statistical computations, metrics, aggregations, or analytics algorithms.
---

# miConte Statistical Validation Guidelines

This skill governs the development, documentation, and mathematical rigor of all analytics, metrics, and statistical routines in **miConte**.

miConte is a content intelligence platform analyzing YouTube statistics. Calculations must be transparent, numerically stable, statistically sound, and completely deterministic, implemented using Python standard libraries and `pandas`, `NumPy`, `SciPy`, and `statsmodels` without relying on LLMs or MCPs.

---

## 1. Metric Definitions & Formula Documentation

Every metric, aggregation, and statistical function in `services/analytics/` or `services/statistics/` must include a comprehensive docstring documenting:
1. **Mathematical Definition**: The explicit formula in LaTeX notation.
2. **Domain & Boundaries**: Input constraints and valid output range (e.g., $[0, 1]$ for rates, $[0, \infty)$ for counts).
3. **Edge Case Handling**: Zero division, empty series, negative duration, and single-element cohorts.
4. **Implementation Reference**: Citations to YouTube Analytics API documentation or standard statistical literature where applicable.

### Standard YouTube Metric Formulas in miConte

* **Click-Through Rate (CTR)**:
  $$\text{CTR} = \begin{cases} \frac{\text{clicks}}{\text{impressions}} & \text{if impressions} > 0 \\ 0.0 & \text{if impressions} = 0 \end{cases}$$
  *Never allow division by zero or return `NaN` when impressions are zero.*

* **Average Percentage Viewed (APV / Retention)**:
  $$\text{APV} = \begin{cases} \frac{\text{Average Watch Time}}{\text{Video Duration}} & \text{if Video Duration} > 0 \\ 0.0 & \text{if Video Duration} \le 0 \end{cases}$$

* **Engagement Rate (ER)**:
  $$\text{ER} = \frac{\text{likes} + \text{comments} + \text{shares}}{\max(\text{views}, 1)}$$

* **Normalized Velocity ($V_{24h}$)**:
  $$V_{24h} = \frac{\text{Views at 24 hours}}{\text{Channel Median 24h Views Baseline}}$$

---

## 2. Sample Size & Distribution Validation

Statistical inference (comparing video cohorts, testing thumbnail performance, seasonal adjustments) requires rigorous sample validation before drawing conclusions:

### Sample Size Thresholds
- **Minimum Observations**:
  - Point estimates (mean, median): Minimum $N \ge 10$ videos per cohort.
  - Two-sample hypothesis tests (t-test, Mann-Whitney U): Minimum $N_1, N_2 \ge 20$.
  - Regression / Time Series (statsmodels): Minimum $N \ge 30$ observations (or 2 complete seasonal cycles).
- **Small Sample Caveat**: When $N < 10$, report raw numbers and percentiles only; do **not** run p-value hypothesis tests.

### Normality & Test Selection Protocol
1. **Distribution Check**: Run normality tests (`scipy.stats.shapiro` for $N < 50$ or `scipy.stats.kstest` for $N \ge 50$). YouTube metrics (views, watch time) are almost always heavily right-skewed (log-normal or Pareto-distributed).
2. **Parametric vs. Non-Parametric**:
   - If distributions are non-normal (typical for YouTube): Prefer non-parametric tests (`scipy.stats.mannwhitneyu`, `scipy.stats.wilcoxon`) or report median and Interquartile Range (IQR).
   - If log-transformed data approximates normality: Parametric tests may be used on $\log(X + 1)$ with explicit documentation in the response schema.
3. **Confidence Intervals**: Always report $95\%$ Confidence Intervals alongside point estimates using bootstrap (`scipy.stats.bootstrap`) or standard error:
   $$\text{CI}_{95\%} = \hat{\mu} \pm 1.96 \cdot \frac{s}{\sqrt{N}}$$

---

## 3. Missing Data & Censoring Treatment

YouTube analytics APIs frequently return incomplete time windows, delayed reporting (e.g., revenue or demographic metrics take 48-72h to settle), or missing metrics for low-volume videos.

### Rules for Missing Data
1. **No Silent Zero-Filling**: Never replace `NaN` / `None` with `0` unless a zero value is mathematically meaningful (e.g., 0 likes on an active video). A missing retention curve is `Missing`, not 0% retention.
2. **Distinguish MCAR vs. MAR**:
   - *Missing Completely at Random*: Random API ingestion gaps. Handled via interpolation or complete case analysis.
   - *Systematic Missingness*: Low-impression videos where YouTube suppresses demographic data for privacy. Preserve as `data_suppressed: true` in schemas.
3. **Right-Censored Data Handling**:
   - For freshly published videos ($< 72\text{ hours}$ old), total lifetime views is a right-censored variable.
   - Never compare raw views of a 2-day-old video against a 30-day-old video without normalizing by age window (e.g., $V_{24h}$ or $V_{48h}$).

---

## 4. Preventing Unjustified Causal Claims

A core requirement of miConte is preventing false or exaggerated causal conclusions in analytical insights, UI charts, or reports.

### Correlation vs. Causation Rules
* **No Causal Assertions Without Controlled Design**:
  Observational YouTube metrics cannot establish causality. A correlation between video length and retention does **not** prove that changing length causes retention shifts.
* **Identify Confounding Factors**:
  Always consider and document confounders:
  - Channel growth / subscriber baseline expansion over time.
  - Publishing schedule (weekday vs. weekend seasonality).
  - External traffic spikes (Reddit, X, external embeds).
  - YouTube recommendation algorithm alterations.

### Prescribed Language for Analytics Insights
| Forbidden Causal Phrasing | Permitted Descriptive Phrasing |
| :--- | :--- |
| "Adding emojis to titles **caused** a 25% increase in views." | "Videos with emojis in titles were **associated with** a 25% higher median view count in this sample ($p = 0.04$)." |
| "This thumbnail change **drove** the drop in CTR." | "A lower CTR was **observed following** the thumbnail change ($3.2\%$ vs. prior $4.8\%$, baseline CI $[4.1\%, 5.5\%]$)." |
| "Publishing at 5 PM **is the reason** for peak engagement." | "Peak historical engagement **coincides with** the 5 PM publishing window." |

---

## 5. Implementation & Verification Checklist

When implementing any statistical routine in miConte:
- [ ] Formula is mathematically documented with a docstring and unit test verifying known analytical inputs/outputs.
- [ ] Division by zero, empty collections, and single-value inputs are tested and handled safely.
- [ ] Output metrics are bounded to their mathematically valid range.
- [ ] Normality is checked before applying parametric hypothesis tests; non-parametric alternatives used when appropriate.
- [ ] Missing values are explicitly represented (`None` / `np.nan` / custom schema flag), never silently zeroed.
- [ ] Descriptive rather than causal language is used across schemas, response models, and UI labels.
- [ ] Python unit tests verify calculation reproducibility without network access or LLM inference.
