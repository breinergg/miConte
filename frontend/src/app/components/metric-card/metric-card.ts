import { Component, input, computed } from '@angular/core';
import { MetricStats } from '../../models/analytics.model';

@Component({
  selector: 'app-metric-card',
  standalone: true,
  template: `
    <div class="metric-card">
      <div class="metric-label">{{ label() }}</div>
      @if (stats().n === 0) {
        <div class="metric-value metric-na">Sin datos</div>
      } @else {
        <div class="metric-value">{{ formattedValue() }}</div>
        <div class="metric-meta">
          <span class="metric-n">n={{ stats().n }}</span>
          @if (stats().ci_95) {
            <span class="metric-ci" title="Intervalo de confianza al 95%">
              IC₉₅ [{{ formatNum(stats().ci_95![0]) }}, {{ formatNum(stats().ci_95![1]) }}]
            </span>
          }
        </div>
        @if (stats().limitations.length > 0) {
          <div class="metric-limitations">
            @for (lim of stats().limitations; track lim) {
              <span class="limitation-tag">{{ lim }}</span>
            }
          </div>
        }
      }
    </div>
  `,
  styles: [`
    .metric-card {
      background: var(--surface-card);
      border: 1px solid var(--border-default);
      border-radius: 8px;
      padding: 1rem 1.25rem;
      min-width: 0;
    }
    .metric-label {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-tertiary);
      margin-bottom: 0.375rem;
    }
    .metric-value {
      font-size: 1.5rem;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 0.25rem;
    }
    .metric-na {
      font-size: 1rem;
      color: var(--text-tertiary);
      font-weight: 400;
    }
    .metric-meta {
      display: flex;
      gap: 0.75rem;
      font-size: 0.75rem;
      color: var(--text-tertiary);
    }
    .metric-ci { font-style: italic; }
    .metric-limitations {
      margin-top: 0.5rem;
      display: flex;
      flex-wrap: wrap;
      gap: 0.25rem;
    }
    .limitation-tag {
      font-size: 0.6875rem;
      background: var(--surface-warning);
      color: var(--text-secondary);
      padding: 0.125rem 0.5rem;
      border-radius: 4px;
      line-height: 1.4;
    }
  `],
})
export class MetricCardComponent {
  label = input.required<string>();
  stats = input.required<MetricStats>();
  unit = input<string>('');

  formattedValue = computed(() => {
    const s = this.stats();
    if (s.median !== null) return this.formatNum(s.median);
    if (s.mean !== null) return this.formatNum(s.mean);
    return '—';
  });

  formatNum(val: number): string {
    if (Math.abs(val) >= 1000) return val.toLocaleString('es-CO', { maximumFractionDigits: 0 });
    if (Math.abs(val) < 0.01) return val.toFixed(4);
    return val.toLocaleString('es-CO', { maximumFractionDigits: 2 });
  }
}
