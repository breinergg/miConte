import { Component, signal, OnInit } from '@angular/core';
import { ChannelService } from '../../services/channel.service';
import { AnalyticsService } from '../../services/analytics.service';
import { Recommendation } from '../../models/recommendation.model';
import { ApiError } from '../../services/api.service';
import { LoadingSpinnerComponent } from '../../components/loading-spinner/loading-spinner';
import { EmptyStateComponent } from '../../components/empty-state/empty-state';
import { ComplianceNoticeComponent } from '../../components/compliance-notice/compliance-notice';
import { DatePipe } from '@angular/common';

const PRIORITY_CONFIG: Record<string, { label: string; cssClass: string }> = {
  high: { label: 'Alta', cssClass: 'priority-high' },
  medium: { label: 'Media', cssClass: 'priority-medium' },
  low: { label: 'Baja', cssClass: 'priority-low' },
  info: { label: 'Informativa', cssClass: 'priority-info' },
};

@Component({
  selector: 'app-recommendations',
  standalone: true,
  imports: [LoadingSpinnerComponent, EmptyStateComponent, ComplianceNoticeComponent, DatePipe],
  template: `
    @switch (state()) {
      @case ('loading') {
        <app-loading />
      }
      @case ('no-channel') {
        <app-empty-state icon="🔗" title="Sin canal" description="Conecta un canal para ver recomendaciones." />
      }
      @case ('compliance-blocked') {
        <app-compliance-notice [message]="complianceMessage()" />
      }
      @case ('error') {
        <div class="error-banner"><p>{{ errorMessage() }}</p></div>
      }
      @case ('loaded') {
        <div class="page-header">
          <h2>Recomendaciones</h2>
          <button class="run-btn" (click)="runAnalysis()" [disabled]="running()">
            {{ running() ? 'Analizando...' : 'Ejecutar análisis' }}
          </button>
        </div>

        @if (lastRunMessage()) {
          <div class="run-result">{{ lastRunMessage() }}</div>
        }

        @if (recommendations().length === 0) {
          <app-empty-state
            icon="💡"
            title="Sin recomendaciones"
            description="Ejecuta un análisis para generar recomendaciones basadas en los datos disponibles." />
        } @else {
          <div class="rec-list">
            @for (rec of recommendations(); track rec.recommendation_id) {
              <div class="rec-card">
                <div class="rec-header">
                  <span class="priority-badge" [class]="priorityClass(rec.priority)">
                    {{ priorityLabel(rec.priority) }}
                  </span>
                  <span class="rule-code">{{ rec.rule_code }}</span>
                </div>
                <h4 class="rec-title">{{ rec.title }}</h4>
                <p class="rec-desc">{{ rec.description }}</p>

                @if (hasEvidence(rec)) {
                  <details class="rec-evidence">
                    <summary>Evidencia métrica</summary>
                    <div class="evidence-grid">
                      @for (entry of evidenceEntries(rec); track entry[0]) {
                        <div class="evidence-item">
                          <span class="ev-key">{{ entry[0] }}</span>
                          <span class="ev-val">{{ entry[1] }}</span>
                        </div>
                      }
                    </div>
                  </details>
                }

                <div class="rec-footer">
                  <span class="rec-date">{{ rec.created_at | date:'medium' }}</span>
                </div>
              </div>
            }
          </div>
        }
      }
    }
  `,
  styles: [`
    .page-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      margin-bottom: 1.25rem;
      flex-wrap: wrap;
    }
    .page-header h2 { margin: 0; font-size: 1.25rem; color: var(--text-primary); }
    .run-btn {
      padding: 0.5rem 1rem;
      background: var(--color-primary);
      color: #fff;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.875rem;
      font-weight: 500;
    }
    .run-btn:hover { opacity: 0.9; }
    .run-btn:disabled { opacity: 0.5; cursor: default; }

    .run-result {
      padding: 0.75rem 1rem;
      background: var(--surface-card);
      border: 1px solid var(--border-default);
      border-radius: 6px;
      margin-bottom: 1rem;
      font-size: 0.8125rem;
      color: var(--text-secondary);
    }

    .rec-list { display: flex; flex-direction: column; gap: 0.75rem; }
    .rec-card {
      background: var(--surface-card);
      border: 1px solid var(--border-default);
      border-radius: 8px;
      padding: 1.25rem;
    }
    .rec-header {
      display: flex;
      align-items: center;
      gap: 0.625rem;
      margin-bottom: 0.5rem;
    }
    .priority-badge {
      font-size: 0.6875rem;
      font-weight: 600;
      text-transform: uppercase;
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
    }
    .priority-high { background: #fde8e8; color: #b91c1c; }
    .priority-medium { background: #fef3c7; color: #92400e; }
    .priority-low { background: #dbeafe; color: #1e40af; }
    .priority-info { background: #e0e7ff; color: #3730a3; }
    .rule-code {
      font-size: 0.6875rem;
      color: var(--text-tertiary);
      font-family: monospace;
    }
    .rec-title {
      margin: 0 0 0.375rem;
      font-size: 0.9375rem;
      color: var(--text-primary);
    }
    .rec-desc {
      margin: 0;
      font-size: 0.8125rem;
      color: var(--text-secondary);
      line-height: 1.5;
    }

    .rec-evidence {
      margin-top: 0.75rem;
      font-size: 0.8125rem;
    }
    .rec-evidence summary {
      cursor: pointer;
      color: var(--text-tertiary);
      font-size: 0.75rem;
    }
    .evidence-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 0.375rem;
      margin-top: 0.5rem;
    }
    .evidence-item {
      display: flex;
      justify-content: space-between;
      gap: 0.5rem;
      padding: 0.25rem 0;
    }
    .ev-key { color: var(--text-tertiary); }
    .ev-val { color: var(--text-primary); font-weight: 500; }

    .rec-footer {
      margin-top: 0.75rem;
      font-size: 0.6875rem;
      color: var(--text-tertiary);
    }

    .error-banner {
      padding: 1rem 1.25rem;
      background: var(--surface-error);
      border: 1px solid var(--border-error);
      border-radius: 8px;
    }
    .error-banner p { margin: 0; font-size: 0.875rem; color: var(--text-primary); }
  `],
})
export class RecommendationsComponent implements OnInit {
  state = signal<'loading' | 'loaded' | 'no-channel' | 'compliance-blocked' | 'error'>('loading');
  recommendations = signal<Recommendation[]>([]);
  running = signal(false);
  lastRunMessage = signal('');
  errorMessage = signal('');
  complianceMessage = signal('');

  private channelId = '';

  constructor(
    private channelService: ChannelService,
    private analyticsService: AnalyticsService,
  ) {}

  ngOnInit(): void {
    this.channelService.listSynchronizableChannels().subscribe({
      next: (channels) => {
        if (channels.length === 0) {
          this.state.set('no-channel');
          return;
        }
        this.channelId = channels[0].channel_id;
        this.loadRecommendations();
      },
      error: (err: ApiError) => {
        this.errorMessage.set(err.message);
        this.state.set('error');
      },
    });
  }

  runAnalysis(): void {
    this.running.set(true);
    this.lastRunMessage.set('');
    this.analyticsService.runAnalysis(this.channelId).subscribe({
      next: (result) => {
        this.running.set(false);
        this.lastRunMessage.set(
          `Análisis completado: ${result.n_videos_analyzed} videos analizados, ` +
          `${result.n_rules_triggered} reglas activadas.`,
        );
        this.loadRecommendations();
      },
      error: (err: ApiError) => {
        this.running.set(false);
        if (err.isComplianceBlock) {
          this.complianceMessage.set(err.message);
          this.state.set('compliance-blocked');
        } else {
          this.lastRunMessage.set(`Error: ${err.message}`);
        }
      },
    });
  }

  priorityLabel(p: string): string {
    return PRIORITY_CONFIG[p]?.label ?? p;
  }

  priorityClass(p: string): string {
    return PRIORITY_CONFIG[p]?.cssClass ?? '';
  }

  hasEvidence(rec: Recommendation): boolean {
    return Object.keys(rec.metrics_evidence).length > 0;
  }

  evidenceEntries(rec: Recommendation): [string, unknown][] {
    return Object.entries(rec.metrics_evidence);
  }

  private loadRecommendations(): void {
    this.analyticsService.getRecommendations(this.channelId).subscribe({
      next: (data) => {
        this.recommendations.set(data.recommendations);
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
