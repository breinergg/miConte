import { Component, signal, OnInit } from '@angular/core';
import { ChannelService } from '../../services/channel.service';
import { AnalyticsService } from '../../services/analytics.service';
import { AiService } from '../../services/ai.service';
import { ChannelSummaryResponse, SynchronizableChannel } from '../../models/channel.model';
import { ChannelAnalyticsResponse } from '../../models/analytics.model';
import { AIInterpretResponse } from '../../models/ai.model';
import { ApiError } from '../../services/api.service';
import { LoadingSpinnerComponent } from '../../components/loading-spinner/loading-spinner';
import { EmptyStateComponent } from '../../components/empty-state/empty-state';
import { ComplianceNoticeComponent } from '../../components/compliance-notice/compliance-notice';
import { MetricCardComponent } from '../../components/metric-card/metric-card';
import { DecimalPipe } from '@angular/common';

type PageState = 'loading' | 'loaded' | 'no-channel' | 'compliance-blocked' | 'error';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    LoadingSpinnerComponent,
    EmptyStateComponent,
    ComplianceNoticeComponent,
    MetricCardComponent,
    DecimalPipe,
  ],
  template: `
    @switch (state()) {
      @case ('loading') {
        <app-loading />
      }
      @case ('no-channel') {
        <app-empty-state
          icon="link"
          title="Sin canal conectado"
          description="Conecta tu canal de YouTube desde la sección de Conexión para comenzar." />
      }
      @case ('compliance-blocked') {
        <app-compliance-notice [message]="complianceMessage()" />
      }
      @case ('error') {
        <div class="error-banner">
          <p>{{ errorMessage() }}</p>
        </div>
      }
      @case ('loaded') {
        @if (summary()) {
          <section class="dashboard-header">
            <div class="channel-info">
              @if (summary()!.thumbnail_url) {
                <img
                  class="channel-thumb"
                  [src]="summary()!.thumbnail_url"
                  [alt]="summary()!.title"
                  (error)="onThumbError($event)" />
              } @else {
                <div class="channel-thumb channel-thumb-fallback" [attr.aria-label]="summary()!.title">
                  {{ summary()!.title.charAt(0).toUpperCase() }}
                </div>
              }
              <div>
                <h2>{{ summary()!.title }}</h2>
                @if (summary()!.custom_url) {
                  <span class="channel-url">{{ summary()!.custom_url }}</span>
                }
              </div>
            </div>
            @if (summary()!.snapshot) {
              <div class="snapshot-cards">
                <div class="snap-card">
                  <span class="snap-label">Visualizaciones</span>
                  <span class="snap-value">{{ summary()!.snapshot!.view_count | number }}</span>
                </div>
                <div class="snap-card">
                  <span class="snap-label">Suscriptores</span>
                  <span class="snap-value">{{ summary()!.snapshot!.subscriber_count | number }}</span>
                </div>
                <div class="snap-card">
                  <span class="snap-label">Videos</span>
                  <span class="snap-value">{{ summary()!.snapshot!.video_count | number }}</span>
                </div>
              </div>
            }
          </section>
        }

        @if (analytics()) {
          <section class="analytics-section">
            <div class="section-header">
              <h3>Analítica del canal</h3>
              <span class="period-badge">
                {{ analytics()!.period_start }} — {{ analytics()!.period_end }}
                · {{ analytics()!.n_days_with_data }} días con datos
              </span>
            </div>
            <div class="metrics-grid">
              <app-metric-card label="Visualizaciones diarias" [stats]="analytics()!.views_stats" />
              <app-metric-card label="Porcentaje medio visto (APV)" [stats]="analytics()!.apv_stats" />
              <app-metric-card label="Tasa de interacción (ER)" [stats]="analytics()!.er_stats" />
              <app-metric-card label="Conversión neta suscr. / 1k vistas" [stats]="analytics()!.nsc_1k_stats" />
            </div>
          </section>

          @if (!aiLoading() && aiResult()) {
            <section class="ai-section">
              <div class="ai-header">
                <div class="ai-badge">
                  <svg class="ai-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 0 0-2.455 2.456Z"/>
                  </svg>
                  Interpretación IA
                </div>
                @if (aiResult()!.degraded) {
                  <span class="ai-status-chip">{{ aiResult()!.note }}</span>
                }
              </div>
              @if (aiResult()!.ai_summary) {
                <p class="ai-summary">{{ aiResult()!.ai_summary }}</p>
                <p class="ai-disclaimer">
                  Generado por {{ aiResult()!.provider }} a partir de resultados calculados
                  por el motor estadístico de miConte. No es una medición verificada.
                </p>
              }
            </section>
          }
        }
      }
    }
  `,
  styles: [`
    .dashboard-header { margin-bottom: 2rem; }
    .channel-info {
      display: flex;
      align-items: center;
      gap: 1rem;
      margin-bottom: 1.5rem;
    }
    .channel-thumb {
      width: 56px; height: 56px;
      border-radius: 50%;
      object-fit: cover;
      box-shadow: var(--shadow-sm);
    }
    .channel-thumb-fallback {
      width: 56px; height: 56px;
      border-radius: 50%;
      background: var(--accent-subtle);
      color: var(--accent);
      font-size: 1.25rem;
      font-weight: 700;
      display: none;
      align-items: center;
      justify-content: center;
      box-shadow: var(--shadow-sm);
      flex-shrink: 0;
    }
    .channel-info h2 {
      margin: 0;
      font-size: 1.375rem;
      font-weight: 700;
      color: var(--ink);
      letter-spacing: -0.01em;
    }
    .channel-url {
      font-size: 0.8125rem;
      color: var(--ink-faint);
    }

    .snapshot-cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 0.75rem;
    }
    .snap-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.25rem 1.5rem;
      box-shadow: var(--shadow-sm);
    }
    .snap-label {
      display: block;
      font-size: 0.8125rem;
      font-weight: 500;
      color: var(--ink-soft);
      margin-bottom: 0.375rem;
    }
    .snap-value {
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--ink);
      letter-spacing: -0.02em;
    }

    .section-header {
      display: flex;
      align-items: baseline;
      gap: 1rem;
      flex-wrap: wrap;
      margin-bottom: 1rem;
    }
    .section-header h3 {
      margin: 0;
      font-size: 1.125rem;
      font-weight: 600;
      color: var(--ink);
    }
    .period-badge {
      font-size: 0.75rem;
      color: var(--ink-faint);
      background: var(--card);
      padding: 0.25rem 0.75rem;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
    }

    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 0.75rem;
    }

    .error-banner {
      padding: 1rem 1.25rem;
      background: var(--error-bg);
      border: 1px solid var(--error-border);
      border-radius: var(--radius);
      color: var(--ink);
    }
    .error-banner p { margin: 0; font-size: 0.875rem; }

    .ai-section {
      margin-top: 2rem;
      padding: 1.5rem;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow-sm);
    }
    .ai-header {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 0.75rem;
      flex-wrap: wrap;
    }
    .ai-badge {
      display: flex;
      align-items: center;
      gap: 0.375rem;
      font-size: 0.875rem;
      font-weight: 600;
      color: var(--accent);
    }
    .ai-icon { width: 18px; height: 18px; }
    .ai-status-chip {
      font-size: 0.75rem;
      padding: 0.2rem 0.625rem;
      border-radius: var(--radius-sm);
      background: var(--warn-bg);
      border: 1px solid var(--warn-border);
      color: var(--warn-ink);
    }
    .ai-summary {
      margin: 0 0 0.75rem;
      font-size: 0.9375rem;
      line-height: 1.65;
      color: var(--ink);
    }
    .ai-disclaimer {
      margin: 0;
      font-size: 0.75rem;
      color: var(--ink-faint);
      font-style: italic;
    }
  `],
})
export class DashboardComponent implements OnInit {
  state = signal<PageState>('loading');
  summary = signal<ChannelSummaryResponse | null>(null);
  analytics = signal<ChannelAnalyticsResponse | null>(null);
  aiResult = signal<AIInterpretResponse | null>(null);
  aiLoading = signal(false);
  errorMessage = signal('');
  complianceMessage = signal('');

  private channelId = signal<string | null>(null);

  constructor(
    private channelService: ChannelService,
    private analyticsService: AnalyticsService,
    private aiService: AiService,
  ) {}

  ngOnInit(): void {
    this.channelService.listSynchronizableChannels().subscribe({
      next: (channels) => {
        if (channels.length === 0) {
          this.state.set('no-channel');
          return;
        }
        this.channelId.set(channels[0].channel_id);
        this.loadSummary(channels[0].channel_id);
      },
      error: (err: ApiError) => {
        this.errorMessage.set(err.message);
        this.state.set('error');
      },
    });
  }

  onThumbError(event: Event): void {
    const img = event.target as HTMLImageElement;
    img.style.display = 'none';
    const fallback = img.parentElement?.querySelector('.channel-thumb-fallback');
    if (fallback) (fallback as HTMLElement).style.display = 'flex';
  }

  private loadSummary(channelId: string): void {
    this.channelService.getChannelSummary(channelId).subscribe({
      next: (data) => {
        this.summary.set(data);
        this.state.set('loaded');
        this.loadAnalytics(channelId);
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

  private loadAnalytics(channelId: string): void {
    this.analyticsService.getChannelAnalytics(channelId).subscribe({
      next: (data) => {
        this.analytics.set(data);
        this.loadAiInterpretation(channelId, data);
      },
      error: (err: ApiError) => {
        if (!err.isComplianceBlock) {
          console.warn('Error cargando analítica:', err.message);
        }
      },
    });
  }

  private loadAiInterpretation(channelId: string, data: import('../../models/analytics.model').ChannelAnalyticsResponse): void {
    const summary = this.summary();
    if (!summary) return;

    const metrics = [
      { label: 'Visualizaciones diarias', value: data.views_stats.median, unit: 'views/day', n: data.views_stats.n, ci_95: data.views_stats.ci_95, limitations: data.views_stats.limitations },
      { label: 'APV', value: data.apv_stats.median, unit: '%', n: data.apv_stats.n, ci_95: data.apv_stats.ci_95, limitations: data.apv_stats.limitations },
      { label: 'ER', value: data.er_stats.median, unit: '%', n: data.er_stats.n, ci_95: data.er_stats.ci_95, limitations: data.er_stats.limitations },
      { label: 'NSC_1k', value: data.nsc_1k_stats.median, unit: 'subs/1k', n: data.nsc_1k_stats.n, ci_95: data.nsc_1k_stats.ci_95, limitations: data.nsc_1k_stats.limitations },
    ];

    this.aiLoading.set(true);
    this.aiService.interpretChannelAnalytics(channelId, {
      channel_title: summary.title,
      period_label: `${data.period_start} — ${data.period_end}`,
      metrics,
      recommendations: [],
    }).subscribe({
      next: (result) => {
        this.aiResult.set(result);
        this.aiLoading.set(false);
      },
      error: () => this.aiLoading.set(false),
    });
  }
}
