# ADR-0006: Cifrado Autenticado de Tokens OAuth (AES-256-GCM), Gestión de Claves y Ciclo de Vida OAuth 2.0

* **Estado:** Aprobado
* **Fecha:** 2026-10-25
* **Fase:** Fase 4 — Integración de Producción con YouTube

---

## Contexto

En la Fase 3 se definieron en el modelo relacional las columnas `encrypted_access_token` y `encrypted_refresh_token` dentro de la tabla `oauth_connections`. Como se documentó explícitamente en el cierre de la Fase 3, la existencia de estas columnas representaba únicamente campos reservados para texto cifrado (*ciphertext*), pero no garantizaba por sí misma la protección criptográfica.

En la Fase 4 se implementa la integración de producción con las APIs oficiales de Google/YouTube mediante adaptadores HTTP (`YouTubeDataClient`, `YouTubeAnalyticsClient`, `YouTubeReportingClient`) y el flujo de autorización Web Server de OAuth 2.0.

De acuerdo con las reglas de seguridad de **miConte** (AGENTS.md, OWASP y directrices de protección de credenciales):
1. Ningún token de acceso ni token de actualización puede persistirse en texto plano.
2. Los tokens nunca deben exponerse al frontend ni viajar en URLs o cookies de sesión accesibles por JavaScript.
3. Las excepciones, trazas y registros de log nunca deben incluir tokens descifrados ni claves criptográficas.
4. El mecanismo de cifrado debe ser autenticado (AEAD) para detectar de inmediato cualquier alteración maliciosa o corrupción de datos.
5. Las credenciales deben estar vinculadas criptográficamente a su contexto de usuario y canal (evitando que un token cifrado sea trasplantado a otra cuenta).

---

## Decisión

### 1. Mecanismo Criptográfico: AES-256-GCM con Envoltura Versionada

Se adopta **AES-GCM (Galois/Counter Mode) con claves de 256 bits** mediante la biblioteca mantenida `cryptography`:
* **Autenticación Integrada:** AES-GCM calcula un tag de autenticación de 128 bits que garantiza simultáneamente confidencialidad e integridad. Cualquier modificación en el texto cifrado o en los datos asociados (*AAD*) hace que el descifrado falle con `DecryptionError`.
* **Nonce Único (96 bits):** Cada operación de cifrado genera un vector de inicialización único mediante el generador criptográfico seguro del sistema operativo (`os.urandom(12)`). Se prohíbe taxativamente la reutilización de nonces bajo una misma clave.
* **Envoltura Versionada:** El texto cifrado se almacena en las columnas `Text` de PostgreSQL con el formato:
  $$\text{v1}:\langle\text{key\_id}\rangle:\langle\text{nonce\_b64}\rangle:\langle\text{ciphertext+tag\_b64}\rangle$$
* **Preparación para Rotación de Claves:** El identificador `key_id` (p. ej. `k1`, `k2`) permite operar con una clave activa para nuevos cifrados y mantener claves históricas (*fallback keys*) para descifrar credenciales previas durante una ventana de rotación, sin requerir migraciones DDL ni caídas de servicio.

### 2. Vinculación de Contexto mediante Datos Autenticados Asociados (AAD)

Para impedir ataques de corte y sustitución donde un atacante mueva un ciphertext de una fila a otra en la base de datos, toda operación de cifrado y descifrado vincula deterministamente el token a su contexto de dominio mediante AAD:
$$\text{AAD} = \text{user\_id} \parallel \text{":"} \parallel \text{platform} \parallel \text{":"} \parallel \text{external\_channel\_id} \parallel \text{":"} \parallel \text{credential\_kind}$$
Si se intenta descifrar un token de actualización en el contexto de otro usuario o de otro canal, la verificación criptográfica del tag falla de inmediato.

### 3. Separación Estricta de Claves de Cifrado

* Las claves maestras **nunca se almacenan en la base de datos** ni se incluyen en el repositorio Git.
* Se suministran al backend exclusivamente a través de variables de entorno seguras (`MICONTE_TOKEN_ENCRYPTION_KEY`) o sistemas KMS/Vault en entornos productivos.
* Para desarrollo local y pruebas se define una clave de 256 bits por defecto en `Settings` con advertencias en la documentación.

### 4. Ciclo de Vida OAuth 2.0, Protección Anti-CSRF y PKCE

1. **Protección Anti-CSRF y Transacciones de Un Solo Uso (*Single-Use State*):**
   * El parámetro `state` se construye como una carga útil JSON firmada criptográficamente con HMAC-SHA256 (`b64_payload.hmac_sig`), incluyendo el `user_id` del solicitante, un identificador aleatorio (`rnd`) y una marca de tiempo de expiración (TTL de 10 minutos).
   * **Consumo de Un Solo Uso:** `OAuthTransactionStore` gestiona las transacciones activas de autorización con exclusión mutua (`threading.Lock`). El estado se valida y se marca como consumido **antes de cualquier llamada de red a Google**. Si un callback se reintenta o repite, es rechazado de inmediato con `OAuthError("already been consumed")`, bloqueando ataques de repetición (*replay attacks*).
   * **Limitación Arquitectónica de Almacén en Memoria:** `OAuthTransactionStore` opera en la memoria del proceso local. Para despliegues futuros en producción con múltiples workers (ej. Gunicorn con Uvicorn workers) o múltiples réplicas en pods, se requerirá un almacén de transacciones distribuido (Redis o tabla transaccional en PostgreSQL con TTL) para compartir el estado entre procesos independientes.
2. **Soporte Obligatorio de PKCE (RFC 7636):**
   * Se genera un `code_verifier` de 64 caracteres criptográficamente seguros y su correspondiente `code_challenge` mediante SHA-256 (`code_challenge_method=S256`).
   * El `code_verifier` se almacena temporalmente en la transacción de autorización y se envía a Google durante el intercambio de tokens, bloqueando ataques de intercepción del código de autorización.
3. **Principio de Mínimo Privilegio (Solo Lectura):**
   * Se solicitan estrictamente los scopes:
     * `https://www.googleapis.com/auth/youtube.readonly`
     * `https://www.googleapis.com/auth/yt-analytics.readonly`
   * Si la respuesta de Google no incluye todos los permisos requeridos, el backend rechaza la conexión con `InsufficientPermissionsError`.
4. **Regla de Preservación de Refresh Tokens:**
   * Cuando un usuario repite el flujo de autorización para un canal previamente conectado, Google típicamente emite un nuevo `access_token` pero puede omitir el `refresh_token` (si el consentimiento ya había sido otorgado).
   * **El servicio `OAuthService` detecta esta condición y conserva el `encrypted_refresh_token` previamente persistido**, evitando que quede en `None` y garantice la continuidad operativa sin obligar al usuario a revocar accesos en Google Security.
5. **Renovación Transparente y Desconexión en Dos Fases:**
   * El método `get_valid_access_token` comprueba el tiempo restante de expiración. Si el token vence en menos de 60 segundos (o ya venció), realiza la llamada de refresco a `https://oauth2.googleapis.com/token`, cifra el nuevo `access_token` y actualiza la fecha de vencimiento en la base de datos.
   * **Semántica Explícita de Desconexión:** La desconexión separa claramente:
     1. **Revocación remota:** Intenta revocar ante Google (`https://oauth2.googleapis.com/revoke` vía POST body con el `refresh_token` raíz).
     2. **Purga local obligatoria:** Elimina de inmediato los textos cifrados (`encrypted_access_token = None`, `encrypted_refresh_token = None`, `token_expires_at = None`) y desactiva la conexión en la base de datos local.
     3. La respuesta API (`DisconnectResponse`) informa transparentemente si la revocación remota fue confirmada (`remote_revoked: True/False`) y que la desconexión local se ejecutó (`local_disconnected: True`), sin afirmar falsamente un éxito remoto si Google no respondió o rechazó la petición.
6. **Autenticación Estricta de Rutas e Inmunidad a IDOR:**
   * Los endpoints `/authorize`, `/status` y `/disconnect` obtienen la identidad del usuario exclusivamente de la dependencia `CurrentUserDep`.
   * En entornos de desarrollo y pruebas, `CurrentUserDep` permite la cabecera `X-User-Id` validándola contra usuarios reales y activos en la base de datos.
   * **En producción, la cabecera `X-User-Id` está terminantemente prohibida (retorna `HTTP 403 Forbidden`)**, exigiendo una sesión verificada por el servidor para evitar que un cliente elija arbitrariamente su identidad.

---

## Consecuencias

### Positivas
* Los tokens de acceso y actualización residen en la base de datos exclusivamente como ciphertexts autenticados de AES-256-GCM.
* La rotación de claves puede ejecutarse de forma programada gracias al encabezado `key_id`.
* La vinculación por AAD bloquea el secuestro de credenciales entre cuentas de usuario.
* La API REST nunca expone tokens a clientes web o JavaScript, cumpliendo los principios de mínima exposición y defensa en profundidad.

### Negativas / Compromisos
* Requiere gestionar de forma rigurosa la variable de entorno `MICONTE_TOKEN_ENCRYPTION_KEY` en despliegues e infraestructura de producción (evitando pérdida de la clave que impediría descifrar los refresh tokens).
