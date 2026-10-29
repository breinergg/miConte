import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { ChannelAnalyticsResponse } from '../models/analytics.model';
import { VideoListResponse, VideoAnalyticsResponse } from '../models/video.model';
import {
  RecommendationsListResponse,
  AnalysisRunResponse,
} from '../models/recommendation.model';

@Injectable({ providedIn: 'root' })
export class AnalyticsService {
  constructor(private api: ApiService) {}

  getChannelAnalytics(channelId: string, periodDays = 30): Observable<ChannelAnalyticsResponse> {
    return this.api.get<ChannelAnalyticsResponse>(
      `/channels/${channelId}/analytics`,
      { period_days: periodDays },
    );
  }

  getVideoList(channelId: string, limit = 50, offset = 0): Observable<VideoListResponse> {
    return this.api.get<VideoListResponse>(
      `/channels/${channelId}/videos`,
      { limit, offset },
    );
  }

  getVideoAnalytics(
    videoId: string,
    channelId: string,
    periodDays = 30,
  ): Observable<VideoAnalyticsResponse> {
    return this.api.get<VideoAnalyticsResponse>(
      `/videos/${videoId}/analytics`,
      { channel_id: channelId, period_days: periodDays },
    );
  }

  getRecommendations(channelId: string, limit = 50): Observable<RecommendationsListResponse> {
    return this.api.get<RecommendationsListResponse>(
      `/channels/${channelId}/recommendations`,
      { limit },
    );
  }

  runAnalysis(channelId: string): Observable<AnalysisRunResponse> {
    return this.api.post<AnalysisRunResponse>(`/channels/${channelId}/analysis/run`);
  }
}
