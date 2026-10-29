export interface MetricInput {
  label: string;
  value: number | null;
  unit?: string | null;
  n?: number | null;
  ci_95?: [number, number] | null;
  limitations: string[];
}

export interface RecommendationInput {
  rule_code: string;
  priority: string;
  description: string;
  metrics_evidence: Record<string, unknown>;
}

export interface AIInterpretRequest {
  channel_title: string;
  period_label: string;
  metrics: MetricInput[];
  recommendations: RecommendationInput[];
  // real_data is absent: the server derives data origin from its own settings.
}

export interface AIInterpretResponse {
  channel_id: string;
  ai_status: 'ok' | 'disabled' | 'unavailable' | 'error';
  ai_summary: string | null;
  provider: string;
  degraded: boolean;
  note: string;
}
