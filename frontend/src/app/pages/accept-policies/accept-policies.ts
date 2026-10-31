import { Component, signal, inject, OnInit } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { PolicyService, PolicyStatusResponse } from '../../services/policy.service';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-accept-policies',
  standalone: true,
  imports: [RouterLink, FormsModule],
  template: `
    <div class="accept-page">
      <div class="accept-card">
        <div class="accept-header">
          <div class="brand-mark">m</div>
          <div>
            <h1 class="accept-title">Antes de continuar</h1>
            <p class="accept-subtitle">
              miConte requiere que aceptes los documentos legales vigentes.
            </p>
          </div>
        </div>

        @if (loading()) {
          <div class="accept-loading">Cargando documentos…</div>
        } @else if (error()) {
          <div class="accept-error">{{ error() }}</div>
        } @else {
          <div class="documents">
            <label class="doc-row">
              <input type="checkbox" [(ngModel)]="acceptedPrivacy" />
              <span class="doc-label">
                He leído y acepto la
                <a routerLink="/privacy" target="_blank">Política de Privacidad</a>,
                incluyendo el uso de YouTube API Services y la
                <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">
                  Política de Privacidad de Google
                </a>.
              </span>
            </label>

            <label class="doc-row">
              <input type="checkbox" [(ngModel)]="acceptedTerms" />
              <span class="doc-label">
                He leído y acepto los
                <a routerLink="/terms" target="_blank">Términos de Uso</a>
                y los
                <a href="https://www.youtube.com/t/terms" target="_blank" rel="noopener noreferrer">
                  Términos de Servicio de YouTube
                </a>.
              </span>
            </label>
          </div>

          <p class="revocation-note">
            Puedes revocar el acceso de miConte a Google en cualquier momento desde
            <a href="https://security.google.com/settings/security/permissions"
               target="_blank" rel="noopener noreferrer">
              los ajustes de seguridad de Google
            </a>.
          </p>

          @if (submitError()) {
            <div class="accept-error">{{ submitError() }}</div>
          }

          <button
            class="accept-btn"
            [disabled]="!acceptedPrivacy || !acceptedTerms || submitting()"
            (click)="submit()"
          >
            @if (submitting()) {
              Guardando…
            } @else {
              Aceptar y continuar
            }
          </button>
        }
      </div>
    </div>
  `,
  styles: [`
    .accept-page {
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--bg);
      padding: 1rem;
    }
    .accept-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 2rem;
      width: 100%;
      max-width: 520px;
    }
    .accept-header {
      display: flex;
      align-items: flex-start;
      gap: 1rem;
      margin-bottom: 1.75rem;
    }
    .brand-mark {
      width: 40px;
      height: 40px;
      background: var(--accent);
      color: #fff;
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 1.25rem;
      flex-shrink: 0;
    }
    .accept-title {
      margin: 0 0 0.25rem;
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--ink);
    }
    .accept-subtitle {
      margin: 0;
      font-size: 0.875rem;
      color: var(--ink-soft);
    }
    .documents {
      display: flex;
      flex-direction: column;
      gap: 1rem;
      margin-bottom: 1.25rem;
    }
    .doc-row {
      display: flex;
      align-items: flex-start;
      gap: 0.75rem;
      cursor: pointer;
    }
    .doc-row input[type="checkbox"] {
      margin-top: 0.2rem;
      width: 16px;
      height: 16px;
      flex-shrink: 0;
      accent-color: var(--accent);
      cursor: pointer;
    }
    .doc-label {
      font-size: 0.875rem;
      color: var(--ink-soft);
      line-height: 1.6;
    }
    .doc-label a {
      color: var(--accent);
      text-decoration: underline;
    }
    .revocation-note {
      font-size: 0.8125rem;
      color: var(--ink-faint);
      line-height: 1.6;
      margin-bottom: 1.5rem;
    }
    .revocation-note a {
      color: var(--accent);
      text-decoration: underline;
    }
    .accept-btn {
      width: 100%;
      padding: 0.75rem;
      background: var(--accent);
      color: #fff;
      border: none;
      border-radius: var(--radius-sm);
      font-size: 0.9375rem;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.15s;
    }
    .accept-btn:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    .accept-btn:not(:disabled):hover { opacity: 0.88; }
    .accept-loading, .accept-error {
      text-align: center;
      padding: 1rem 0;
      font-size: 0.875rem;
      color: var(--ink-soft);
    }
    .accept-error { color: var(--danger, #dc2626); }
  `],
})
export class AcceptPoliciesComponent implements OnInit {
  private policyService = inject(PolicyService);
  private authService = inject(AuthService);
  private router = inject(Router);

  loading = signal(true);
  error = signal<string | null>(null);
  submitting = signal(false);
  submitError = signal<string | null>(null);

  acceptedPrivacy = false;
  acceptedTerms = false;

  ngOnInit(): void {
    this.policyService.getVersions().subscribe({
      next: (status: PolicyStatusResponse) => {
        this.loading.set(false);
        if (status.all_current_accepted) {
          this.router.navigate(['/dashboard']);
        }
      },
      error: (err) => {
        if (err?.status === 401) {
          this.authService.initiateGoogleLogin();
          return;
        }
        this.loading.set(false);
        this.error.set('No se pudieron cargar los documentos. Intenta recargar la página.');
      },
    });
  }

  submit(): void {
    if (!this.acceptedPrivacy || !this.acceptedTerms) return;
    this.submitting.set(true);
    this.submitError.set(null);

    this.policyService.acceptAll().subscribe({
      next: () => {
        this.submitting.set(false);
        this.router.navigate(['/dashboard']);
      },
      error: (err) => {
        if (err?.status === 401) {
          this.authService.initiateGoogleLogin();
          return;
        }
        this.submitting.set(false);
        this.submitError.set('No se pudo guardar la aceptación. Intenta de nuevo.');
      },
    });
  }
}
