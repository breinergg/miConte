# miConte — Cumplimiento de Políticas y Términos de Servicio de YouTube API

Este documento define el marco normativo, los requisitos de cumplimiento técnico y las restricciones imperativas aplicables al almacenamiento, tratamiento y cálculo de métricas sobre datos obtenidos de las APIs de YouTube en **miConte**, en estricta conformidad con las políticas oficiales de Google y YouTube:

* [Términos de Servicio de los Servicios de la API de YouTube](https://developers.google.com/youtube/terms/api-services-terms-of-service)
* [Políticas para Desarrolladores de YouTube](https://developers.google.com/youtube/terms/developer-policies)
* [Guía de Políticas para Desarrolladores de YouTube](https://developers.google.com/youtube/terms/developer-policies-guide)
* [Política de Métricas Derivadas de YouTube](https://developers.google.com/youtube/terms/derived-metrics-policy)

---

## 1. Estado Oficial de Autorización de miConte

> [!WARNING]
> **Declaración Taxativa de Estado:** A la fecha de este documento, **miConte se encuentra en fase de desarrollo, validación técnica en entorno local y pruebas de laboratorio**. El proyecto **NO** cuenta con una aprobación, verificación o auditoría oficial de cumplimiento (*Google Cloud OAuth Verification / YouTube API Compliance Audit*) por parte de Google LLC ni de YouTube.
>
> No existe autorización formal concedida ni solicitud aprobada en este momento. La obtención de la verificación oficial de Google Cloud y la aprobación específica para casos de uso analíticos y métricas derivadas constituyen una **condición previa obligatoria e indispensable** antes de desplegar la plataforma con datos de canales reales de terceros o usuarios en producción.

---

## 2. Categorización Diferenciada de Datos, Plazos de Retención y Reglas de Eliminación

Las políticas de YouTube **no aplican un único plazo de retención uniforme** a todas las clases de información. En miConte se distinguen explícitamente cuatro categorías de datos, cada una sujeta a reglas y plazos normativos específicos:

| Categoría de Datos | Descripción y Fuente en miConte | Plazo de Retención Aplicable | Requisitos de Verificación y Purga |
| :--- | :--- | :--- | :--- |
| **1. Estadísticas privadas autorizadas por el propietario** | Series temporales diarias e informes de rendimiento obtenidos con autorización OAuth del propietario del canal (`Analytics API v2`, `Reporting API v1` y `Data API v3` en modo autenticado). | Conservadas para análisis longitudinal exclusivo del propietario mientras la cuenta esté activa y la autorización continúe vigente. | **Verificación periódica de autorización y disponibilidad (>30 días):** Al conservar estadísticas autorizadas durante más de 30 días, las políticas de YouTube exigen verificar periódicamente la autorización activa del usuario y la disponibilidad de los videos en YouTube (al menos cada 30 días). Si la autorización caduca o el video es suprimido/privatizado, el acceso cesa y los datos no verificados deben actualizarse o purgarse. |
| **2. Estadísticas públicas obtenidas sin autorización del propietario** | Instantáneas puntuales de estadísticas públicas (vistas públicas, suscriptores redondeados públicos, recuentos de comentarios) obtenidas vía API Key o sin token del propietario. | **Límite máximo estricto de 30 días calendario** sin refresco contra la API. | **Regla de actualizar o eliminar en 30 días:** Conforme a la Sección III.E.4 de las Políticas para Desarrolladores de YouTube, está prohibido almacenar estadísticas públicas por más de 30 días sin actualizar. El motor de sincronización (`SyncService`) debe refrescar las instantáneas dentro de la ventana de 30 días o eliminarlas definitivamente antes de servirlas. |
| **3. Otros datos autorizados, incluidos metadatos** | Metadatos descriptivos de catálogo: títulos, descripciones, etiquetas (*tags*), miniaturas (*thumbnails*), identificadores y duración de publicaciones. | **Sujetos a la regla de refresco o eliminación en 30 días.** | **Verificación periódica de disponibilidad (*Resource Availability Check*):** Se debe comprobar al menos cada 30 días si el contenido sigue disponible públicamente en YouTube. Si un video o canal es eliminado, suspendido o configurado como privado por su autor, los metadatos almacenados deben actualizarse o eliminarse de inmediato, sin conservar datos de recursos suprimidos. |
| **4. Solicitudes de eliminación del usuario o cancelación de cuenta** | Todos los datos de API, metadatos, series temporales, instantáneas y credenciales vinculadas al usuario solicitante. | **Eliminación obligatoria lo antes posible y en un plazo máximo de 7 días calendario**. | **Regla principal de eliminación de YouTube:** Si un usuario solicita eliminar los datos que miConte almacena sobre él o cancela su cuenta, todos sus datos deben eliminarse de la base de datos de manera definitiva dentro de un plazo improrrogable de **7 días calendario** (la regla de 30 días bajo ninguna circunstancia aplica a solicitudes de eliminación del usuario). |

---

### 2.1. Verificación Periódica de Autorización y Disponibilidad de Recursos (>30 Días)

De acuerdo con las Políticas para Desarrolladores de YouTube, la conservación de estadísticas autorizadas por periodos superiores a 30 días impone obligaciones continuas de verificación que deben distinguirse claramente de la regla general de refresco de datos no autorizados:

1. **Verificación Periódica de la Autorización del Usuario:**
   - La retención longitudinal de estadísticas privadas (más de 30 días) es legítima únicamente mientras subsista la autorización válida del propietario.
   - El sistema debe revalidar periódicamente (al menos cada 30 días o en cada ciclo de sincronización) que el token de refresco OAuth sigue activo y no ha sido revocado ni invalidado por el usuario.
2. **Verificación Periódica de Disponibilidad de Videos (*Video Availability Check*):**
   - Cuando se conservan métricas y estadísticas históricas asociadas a videos durante más de 30 días, el sistema debe comprobar periódicamente (al menos cada 30 días) que los videos continúan disponibles públicamente en YouTube.
   - Si un video ha sido eliminado, suspendido o establecido como privado en YouTube, miConte debe actualizar sus registros o eliminar los datos correspondientes a dicho recurso, absteniéndose de continuar sirviendo o reteniendo estadísticas de recursos no disponibles.
3. **Diferenciación frente a Datos No Autorizados y Metadatos:**
   - *Datos No Autorizados (Estadísticas Públicas sin OAuth):* Tienen un plazo de vida máximo de 30 días; no pueden conservarse a largo plazo y deben actualizarse obligatoriamente antes de los 30 días o borrarse.
   - *Metadatos Descriptivos:* Están sujetos a la regla de "actualizar o eliminar en 30 días", debiendo reflejar cualquier cambio de título, descripción o estado de disponibilidad realizado en YouTube.
   - *Estadísticas Privadas Autorizadas:* Admiten conservación histórica superior a 30 días exclusivamente para el análisis longitudinal del creador, siempre que se satisfaga rigurosamente la verificación periódica de autorización y disponibilidad antes descrita.

---

### 2.2. Procedimientos de Eliminación y Plazos Específicos

En cumplimiento estricto de las directivas de Google API User Data Policy y YouTube Developer Policies, miConte establece procedimientos operativos diferenciados con plazos normativos específicos según el evento detonante, prohibiendo generalizar todos los supuestos a un único plazo:

| Evento Detonante | Plazo Oficial Aplicable | Procedimiento Operativo en miConte |
| :--- | :--- | :--- |
| **A. Solicitud de eliminación de datos del usuario o cancelación de cuenta** | **Lo antes posible y en un plazo máximo e improrrogable de 7 días calendario** (*as soon as possible and within 7 calendar days*). | Supresión integral, definitiva e irreversible de todos los datos de API almacenados (estadísticas públicas, métricas privadas, series temporales, instantáneas, metadatos descriptivos de videos/canales y credenciales OAuth) de la base de datos `miconte_db` y de cualquier archivo temporal o caché. La regla de 30 días no aplica bajo ningún concepto a solicitudes expresas de supresión formuladas por el usuario. |
| **B. Revocación del consentimiento a través de miConte (`/disconnect`)** | **Inmediato (*immediate*)**. | En el mismo instante en que el usuario ejecuta la desconexión local: <br>1. Las credenciales cifradas (`encrypted_access_token`, `encrypted_refresh_token`) se destruyen permanentemente de la tabla `oauth_connections`. <br>2. Se cancelan de inmediato las sincronizaciones automáticas programadas en `SyncScheduler`. <br>3. Se emite una solicitud síncrona al endpoint oficial de revocación de Google (`https://oauth2.googleapis.com/revoke`). <br>4. Cesa de inmediato todo consumo o petición a las APIs de YouTube para dicho canal. <br>5. Los datos de API obtenidos o almacenados conforme al consentimiento revocado se eliminan lo antes posible y en un plazo máximo de 7 días calendario. Esta eliminación es automática: no requiere una segunda solicitud de borrado por parte del usuario. |
| **C. Revocación a través de la configuración de seguridad de Google** | **Inmediato tras la notificación o detección (*immediately upon notification or discovery*)**. | Cuando el usuario revoca los permisos otorgados a miConte desde el panel de seguridad de su cuenta Google (*Google Account Third-Party App Permissions*): <br>1. Al recibir notificación de seguridad de Google o en la primera petición donde la API retorne `invalid_grant` / token revocado, miConte cesa de inmediato cualquier acceso a las APIs de YouTube. <br>2. Las credenciales locales quedan marcadas como revocadas y se destruyen de `oauth_connections`. <br>3. Se detiene el planificador para el canal afectado. <br>4. Los datos de API obtenidos o almacenados bajo ese consentimiento —distintos de las credenciales destruidas en el paso 2— se eliminan lo antes posible y en un plazo máximo de 30 días calendario **desde la revocación del consentimiento**. La detección tardía no reinicia ni amplía ese plazo. La invalidación de credenciales (inmediata) y la eliminación de datos de API (máximo 30 días desde la revocación) son procesos con plazos normativos propios e independientes. <br>5. La aplicación revalida periódicamente la vigencia de los tokens OAuth. Si el token no puede renovarse y transcurre la ventana de 30 días sin revalidación exitosa, los datos de API del canal afectado se eliminan definitivamente (véase también Caso D). |
| **D. Imposibilidad de renovar o verificar la autorización** | **Cese inmediato de acceso; ventana máxima de 30 días para renovación o eliminación definitiva**. | Si el token de refresco expira, es invalidado o el sistema no puede revalidar la autorización del creador (por errores de autenticación HTTP 401/403 persistentes): <br>1. Cesa inmediatamente toda recolección y sincronización de datos de la API. <br>2. Se marca el estado del canal como desautorizado / pendiente de reconexión. <br>3. Dado que la retención de estadísticas privadas por más de 30 días exige la verificación periódica de autorización activa, si la autorización no puede ser revalidada dentro del ciclo periódico (máximo 30 días desde la última verificación exitosa), todos los datos de API no verificados de dicho canal deben eliminarse definitivamente de la base de datos de miConte. |

---

## 3. Política de Métricas Derivadas y Caso Analítico

La creación de métricas derivadas y el almacenamiento analítico extendido están estrictamente regulados por la [Política de Métricas Derivadas de YouTube](https://developers.google.com/youtube/terms/derived-metrics-policy) y las Políticas para Desarrolladores:

1. **Sujeción a Condiciones y Autorizaciones Adicionales:**
   - El almacenamiento de datos analíticos para la generación de métricas derivadas en herramientas de terceros está sujeto a la aprobación de Google durante la revisión de la aplicación OAuth (*Compliance Review / Additional Audit for Analytics Use Cases*).
   - miConte **no cuenta actualmente con dicha aprobación formal**, encontrándose el proyecto en etapa de diseño técnico y pruebas locales.
2. **Prohibición de Distorsión o Métricas Engañosas:**
   - Está prohibido crear métricas derivadas que contradigan, desvirtúen o sustituyan engañosamente las métricas oficiales de YouTube (vistas, suscriptores, tiempo de visualización, likes).
   - Ningún indicador de miConte puede presentarse como un "recuento alternativo oficial" de YouTube.
3. **Obligación de Distinción Explícita de Fuente (*Provenance Labeling*):**
   - En toda respuesta de la API REST y en cada visualización del panel web, los indicadores deben distinguirse nítidamente:
     * `source: "youtube_official"` (o `YouTube Data API v3`, `YouTube Analytics API v2`, `YouTube Reporting API v1`): Para datos reportados directamente por las APIs oficiales de Google.
     * `source: "miconte_derived"`: Para métricas calculadas internamente por el motor determinista de miConte (ej. $V_{24h}$, engagement rate, CTR derivado, APV relativo).
   - La interfaz gráfica no puede superponer indicadores derivados sobre métricas oficiales sin una diferenciación tipográfica o visual clara e inequívoca.
   - No se utilizarán marcas ni logotipos de YouTube de forma que sugieran patrocinio, respaldo o certificación oficial de los cálculos derivados.
4. **Condición Previa Formal para la Fase 6:**
   - La **Fase 6 (Motor Estadístico Determinista)** implementará y comprobará sus algoritmos, pruebas no paramétricas, intervalos de confianza bootstrap y detección de anomalías utilizando exclusivamente **datos sintéticos (*mock data*) y muestras de laboratorio locales**.
   - El uso de datos reales obtenidos de las APIs de YouTube para alimentar cálculos de métricas derivadas en entornos operativos queda formalmente condicionado a la obtención previa de la autorización y verificación oficial de Google Cloud.

---

## 4. Prohibición de Combinar API Data y Reglas Estrictas de Agregación entre Canales

De acuerdo con las Políticas para Desarrolladores de YouTube (Sección III.E — *Aggregation*):

> *"You must not aggregate, co-mingle, or combine API Data from multiple content owners or creators..."*

1. **La Regla de No-Combinación no Admite Excepciones por Consentimiento Individual:**
   - La política oficial prohíbe taxativamente mezclar, consolidar o agregar datos de API procedentes de distintos propietarios de contenido (*content owners*).
   - **El consentimiento individual de los usuarios NO constituye una excepción:** Está terminantemente prohibido consolidar datos de múltiples propietarios de contenido para construir bases de datos compartidas, modelos analíticos globales, inteligencia de mercado agregada o rankings comparativos entre creadores independientes, aun cuando los usuarios hubieran prestado su consentimiento explícito en los términos de servicio de la aplicación.
2. **Alcance Estricto de la Excepción de Agregación de API Data:**
   - Conforme a la política oficial vigente de YouTube, la agregación de API Data a través de distintos canales de YouTube está permitida **única y exclusivamente si todos esos canales están bajo el mismo Propietario de Contenido (*Content Owner*), reconocido formalmente por YouTube de conformidad con sus acuerdos de licencia o de socio aplicables (*applicable YouTube partner or license agreements*, tales como contratos de Content Manager / Content Partner de YouTube)**.
   - **No Presunción de Titularidad por Vinculación Local:** **Bajo ninguna circunstancia se debe presuponer que la vinculación o asociación de múltiples canales a una misma cuenta de usuario en miConte demuestra o satisface automáticamente este requisito**. El hecho de que un usuario autentique dos o más canales dentro de miConte no prueba que YouTube reconozca esos canales bajo un mismo *Content Owner* en el marco de sus acuerdos de licencia oficiales.
   - **Restricción Exclusiva de Resultados Agregados:** En los casos donde exista reconocimiento formal por parte de YouTube bajo acuerdos aplicables, cualquier resultado agregado o cálculo consolidado permitido debe quedar **restringido de manera estricta y exclusiva a ese mismo propietario de contenido**. Está absolutamente prohibido exhibir dichos resultados agregados a terceros o utilizarlos para comparaciones inter-propietario.
3. **Aislamiento Multi-Inquilino y por Canal en la Arquitectura de miConte:**
   - Dado que miConte no implementa en su estado actual verificación de acuerdos de licencia de *Content Owner* de YouTube, el sistema aplica un **aislamiento estricto a nivel de usuario y a nivel de canal individual**, absteniéndose de realizar cualquier tipo de consolidación de API Data entre canales distintos.
   - **En Base de Datos:** Cada canal, video, snapshot y serie temporal está segregado mediante claves foráneas directas (`user_id`, `channel_id`).
   - **En la Capa de API:** Todas las rutas de sincronización (`/api/v1/sync/*`) y de gestión OAuth (`/api/v1/oauth/*`) resuelven al usuario a través del token de sesión verificado por el servidor ([`CurrentUserDep`](file:///Users/breinergonzalezmachado/DESARROLLO%20WEB/miConte/src/miconte/api/deps.py)), rechazando con `HTTP 404 Not Found` o `HTTP 403 Forbidden` cualquier solicitud que intente acceder o sincronizar canales de terceros (inmunidad contra IDOR).

---

## 5. Proceso de Solicitud de Autorización y Auditoría ante Google Cloud

Para que miConte pueda transicionar en el futuro desde el entorno de desarrollo local hacia un despliegue con usuarios reales en producción, se deberá agotar formalmente el siguiente procedimiento:

1. **Verificación de Aplicación OAuth (Google Cloud Console):**
   - Presentación de dominio verificado, política de privacidad y términos de servicio públicos.
   - Demostración en video (*screencast*) del flujo de consentimiento OAuth 2.0 y justificación estricta de la necesidad técnica de los alcances de solo lectura solicitados (`youtube.readonly`, `yt-analytics.readonly`).
2. **Evaluación de Seguridad CASA (Cloud Application Security Assessment):**
   - Superación de una evaluación de seguridad independiente CASA Tier 2 o Tier 3 con un evaluador autorizado, que audita el cifrado AES-256-GCM en reposo, el manejo seguro de secretos y las directivas OWASP.
3. **Revisión de Cumplimiento de Casos Analíticos y Métricas Derivadas:**
   - Aprobación expresa del equipo de cumplimiento de YouTube API para el almacenamiento de series temporales y el cálculo de indicadores analíticos para uso exclusivo del propio creador.

---

## 6. Resumen de Condiciones de Cumplimiento Pendientes

| Condición de Cumplimiento | Estado Actual en miConte | Acción Requerida antes de Producción |
| :--- | :--- | :--- |
| **Aislamiento multi-inquilino y por canal** | **Cumplido técnicamente** en persistencia y API (Fases 3, 4 y 5). No se agrega API Data entre canales distintos ni se presume relación de *Content Owner*. | Mantener segregación estricta en todas las capas analíticas futuras. |
| **Agregación restringida a Content Owner oficial** | **Documentado formalmente.** Prohibido agregar datos entre canales salvo reconocimiento oficial de YouTube bajo acuerdos de licencia. No se presume por vinculación en miConte. | Si se soportara agregación multicanal en el futuro, exigir integración con YouTube Content Manager API y verificación de acuerdos oficiales. |
| **Purga inmediata de tokens al desconectar** | **Cumplido técnicamente** en `/disconnect` (Fase 4). | Mantener sin alteraciones. |
| **Plazos diferenciados de eliminación de datos de API** | **Documentado formalmente** según el evento detonante. Caso A: datos eliminados en máx. 7 días. Caso B: revocación de credenciales inmediata + datos de API eliminados en máx. 7 días (automático, sin segunda solicitud). Caso C: invalidación de credenciales inmediata + datos de API eliminados en máx. 30 días. Caso D: 30 días máx. para revalidar o eliminar datos no verificados. | Implementar endpoint de borrado total de cuenta/datos de usuario en la fase correspondiente. |
| **Verificación periódica de autorización y disponibilidad (>30 días)** | **Documentado formalmente**; cubierto operativamente por el ciclo de `SyncScheduler`. | Mantener comprobación periódica y purga de recursos eliminados o privatizados en YouTube. |
| **Verificación OAuth de Google Cloud** | **Pendiente / No iniciada.** Proyecto en modo desarrollo/pruebas locales. | Someter la aplicación a verificación formal de Google Cloud antes de abrir el acceso a creadores externos. |
| **Auditoría de Métricas Derivadas de YouTube** | **Pendiente / No iniciada.** No existe autorización concedida. | Requisito formal previo al uso de datos reales en producción durante la Fase 6. |
