import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { SyncRunResponse, SchedulerStatus } from '../models/sync.model';

@Injectable({ providedIn: 'root' })
export class SyncService {
  constructor(private api: ApiService) {}

  triggerSync(channelId: string): Observable<SyncRunResponse> {
    return this.api.post<SyncRunResponse>(`/sync/channels/${channelId}/trigger`);
  }

  getSyncRuns(channelId: string, limit = 20): Observable<SyncRunResponse[]> {
    return this.api.get<SyncRunResponse[]>(
      `/sync/channels/${channelId}/runs`,
      { limit },
    );
  }

  getSchedulerStatus(): Observable<SchedulerStatus> {
    return this.api.get<SchedulerStatus>('/sync/scheduler/status');
  }
}
