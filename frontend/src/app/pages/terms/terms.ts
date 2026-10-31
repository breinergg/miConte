import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-terms',
  standalone: true,
  imports: [RouterLink],
  template: `
    <div class="terms-page">
      <h2 class="page-title">Términos de Uso</h2>
      <p class="last-updated">Versión 1.0 — octubre de 2026</p>

      <section class="terms-section acceptance-box">
        <p>
          <strong>Al utilizar miConte, aceptas estos términos de uso y los
          <a href="https://www.youtube.com/t/terms" target="_blank" rel="noopener noreferrer">
            Términos de Servicio de YouTube
          </a>.</strong>
        </p>
      </section>

      <section class="terms-section">
        <h3>1. Uso permitido</h3>
        <p>
          miConte es una herramienta de análisis de contenido para creadores de YouTube.
          Está diseñada exclusivamente para uso personal del propietario del canal conectado.
          No está permitido el uso de la plataforma para acceder a datos de canales ajenos
          ni para fines comerciales de terceros.
        </p>
      </section>

      <section class="terms-section">
        <h3>2. YouTube API Services</h3>
        <p>
          miConte utiliza <strong>YouTube API Services</strong> para acceder a tus datos de
          canal. Al usar esta aplicación aceptas también los
          <a href="https://developers.google.com/youtube/terms/api-services-terms-of-service"
             target="_blank" rel="noopener noreferrer">
            Términos de Servicio de YouTube API Services
          </a>
          y la
          <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">
            Política de Privacidad de Google
          </a>.
        </p>
        <p>
          Puedes revocar el acceso en cualquier momento desde
          <a href="https://security.google.com/settings/security/permissions"
             target="_blank" rel="noopener noreferrer">
            los ajustes de seguridad de Google
          </a>
          o usando el botón «Desconectar» en la sección Conexión.
        </p>
      </section>

      <section class="terms-section">
        <h3>3. Responsabilidad</h3>
        <p>
          miConte se proporciona tal cual, en fase de desarrollo, sin garantía de
          disponibilidad continua ni exactitud absoluta de los datos. El usuario es
          responsable de las decisiones tomadas a partir de los análisis generados.
        </p>
      </section>

      <section class="terms-section">
        <h3>4. Privacidad</h3>
        <p>
          Consulta la <a routerLink="/privacy">Política de Privacidad</a> para saber
          qué datos se recopilan, cómo se utilizan y cómo eliminarlos.
        </p>
      </section>
    </div>
  `,
  styles: [`
    .terms-page {
      max-width: 720px;
      padding-bottom: 3rem;
    }
    .page-title {
      margin: 0 0 0.375rem;
      font-size: 1.375rem;
      font-weight: 700;
      color: var(--ink);
    }
    .last-updated {
      margin: 0 0 2rem;
      font-size: 0.8125rem;
      color: var(--ink-faint);
    }
    .terms-section {
      margin-bottom: 1.75rem;
    }
    .acceptance-box {
      background: var(--accent-subtle, rgba(99,102,241,0.07));
      border-left: 3px solid var(--accent);
      border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
      padding: 0.875rem 1rem;
    }
    .terms-section h3 {
      margin: 0 0 0.625rem;
      font-size: 1rem;
      font-weight: 600;
      color: var(--ink);
    }
    .terms-section p {
      font-size: 0.875rem;
      color: var(--ink-soft);
      line-height: 1.7;
      margin: 0 0 0.5rem;
    }
    .terms-section a {
      color: var(--accent);
      text-decoration: underline;
    }
  `],
})
export class TermsComponent {}
