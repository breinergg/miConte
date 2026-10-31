import { Component, signal, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { AnalyticsService } from '../../services/analytics.service';
import { VideoAnalyticsResponse, VideoMetricPoint } from '../../models/video.model';
import { ApiError } from '../../services/api.service';
import { LoadingSpinnerComponent } from '../../components/loading-spinner/loading-spinner';
import { EmptyStateComponent } from '../../components/empty-state/empty-state';
import { ComplianceNoticeComponent } from '../../components/compliance-notice/compliance-notice';

const METRIC_LABELS: Record<string, string> = {
  average_percentage_viewed: 'Porcentaje medio visto (APV)',
  click_through_rate: 'Tasa de clics (CTR)',
  engagement_rate: 'Tasa de interacción (ER)',
  net_subscriber_conversion_1k: 'Conversión neta suscr. / 1k vistas',
  velocity_24h: 'Velocidad normalizada 24h',
  no_data: 'Sin métricas disponibles',
};

@Component({
  selector: 'app-video-detail',
  standalone: true,
  imports: [LoadingSpinnerComponent, EmptyStateComponent, ComplianceNoticeComponent],
  template: `
    @switch (state()) {
      @case ('loading') {
        <app-loading />
      }
      @case ('compliance-blocked') {
        <app-compliance-notice [message]="complianceMessage()" />
      }
      @case ('error') {
        <div class="error-banner"><p>{{ errorMessage() }}</p></div>
      }
      @case ('loaded') {
        @if (data()) {
          <div class="detail-header">
            <h2>{{ data()!.title }}</h2>
            <span class="detail-meta">
              {{ formatDuration(data()!.duration_seconds) }}
              · {{ data()!.period_start }} — {{ data()!.period_end }}
              · {{ data()!.n_days_with_data }} días con datos
            </span>
          </div>

          @if (data()!.n_days_with_data === 0) {
            <app-empty-state
              icon="chart"
              title="Sin datos analíticos"
              description="No hay métricas diarias disponibles para este video en el período solicitado." />
          } @else {
            <div class="metrics-list">
              @for (metric of data()!.metrics; track metric.metric_key) {
                <div class="metric-row">
                  <div class="metric-header">
                    <span class="metric-name">{{ metricLabel(metric.metric_key) }}</span>
                    <span class="metric-unit">{{ metric.unit }}</span>
                  </div>
                  <div class="metric-value">
                    @if (metric.value !== null) {
                      {{ formatValue(metric.value) }}
                    } @else {
                      <span class="na">No disponible</span>
                    }
                  </div>
                  @if (metric.limitations.length > 0) {
                    <div class="metric-limitations">
                      @for (lim of metric.limitations; track lim) {
                        <span class="lim-tag">{{ lim }}</span>
                      }
                    </div>
                  }
                </div>
              }
            </div>
          }
        }
      }
    }
  `,
  styles: [`
    .detail-header { margin-bottom: 1.5rem; }
    .detail-header h2 {
      margin: 0 0 0.375rem;
      font-size: 1.375rem;
      font-weight: 700;
      color: var(--ink);
      letter-spacing: -0.01em;
    }
    .detail-meta {
      font-size: 0.8125rem;
      color: var(--ink-faint);
    }

    .metrics-list {
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }
    .metric-row {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.25rem 1.5rem;
      box-shadow: var(--shadow-sm);
    }
    .metric-header {
      display: flex;
      gap: 0.5rem;
      align-items: baseline;
      margin-bottom: 0.375rem;
    }
    .metric-name {
      font-size: 0.875rem;
      font-weight: 500;
      color: var(--ink-soft);
    }
    .metric-unit {
      font-size: 0.75rem;
      color: var(--ink-faint);
    }
    .metric-value {
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--ink);
      letter-spacing: -0.02em;
    }
    .na {
      font-size: 0.875rem;
      font-weight: 400;
      color: var(--ink-faint);
      font-style: italic;
    }
    .metric-limitations { margin-top: 0.625rem; }
    .lim-tag {
      display: inline-block;
      font-size: 0.6875rem;
      background: var(--warn-bg);
      color: var(--warn-ink);
      padding: 0.125rem 0.5rem;
      border-radius: var(--radius-sm);
      margin: 0.125rem 0.25rem 0.125rem 0;
    }

    .error-banner {
      padding: 1rem 1.25rem;
      background: var(--error-bg);
      border: 1px solid var(--error-border);
      border-radius: var(--radius);
    }
    .error-banner p { margin: 0; font-size: 0.875rem; color: var(--ink); }
  `],
})
export class VideoDetailComponent implements OnInit {
  state = signal<'loading' | 'loaded' | 'compliance-blocked' | 'error'>('loading');
  data = signal<VideoAnalyticsResponse | null>(null);
  errorMessage = signal('');
  complianceMessage = signal('');

  constructor(
    private route: ActivatedRoute,
    private analyticsService: AnalyticsService,
  ) {}

  ngOnInit(): void {
    const videoId = this.route.snapshot.paramMap.get('videoId')!;
    const channelId = this.route.snapshot.queryParamMap.get('channel_id') ?? '';
    if (!channelId) {
      this.errorMessage.set('Falta el parámetro channel_id');
      this.state.set('error');
      return;
    }
    this.analyticsService.getVideoAnalytics(videoId, channelId).subscribe({
      next: (res) => {
        this.data.set(res);
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

  metricLabel(key: string): string {
    return METRIC_LABELS[key] ?? key;
  }

  formatValue(val: number): string {
    if (Math.abs(val) >= 1000) return val.toLocaleString('es-CO', { maximumFractionDigits: 0 });
    return val.toLocaleString('es-CO', { maximumFractionDigits: 4 });
  }

  formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  }
}
