import { Component, input } from '@angular/core';

@Component({
  selector: 'app-compliance-notice',
  standalone: true,
  template: `
    <div class="compliance-notice">
      <div class="compliance-icon-wrap">
        <svg class="compliance-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"/>
        </svg>
      </div>
      <div class="compliance-content">
        <h3>Funcionalidad no disponible</h3>
        <p>{{ message() }}</p>
        <p class="compliance-detail">
          La analítica sobre datos reales de YouTube requiere cumplir dos requisitos independientes:
          la verificación de la aplicación OAuth de Google y el cumplimiento de los requisitos de
          YouTube Data API para métricas derivadas. Ninguna de estas aprobaciones ha sido obtenida todavía.
        </p>
      </div>
    </div>
  `,
  styles: [`
    .compliance-notice {
      display: flex;
      gap: 1rem;
      padding: 1.5rem;
      background: var(--warn-bg);
      border: 1px solid var(--warn-border);
      border-radius: var(--radius);
      margin: 1rem 0;
    }
    .compliance-icon-wrap {
      flex-shrink: 0;
    }
    .compliance-icon {
      width: 24px;
      height: 24px;
      color: var(--warn-ink);
    }
    h3 {
      margin: 0 0 0.5rem;
      font-size: 1rem;
      font-weight: 600;
      color: var(--ink);
    }
    p {
      margin: 0 0 0.5rem;
      font-size: 0.875rem;
      color: var(--ink-soft);
      line-height: 1.6;
    }
    .compliance-detail {
      font-size: 0.8125rem;
      color: var(--ink-faint);
    }
  `],
})
export class ComplianceNoticeComponent {
  message = input('La analítica derivada de datos reales de YouTube no está disponible.');
}
