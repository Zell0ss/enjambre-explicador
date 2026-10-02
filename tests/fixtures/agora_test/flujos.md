# Flujos de agora

Todos los saltos están confirmados abriendo el código en `/data/agora/backend/`. Agora no tiene jobs, cron, `BackgroundTasks` ni `create_task` (comprobado con grep). El flujo 3 es lo más parecido a un disparo "no humano": un efecto lateral que arranca solo dentro de un turno.

## Flujo 1 — Turno de debate (mensaje del usuario)
**Por qué este:** es el producto: el round-robin de tertulianos con menciones por SSE.
**Arranca en:** `POST /channels/{channel_id}/messages` con `TurnRequest{content}`.
**Termina en:** una fila `human` y N filas `persona` en `messages` (con tokens y coste), y un stream SSE cerrado con `TURN_COMPLETE`.

### Esquema

frontend POST /channels/{id}/messages
    ↓
post_message()                 ← comprueba que el canal existe (404 si no)
    ↓
StreamingResponse(run_turn())  ← el generador se ejecuta al consumir el stream, no antes
    ↓
run_turn()
    ├─ get_channel()
    ├─ maybe_compress()        ← ver flujo 3
    ├─ insert_message(human)
    ├─ get_active_roster()
    ├─ parse_mention()         ← 1 hablante si hay @nombre válido, si no todo el roster
    └─ por cada hablante:
         get_latest_summary() → get_context_messages(after=covers_up_to_msg_id)
              ↓
         build_context()       ← system (andamio) + bloques con cache_control
              ↓
         stream_turn()         ← Anthropic en streaming; yield tokens y al final dict usage
              ↓
         insert_message(persona, tokens, coste)
              ↓
         SSE done
    ↓
get_total_cost_usd() → SSE TURN_COMPLETE

### Paso a paso
1. **`post_message()`** en `backend/api/stream.py` — pieza `orquestacion-turno`
   Recibe `channel_id` y `request.content`. Llama a `get_channel()` y lanza 404 si no existe. Devuelve `StreamingResponse(run_turn(channel_id, request.content), media_type="text/event-stream")` con `X-Accel-Buffering: no`.
2. **`get_channel()`** en `backend/db/queries/channels.py` — pieza `acceso-datos`
   `SELECT * FROM channels`. Se llama dos veces: en el endpoint y otra vez al empezar `run_turn()`.
3. **`run_turn()`** en `backend/services/orchestrator.py` — pieza `orquestacion-turno`
   Es un generador async. Todo lo que sigue ocurre ya con la respuesta HTTP 200 abierta.
4. **`maybe_compress(channel_id, mode)`** en `backend/services/compressor.py` — pieza `compresion-contexto`
   Es lo primero que se hace, antes de guardar el mensaje humano. Puede insertar una fila en `summaries`. Ver flujo 3.
5. **`insert_message(role="human")`** en `backend/db/queries/messages.py` — pieza `acceso-datos`
   Solo si `save_human=True`, que es el caso de este flujo.
6. **`get_active_roster()`** en `backend/db/queries/channels.py` — pieza `acceso-datos`
   Devuelve perfiles completos (`p.*` más `speaking_order`) con `cp.active` y `NOT p.archived`, ordenados por `speaking_order`. Si el roster está vacío, emite `TURN_COMPLETE` y termina sin llamar a ningún modelo.
7. **`parse_mention()`** en `backend/services/orchestrator.py` — pieza `orquestacion-turno`
   Regex `@(\S+)` sobre el texto humano. Compara el nombre sin acentos y en minúsculas con los del roster. `speakers = [mention] if mention else roster`. Una mención desconocida no da error y habla todo el roster.
8. **Bucle por hablante**, en `run_turn()`:
   - `get_latest_summary()` y `get_context_messages(after_msg_id=summary.covers_up_to_msg_id)`, ambas en `backend/db/queries/messages.py`. Se repiten **por cada hablante**, así que el segundo tertuliano ya ve lo que dijo el primero en este mismo turno, porque este se guarda al terminar su stream.
   - **`build_context()`** en `backend/services/andamio.py` — pieza `construccion-prompt`. Recibe `profile`, `channel`, `messages`, `profile_names` y `summary`. Devuelve `(system, [{"role":"user","content":[bloques]}])`. El system es `ANDAMIO_DEBATE` o `ANDAMIO_CRITICA` más el `system_prompt` del perfil (solo el `system_prompt` si `tipo == "facilitador"`). Los bloques van en este orden: `base_text` (con cache), acta, mensajes (el último con cache).
   - SSE `start` con `profile_id` y `profile_name`.
   - **`stream_turn(system, api_messages, model, temperature)`** en `backend/services/llm.py` — pieza `cliente-llm`. Abre `client.messages.stream(max_tokens=1024)`, omite `temperature` si el modelo está en `_MODELS_NO_TEMPERATURE`, y hace `yield` de cada `str`. Al final hace `yield` de un `dict` con `tokens_in`, `tokens_out`, `cost_usd`, `cache_write` y `cache_read`. `run_turn()` distingue ambos con `isinstance(chunk, str)`.
   - Cada `str` sale como SSE `token`. Si hay excepción, se loguea y se **re-lanza**: el stream se corta sin evento `error`.
   - **`insert_message(role="persona", profile_id, tokens_in, tokens_out, cost_usd)`**: se guarda el texto completo después de terminar el stream.
   - SSE `done` con tokens y coste.
9. **`get_total_cost_usd()`** en `backend/db/queries/messages.py` — pieza `acceso-datos`
   `SUM(cost_usd)` del canal. Se emite como SSE `TURN_COMPLETE`. Fin.

### El punto clave
Una sola petición HTTP sostiene todo el turno: la BD se lee y se escribe a mitad de stream. La BD es el canal de comunicación entre hablantes del mismo turno, porque cada persona se inserta antes de que empiece la siguiente y `get_context_messages` se relee en cada vuelta. El prompt que ve cada tertuliano se arma por hablante, no por turno.

Si un modelo falla a mitad, los hablantes anteriores ya están guardados y el siguiente no. No hay transacción, y el cliente solo ve el corte de conexión.

Variante: **`post_round()`** (`POST /channels/{id}/rounds`, mismo fichero) busca `get_last_human_message()` y llama a `run_turn(..., save_human=False)`. Reutiliza el texto del último mensaje humano, así que una `@mención` de ese mensaje vuelve a aplicarse en cada ronda.

---

## Flujo 2 — Síntesis / export de un canal
**Por qué este:** es el flujo que cruza más piezas distintas en una sola petición: API, datos (6 queries), perfil especial, cliente LLM y caché.
**Arranca en:** `POST /channels/{channel_id}/synthesize`.
**Termina en:** markdown con frontmatter, devuelto como stream SSE, y fila en `channel_syntheses` (si no venía de caché).

### Esquema

frontend POST /channels/{id}/synthesize
    ↓
synthesize()                  ← 404 si no hay canal
    ↓
run_synthesis()               ← generador SSE
    ├─ get_channel()          (segunda vez)
    ├─ get_moderador_profile()   ← perfil con funcion LIKE '%moderador%'
    ├─ get_full_transcript()
    ├─ get_last_message_id()
    ├─ get_synthesis_cache()  ── up_to_msg_id == last_msg_id ──► SSE start/token(todo)/done, FIN
    ├─ get_active_roster()    ← solo para nombres y líneas de postura
    ├─ _SYNTHESIS_PROMPT.format(...)
    ├─ stream_turn(system=moderador.system_prompt, model=moderador.model)
    │        └─ SSE token por token
    └─ save_synthesis(channel_id, texto, last_msg_id)
    ↓
SSE done

### Paso a paso
1. **`synthesize()`** en `backend/api/synthesize.py` — pieza `sintesis-export`
   Comprueba el canal con `get_channel()` (404 si no existe) y devuelve `StreamingResponse(run_synthesis(channel_id))`.
2. **`run_synthesis()`** en `backend/services/synthesizer.py` — pieza `sintesis-export`
   Hace en orden `get_channel`, `get_moderador_profile`, `get_full_transcript` y `get_last_message_id`. Cada fallo sale como SSE `error` con `return` (sin Moderador, sin mensajes).
3. **`get_moderador_profile()`** en `backend/db/queries/profiles.py` — pieza `acceso-datos`
   `WHERE LOWER(funcion) LIKE '%moderador%' AND archived = FALSE LIMIT 1`. Da el `system_prompt`, `model` y `temperature` que se usarán.
4. **`get_synthesis_cache()`** en `backend/db/queries/channels.py` — pieza `acceso-datos`
   Si `cached["up_to_msg_id"] == last_msg_id`, se envían `start`, un único `token` con todo el contenido y `done`, y no se llama a Anthropic.
5. **`get_active_roster()`** en `backend/db/queries/channels.py` — pieza `acceso-datos`
   Se usa solo para nombres y `posture_lines` de la plantilla.
6. **`stream_turn()`** en `backend/services/llm.py` — pieza `cliente-llm`
   Recibe `system=moderador["system_prompt"]` y `messages=[{"role":"user","content": <str>}]` (aquí el contenido es un string, no bloques como en el flujo 1). Los tokens salen como SSE `token`. Se ignora el `dict` de coste: **no se guarda coste** de la síntesis. Los errores se convierten en SSE `error` (aquí sí hay evento, a diferencia del flujo 1).
7. **`save_synthesis()`** en `backend/db/queries/channels.py` — pieza `acceso-datos`
   `INSERT ... ON DUPLICATE KEY UPDATE`, una fila por canal. Solo se llama si hubo texto y `last_msg_id` no es None. Después sale SSE `done`.

### El punto clave
La caché se valida contra el último `id` de mensaje: nueva conversación equivale a regenerar. Además hay un segundo invalidador en otra pieza: **`patch_channel()`** (`backend/api/channels.py:63`) llama a `delete_synthesis_cache()` cuando se modifica `base_text`. Es el único llamador de ese borrado en todo el backend.

Cosas que se ven solo al cruzar piezas:
- `stream_turn()` fija `max_tokens=1024`, también para la síntesis, así que una síntesis larga se trunca y el texto truncado se guarda en caché como válido.
- El Moderador es solo un perfil de la tabla `profiles`. Nada impide que esté en un roster (ver discrepancias).
- La síntesis lee la transcripción completa y no pasa por el acta de `summaries`.

---

## Flujo 3 — Compresión de contexto (acta rodante, disparo implícito)
**Por qué este:** es lo único que se dispara sin que el usuario lo pida; no hay job real, se engancha a cada turno.
**Arranca en:** `maybe_compress()`, llamada al inicio de `run_turn()` (flujo 1) en cada `POST /messages` o `/rounds`.
**Termina en:** una fila nueva en `summaries` (acta + `covers_up_to_msg_id`), o en nada (por debajo del umbral, fallo de Haiku o acta vacía).

### Esquema

run_turn()
    ↓
maybe_compress(channel_id, mode)
    ├─ get_latest_summary()
    ├─ count_messages_after(covers_up_to_msg_id)
    │      < 30 → return
    ├─ get_messages_chunk(limit=20)   ← los 20 más antiguos sin comprimir (JOIN profiles)
    ├─ _update_acta(acta_previa, chunk, mode)
    │      └─ _build_user_message() → _client.messages.create(Haiku, no streaming)
    │      excepción → log error y return (el turno sigue)
    │      texto vacío → warning y return
    └─ insert_summary(channel_id, acta, covers_up_to_msg_id = chunk[-1].id)
    ↓
(vuelve a run_turn; en cada hablante get_latest_summary() ya ve el acta nueva)

### Paso a paso
1. **`maybe_compress()`** en `backend/services/compressor.py` — pieza `compresion-contexto`
   Recibe `channel_id` y `mode`. Lee el último resumen y cuenta con `count_messages_after()` los mensajes con `id` mayor que `covers_up_to_msg_id` (todos si no hay resumen). Cuenta todos los roles, incluidos `human` y `system`.
2. **`get_messages_chunk()`** en `backend/db/queries/messages.py` — pieza `acceso-datos`
   Devuelve como mucho 20 filas ordenadas por `id`, con `profile_name` por JOIN.
3. **`_update_acta()`** en `backend/services/compressor.py` — pieza `compresion-contexto`
   Llama directamente a `AsyncAnthropic.messages.create()` con Haiku (cliente propio `_client`, no `stream_turn()`). Pasa el acta anterior y el chunk, y recibe el acta completa reescrita.
4. **`insert_summary()`** en `backend/db/queries/messages.py` — pieza `acceso-datos`
   Se inserta una fila **nueva**, no se actualiza la anterior. `get_latest_summary()` coge la de `created_at` más reciente.
5. De vuelta en `run_turn()`: para cada hablante, `get_latest_summary()` devuelve la nueva acta. `get_context_messages(after=covers_up_to_msg_id)` solo trae lo posterior, y `build_context()` mete el acta como bloque 2.

### El punto clave
La compresión es síncrona respecto al turno: el usuario espera esa llamada a Haiku antes de que empiece el primer token del primer tertuliano, y lo hace con la respuesta HTTP ya abierta. Su fallo es silencioso para el usuario (solo log).

Cada turno comprime como mucho un chunk de 20, aunque haya más de 30 pendientes. Con el umbral de 30 y el chunk de 20 quedan al menos 10 mensajes sin comprimir y el contexto crece hasta que se vuelve a alcanzar el umbral.

El coste de Haiku **no se registra** en `messages.cost_usd`, así que `TURN_COMPLETE.total_cost_usd` (suma de `messages`) lo infravalora. Lo mismo pasa con la síntesis (flujo 2).

---

## Discrepancias con las fichas
- **`sintesis-export`, "Lo no obvio" 4:** dice que `orquestacion-turno` excluye al Moderador del round-robin. No es así: `run_turn()` recorre `get_active_roster()` sin filtrar por `funcion` ni `tipo`. Un perfil Moderador metido en un roster hablaría como cualquier otro.
- **`cliente-llm`, "Llama a":** dice que el cliente está en `backend/config.py`. Está en `backend/services/llm.py` (`client = anthropic.AsyncAnthropic(...)`).
- **`cliente-llm`, entrada de `messages`:** la ficha describe `{"role","content": "..."}` con string. En el flujo de turno `content` es una lista de bloques con `cache_control` (la produce `build_context()`). Solo el Moderador usa string.
- **`acceso-datos`, dudas y "Lo no obvio" 5:** pregunta quién invoca `delete_synthesis_cache()` y supone que es `sintesis-export`. Lo llama `patch_channel()` en `backend/api/channels.py:63`, y `sintesis-export` nunca lo llama.
- **`orquestacion-turno`, "Lo no obvio" 6:** dice que el error del stream "sube al handler de FastAPI". La respuesta ya está iniciada (200), así que el efecto es que la conexión se corta sin evento SSE de error. El error de síntesis sí sale como evento `error`.
- **`sintesis-export`, "Lo no obvio" 2:** dice "en el siguiente GET /synthesize", pero el endpoint es `POST`.
- **`api-entidades`, "Lo no obvio" 2 y pregunta 2:** consistente con el código, pero la ficha afirma que `delete_channel` "probablemente" cascada. `delete_channel()` borra `summaries` explícitamente y delega en el esquema para `messages` y `channel_profiles`. La cascada del esquema no la he comprobado en `init.sql`: no confirmado.
- **Hueco compartido sin resolver:** el origen del perfil Moderador en producción no está en el repo. `init.sql` solo siembra a Sócrates, según las fichas; solo he visto `get_moderador_profile()` y `CLAUDE.md` de agora, que lo menciona como perfil de "utilidad". No he abierto `init.sql`: no confirmado.
