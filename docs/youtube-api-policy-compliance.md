# miConte — Cumplimiento de Políticas y Términos de Servicio de YouTube API

Este documento establece el marco normativo, los requisitos de cumplimiento y las restricciones aplicables al uso de datos de YouTube en **miConte**, en estricta conformidad con los [Términos de Servicio de los Servicios de la API de YouTube](https://developers.google.com/youtube/terms/api-services-terms-of-service) y las [Políticas para Desarrolladores de YouTube](https://developers.google.com/youtube/terms/developer-policies).

---

## 1. Estado Oficial de Autorización de miConte

> [!WARNING]
> **Declaración de Estado:** A la fecha de este documento, **miConte se encuentra en fase de desarrollo, validación técnica y pruebas de laboratorio**. El proyecto **NO** cuenta con una aprobación, certificación o auditoría oficial de cumplimiento (*Google Cloud API Verification / Compliance Audit*) por parte de Google LLC o YouTube.
>
> La obtención de la verificación oficial de Google Cloud y la aprobación de casos de uso analíticos constituyen una **condición previa obligatoria e indispensable** antes de desplegar la plataforma con datos de canales reales de terceros o usuarios en producción.

---

## 2. Restricciones Aplicables a las Métricas Derivadas

De acuerdo con la Sección III.E de los Términos de Servicio de YouTube API y las directrices de métricas derivadas:

1. **Prohibición de Distorsión o Reemplazo:**
   - La aplicación no debe generar métricas derivadas que contradigan, desvirtúen o sustituyan engañosamente las métricas oficiales de YouTube (vistas, suscriptores, tiempo de reproducción, likes).
   - Ningún algoritmo determinista o heurístico de miConte puede presentarse como un "recuento alternativo oficial" de YouTube.
2. **Cálculos Permitidos:**
   - Se permiten métricas calculadas que combinen datos brutos para fines analíticos (por ejemplo: CTR derivado, porcentaje medio de visualización, tasa de interacción o engagement rate, velocidad normalizada $V_{24h}$), siempre que su metodología matemática sea transparente, auditable y determinista.
3. **Prohibición de Inferencia Causal No Probada:**
   - Conforme a `AGENTS.md` y `miconte-statistical-validation`, está expresamente prohibido que el sistema declare relaciones causa-efecto basadas en correlaciones observadas. Las métricas derivadas deben presentarse con su correspondiente tamaño muestral ($N$), intervalos de confianza y advertencias de no causalidad.

---

## 3. Obligación de Distinción entre Métricas Oficiales y Métricas miConte

Para cumplir con las directivas de transparencia hacia el creador:

1. **Etiquetado Explícito de Fuente (*Provenance Labeling*):**
   - En toda respuesta de la API REST y en cada vista del panel de usuario, toda cifra debe llevar un origen explícito:
     * `source: "youtube_official"` (o `YouTube Data API v3`, `YouTube Analytics API v2`, `YouTube Reporting API v1`): Para datos reportados directamente por las APIs de Google.
     * `source: "miconte_derived"`: Para métricas calculadas internamente por el motor determinista de miConte (ej. $V_{24h}$, engagement ratios, benchmarks históricos del propio canal).
2. **Visualización Separada:**
   - La interfaz gráfica no puede superponer métricas derivadas sobre gráficos oficiales sin una diferenciación tipográfica o de simbología inequívoca.
   - No se utilizarán logotipos ni marcas registradas de YouTube de forma que sugieran patrocinio, respaldo o coautoría de las métricas derivadas.

---

## 4. Requisitos de Retención, Actualización y Eliminación de Datos

De acuerdo con la Sección III.E.4 de los Términos de Servicio de YouTube API:

1. **Ventana de Retención y Refresco (Regla de los 30 Días):**
   - Los datos obtenidos de las APIs de YouTube no deben conservarse por más de 30 días calendario sin ser actualizados o revalidados contra las APIs oficiales.
   - Las instantáneas históricas (`public_snapshots`, `daily_metrics`) almacenadas en `miconte_db` son conservadas para análisis longitudinal exclusivamente para el usuario autenticado que autorizó el canal, y su refresco periódico se gestiona a través de `SyncService` y `SyncScheduler`.
2. **Desconexión y Derecho al Olvido (Eliminación Inmediata y Definitiva):**
   - Cuando un usuario revoca la autorización a través de `/api/v1/oauth/youtube/disconnect` o cuando Google notifica la revocación:
     * Los tokens de acceso y de actualización cifrados son purgados inmediatamente de `oauth_connections`.
     * Las credenciales ya no se retienen bajo ninguna circunstancia.
   - Si un usuario solicita la eliminación de su cuenta, todos los datos almacenados de sus canales y videos deben ser eliminados de PostgreSQL dentro de un plazo máximo de 30 días, conforme a la normativa de privacidad y los términos de Google.
3. **No Retención de Datos Suprimidos:**
   - Si un video o canal es eliminado en YouTube o se vuelve privado, la sincronización reflejará dicho estado y no intentará exponer públicamente metadatos que el creador ha retirado.

---

## 5. Limitaciones sobre Agregaciones entre Distintos Propietarios de Contenido

YouTube prohíbe taxativamente la agregación de datos analíticos privados para crear productos de inteligencia competitiva o rankings entre distintos propietarios sin su consentimiento expreso e informado:

1. **Aislamiento Multi-Inquilino Estricto:**
   - miConte impone una política de aislamiento total: cada usuario autenticado (`user_id`) solo puede visualizar, sincronizar y procesar los canales que le pertenecen legítimamente (`channel.user_id == current_user.id`).
   - Los endpoints de la API (`/api/v1/sync/*`, `/api/v1/oauth/*`) rechazan cualquier acceso a canales ajenos con `HTTP 404 / 403` (prevención de IDOR).
2. **Prohibición de *Cross-Channel Benchmarking* Público o no Autorizado:**
   - miConte **NO** realiza agregaciones de datos analíticos privados entre diferentes canales de distintos usuarios.
   - Las comparaciones y percentiles estadísticos calculados en la Fase 6 se circunscriben estrictamente a:
     * El historial cronológico del **mismo canal**.
     * Canales distintos pertenecientes al **mismo usuario autenticado**, si éste lo solicita expresamente.
   - Está prohibido alimentar bases de datos globales o modelos compartidos con métricas privadas de creadores independientes.

---

## 6. Proceso de Solicitud de Autorización y Auditoría ante Google Cloud

Antes de habilitar el sistema para usuarios reales en entornos de producción, se debe agotar el siguiente procedimiento ante Google Cloud:

1. **Verificación de Aplicación OAuth (OAuth App Verification):**
   - Publicar la política de privacidad y los términos de servicio accesibles en un dominio verificado.
   - Grabar un video de demostración (*screencast*) exhibiendo el flujo OAuth 2.0 y justificando detalladamente el uso de cada alcance solicitado (`youtube.readonly`, `yt-analytics.readonly`, `yt-analytics-monetary.readonly`).
   - Justificar por qué los alcances restringidos son estrictamente necesarios para los fines de diagnóstico analítico del creador.
2. **Evaluación de Seguridad de Aplicaciones en la Nube (CASA / Cloud Application Security Assessment):**
   - Si la aplicación maneja más de 100 usuarios o solicita alcances sensibles/restringidos a escala, Google exige someter la arquitectura a una auditoría CASA Tier 2 o Tier 3 con un evaluador autorizado.
   - Esta auditoría valida la protección criptográfica en reposo (AES-256-GCM implementado en miConte), la gestión de vulnerabilidades OWASP y las directrices de transporte seguro (TLS 1.3).
3. **Auditoría de Cumplimiento de Políticas de YouTube (YouTube Compliance Audit):**
   - Presentar el diseño del motor analítico determinista ante el equipo de políticas de YouTube API para confirmar que las métricas derivadas respetan las directrices de la Sección III.E.

---

## 7. Condición Previa para la Fase 6

> [!IMPORTANT]
> **Condición Previa Formal:** La implementación del motor estadístico determinista en la **Fase 6** se desarrollará y validará inicialmente utilizando pruebas unitarias/de integración con datos sintéticos y muestras históricas locales.
>
> El uso de las métricas derivadas con datos de producción de canales reales queda explícitamente condicionado a la obtención formal de la autorización de Google Cloud y la superación del proceso de verificación correspondiente.
