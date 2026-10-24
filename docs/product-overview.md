# Visión del Producto — miConte (`docs/product-overview.md`)

## 1. El Problema que Resuelve miConte

Los creadores de contenido en YouTube y los pequeños equipos editoriales se enfrentan a tres problemas estructurales al analizar el rendimiento de sus canales:

1. **Métricas crudas sin validación estadística:** Las herramientas nativas muestran promedios simples o gráficos descriptivos sin indicar si una diferencia entre dos grupos de videos (por ejemplo, diferentes formatos, duraciones o ventanas de publicación) es estadísticamente significativa o producto del azar en muestras pequeñas ($N < 10$).
2. **Sesgo por asimetría y censura temporal:** Las métricas de YouTube (visualizaciones, tiempo de visualización) presentan distribuciones fuertemente asimétricas hacia la derecha (*right-skewed*, log-normal o Pareto). Además, comparar el total acumulado de un video publicado hace 48 horas con uno publicado hace 30 días introduce **censura por la derecha** (*right-censoring*), llevando a conclusiones erróneas.
3. **Alucinaciones y falsas atribuciones causales en herramientas con IA:** Muchas soluciones modernas delegan el análisis directamente a un modelo de lenguaje (LLM), el cual inventa cálculos numéricos o afirma relaciones de causa-efecto ("usar emojis en el título causó un 30% más de vistas") a partir de datos puramente observacionales plagados de variables de confusión (crecimiento orgánico del canal, estacionalidad semanal, tráfico externo).

**miConte** resuelve este problema separando de raíz el **cálculo matemático determinista** de la **interpretación textual**: analiza el historial de YouTube mediante pruebas estadísticas formales, respeta los tamaños muestrales e intervalos de confianza, y emite recomendaciones auditables sin depender de un LLM.

---

## 2. Usuarios Objetivo

1. **Creador de Contenido Independiente (Propietario de Canal):**
   * Gestiona su propio canal de YouTube y cuenta con autorización OAuth 2.0 sobre sus datos privados (impresiones, CTR, tiempo medio de visualización, retención).
   * Busca entender qué patrones históricos de publicación, duración y temática se asocian con un mejor rendimiento relativo frente a la línea base de su propio canal.
2. **Analista de Contenido / Estratega Digital:**
   * Audita el rendimiento de uno o varios canales (tanto con acceso OAuth a métricas privadas del creador como mediante análisis de métricas públicas de canales de referencia a través de `YouTube Data API v3`).
   * Necesita rigor metodológico: intervalos de confianza al 95%, medianas y rangos intercuartílicos (IQR) en lugar de promedios distorsionados por un único video viral (*outlier*).
3. **Desarrollador / Investigador Técnico (Auto-alojamiento Local):**
   * Ejecuta **miConte** en su entorno local con control total de sus datos en PostgreSQL (`miconte_db`) y, si desea resúmenes en lenguaje natural, conecta su propia instancia local de **Ollama** sin enviar datos sensibles a terceros.

---

## 3. Casos de Uso Principales

* **CU-01: Conectar y sincronizar un canal de YouTube (Público y Privado OAuth):**
  El usuario vincula su canal de YouTube mediante OAuth 2.0 (o registra un canal público por su ID) y sincroniza el catálogo de videos junto con sus series temporales de métricas hacia `miconte_db`.
* **CU-02: Analizar la línea base histórica del canal:**
  El usuario consulta la evolución histórica del canal visualizando métricas robustas (mediana, IQR, media recortada, intervalos de confianza al 95%) filtradas por ventanas de edad del video (24h, 48h, 7d, 30d) para evitar el sesgo de censura por la derecha.
* **CU-03: Identificar patrones y comparar cohortes de videos:**
  El usuario compara dos o más cohortes de videos (por ejemplo, videos por rango de duración, día de publicación o etiqueta temática). El motor estadístico verifica el tamaño muestral ($N$), evalúa la normalidad (Shapiro-Wilk o Kolmogorov-Smirnov) y ejecuta la prueba pertinente (Mann-Whitney U / Wilcoxon o t-test sobre $\log(X+1)$), reportando la magnitud del efecto y el valor $p$ cuando $N$ lo permite.
* **CU-04: Obtener recomendaciones deterministas respaldadas por datos:**
  El sistema evalúa los resultados del motor estadístico mediante un motor de reglas deterministas y genera recomendaciones accionables que incluyen la evidencia numérica, el periodo evaluado, el tamaño de muestra y las limitaciones metodológicas (sin lenguaje causal injustificado).
* **CU-05: Solicitar una interpretación asistida por IA (Opcional):**
  Con los resultados estadísticos y las recomendaciones deterministas ya calculados, el usuario solicita opcionalmente a un proveedor LLM configurado (Ollama local o API externa) una síntesis ejecutiva en lenguaje natural que explica los datos sin alterar ni inventar ninguna cifra.

---

## 4. Objetivo General y Objetivos Específicos

### Objetivo General
Construir **miConte**, una plataforma modular de inteligencia de contenido para YouTube que almacene el historial de publicaciones y métricas en PostgreSQL, ejecute análisis estadísticos deterministas y trazables en Python, exponga sus capacidades mediante una API REST en FastAPI y las presente en una interfaz web moderna en Angular, manteniendo la capa de IA (LLM) como un intérprete opcional y desacoplado.

### Objetivos Específicos
1. **Integrar las APIs oficiales de YouTube** (`YouTube Data API v3` para catálogo y estadísticas públicas; `YouTube Analytics API v2` para métricas privadas autorizadas vía OAuth 2.0) respetando cuotas y políticas de Google.
2. **Diseñar un modelo de persistencia histórico en PostgreSQL (`miconte_db`)** gestionado con SQLAlchemy 2.0 y Alembic que separe metadatos de entidades (canales, videos) de series temporales e instantáneas (*snapshots*) inmutables.
3. **Desarrollar un motor estadístico puro y determinista** con `pandas`, `NumPy`, `SciPy` y `statsmodels`, completamente aislado del framework web y de cualquier LLM, que implemente validación muestral, pruebas de normalidad y manejo explícito de datos ausentes o censurados.
4. **Implementar un motor de recomendaciones deterministas** capaz de traducir hallazgos estadísticos en sugerencias trazables utilizando lenguaje descriptivo/asociativo y nunca causal.
5. **Construir una interfaz web en Angular** clara, rápida y accesible que visualice métricas, intervalos de confianza, advertencias muestrales y recomendaciones con total transparencia.
6. **Proveer un puerto de abstracción de IA (`LLMProviderPort`)** con adaptador inicial para Ollama local y soporte para APIs externas, garantizando que el sistema funcione al 100% cuando ningún proveedor de IA esté activo.

---

## 5. Alcance Exacto del MVP vs. Funcionalidades Fuera de Alcance

### Alcance Exacto del MVP
* **Plataforma única:** Exclusivamente **YouTube**.
* **Ingesta y Sincronización:** Extracción bajo demanda y programable de metadatos de canal, lista de videos publicados, conteos públicos (`views`, `likes`, `comments`) y métricas analíticas diarias privadas (`views`, `estimatedMinutesWatched`, `averageViewDuration`, `averageViewPercentage`, `subscribersGained`, `subscribersLost`, etc., sujetas a validación empírica en la **Fase 2: Validación Técnica de las APIs de YouTube**).
* **Persistencia:** Base de datos relacional PostgreSQL (`miconte_db`) con control de migraciones vía Alembic.
* **Motor Estadístico:** Estadística descriptiva robusta, velocidades normalizadas ($V_{24h}$, $V_{7d}$), detección de valores atípicos (*outliers*), comparaciones de cohortes (paramétricas y no paramétricas) y descomposición básica de tendencias temporales cuando $N \ge 30$.
* **Recomendaciones Deterministas:** Generación de alertas y sugerencias basadas en reglas deterministas auditables sin intervención de IA.
* **API y Frontend:** Backend FastAPI + SPA en Angular con visualización de estado del canal, tabla analítica de videos, comparador de cohortes y panel de recomendaciones.
* **Adaptador LLM Opcional:** Integración en modo lectura de resultados precalculados hacia Ollama local (o proveedor externo configurable por variables `MICONTE_`), desactivable sin pérdida funcional.

### Expresamente Fuera del Alcance del MVP
* **Otras redes sociales:** TikTok, Instagram, X, Twitch o LinkedIn quedan excluidos del MVP (la arquitectura de puertos permitirá incorporarlos en fases futuras post-MVP).
* **Model Context Protocol (MCP):** No se implementará ningún servidor ni cliente MCP dentro del MVP obligatorio.
* **Entrenamiento de modelos propios (*Custom ML/DL*):** No se entrenarán redes neuronales, modelos de visión por computadora sobre miniaturas (*thumbnails*) ni modelos NLP propios desde cero.
* **Analítica predictiva avanzada no justificada:** No se prometerán predicciones exactas de vistas futuras de un video antes de publicarse cuando los datos históricos del canal carezcan de soporte estadístico suficiente.
* **Infraestructura de microservicios:** No se utilizarán arquitecturas distribuidas de microservicios, buses de eventos complejos (Kafka/RabbitMQ) ni orquestadores de contenedores de nivel empresarial (Kubernetes). El despliegue será un monolito modular limpio.
* **Edición o publicación de contenido en YouTube:** **miConte** es una plataforma de inteligencia y lectura analítica; no subirá videos ni modificará títulos/miniaturas en YouTube (solo solicitará permisos OAuth de lectura `readonly`).
