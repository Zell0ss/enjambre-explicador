# Ficha: Síntesis y export

## Qué hace

Genera un documento markdown final de un canal de tertulia (frontmatter YAML + decisiones, posturas, fricción, gestalt) usando el perfil especial "Moderador". Devuelve el resultado en streaming SSE para exportar a Obsidian. La síntesis se cachea automáticamente: se reutiliza si no hay mensajes nuevos desde que se generó, y se regenera cuando la conversación avanza.

## Ficheros

- `backend/api/synthesize.py` — Endpoint HTTP POST `/channels/{channel_id}/synthesize` que valida el canal y devuelve StreamingResponse
- `backend/services/synthesizer.py` — Lógica de síntesis: `run_synthesis()` (async generator), `_SYNTHESIS_PROMPT` (plantilla del prompt), `get_moderador_profile()` importado de acceso-datos

## Funciones tronco

### `synthesize(channel_id)` — `backend/api/synthesize.py`
- **Recibe:** `channel_id` (int, ruta HTTP)
- **Devuelve:** `StreamingResponse` con media type `text/event-stream`
- **Qué hace, paso a paso:**
  1. Valida que el canal exista en BD; si no, lanza `HTTPException(404)`
  2. Invoca `run_synthesis(channel_id)` (async generator)
  3. Envuelve el resultado en `StreamingResponse` con headers de cache control (`no-cache`, `no` buffering en nginx)
- **Llama a:** 
  - `get_channel(channel_id)` — acceso-datos
  - `run_synthesis(channel_id)` — esta pieza (synthesizer.py)

### `run_synthesis(channel_id)` — `backend/services/synthesizer.py`
- **Recibe:** `channel_id` (int)
- **Devuelve:** `AsyncGenerator[str, None]` — genera eventos SSE en formato JSON (líneas `data: {...}\n\n`)
- **Qué hace, paso a paso:**
  1. Fetcha el canal; si no existe, yield error `"Canal no encontrado"` y retorna
  2. Fetcha el perfil Moderador; si no existe, yield error `"Perfil Moderador no encontrado en la BD"` y retorna
  3. Fetcha la transcripción completa (mensajes de rol `human` y `persona` con nombres de speaker); si vacía, yield error y retorna
  4. Fetcha el ID del último mensaje en el canal (`last_msg_id`)
  5. Intenta leer de caché (`get_synthesis_cache`):
     - Si existe y `cached["up_to_msg_id"] == last_msg_id`, yield caché (completa en un bloque) con tipo `start`, `token` (contenido completo), `done`, y **retorna sin generar nueva síntesis**
     - Si no existe o es stale, continúa con síntesis nueva
  6. Fetcha el roster activo del canal (perfiles participantes ordenados por `speaking_order`)
  7. Construye el user prompt (texto) usando `_SYNTHESIS_PROMPT` (plantilla), interpolando:
     - Título del canal
     - Modo (`debate` o `crítica`)
     - Nombres de participantes (del roster) o "desconocidos"
     - Fecha actual (hoy)
     - Transcripción formateada: "Tú" si rol='human', sino nombre del speaker
     - Líneas de postura (plantilla con cada participante, una línea por nombre)
  8. Yield evento SSE `{'type': 'start'}`
  9. Itera sobre `stream_turn()` (cliente LLM) pasando:
     - `system`: el `system_prompt` del perfil Moderador
     - `messages`: un array con un único mensaje de rol `user` con el user prompt
     - `model`: del perfil Moderador
     - `temperature`: del perfil Moderador
  10. Por cada token recibido (chunk str), acumula en lista y yield evento SSE `{'type': 'token', 'token': chunk}`
  11. Si hay excepción, yield error SSE y retorna
  12. Si la síntesis se completó (lista no vacía) y `last_msg_id` no es None, llama a `save_synthesis()` con el contenido concatenado y el `last_msg_id` (para caché futura)
  13. Yield evento SSE `{'type': 'done'}`
- **Llama a:**
  - `get_channel(channel_id)` — acceso-datos
  - `get_moderador_profile()` — acceso-datos
  - `get_full_transcript(channel_id)` — acceso-datos
  - `get_last_message_id(channel_id)` — acceso-datos
  - `get_synthesis_cache(channel_id)` — acceso-datos
  - `get_active_roster(channel_id)` — acceso-datos
  - `stream_turn(system, messages, model, temperature)` — cliente-llm
  - `save_synthesis(channel_id, contenido, last_msg_id)` — acceso-datos

## Datos que toca

**Lee de BD:**
- Tabla `channels`: columnas `id`, `title`, `mode` (vía `get_channel()`)
- Tabla `profiles`: columnas `id`, `name`, `funcion`, `system_prompt`, `model`, `temperature`, `archived` (búsqueda por `funcion LIKE '%moderador%'`, vía `get_moderador_profile()`)
- Tabla `messages`: columnas `id`, `role`, `content`, `profile_id`, ordenado por `created_at` (vía `get_full_transcript()`)
- Tabla `profiles` (join con messages): columnas `name` para obtener speaker (vía `get_full_transcript()`)
- Tabla `channel_profiles`: columnas `channel_id`, `profile_id`, `active`, `speaking_order` (vía `get_active_roster()`)
- Tabla `profiles` (join con channel_profiles): nombres ordenados por `speaking_order` (vía `get_active_roster()`)
- Tabla `messages`: columnas `id` (`MAX(id)`) (vía `get_last_message_id()`)
- Tabla `channel_syntheses`: columnas `content`, `up_to_msg_id` (vía `get_synthesis_cache()`)

**Escribe a BD:**
- Tabla `channel_syntheses`: inserta o actualiza registros con `channel_id`, `content` (síntesis en markdown), `up_to_msg_id` (vía `save_synthesis()`, usa `ON DUPLICATE KEY UPDATE`)

**No toca pero depende de:**
- Variables de perfil Moderador (system_prompt, model, temperature): proceden de BD pero son datos de entrada (no se modifican)

## Entradas y salidas de la pieza

**Quién la llama:**
- Cliente HTTP (frontend) con POST `/channels/{channel_id}/synthesize`

**A quién llama:**
- `acceso-datos`: 6 funciones de lectura/escritura (get_channel, get_moderador_profile, get_full_transcript, get_last_message_id, get_synthesis_cache, get_active_roster, save_synthesis)
- `cliente-llm`: `stream_turn()` para generar la síntesis con Anthropic

**Cómo entrega la respuesta:**
- HTTP `StreamingResponse` con media type `text/event-stream`
- Eventos JSON línea a línea (formato SSE estándar): `data: {json}\n\n`
- Tipos de evento: `start` (inicio), `token` (chunk de síntesis), `done` (fin exitoso), `error` (fallo)

## Lo no obvio

1. **Búsqueda del Moderador por `funcion`, no por name:** El código busca un perfil donde `LOWER(funcion) LIKE '%moderador%'`, no por `name='Moderador'`. Esto significa que cualquier perfil con "moderador" en el campo `funcion` sirve como sintetizador. Responde a la pregunta del mapa: no hay un perfil hardcodeado con name='Moderador' en `init.sql`, sino un criterio de búsqueda flexible en el campo `funcion`.

2. **Cache basado en progresión de mensajes:** La caché se valida comparando `cached["up_to_msg_id"] == last_msg_id`. No hay flags de "invalidar manualmente" ni timestamps. Esto implica:
   - La caché se regenera automáticamente en el siguiente `GET /synthesize` después de que se añada cualquier mensaje nuevo al canal
   - Si el cliente pide síntesis consecutivas sin mensajes nuevos, siempre obtiene caché (rápido, sin costo de LLM)
   - Si el usuario quiere forzar regeneración, debe añadir un mensaje (o no hay forma con el API actual)

3. **Flujo de caché directo sin retrasos:** Si la caché es válida, `run_synthesis()` devuelve todo el contenido cacheado de una vez en un único evento SSE de tipo `token`, no token a token. Esto es más eficiente pero difiere del flujo "vivo" donde llega token por token desde Anthropic.

4. **Moderador como "utilidad," no como tertulia:** El perfil Moderador nunca participa en los turnos (orquestacion-turno lo excluye del round-robin); solo se usa aquí como invocador de síntesis. Tiene su propio system_prompt, model y temperature configurables, desacoplados de los perfiles de debate.

5. **Acumulación de tokens antes de guardar:** La síntesis se acumula en memoria (`accumulated` list) durante el streaming. Solo después de que `stream_turn()` complete (sin excepción) se guarda en caché. Si falla a mitad del streaming, no hay caché (se perderá la síntesis parcial).

6. **Transcript sin summaries (acta):** `get_full_transcript()` devuelve solo mensajes con `role IN ('human', 'persona')`, sin incluir resúmenes/actas de la tabla `summaries`. La síntesis ve la transcripción completa sin comprimir, aunque en un turno real se compriman los mensajes antiguos.

## Respuestas a las preguntas del Despiezador

### 1. ¿Cuándo se invalida o reusa la caché en `channel_syntheses`?

La caché se reusa si y solo si el `up_to_msg_id` guardado en la caché coincide con el ID del último mensaje actual del canal. En otras palabras:
- **Reutiliza:** Si no ha habido nuevos mensajes desde la última síntesis
- **Invalida (regenera):** En el siguiente `GET /synthesize` después de que se añada cualquier nuevo mensaje

El código en líneas 79-84 de `synthesizer.py` lo muestra explícitamente: `if cached and cached["up_to_msg_id"] == last_msg_id: ... return`. No hay flag de timestamp ni de invalidación manual; es un sistema basado en la progresión del conversación.

### 2. ¿De dónde sale el perfil Moderador en producción?

**No viene de un nombre hardcodeado.** La búsqueda es flexible:
```python
SELECT * FROM profiles WHERE LOWER(funcion) LIKE '%moderador%' AND archived = FALSE LIMIT 1
```
Cualquier perfil (con cualquier `name`) que tenga "moderador" (case-insensitive) en su campo `funcion` será detectado. En producción, alguien debe haber insertado un perfil en la tabla `profiles` con un valor `funcion` que contenga "moderador" (p. ej., `funcion = 'Moderador Sintesis'` o similar). Si no existe ninguno, `get_moderador_profile()` retorna `None` y `run_synthesis()` yielda error.

### 3. ¿Se puede forzar la regeneración a demanda?

**No, con el API actual.** La síntesis se regenera automáticamente cuando hay mensajes nuevos; de otro modo, se sirve caché. No hay un parámetro tipo `?force=true` ni un endpoint de `DELETE /channels/{channel_id}/synthesis-cache`. 

Si el usuario quiere forzar regeneración, tendría que:
- Agregar un mensaje dummy al canal (y luego borrarlo, aunque esto no es prácticamente viable)
- O el backend tendría que exponer un endpoint de invalidación de caché (no existe)

El comportamiento es determinista y eficiente pero no permite manual override desde la API HTTP.

## Dudas

- No hay dudas técnicas bloquedoras identificadas en el código. El comportamiento es claro y consistente. La única incógnita que queda abierta es si en producción existe un perfil con "moderador" en el campo `funcion`, pero eso es un dato de despliegue/seeds, no un problema del código.
