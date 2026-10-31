import { Component, input } from '@angular/core';

const ICON_PATHS: Record<string, string> = {
  chart: 'M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5M9 11.25v-5.5',
  link: 'M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244',
  video: 'm15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9A2.25 2.25 0 0 0 13.5 5.25h-9A2.25 2.25 0 0 0 2.25 7.5v9A2.25 2.25 0 0 0 4.5 18.75Z',
  bolt: 'M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75Z',
};

@Component({
  selector: 'app-empty-state',
  standalone: true,
  template: `
    <div class="empty-state">
      <div class="empty-icon-wrap">
        <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path [attr.d]="iconPath()" />
        </svg>
      </div>
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
      padding: 4rem 1rem;
      color: var(--ink-soft);
    }
    .empty-icon-wrap {
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: var(--accent-subtle);
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 1rem;
    }
    .empty-icon {
      width: 28px;
      height: 28px;
      color: var(--accent);
    }
    h3 {
      margin: 0 0 0.375rem;
      font-size: 1rem;
      font-weight: 600;
      color: var(--ink);
    }
    p {
      margin: 0;
      font-size: 0.875rem;
      max-width: 28rem;
      line-height: 1.6;
    }
  `],
})
export class EmptyStateComponent {
  icon = input('chart');
  title = input('Sin datos');
  description = input('No hay datos disponibles para mostrar.');

  iconPath(): string {
    return ICON_PATHS[this.icon()] ?? ICON_PATHS['chart'];
  }
}
