export interface ChannelSnapshot {
  captured_at: string | null;
  view_count: number | null;
  subscriber_count: number | null;
  video_count: number | null;
}

export interface ChannelSummaryResponse {
  channel_id: string;
  youtube_channel_id: string;
  title: string;
  description: string | null;
  custom_url: string | null;
  thumbnail_url: string | null;
  snapshot: ChannelSnapshot | null;
  compliance_notice: string;
}

export interface SynchronizableChannel {
  channel_id: string;
  youtube_channel_id: string;
  title: string;
  is_oauth_connected: boolean;
  last_sync_at: string | null;
  last_sync_status: string | null;
  uploads_playlist_id: string;
}
