# Ficha: arranque-config

## Qué hace
Levanta la aplicación FastAPI, carga los parámetros de configuración desde el archivo `.env` (credenciales de BD, API key de Anthropic), inicializa el pool de conexiones a MariaDB al arrancar, y configura el logging JSON centralizado que envía los eventos a través de LogCentral.

## Ficheros
- `backend/main.py` — punto de entrada de la app FastAPI, define el ciclo de vida y monta los routers
- `backend/config.py` — esquema Pydantic que valida y expone la configuración del `.env`
- `backend/logger.py` — configura loguru con un sink personalizado que escribe logs en formato JSON

## Funciones tronco

### `lifespan(app: FastAPI)` — `backend/main.py`
- **Recibe:** la instancia de FastAPI
- **Devuelve:** generador async (context manager)
- **Qué hace, paso a paso:**
  1. Al arrancar: invoca `await init_pool()` para inicializar el pool de conexiones async a MariaDB
  2. Registra un log "startup: DB pool initialized"
  3. Cede el control a la app (yield)
  4. Al parar: invoca `await close_pool()` para cerrar todas las conexiones del pool
- **Llama a:** 
  - `init_pool()` (pieza acceso-datos)
  - `close_pool()` (pieza acceso-datos)
  - `logger.info()` (dentro de esta pieza)

### `Settings` — `backend/config.py`
- **Recibe:** nada (se instancia desde `.env` via Pydantic)
- **Devuelve:** objeto Settings con los parámetros validados
- **Qué hace, paso a paso:**
  1. Define un esquema Pydantic que mapea variables del `.env`
  2. Especifica qué campos son obligatorios y cuáles tienen default
  3. Valida tipos (str, int) antes de exponerlos
  4. Lanza ValidationError si falta alguna variable requerida
- **Campos:**
  - Obligatorios: `anthropic_api_key`, `db_user`, `db_password`
  - Opcionales (con defaults): `db_host="localhost"`, `db_port=3306`, `db_name="tertulia_db"`

### `settings` — `backend/config.py`
- **Recibe:** nada
- **Devuelve:** instancia singleton de Settings
- **Qué hace:** expone la configuración validada como un módulo que importan el resto de piezas

### `_json_sink(message)` — `backend/logger.py`
- **Recibe:** un objeto `message` de loguru
- **Devuelve:** nada (efecto: escribe una línea en el fichero de log)
- **Qué hace, paso a paso:**
  1. Extrae el registro (record) del mensaje de loguru
  2. Construye un diccionario con: timestamp (ISO 8601 UTC, milisegundos), level, source="tertulia", message
  3. Abre el fichero `logs/tertulia.log` en modo append
  4. Escribe el diccionario como JSON en una sola línea
  5. Cierra el fichero
- **Formato del JSON:**
  ```json
  {
    "timestamp": "2025-10-02T15:30:45.123Z",
    "level": "INFO",
    "source": "tertulia",
    "message": "startup: DB pool initialized"
  }
  ```

## Datos que toca
- **Lee:** variables de entorno desde `.env` (vía Pydantic BaseSettings)
- **Escribe:** logs JSON línea a línea en `logs/tertulia.log`
- **Inicializa:** pool de conexiones async a MariaDB (coordinado con acceso-datos)

## Entradas y salidas de la pieza
- **Quién la llama:**
  - Uvicorn (servidor ASGI), invoca lifespan al arrancar/parar
  - Cualquier módulo que importe `settings` de config.py o `logger` de logger.py
- **A quién llama:**
  - `acceso-datos`: init_pool() y close_pool()
  - `api-entidades`, `orquestacion-turno`, `sintesis-export` (indirectamente, a través de app.include_router)

## Lo no obvio

1. **El ciclo de vida es hook FastAPI.** `lifespan()` es el mecanismo oficial de FastAPI 0.93+ para ejecutar código al arrancar/parar; sustituye a `startup` y `shutdown` events. Garantiza que el pool se cierre incluso si la app crashea.

2. **Validación temprana de `.env`.** Si falta `anthropic_api_key`, `db_user` o `db_password`, Pydantic levanta ValidationError al instanciar `settings`. Esto ocurre antes de que FastAPI haya siquiera creado la app, bloqueando el arranque. Eso es a propósito: mejor fallar temprano que descubrir la falta en el primer request.

3. **JSONL, no JSON.** El logger escribe un objeto JSON por línea (línea-delimitado), no un array. Cada evento es autocontenido. El archivo crece de forma streaming.

4. **"source" es hardcoded.** Todos los eventos de esta app llevan `"source": "tertulia"` en el JSON. LogCentral (u otra herramienta) usa ese campo para agrupar/filtrar logs de este servicio frente a otros.

5. **Sin integración directa con LogCentral en el código.** El JSON se escribe en local (`logs/tertulia.log`); un agente externo (Syncthing, LogStash, logcentral-client) lee ese archivo y lo envía a LogCentral. Esta pieza solo produce el JSON.

## Respuestas a las preguntas del Despiezador

### ¿Qué hace exactamente `lifespan()` al arrancar y al parar, más allá de abrir/cerrar el pool?
Solo eso: abre el pool con `init_pool()` y lo cierra con `close_pool()`. Antes y después de ceder control con `yield`, no hay más operaciones.

### ¿Qué variables de `Settings` son obligatorias y qué pasa si falta alguna en el `.env`?
- **Obligatorias (sin default):** `anthropic_api_key`, `db_user`, `db_password`
- **Opcionales (con default):** `db_host="localhost"`, `db_port=3306`, `db_name="tertulia_db"`
- **Si falta una requerida:** Pydantic BaseSettings levanta `ValidationError` al instanciar `settings`, que ocurre en el import, bloqueando el arranque del proceso antes de que FastAPI siquiera arranque.

### ¿Cómo llega el JSON de `_json_sink()` hasta LogCentral (formato exacto, transporte)?
- **Formato exacto:** JSON línea-delimitado con campos `timestamp` (ISO 8601 UTC ms), `level`, `source="tertulia"`, `message`
- **Transporte desde el código:** No hay. Este módulo solo escribe en `logs/tertulia.log` localmente. La integración con LogCentral es externa: un agente (posiblemente basado en Syncthing o logcentral-client, vivo en `STACK.md`) lee el archivo y lo envía al servicio centralizador.

## Dudas
Ninguna — el código es claro y autocontenido. La única incógnita es cómo exactamente LogCentral consume `logs/tertulia.log`, pero eso es infraestructura de despliegue fuera de este repo (probablemente configurada en `STACK.md` o el playbook de despliegue).
