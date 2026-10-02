# Agora: cómo funciona por dentro

## En dos minutos

Agora es un chat web multiagente que corre en seb01, accesible solo por Tailscale. Los participantes ("tertulianos") no son personas: cada uno es una instancia de Claude (API de Anthropic) con su propia personalidad y su rol, guardados como un "perfil" en base de datos. El usuario crea un canal (una conversación), mete entre 1 y 3 tertulianos, y escribe. Los tertulianos responden uno detrás de otro, en round-robin, sobre un contexto compartido, así que cada uno puede reaccionar a lo que dijo el anterior. El canal tiene dos modos: `debate` (discutir ideas) y `critica` (analizar un texto concreto, el `base_text` del canal).

Hay dos superficies: el chat, con respuestas en streaming y export a markdown para Obsidian, y un editor de perfiles. Este artículo cuenta solo el backend (FastAPI + MariaDB).

```
navegador (React, fuera de este artículo)
   │  HTTP + SSE (por nginx, /api)
   ▼
FastAPI (backend/main.py, uvicorn en 127.0.0.1:8001)
   ├─ api/channels.py, api/profiles.py   CRUD de canales, roster y perfiles
   ├─ api/stream.py                      POST messages / rounds  ──► services/orchestrator.py
   │                                                                  ├─ compressor.py  (acta, Haiku)
   │                                                                  ├─ andamio.py     (prompt)
   │                                                                  └─ llm.py         (Anthropic, streaming)
   └─ api/synthesize.py                  POST synthesize ──► services/synthesizer.py ──► llm.py
   │
   ▼
MariaDB: profiles, channels, channel_profiles, messages, summaries, channel_syntheses
```

Una idea atraviesa todo: no hay colas, jobs, cron ni tareas en segundo plano. Todo el trabajo ocurre dentro de una petición HTTP que se queda abierta emitiendo eventos SSE (Server-Sent Events, un stream de texto `data: {...}` por HTTP).

## Las piezas

- **Arranque y configuración**: levanta la app FastAPI, carga el `.env` y configura el log JSON.
- **Acceso a base de datos**: pool async a MariaDB y todas las queries SQL, agrupadas por tabla.
- **API CRUD de canales y perfiles**: los endpoints REST de gestión, sin lógica de debate.
- **Construcción del prompt (andamio)**: decide qué system prompt y qué bloques de contexto recibe cada tertuliano.
- **Cliente del modelo**: llama a Anthropic en streaming y calcula el coste.
- **Orquestación de un turno**: el round-robin, las menciones `@nombre`, el SSE y la persistencia de las respuestas.
- **Compresión de contexto**: resume los mensajes antiguos en un "acta" rodante para que el contexto no crezca sin fin.
- **Síntesis y export**: genera el markdown final del canal con el perfil Moderador.

Relación entre ellas: arranque abre el pool de acceso a datos; la API CRUD prepara canales, perfiles y roster; la orquestación, cuando llega un mensaje, usa compresión, luego construcción del prompt y cliente del modelo por cada tertuliano, y guarda todo vía acceso a datos. Síntesis es una rama aparte que reutiliza el cliente del modelo.

## Arranque y configuración

Es la infraestructura de proceso. `backend/main.py` define `app = FastAPI()` y una función `lifespan()`, el hook de ciclo de vida de FastAPI: al arrancar llama a `init_pool()` y escribe "startup: DB pool initialized"; al parar llama a `close_pool()`. No hace nada más. Monta además los routers de las demás piezas.

`backend/config.py` define `Settings` (Pydantic) y la instancia global `settings`, que importa el resto del código. Son obligatorias `anthropic_api_key`, `db_user` y `db_password`; tienen valor por defecto `db_host="localhost"`, `db_port=3306` y `db_name="tertulia_db"`. Si falta una obligatoria, Pydantic lanza `ValidationError` en el import y el proceso no arranca: falla pronto a propósito.

`backend/logger.py` configura loguru con un sink propio, `_json_sink()`, que añade una línea JSON a `logs/tertulia.log` con `timestamp` (ISO 8601 UTC, milisegundos), `level`, `source` y `message`. El `source` está fijo en `"tertulia"`. El código no habla con LogCentral: solo escribe el fichero, y un agente externo (que este repo no describe) lo recoge.

## Acceso a base de datos

Toda la persistencia pasa por aquí. `backend/db/connection.py` tiene `init_pool()` (pool aiomysql con minsize 1 y maxsize 10, utf8mb4, `autocommit=True`), `close_pool()` y `get_db()`, un context manager async que presta un cursor `DictCursor` (filas como diccionarios) y devuelve la conexión al salir. Las queries viven en tres ficheros por tema:

- `backend/db/queries/profiles.py`: `get_profile()`, `list_profiles()`, `insert_profile()`, `update_profile()`, `archive_profile()`, `get_moderador_profile()`.
- `backend/db/queries/channels.py`: canales (`get_channel()`, `insert_channel()`, `update_channel()`, `delete_channel()`), roster (`get_active_roster()`, `get_full_roster()`, `get_roster_entry()`, `add_to_roster()`, `remove_from_roster()`, `count_active_roster()`) y caché de síntesis (`get_synthesis_cache()`, `save_synthesis()`, `delete_synthesis_cache()`).
- `backend/db/queries/messages.py`: `insert_message()`, `get_context_messages()`, `get_latest_summary()`, `insert_summary()`, `count_messages_after()`, `get_messages_chunk()`, `get_full_transcript()`, `get_last_message_id()`, `get_last_human_message()`, `get_total_cost_usd()`.

Las tablas: `profiles`, `channels`, `channel_profiles` (el roster: qué perfil está en qué canal, con `speaking_order` y `active`), `messages` (rol `human`/`persona`/`system`, tokens y `cost_usd`), `summaries` (las actas) y `channel_syntheses` (caché del export).

Lo no obvio:

- **Autocommit y sin transacciones.** Cada statement se confirma solo. `delete_channel()` borra primero `summaries` y luego el canal, en dos statements sueltos. El motivo: `summaries.covers_up_to_msg_id` es una FK con `RESTRICT` hacia `messages`, así que si se borrara el canal primero, el borrado en cascada de sus mensajes chocaría con las actas que los referencian. Con `summaries` ya vacía, el `DELETE` del canal arrastra solo, por `ON DELETE CASCADE`, a `messages`, `channel_profiles` y `channel_syntheses`; por eso el código no los borra a mano.
- **Borrado lógico.** `archive_profile()` pone `archived = TRUE` y `remove_from_roster()` pone `active = FALSE`. `add_to_roster()` usa `ON DUPLICATE KEY UPDATE`, así que re-añadir un perfil quitado lo reactiva.
- **`get_active_roster()`** filtra `cp.active` y `NOT p.archived`, ordena por `speaking_order` y devuelve el perfil completo más ese campo.
- **`save_synthesis()`** hace upsert: una fila por canal (la clave primaria es `channel_id`).
- **Sin reintentos.** Si el pool no conecta, la excepción sube y la app no arranca.

## API CRUD de canales y perfiles

Es la parte aburrida a propósito: REST clásico sin lógica de debate. `backend/api/channels.py` cubre canales (`GET/POST /channels`, `GET/PATCH/DELETE /channels/{id}`), mensajes de un canal (`GET /channels/{id}/messages`, `list_channel_messages`) y el roster (`GET/POST /channels/{id}/profiles`, `PATCH/DELETE /channels/{id}/profiles/{profile_id}`). `backend/api/profiles.py` cubre `/profiles`. Los schemas Pydantic están en `backend/schemas/models.py` (`ChannelIn/Out/Patch`, `ProfileIn/Out/Patch`, `RosterAddIn/Patch/Entry`, `TurnRequest`, `MessageOut`).

Cada función hace lo mismo: comprobar que la entidad existe (404 si no), llamar a la query y devolver el estado final releyéndolo. Lo que merece saberse:

- **Máximo 3 perfiles activos por canal.** `add_profile_to_channel()` cuenta con `count_active_roster()` y rechaza con 400 si ya hay 3.
- **`speaking_order` lo manda el cliente** (`RosterAddIn`, por defecto 0). El backend lo guarda sin validar ni recalcular; con dos perfiles con el mismo valor, el desempate no está definido en el código que se leyó.
- **`tipo` de un perfil no se puede cambiar**: `ProfilePatch` no lo incluye. `tipo` es `tertuliano` o `facilitador`.
- **`delete_profile()`** solo archiva.
- **`patch_channel()`** llama a `delete_synthesis_cache()` si cambia `base_text`. Es el único sitio del backend que invalida esa caché a mano.
- Los perfiles se crean con `model="claude-sonnet-4-6"` y `temperature=0.7` por defecto.

## Construcción del prompt (andamio)

El mismo perfil debe comportarse distinto según el canal en el que habla. `backend/services/andamio.py` resuelve eso con `build_context(profile, channel, messages, profile_names, summary=None)`, que devuelve `(system, api_messages)`.

El system prompt se elige así:

- Perfil `tipo == "facilitador"`: solo su `system_prompt`, sin andamio.
- Canal en modo `critica`: `ANDAMIO_CRITICA` + `system_prompt` del perfil.
- Cualquier otro caso: `ANDAMIO_DEBATE` + `system_prompt`.

`ANDAMIO_DEBATE` pide ser un participante auténtico de una conversación grupal: reaccionar a otros, discrepar, ser breve, mantener el sesgo propio. `ANDAMIO_CRITICA` pide analizar un texto concreto: citar, señalar qué funciona y qué falla. Ambos piden respuestas en español.

Los mensajes salen como un único mensaje `user` con una lista de bloques, en este orden:

1. `base_text` del canal, si existe, con `cache_control` efímero.
2. El acta de `summaries`, si existe, envuelta en `[Acta de la conversación] ... [Fin del acta]`, sin marca de caché.
3. Cada mensaje del historial como texto etiquetado: `human` sale siempre como "Josem: ..." (el nombre del dueño del proyecto está fijo en el código: Agora es de un solo usuario), `persona` con el nombre del tertuliano, y los `system` se ignoran. El último bloque lleva `cache_control`.
4. Si no hay mensajes, un bloque "(La conversación acaba de comenzar.)".

Dos detalles: si un `profile_id` no está en `profile_names`, el nombre cae a `"Participante {id}"`; y `build_context()` no limita ni cuenta tokens, así que quien lo llama es responsable de pasarle solo lo que quepa (en la práctica, lo posterior al último acta).

## Cliente del modelo

`backend/services/llm.py` es el único sitio que habla en streaming con Anthropic. Tiene un cliente global `client = anthropic.AsyncAnthropic(...)` y la función generadora `stream_turn(system, messages, model, temperature)`.

Hace `yield` de cada fragmento de texto como `str` y, al final, de un único `dict` con `tokens_in`, `tokens_out`, `cost_usd` (Decimal, 8 decimales), `cache_write` y `cache_read`. Quien consume distingue ambos casos con `isinstance(chunk, str)`. Internamente abre `client.messages.stream()` con `max_tokens=1024` fijo, y omite `temperature` si el modelo está en `_MODELS_NO_TEMPERATURE` (un set de modelos que no aceptan ese parámetro; las fichas no dicen cuáles contiene). El coste sale de la tabla `_COST_PER_TOKEN`, con tres claves: `"claude-haiku-4-5-20251001"`, `"claude-sonnet-4-6"` y `"claude-opus-4-8"`: entrada normal, más escritura de caché a 1,25x, más lectura de caché a 0,1x, más salida.

Lo no obvio:

- **Modelo fuera de `_COST_PER_TOKEN`: coste 0, sin error.** Un modelo nuevo se reportaría como gratis.
- **`max_tokens=1024` para todos**, incluida la síntesis, que por eso puede truncarse.
- **`temperature` se descarta en silencio** para los modelos de `_MODELS_NO_TEMPERATURE`. Si un modelo que no la acepta no está en el set, la API rechazará la llamada.
- **No es el único llamador de Anthropic.** El compresor tiene su propio cliente.

## Orquestación de un turno

Es el corazón del producto. Los endpoints están en `backend/api/stream.py`: `post_message()` (`POST /channels/{id}/messages`) y `post_round()` (`POST /channels/{id}/rounds`). La lógica está en `backend/services/orchestrator.py`: `run_turn()` y `parse_mention()` (más `_normalize()`).

`post_message()` comprueba que el canal existe (404 si no) y devuelve un `StreamingResponse` con media type `text/event-stream` y cabecera `X-Accel-Buffering: no` (para que nginx no acumule el stream). Envuelve el generador `run_turn(channel_id, request.content)`, que no se ejecuta hasta que se consume el stream: todo lo que pasa dentro ocurre con el HTTP 200 ya abierto.

`post_round()` busca el último mensaje humano con `get_last_human_message()` (400 si no hay ninguno) y llama a `run_turn(..., save_human=False)`: repite el turno sin guardar de nuevo el mensaje. Ojo: reutiliza el texto, así que una `@mención` de ese mensaje vuelve a aplicarse en cada ronda. No hay tope de rondas; el cliente decide cuántas veces llama.

`parse_mention(text, roster)` busca `@(\S+)`, normaliza el nombre (sin acentos, minúsculas, sin puntuación final) y lo compara con los nombres del roster. Devuelve el perfil o `None`. La regla de `run_turn()` es binaria: con mención válida habla solo ese perfil; sin mención, o con una desconocida (que no da error), hablan todos los del roster en orden de `speaking_order`.

Lo no obvio:

- **El prompt se arma por hablante, no por turno.** En cada vuelta del bucle se relee `get_latest_summary()` y `get_context_messages()`. Como cada respuesta se inserta en BD al terminar su stream, el segundo tertuliano ya ve lo que dijo el primero. La BD es el canal de comunicación entre ellos.
- **Se guarda al terminar.** La respuesta completa se persiste con `insert_message()` (rol `persona`, tokens y coste) después del stream.
- **Los errores cortan el stream sin avisar.** Si `stream_turn()` falla, `run_turn()` lo loguea y re-lanza. Como la respuesta ya empezó, el cliente solo ve la conexión cortada, sin evento `error`. Los hablantes anteriores quedan guardados y los siguientes no; no hay transacción.
- **Roster vacío:** emite `TURN_COMPLETE` y termina sin llamar a ningún modelo.
- **El Moderador no está excluido del round-robin.** `run_turn()` no filtra por `funcion` ni `tipo`; un Moderador metido en un roster hablaría como cualquier otro.

Los eventos SSE emitidos son `start` (con `profile_id` y `profile_name`), `token`, `done` (tokens y coste) y, al final, `TURN_COMPLETE` con el coste total del canal (`get_total_cost_usd()`).

## Compresión de contexto

Una tertulia larga acabaría desbordando el contexto. `backend/services/compressor.py` lo evita con un "acta" rodante: un markdown que resume lo antiguo y que Haiku reescribe cada vez.

`maybe_compress(channel_id, mode)` lee el último resumen y cuenta con `count_messages_after()` los mensajes posteriores a `covers_up_to_msg_id` (todos los roles). Si hay menos de 30 (`COMPRESSION_THRESHOLD`), no hace nada. Si hay 30 o más, toma los 20 más antiguos pendientes (`COMPRESSION_CHUNK`, vía `get_messages_chunk()`), llama a `_update_acta(previous_acta, chunk, mode)` e inserta con `insert_summary()` una fila **nueva** cuyo `covers_up_to_msg_id` es el id del último mensaje del chunk. `get_latest_summary()` coge la más reciente por `created_at`.

`_update_acta()` usa un cliente propio `_client` (`AsyncAnthropic`) y llama a `messages.create()` sin streaming, con Haiku, `max_tokens=1200` y `temperature=0.2`. `_build_user_message()` construye el prompt con bloques `<acta_anterior>` y `<mensajes_nuevos>`. La instrucción es devolver el acta completa actualizada, no un delta. El formato tiene dos variantes según el modo: en debate secciones como "Posiciones por hablante" y "Desacuerdos abiertos", y en crítica "Observaciones por crítico", entre otras. El límite de 800 tokens (`ACTA_MAX_TOKENS`) es una petición a Haiku, no un tope duro.

Lo no obvio:

- **Es síncrona con el turno.** Se ejecuta lo primero en `run_turn()`, antes de guardar el mensaje humano, así que el usuario espera a Haiku antes del primer token.
- **Fallo silencioso.** Si Haiku falla, se loguea y el turno sigue sin comprimir; un acta vacía se descarta con warning.
- **Un chunk por turno.** Aunque haya más de 30 pendientes, solo se comprimen 20. Quedan al menos 10 sin comprimir y el contexto crece hasta volver a llegar al umbral.
- **El coste de Haiku no se registra** en `messages.cost_usd`, así que `TURN_COMPLETE.total_cost_usd` lo infravalora.

## Síntesis y export

Para sacar la conversación a Obsidian, `backend/api/synthesize.py` expone `synthesize()` (`POST /channels/{id}/synthesize`), que comprueba el canal y devuelve un `StreamingResponse` de `run_synthesis()` en `backend/services/synthesizer.py`.

`run_synthesis()` lee el canal, el perfil Moderador, la transcripción completa y el id del último mensaje; cada fallo sale como evento SSE `error` y termina. El Moderador es un perfil más de `profiles`, localizado por `get_moderador_profile()` con `WHERE LOWER(funcion) LIKE '%moderador%' AND archived = FALSE LIMIT 1`: se busca por el campo `funcion` (columna de `profiles` distinta de `name`, que describe el papel del perfil; un perfil cuya `funcion` contenga "moderador" es el Moderador), no por `name`. Su `system_prompt`, `model` y `temperature` son los que se usan. La transcripción viene de `get_full_transcript()` (solo `human` y `persona`, con nombre del hablante) y no pasa por el acta.

La caché decide si se llama a Anthropic: si `get_synthesis_cache()` devuelve una fila con `up_to_msg_id` igual al último id de mensaje, se emiten `start`, un único `token` con todo el texto y `done`. Si no, se arma el prompt con `_SYNTHESIS_PROMPT` (título, modo, participantes del roster, fecha, transcripción, líneas de postura), se llama a `stream_turn()` con el prompt como string (no como bloques) y se emiten los `token` al llegar. Al acabar, `save_synthesis()` guarda el texto con el último id. Los errores de `stream_turn()` aquí sí se convierten en evento SSE `error`.

Lo no obvio:

- Nuevo mensaje equivale a regenerar; además `patch_channel()` borra la caché al cambiar `base_text`. No hay parámetro para forzar la regeneración.
- No se guarda coste de la síntesis.
- Con `max_tokens=1024` una síntesis larga se trunca y el texto truncado se guarda en caché como válido.

## Todo junto: un turno de debate

Alguien escribe en un canal con tres tertulianos y el frontend hace `POST /channels/{id}/messages` con `{content}`.

`post_message()` comprueba el canal y devuelve el `StreamingResponse`. A partir de aquí manda `run_turn()`, con el 200 ya abierto. Lo primero es `get_channel()` y `maybe_compress()`, que quizá inserte un acta nueva. Después se guarda el mensaje humano con `insert_message()`, se lee `get_active_roster()` y se llama a `parse_mention()`. Sin `@nombre` válido hablan los tres, en orden de `speaking_order`.

Para cada hablante: se lee el último acta y los mensajes posteriores a ella, `build_context()` arma el system (andamio más prompt del perfil) y los bloques (`base_text`, acta, historial), se emite `start` y `stream_turn()` empieza a producir fragmentos, que salen como eventos `token`. Al terminar se inserta la respuesta como `persona` con tokens y coste, y se emite `done`. El siguiente hablante repite el proceso y ya ve en la BD lo que dijo el anterior. Cuando acaba el último, `get_total_cost_usd()` suma el coste del canal y sale `TURN_COMPLETE`.

Si el usuario pulsa "otra ronda", `POST /channels/{id}/rounds` repite lo mismo con el último mensaje humano y sin volver a guardarlo.

## Todo junto: exportar un canal

`POST /channels/{id}/synthesize` llega a `synthesize()`, que valida el canal y entrega el generador `run_synthesis()`. Este carga canal, Moderador, transcripción y último id de mensaje. Consulta la caché: si coincide el id, responde al instante con el texto guardado. Si no, carga el roster (solo para nombres y líneas de postura), rellena `_SYNTHESIS_PROMPT`, llama a `stream_turn()` con el perfil del Moderador y reenvía los tokens. Al terminar guarda el texto en `channel_syntheses` y emite `done`. El resultado es un markdown con frontmatter, decisiones y posturas.

## Todo junto: la compresión que nadie pidió

Es lo único que arranca sin que el usuario lo pida, pero no es un job: va enganchado a cada turno. Al inicio de `run_turn()`, `maybe_compress()` mira cuántos mensajes hay sin cubrir por un acta. Con menos de 30 no hace nada. Con 30 o más, trae los 20 más antiguos, pide a Haiku el acta completa reescrita a partir de la anterior y el chunk, e inserta una fila nueva en `summaries`. Si algo falla, solo hay un log y el turno sigue. De vuelta en `run_turn()`, cada hablante llama a `get_latest_summary()`, recibe el acta nueva, y `get_context_messages()` le trae solo lo posterior a `covers_up_to_msg_id`. `build_context()` pone el acta como segundo bloque.

## Lo que este artículo no cubre

- **El frontend** (`frontend/src/**`): React 18 + Vite + Tailwind, con chat, editor de perfiles, stores y servicios SSE. No se ha despiezado.
- **Despliegue**: nginx como reverse proxy (`frontend/nginx.conf`, :5151 hacia el backend en :8001 bajo `/api`), los servicios systemd (`agora-backend` activo, `agora-frontend` deshabilitado en prod) y el `Makefile`. El puerto exacto de producción no se pudo determinar.
- **LogCentral**: el repo solo escribe `logs/tertulia.log`; el agente que lo recoge está fuera.
- **Sin determinar:**
  - Quién crea los perfiles de uso real. El código solo trae un perfil de ejemplo (Sócrates) y un canal de prueba sembrados en `init.sql`; el resto (por ejemplo Gilito, Pratchett, Pragmático, Visionario y el Moderador, que se mencionan en la documentación del proyecto) se supone creado por el usuario a través del editor de perfiles y `POST /profiles`, pero el material no lo confirma.
  - Qué pasa cuando dos perfiles comparten `speaking_order`.
  - Un tope de rondas: no existe en el código visto.
  - Versionado de perfiles: no existe; se sobrescriben en vivo.

## Dónde mirar en el código

| Si quieres entender... | Abre |
|---|---|
| Cómo arranca y se cierra el proceso | `backend/main.py`, `lifespan()` |
| Qué variables exige el `.env` | `backend/config.py`, `Settings` |
| El pool y los cursores | `backend/db/connection.py`, `get_db()` |
| Qué hablantes participan y en qué orden | `backend/db/queries/channels.py`, `get_active_roster()` |
| Un turno completo, de principio a fin | `backend/services/orchestrator.py`, `run_turn()` |
| Cómo se interpretan las `@menciones` | `backend/services/orchestrator.py`, `parse_mention()` |
| Qué se le dice a cada tertuliano | `backend/services/andamio.py`, `build_context()` |
| La llamada a Anthropic y el cálculo de coste | `backend/services/llm.py`, `stream_turn()` |
| Cuándo y cómo se comprime la conversación | `backend/services/compressor.py`, `maybe_compress()` |
| Cómo se genera el export | `backend/services/synthesizer.py`, `run_synthesis()` |
| Cuándo se reusa o invalida la caché de síntesis | `run_synthesis()` y `patch_channel()` en `backend/api/channels.py` |
| El límite de 3 perfiles por canal | `backend/api/channels.py`, `add_profile_to_channel()` |
| Los endpoints SSE | `backend/api/stream.py`, `backend/api/synthesize.py` |
| Los schemas de entrada y salida | `backend/schemas/models.py` |
