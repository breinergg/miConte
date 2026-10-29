import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import {
  AuthorizeResponse,
  ConnectionStatusResponse,
  DisconnectResponse,
} from '../models/oauth.model';

@Injectable({ providedIn: 'root' })
export class OAuthService {
  constructor(private api: ApiService) {}

  getAuthorizationUrl(): Observable<AuthorizeResponse> {
    return this.api.get<AuthorizeResponse>('/oauth/youtube/authorize');
  }

  getConnectionStatus(channelId: string): Observable<ConnectionStatusResponse> {
    return this.api.get<ConnectionStatusResponse>(
      '/oauth/youtube/status',
      { channel_id: channelId },
    );
  }

  disconnect(channelId: string): Observable<DisconnectResponse> {
    return this.api.post<DisconnectResponse>('/oauth/youtube/disconnect', {
      channel_id: channelId,
    });
  }
}
