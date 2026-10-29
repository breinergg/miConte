export interface SyncStageResult {
  stage: string;
  status: string;
  records_processed: number;
  error_message: string | null;
}

export interface SyncRunResponse {
  sync_run_id: string;
  channel_id: string;
  sync_type: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  records_processed: number;
  stages: SyncStageResult[];
  error_message: string | null;
  is_recoverable: boolean;
}

export interface SchedulerStatus {
  is_running: boolean;
  interval_hours: number;
  last_run_at: string | null;
  next_run_at: string | null;
}
