import { Component } from '@angular/core';

@Component({
  selector: 'app-loading',
  standalone: true,
  template: `
    <div class="loading-container">
      <div class="spinner"></div>
      <p>Cargando...</p>
    </div>
  `,
  styles: [`
    .loading-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 4rem 1rem;
      gap: 1rem;
      color: var(--ink-soft);
    }
    .spinner {
      width: 28px;
      height: 28px;
      border: 2.5px solid var(--border);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    p {
      margin: 0;
      font-size: 0.8125rem;
      font-weight: 500;
    }
  `],
})
export class LoadingSpinnerComponent {}
