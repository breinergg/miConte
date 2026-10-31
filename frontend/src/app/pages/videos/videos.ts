import { Component, signal, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { ChannelService } from '../../services/channel.service';
import { AnalyticsService } from '../../services/analytics.service';
import { VideoSummary } from '../../models/video.model';
import { ApiError } from '../../services/api.service';
import { LoadingSpinnerComponent } from '../../components/loading-spinner/loading-spinner';
import { EmptyStateComponent } from '../../components/empty-state/empty-state';
import { ComplianceNoticeComponent } from '../../components/compliance-notice/compliance-notice';
import { DecimalPipe, DatePipe } from '@angular/common';

@Component({
  selector: 'app-videos',
  standalone: true,
  imports: [LoadingSpinnerComponent, EmptyStateComponent, ComplianceNoticeComponent, DecimalPipe, DatePipe],
  template: `
    @switch (state()) {
      @case ('loading') {
        <app-loading />
      }
      @case ('compliance-blocked') {
        <app-compliance-notice [message]="complianceMessage()" />
      }
      @case ('no-channel') {
        <app-empty-state
          icon="link"
          title="Sin canal conectado"
          description="Conecta tu canal de YouTube para ver los videos." />
      }
      @case ('error') {
        <div class="error-banner">
          <p>{{ errorMessage() }}</p>
        </div>
      }
      @case ('loaded') {
        <div class="page-header">
          <h2>Videos del canal</h2>
          <span class="count-badge">{{ videos().length }} videos</span>
        </div>

        @if (videos().length === 0) {
          <app-empty-state
            icon="video"
            title="Sin videos"
            description="No se encontraron videos para este canal." />
        } @else {
          <div class="video-list">
            @for (video of videos(); track video.video_id) {
              <div class="video-row" (click)="openDetail(video)">
                <div class="video-info">
                  <span class="video-title">{{ video.title }}</span>
                  <span class="video-meta">
                    {{ video.published_at | date:'mediumDate' }}
                    · {{ formatDuration(video.duration_seconds) }}
                  </span>
                </div>
                @if (video.snapshot) {
                  <div class="video-stats">
                    <span class="stat-item">
                      <span class="stat-value">{{ video.snapshot.view_count | number }}</span>
                      <span class="stat-label">vistas</span>
                    </span>
                    <span class="stat-item">
                      <span class="stat-value">{{ video.snapshot.like_count | number }}</span>
                      <span class="stat-label">likes</span>
                    </span>
                  </div>
                } @else {
                  <div class="video-stats">
                    <span class="no-data">Sin snapshot</span>
                  </div>
                }
              </div>
            }
          </div>

          @if (hasMore()) {
            <button class="load-more-btn" (click)="loadMore()" [disabled]="loadingMore()">
              {{ loadingMore() ? 'Cargando...' : 'Cargar más' }}
            </button>
          }
        }
      }
    }
  `,
  styles: [`
    .page-header {
      display: flex;
      align-items: baseline;
      gap: 0.75rem;
      margin-bottom: 1.25rem;
      flex-wrap: wrap;
    }
    .page-header h2 {
      margin: 0;
      font-size: 1.375rem;
      font-weight: 700;
      color: var(--ink);
    }
    .count-badge {
      font-size: 0.75rem;
      font-weight: 500;
      color: var(--ink-faint);
      background: var(--card);
      padding: 0.2rem 0.625rem;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
    }

    .video-list {
      display: flex;
      flex-direction: column;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow-sm);
      overflow: hidden;
    }
    .video-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.875rem 1.25rem;
      cursor: pointer;
      transition: background 0.15s;
      gap: 1rem;
    }
    .video-row:not(:last-child) {
      border-bottom: 1px solid var(--border);
    }
    .video-row:hover { background: var(--accent-subtle); }
    .video-info { min-width: 0; }
    .video-title {
      display: block;
      font-size: 0.875rem;
      font-weight: 500;
      color: var(--ink);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .video-meta {
      font-size: 0.75rem;
      color: var(--ink-faint);
    }
    .video-stats {
      display: flex;
      gap: 1.25rem;
      flex-shrink: 0;
    }
    .stat-item {
      display: flex;
      align-items: baseline;
      gap: 0.25rem;
    }
    .stat-value {
      font-size: 0.875rem;
      font-weight: 600;
      color: var(--ink);
    }
    .stat-label {
      font-size: 0.6875rem;
      color: var(--ink-faint);
    }
    .no-data { color: var(--ink-faint); font-style: italic; font-size: 0.8125rem; }

    .load-more-btn {
      display: block;
      margin: 1.25rem auto 0;
      padding: 0.5rem 1.5rem;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--ink-soft);
      cursor: pointer;
      font-size: 0.875rem;
      font-weight: 500;
      transition: background 0.15s, border-color 0.15s;
    }
    .load-more-btn:hover {
      background: var(--accent-subtle);
      border-color: var(--accent);
      color: var(--accent);
    }
    .load-more-btn:disabled { opacity: 0.5; cursor: default; }

    .error-banner {
      padding: 1rem 1.25rem;
      background: var(--error-bg);
      border: 1px solid var(--error-border);
      border-radius: var(--radius);
    }
    .error-banner p { margin: 0; font-size: 0.875rem; color: var(--ink); }
  `],
})
export class VideosComponent implements OnInit {
  state = signal<'loading' | 'loaded' | 'no-channel' | 'compliance-blocked' | 'error'>('loading');
  videos = signal<VideoSummary[]>([]);
  hasMore = signal(false);
  loadingMore = signal(false);
  errorMessage = signal('');
  complianceMessage = signal('');

  private channelId = '';
  private offset = 0;
  private readonly pageSize = 50;

  constructor(
    private channelService: ChannelService,
    private analyticsService: AnalyticsService,
    private router: Router,
  ) {}

  ngOnInit(): void {
    this.channelService.listSynchronizableChannels().subscribe({
      next: (channels) => {
        if (channels.length === 0) {
          this.state.set('no-channel');
          return;
        }
        this.channelId = channels[0].channel_id;
        this.loadVideos();
      },
      error: (err: ApiError) => {
        this.errorMessage.set(err.message);
        this.state.set('error');
      },
    });
  }

  loadMore(): void {
    this.loadingMore.set(true);
    this.analyticsService.getVideoList(this.channelId, this.pageSize, this.offset).subscribe({
      next: (data) => {
        this.videos.update((prev) => [...prev, ...data.videos]);
        this.offset += data.videos.length;
        this.hasMore.set(data.total_returned === this.pageSize);
        this.loadingMore.set(false);
      },
      error: () => this.loadingMore.set(false),
    });
  }

  openDetail(video: VideoSummary): void {
    this.router.navigate(['/videos', video.video_id], {
      queryParams: { channel_id: this.channelId },
    });
  }

  formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  private loadVideos(): void {
    this.analyticsService.getVideoList(this.channelId, this.pageSize, 0).subscribe({
      next: (data) => {
        this.videos.set(data.videos);
        this.offset = data.videos.length;
        this.hasMore.set(data.total_returned === this.pageSize);
        this.state.set('loaded');
      },
      error: (err: ApiError) => {
        if (err.isComplianceBlock) {
          this.complianceMessage.set(err.message);
          this.state.set('compliance-blocked');
        } else {
          this.errorMessage.set(err.message);
          this.state.set('error');
        }
      },
    });
  }
}
