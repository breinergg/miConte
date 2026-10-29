export interface Recommendation {
  recommendation_id: string;
  rule_code: string;
  title: string;
  description: string;
  priority: 'high' | 'medium' | 'low' | 'info';
  metrics_evidence: Record<string, unknown>;
  created_at: string;
  video_id: string | null;
}

export interface RecommendationsListResponse {
  channel_id: string;
  total_returned: number;
  recommendations: Recommendation[];
  compliance_notice: string;
}

export interface AnalysisRunResponse {
  analysis_run_id: string;
  n_videos_analyzed: number;
  n_rules_triggered: number;
  recommendations: Recommendation[];
  compliance_notice: string;
}
