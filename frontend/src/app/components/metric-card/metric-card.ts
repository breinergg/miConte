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
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.25rem 1.5rem;
      min-width: 0;
      box-shadow: var(--shadow-sm);
      transition: box-shadow 0.15s;
    }
    .metric-card:hover {
      box-shadow: var(--shadow-md);
    }
    .metric-label {
      font-size: 0.8125rem;
      font-weight: 500;
      color: var(--ink-soft);
      margin-bottom: 0.5rem;
    }
    .metric-value {
      font-size: 1.75rem;
      font-weight: 700;
      color: var(--ink);
      margin-bottom: 0.375rem;
      letter-spacing: -0.02em;
    }
    .metric-na {
      font-size: 1rem;
      color: var(--ink-faint);
      font-weight: 400;
    }
    .metric-meta {
      display: flex;
      gap: 0.75rem;
      font-size: 0.75rem;
      color: var(--ink-faint);
    }
    .metric-ci { font-style: italic; }
    .metric-limitations {
      margin-top: 0.625rem;
      display: flex;
      flex-wrap: wrap;
      gap: 0.25rem;
    }
    .limitation-tag {
      font-size: 0.6875rem;
      background: var(--warn-bg);
      color: var(--warn-ink);
      padding: 0.125rem 0.5rem;
      border-radius: var(--radius-sm);
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
