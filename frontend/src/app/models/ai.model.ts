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
  mode?: 'creator' | 'technical';
}

export interface AIInterpretResponse {
  channel_id: string;
  ai_status: 'ok' | 'disabled' | 'unavailable' | 'error';
  ai_summary: string | null;
  provider: string;
  degraded: boolean;
  note: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChannelContext {
  title: string;
  period_label: string;
  metrics: MetricInput[];
  recommendations: RecommendationInput[];
}

export interface AIChatRequest {
  message: string;
  history: ChatMessage[];
  channel_context: ChannelContext;
}

export interface AIChatResponse {
  channel_id: string;
  reply: string | null;
  ai_status: 'ok' | 'disabled' | 'unavailable' | 'error';
  degraded: boolean;
  note: string;
}
