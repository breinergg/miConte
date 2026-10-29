import { Component, input } from '@angular/core';

@Component({
  selector: 'app-empty-state',
  standalone: true,
  template: `
    <div class="empty-state">
      <div class="empty-icon">{{ icon() }}</div>
      <h3>{{ title() }}</h3>
      <p>{{ description() }}</p>
    </div>
  `,
  styles: [`
    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      padding: 3rem 1rem;
      color: var(--text-secondary);
    }
    .empty-icon { font-size: 2.5rem; margin-bottom: 0.75rem; }
    h3 { margin: 0 0 0.5rem; font-size: 1rem; color: var(--text-primary); }
    p { margin: 0; font-size: 0.875rem; max-width: 28rem; line-height: 1.5; }
  `],
})
export class EmptyStateComponent {
  icon = input('📊');
  title = input('Sin datos');
  description = input('No hay datos disponibles para mostrar.');
}
