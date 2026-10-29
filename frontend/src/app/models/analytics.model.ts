export interface MetricStats {
  n: number;
  mean: number | null;
  median: number | null;
  std: number | null;
  min_val: number | null;
  max_val: number | null;
  ci_95: [number, number] | null;
  limitations: string[];
}

export interface ChannelAnalyticsResponse {
  channel_id: string;
  period_start: string;
  period_end: string;
  n_days_with_data: number;
  views_stats: MetricStats;
  apv_stats: MetricStats;
  er_stats: MetricStats;
  nsc_1k_stats: MetricStats;
  compliance_notice: string;
}
