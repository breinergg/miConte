import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { ChannelSummaryResponse, SynchronizableChannel } from '../models/channel.model';

@Injectable({ providedIn: 'root' })
export class ChannelService {
  constructor(private api: ApiService) {}

  listSynchronizableChannels(): Observable<SynchronizableChannel[]> {
    return this.api.get<SynchronizableChannel[]>('/sync/channels');
  }

  getChannelSummary(channelId: string): Observable<ChannelSummaryResponse> {
    return this.api.get<ChannelSummaryResponse>(`/channels/${channelId}/summary`);
  }
}
