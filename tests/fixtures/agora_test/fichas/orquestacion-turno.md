# Ficha: orquestacion-turno

## Qué hace

Orquesta un turno completo de debate en un canal: recibe un mensaje del usuario (nuevo o repetición de uno anterior), decide quién habla en base al roster y las menciones `@nombre`, construye el contexto para cada tertuliano, llama al LLM en streaming, persiste las respuestas en BD y transmite todo al frontend por SSE. Es el corazón de Agora: multiagente, round-robin con menciones.

## Ficheros

- `backend/api/stream.py` — Endpoints HTTP `post_message()` y `post_round()` que reciben peticiones del frontend
- `backend/services/orchestrator.py` — `run_turn()` (orquestación principal), `parse_mention()` (detección de menciones), `_normalize()` (normalización de nombres)

## Funciones tronco

### `post_message(channel_id: int, request: TurnRequest) -> StreamingResponse` — `backend/api/stream.py`

- **Recibe:** ID de canal, objeto TurnRequest con el contenido del mensaje humano
- **Devuelve:** StreamingResponse (SSE) que fluye directamente desde `run_turn()`
- **Qué hace, paso a paso:**
  1. Valida que el canal existe (GET a `get_channel()`)
  2. Si no existe, lanza 404
  3. Llama a `run_turn()` con el contenido del mensaje, `save_human=True` (guarda el mensaje antes de procesar)
  4. Envuelve el generador async en una StreamingResponse con headers SSE estándar
- **Llama a:** 
  - acceso-datos: `get_channel()`
  - esta pieza: `run_turn()`

### `post_round(channel_id: int) -> StreamingResponse` — `backend/api/stream.py`

- **Recibe:** ID de canal
- **Devuelve:** StreamingResponse (SSE) desde `run_turn()`
- **Qué hace, paso a paso:**
  1. Valida que el canal existe
  2. Si no existe, lanza 404
  3. Obtiene el último mensaje humano del canal (GET a `get_last_human_message()`)
  4. Si no hay mensajes previos, lanza 400 ("No hay mensajes en este canal")
  5. Llama a `run_turn()` reutilizando el contenido de ese último mensaje, pero con `save_human=False` (no lo guarda de nuevo)
  6. Envuelve el generador en StreamingResponse con headers SSE
- **Llama a:** 
  - acceso-datos: `get_channel()`, `get_last_human_message()`
  - esta pieza: `run_turn()`

### `run_turn(channel_id: int, human_content: str, save_human: bool = True) -> AsyncGenerator[str, None]` — `backend/services/orchestrator.py`

- **Recibe:**
  - `channel_id`: identificador del canal
  - `human_content`: contenido del mensaje humano (puede ser nuevo o repetido)
  - `save_human`: booleano que indica si guardar el mensaje en BD antes de procesar (True en `post_message()`, False en `post_round()`)
- **Devuelve:** Generador async de strings (eventos SSE formateados como JSON)
- **Qué hace, paso a paso:**
  1. Obtiene el objeto channel completo (GET a `get_channel()`)
  2. **Dispara compresión de contexto** (llama a `maybe_compress()` con el `mode` del canal) — esto ocurre ANTES de todo lo demás
  3. Si `save_human=True`, guarda el mensaje humano en BD con rol "human"
  4. Obtiene el roster activo del canal (perfiles ordenados por `speaking_order`)
  5. Crea un mapeo `{profile_id → profile_name}` para el contexto
  6. Si el roster está vacío, emite evento `TURN_COMPLETE` con coste total y retorna
  7. Parsea menciones en el contenido: busca un patrón `@nombre`
  8. Determina la lista de hablantes:
     - Si hay una mención válida (perfil encontrado en roster): solo ese perfil habla
     - Si no hay mención o no es reconocida: todos los perfiles del roster hablan (en orden de `speaking_order`)
  9. Para cada hablante:
     - Obtiene el resumen más reciente (si existe)
     - Obtiene los mensajes de contexto desde el resumen o desde el inicio
     - Construye el prompt (system + api_messages) con `build_context()` (pieza construccion-prompt)
     - Emite evento `start` con ID y nombre del perfil
     - Fluye tokens desde `stream_turn()` del LLM (pieza cliente-llm)
     - Acumula tokens y metadatos de uso (tokens_in, tokens_out, coste)
     - Guarda la respuesta completa en BD con rol "persona"
     - Emite evento `done` con token counts y coste
  10. Después de todos los hablantes, emite evento `TURN_COMPLETE` con coste total del canal
- **Llama a:**
  - acceso-datos: `get_channel()`, `get_active_roster()`, `get_context_messages()`, `get_latest_summary()`, `get_total_cost_usd()`, `insert_message()` (×N, una por cada hablante)
  - construccion-prompt: `build_context()` (×N)
  - cliente-llm: `stream_turn()` (×N)
  - compresion-contexto: `maybe_compress()` (una sola vez, al inicio)

### `parse_mention(text: str, roster: list[dict]) -> dict | None` — `backend/services/orchestrator.py`

- **Recibe:** 
  - `text`: contenido del mensaje humano
  - `roster`: lista de dicts con perfiles (incluye campos como `id`, `name`, `model`, `temperature`, etc.)
- **Devuelve:** El dict del perfil mencionado, o None si no hay mención o no es reconocida
- **Qué hace, paso a paso:**
  1. Extrae un patrón `@(\S+)` del texto (busca `@` seguido de caracteres no-espacio)
  2. Si no hay coincidencia, retorna None
  3. Normaliza el nombre capturado (elimina acentos, convierte a minúsculas, quita puntuación final)
  4. Busca en el roster un perfil cuyo nombre (también normalizado) coincida
  5. Retorna el perfil encontrado o None si no hay coincidencia
- **Llama a:** ninguna (solo funciones internas: `_normalize()`, regex, búsqueda en lista)

## Datos que toca

**Lee:**
- Tabla `channels` — obtiene modo (debate/crítica), incognito flag, etc.
- Tabla `channel_profiles` (con JOIN a `profiles`) — roster activo, ordenado por `speaking_order`
- Tabla `messages` — mensajes de contexto, último mensaje humano, para reconstruir la conversación
- Tabla `summaries` — resumen/acta más reciente, para saber desde dónde cargar contexto nuevo

**Escribe:**
- Tabla `messages` — inserta mensajes de rol "human" (si `save_human=True`) y "persona" (respuestas del LLM) con metadatos (tokens, coste, profile_id)

**En memoria:**
- `speakers` — lista de profiles a hablar en este turno (puede ser 1 si hay mención, o N si es todo el roster)
- `full_text` — acumula tokens de cada hablante para persistir la respuesta completa
- `usage` — dict con metadatos de la API (tokens_in, tokens_out, cost_usd, cache_write, cache_read)

## Entradas y salidas de la pieza

- **Quién la llama:** 
  - Frontend HTTP POST `/channels/{channel_id}/messages` → `post_message()`
  - Frontend HTTP POST `/channels/{channel_id}/rounds` → `post_round()`
- **A quién llama:**
  - acceso-datos: todas las queries CRUD (canales, roster, mensajes, resúmenes, costes)
  - construccion-prompt: `build_context()` para armar el prompt de cada tertuliano
  - cliente-llm: `stream_turn()` para llamar a Anthropic en streaming
  - compresion-contexto: `maybe_compress()` al inicio de cada turno (antes de construir contexto)

## Lo no obvio

1. **Orden de habla determinístico:** El orden exacto viene del campo `speaking_order` en `channel_profiles`, ordenado en la query `get_active_roster()`. No es aleatorio ni configurable desde `run_turn()`.

2. **Compresión antes de contexto:** `maybe_compress()` se dispara al inicio de `run_turn()`, antes de leer mensajes o construir contexto. Esto asegura que si la conversación es muy larga, se resume ANTES de armarse el prompt del primer hablante.

3. **Mención reemplaza roster:** Si hay una mención válida `@nombre`, solo esa persona habla en ese turno. No hay "repetición de turno" ni reordenamiento; es un cambio de speakers de forma determinística. Una mención no reconocida (`@nombreinvalido`) se ignora silenciosamente y habla todo el roster.

4. **`save_human` permite rondas sin nuevo mensaje:** `post_round()` reutiliza el último mensaje humano sin guardarlo de nuevo (`save_human=False`). Esto permite iterar con el mismo estímulo.

5. **Streaming real:** Los tokens se yielden en tiempo real desde `stream_turn()` mediante eventos SSE. El cliente JavaScript recibe un flujo continuo de `{type: 'token', profile_id, token}`, lo que permite UI reactivo.

6. **Persistencia tras streaming:** La respuesta completa se guarda en BD (en `insert_message()`) después de que el streaming termine, con metadatos de tokens y coste. Si hay error durante el streaming, se loguea pero el flujo no se reversa (error en `cliente-llm` levanta excepción que sube al handler de FastAPI).

7. **Resumen rodante:** Si existe un resumen (tabla `summaries`), el contexto se carga desde `covers_up_to_msg_id` del resumen, no desde el inicio. Esto corta automáticamente la ventana de contexto sin necesidad de parámetros.

8. **Sin límite de rondas en endpoint:** `post_round()` es stateless; el cliente controla cuántas veces lo invoca. No hay throttle visible en este código.

## Respuestas a las preguntas del Despiezador

**1. ¿Cómo decide `run_turn()` el orden exacto de habla (usa `speaking_order` del roster tal cual)?**

Sí. La query `get_active_roster()` en `backend/db/queries/channels.py` (línea 36-50) retorna los perfiles ordenados por `ORDER BY cp.speaking_order`. En `run_turn()`, la línea 63 itera por ese orden sin reordenamiento. Si hay mención, solo habla ese perfil (línea 60); si no, hablan todos en el orden de `speaking_order`.

**2. ¿Qué hace `parse_mention()` cuando detecta un `@nombre` — reordena, prioriza o repite turno?**

Devuelve el perfil encontrado. En `run_turn()` líneas 59-61, si hay mención, esa persona se convierte en la única hablante de ese turno (no como prioridad en una ronda, sino como reemplazo del roster completo). No hay reordenamiento ni repetición; es un cambio binario: "todos hablan" → "solo este habla".

**3. El mapa señala que `post_round()` no parece tener tope de rondas — ¿se confirma, y qué pasa si el usuario pide muchas rondas seguidas?**

Confirmado. `post_round()` es un endpoint de un solo turno, no una estructura de loop. Una "ronda" es una invocación del endpoint. No hay rate limiting, contador de máximo, ni control de concurrencia visible en este código. Si el cliente lo invoca 100 veces seguidas, 100 turnos se ejecutarán (limitados por la capacidad del servidor, el crédito de API Anthropic y nginx timeouts).

**4. ¿En qué punto exacto del flujo de `run_turn()` se llama a `maybe_compress()` (antes o después de construir el contexto)?**

Se llama en la línea 40 de `orchestrator.py`, inmediatamente después de obtener el channel (línea 39) y ANTES de cualquier otra operación: antes de guardar el mensaje humano, antes de cargar el roster, antes de construir contexto. Es lo primero que ocurre en el turno.

## Dudas

Ninguna — el código es claro y las funciones están bien demarcadas. La integración con otras piezas es mediante llamadas explícitas que respeto (no sigo dentro de otras piezas).
