# Dudas del Novato — vuelta 2

## Veredicto
`listo`

## Dudas que bloquean
(ninguna)

## Dudas menores

- **Sección "Cliente del modelo"**: Se mencionan `_MODELS_NO_TEMPERATURE` y `_COST_PER_TOKEN` como estructuras de datos pero no se aclara el contenido exacto. Se dice que `_COST_PER_TOKEN` tiene "tres claves" y se listan los modelos, pero no está claro si es un set cerrado o puede crecer. Tampoco se explica qué modelos específicos están en `_MODELS_NO_TEMPERATURE`.

- **Sección "Construcción del prompt"**: El parámetro `profile_names` que se pasa a `build_context()` no se explica. Se entiende que es un mapeo de ID a nombre (porque "si un `profile_id` no está en `profile_names`, el nombre cae a `"Participante {id}`"), pero no se dice explícitamente de dónde se arma ni si viene del roster.

- **Sección "Construcción del prompt"**: Se menciona `cache_control` como atributo de los bloques de contexto pero no se explica qué es ni por qué es "efímero" en `base_text` pero no en otras partes. Probablemente sea del SDK de Anthropic, pero el artículo no lo aclara.

- **Sección "Acceso a base de datos"**: Los roles de mensaje (`human`, `persona`, `system`) se mencionan varias veces pero solo se explican implícitamente. Una línea clara (ej: "rol `human` = usuario, `persona` = respuesta de tertuliano, `system` = mensajes internos") sería útil.

- **Sección "Todo junto: exportar un canal"**: Se menciona que el resultado es "un markdown con frontmatter, decisiones y posturas", pero no se aclara qué estructura exacta tiene ese markdown ni cómo se calculan las "decisiones" y "posturas".

## La prueba final

1. **¿Qué hace este proyecto, en dos frases?**
   
   Agora es un chat web multiagente donde varios Claude (con personalidades y roles distintos) discuten o analizan textos de forma colaborativa en tiempo real. El usuario escribe un mensaje en un canal, los tertulianos responden uno tras otro en orden de `speaking_order`, se ven entre sí a través de la base de datos, y el contexto se comprime automáticamente con Haiku para que no crezca sin límite.

2. **¿Cuáles son sus piezas y qué hace cada una?**

   1. **Arranque y configuración** (`main.py`, `config.py`, `logger.py`): Levanta la app FastAPI, carga el `.env`, valida con Pydantic, configura loguru para escribir JSON a `logs/tertulia.log`.
   
   2. **Acceso a base de datos** (`db/connection.py`, `db/queries/*`): Pool aiomysql (minsize 1, maxsize 10) hacia MariaDB con autocommit, y todas las queries SQL agrupadas por tabla (profiles, channels, messages, summaries, channel_syntheses).
   
   3. **API CRUD de canales y perfiles** (`api/channels.py`, `api/profiles.py`): Endpoints REST (`GET/POST/PATCH/DELETE`) para gestión de canales, perfiles y roster, con validaciones (máximo 3 perfiles por canal, borrado lógico).
   
   4. **Construcción del prompt (andamio)** (`services/andamio.py`): Función `build_context()` que arma el system prompt (ANDAMIO_DEBATE o ANDAMIO_CRITICA + system_prompt del perfil) y los bloques de contexto (base_text, acta, historial) para cada tertuliano, adaptándose al modo del canal.
   
   5. **Cliente del modelo** (`services/llm.py`): Generador `stream_turn()` que llama a Anthropic en streaming, emite fragmentos de texto, calcula tokens y coste, maneja modelos sin soporte de `temperature`.
   
   6. **Orquestación de un turno** (`services/orchestrator.py`, `api/stream.py`): Corazón del producto. `run_turn()` gestiona el round-robin de tertulianos, parsea `@menciones`, coordina streaming SSE, persiste respuestas en BD, emite eventos (`start`, `token`, `done`, `TURN_COMPLETE`).
   
   7. **Compresión de contexto** (`services/compressor.py`): Función `maybe_compress()` que resume mensajes antiguos en un "acta" rodante (con Haiku), insertando nuevas filas en `summaries` cuando hay 30+ mensajes sin comprimir, reduciendo el contexto que ve cada tertuliano.
   
   8. **Síntesis y export** (`services/synthesizer.py`, `api/synthesize.py`): Función `run_synthesis()` que genera markdown final del canal usando el perfil Moderador (buscado por `funcion LIKE '%moderador%'`), con caché para no regenerar innecesariamente.

3. **Elige el flujo principal y cuéntalo con tus palabras, paso a paso.**

   El flujo es: Usuario escribe un mensaje en un canal → todos los tertulianos responden en orden.
   
   1. Frontend hace `POST /channels/{id}/messages` con el contenido.
   2. `post_message()` abre una `StreamingResponse` con media type `text/event-stream` y cabecera `X-Accel-Buffering: no`.
   3. `run_turn()` comienza (HTTP 200 ya abierto):
      - Lee el canal; 404 si no existe.
      - Llama a `maybe_compress()`: si hay ≥30 mensajes sin cubrir por un acta, pide a Haiku que resuma los 20 más antiguos e inserta una acta nueva en `summaries`.
      - Guarda el mensaje del usuario en `messages` con rol `human`.
      - Lee el roster activo (perfiles activos, no archivados, ordenados por `speaking_order`).
      - `parse_mention()` busca `@nombre`: si encuentra uno válido, habla solo ese perfil; si no, hablan todos en orden.
   4. Para cada tertuliano del roster:
      - Lee el último acta y llama a `get_context_messages()` para traer mensajes posteriores a `covers_up_to_msg_id`.
      - `build_context()` arma system prompt (ANDAMIO_DEBATE o ANDAMIO_CRITICA + system_prompt) y bloques (base_text, acta, historial etiquetado con nombres).
      - Emite SSE `start` (con profile_id y profile_name).
      - `stream_turn()` llama a Anthropic en streaming (`max_tokens=1024`, `temperature` si lo soporta).
      - Cada fragmento se emite como SSE `token`.
      - Al terminar, `stream_turn()` devuelve dict con tokens_in, tokens_out, cost_usd.
      - Guarda la respuesta completa en `messages` con rol `persona` y coste.
      - Emite SSE `done` (tokens y coste de ese tertuliano).
   5. El siguiente tertuliano repite, leyendo BD de nuevo y viendo lo que dijo el anterior.
   6. Al terminar el último, `get_total_cost_usd()` suma coste total y se emite SSE `TURN_COMPLETE`.

4. **Si tuvieras que cambiar cómo funciona una cosa concreta, ¿qué fichero abrirías primero?**

   - Para cambiar qué ve cada tertuliano (system prompt, contexto, bloques): `backend/services/andamio.py`, función `build_context()`.
   - Para cambiar selección de tertulianos (orden, round-robin, menciones): `backend/services/orchestrator.py`, funciones `run_turn()` y `parse_mention()`.
   - Para cambiar cuándo/cómo se comprime (umbral, tamaño del chunk, modelo): `backend/services/compressor.py`, funciones `maybe_compress()` y `_update_acta()`.
   - Para cambiar llamadas a Anthropic (modelo, max_tokens, streaming): `backend/services/llm.py`, función `stream_turn()`.
   - Para cambiar el export (formato markdown, caché): `backend/services/synthesizer.py`, función `run_synthesis()`.
   - Para cambiar límites (máximo de perfiles, máximo de rondas): `backend/api/channels.py` o `backend/api/stream.py`.

## Lo que sobra
(nada: el artículo está bien estructurado y cada sección aporta para entender el sistema)
