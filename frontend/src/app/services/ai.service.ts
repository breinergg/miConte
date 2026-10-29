import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { AIInterpretRequest, AIInterpretResponse } from '../models/ai.model';

@Injectable({ providedIn: 'root' })
export class AiService {
  constructor(private api: ApiService) {}

  interpretChannelAnalytics(
    channelId: string,
    body: AIInterpretRequest,
  ): Observable<AIInterpretResponse> {
    return this.api.post<AIInterpretResponse>(
      `/channels/${channelId}/ai/interpret`,
      body,
    );
  }
}
