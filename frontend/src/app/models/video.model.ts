export interface VideoSnapshot {
  captured_at: string | null;
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
}

export interface VideoSummary {
  video_id: string;
  youtube_video_id: string;
  title: string;
  published_at: string;
  duration_seconds: number;
  snapshot: VideoSnapshot | null;
}

export interface VideoListResponse {
  channel_id: string;
  total_returned: number;
  videos: VideoSummary[];
  compliance_notice: string;
}

export interface VideoMetricPoint {
  metric_key: string;
  value: number | null;
  unit: string;
  limitations: string[];
}

export interface VideoAnalyticsResponse {
  video_id: string;
  channel_id: string;
  title: string;
  duration_seconds: number;
  period_start: string;
  period_end: string;
  n_days_with_data: number;
  metrics: VideoMetricPoint[];
  compliance_notice: string;
}
