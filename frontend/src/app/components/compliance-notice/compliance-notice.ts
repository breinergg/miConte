import { Component, input } from '@angular/core';

@Component({
  selector: 'app-compliance-notice',
  standalone: true,
  template: `
    <div class="compliance-notice">
      <div class="compliance-icon">⚠</div>
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
      background: var(--surface-warning);
      border: 1px solid var(--border-warning);
      border-radius: 8px;
      margin: 1rem 0;
    }
    .compliance-icon {
      font-size: 1.5rem;
      flex-shrink: 0;
    }
    h3 {
      margin: 0 0 0.5rem;
      font-size: 1rem;
      color: var(--text-primary);
    }
    p {
      margin: 0 0 0.5rem;
      font-size: 0.875rem;
      color: var(--text-secondary);
      line-height: 1.5;
    }
    .compliance-detail {
      font-size: 0.8125rem;
      color: var(--text-tertiary);
    }
  `],
})
export class ComplianceNoticeComponent {
  message = input('La analítica derivada de datos reales de YouTube no está disponible.');
}
