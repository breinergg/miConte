import { Component } from '@angular/core';

@Component({
  selector: 'app-privacy',
  standalone: true,
  template: `
    <div class="privacy-page">
      <h2 class="page-title">Política de Privacidad y Uso de YouTube API Services</h2>
      <p class="last-updated">Última actualización: octubre de 2026</p>

      <section class="privacy-section">
        <h3>1. Identificación de la aplicación</h3>
        <p>
          <strong>miConte</strong> es una aplicación de análisis de contenido para creadores de YouTube.
          Se encuentra actualmente en desarrollo y no ha sido verificada por Google ni aprobada para
          distribución pública.
        </p>
      </section>

      <section class="privacy-section">
        <h3>2. Uso de YouTube API Services</h3>
        <p>
          miConte utiliza <strong>YouTube API Services</strong> para acceder a los datos privados de
          tu canal de YouTube. Al conectar tu canal aceptas los
          <a href="https://www.youtube.com/t/terms" target="_blank" rel="noopener noreferrer">
            Términos de Servicio de YouTube
          </a>
          y la
          <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">
            Política de Privacidad de Google
          </a>.
        </p>
        <p>
          Puedes revocar el acceso de miConte a tu cuenta de Google en cualquier momento desde
          <a href="https://security.google.com/settings/security/permissions" target="_blank" rel="noopener noreferrer">
            la página de permisos de seguridad de Google
          </a>
          o usando el botón «Desconectar» en la sección de Conexión de esta aplicación.
        </p>
      </section>

      <section class="privacy-section">
        <h3>3. Datos que miConte recopila y almacena</h3>
        <p>miConte almacena localmente los siguientes datos en su base de datos:</p>
        <ul>
          <li>
            <strong>Credenciales OAuth:</strong> token de acceso y token de actualización de Google,
            cifrados con AES-256-GCM. No se almacenan en texto plano.
          </li>
          <li>
            <strong>Metadatos del canal:</strong> nombre, descripción, URL personalizada,
            miniatura e identificador de canal de YouTube.
          </li>
          <li>
            <strong>Metadatos de videos:</strong> título, descripción, fecha de publicación,
            duración e identificador de video de YouTube.
          </li>
          <li>
            <strong>Métricas de YouTube Analytics:</strong> vistas, minutos estimados vistos,
            duración media, porcentaje medio de visualización, suscriptores ganados y perdidos,
            likes, comentarios y compartidos, por día y por video.
          </li>
          <li>
            <strong>Métricas de alcance (Reporting API):</strong> impresiones de miniatura y
            tasa de clic (CTR) de miniatura, por día y video.
          </li>
        </ul>
      </section>

      <section class="privacy-section">
        <h3>4. Datos de identidad de Google</h3>
        <p>
          Durante el inicio de sesión con Google, miConte recibe tu dirección de correo electrónico
          y tu nombre completo del perfil de Google, junto con un identificador único estable
          (<em>Google sub</em>). Estos datos se almacenan en PostgreSQL para identificarte como
          propietario del canal conectado y no se utilizan con ningún otro fin.
        </p>
      </section>

      <section class="privacy-section">
        <h3>5. Sesiones y cookies</h3>
        <p>
          Tras el inicio de sesión se genera una cookie de sesión <strong>HttpOnly</strong> y
          <strong>Secure</strong>. Este token no es accesible desde JavaScript del navegador y
          expira en 30 días. Se utiliza exclusivamente para autenticar tus peticiones al servidor
          de miConte. No se utilizan cookies de seguimiento ni de terceros.
        </p>
      </section>

      <section class="privacy-section">
        <h3>6. Almacenamiento de datos</h3>
        <p>
          Todos los datos se almacenan en una base de datos <strong>PostgreSQL</strong> local
          gestionada por el propietario de la instalación de miConte. No se utilizan servicios
          de almacenamiento en la nube de terceros para los datos analíticos.
        </p>
      </section>

      <section class="privacy-section">
        <h3>7. Procesamiento por modelos de lenguaje (LLM)</h3>
        <p>
          La funcionalidad de recomendaciones de contenido utiliza modelos de lenguaje para
          generar sugerencias a partir de tus métricas. En este momento, el acceso a métricas
          reales desde YouTube está <strong>deshabilitado</strong> (modo de cumplimiento activo),
          por lo que no se envían datos reales de tu canal a ningún proveedor externo de IA.
          Cuando esta funcionalidad esté habilitada, se indicará explícitamente qué datos se
          comparten y con qué proveedor.
        </p>
      </section>

      <section class="privacy-section">
        <h3>8. Uso de los datos</h3>
        <p>Los datos recopilados se utilizan exclusivamente para:</p>
        <ul>
          <li>Presentar estadísticas de rendimiento al propietario autorizado del canal.</li>
          <li>Generar recomendaciones de contenido basadas en las métricas del canal.</li>
        </ul>
        <p>
          <strong>miConte no comparte estos datos con terceros, no los utiliza para publicidad
          y no los envía a ningún proveedor de IA externo mientras el modo de cumplimiento
          esté activo.</strong>
        </p>
      </section>

      <section class="privacy-section">
        <h3>9. Retención y eliminación de datos</h3>
        <p>
          Los datos analíticos se conservan mientras la conexión OAuth permanezca activa.
          Al revocar la autorización (desde esta aplicación o desde Google), se eliminan
          automáticamente: credenciales OAuth, metadatos del canal, metadatos de videos y
          todas las métricas asociadas. La retención máxima efectiva está acotada por la
          vigencia del token de actualización de Google.
        </p>
        <p>
          La aplicación comprueba periódicamente que los videos almacenados continúan
          disponibles en YouTube. Los videos eliminados por el creador se eliminan también de
          la base de datos local, una vez confirmada su ausencia mediante la YouTube Data API.
        </p>
        <p>
          Para solicitar la eliminación manual de tus datos ponte en contacto con el
          administrador de la instalación de miConte.
          <em>(Contacto: pendiente de configuración en esta instalación.)</em>
        </p>
      </section>

      <section class="privacy-section">
        <h3>10. Referencias externas</h3>
        <ul>
          <li>
            <a href="https://www.youtube.com/t/terms" target="_blank" rel="noopener noreferrer">
              Términos de Servicio de YouTube
            </a>
          </li>
          <li>
            <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">
              Política de Privacidad de Google
            </a>
          </li>
          <li>
            <a href="https://developers.google.com/youtube/terms/api-services-terms-of-service" target="_blank" rel="noopener noreferrer">
              Términos de Servicio de YouTube API Services
            </a>
          </li>
          <li>
            <a href="https://security.google.com/settings/security/permissions" target="_blank" rel="noopener noreferrer">
              Revocar permisos de miConte en Google
            </a>
          </li>
        </ul>
      </section>
    </div>
  `,
  styles: [`
    .privacy-page {
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
    .privacy-section {
      margin-bottom: 1.75rem;
    }
    .privacy-section h3 {
      margin: 0 0 0.625rem;
      font-size: 1rem;
      font-weight: 600;
      color: var(--ink);
    }
    .privacy-section p, .privacy-section li {
      font-size: 0.875rem;
      color: var(--ink-soft);
      line-height: 1.7;
      margin: 0 0 0.5rem;
    }
    .privacy-section ul {
      padding-left: 1.375rem;
      margin: 0.375rem 0 0;
    }
    .privacy-section a {
      color: var(--accent);
      text-decoration: underline;
    }
  `],
})
export class PrivacyComponent {}
