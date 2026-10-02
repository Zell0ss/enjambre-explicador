# Piezas de Agora

## Resumen
| Id | Pieza | Responsabilidad en una frase |
|---|---|---|
| arranque-config | Arranque y configuración | Levanta la app FastAPI, carga el `.env` y configura el logging JSON centralizado. |
| acceso-datos | Acceso a base de datos | Gestiona el pool async a MariaDB y expone las queries CRUD de perfiles, canales, roster, mensajes y resúmenes. |
| api-entidades | API CRUD de canales y perfiles | Expone y valida por HTTP la gestión de canales, roster y perfiles (sin lógica de debate). |
| construccion-prompt | Construcción del prompt (andamio) | Decide qué system prompt y bloques de contexto recibe cada tertuliano según su rol y el modo del canal. |
| cliente-llm | Cliente del modelo (Anthropic) | Llama a la API de Anthropic en streaming para un tertuliano y calcula el coste de cada llamada. |
| orquestacion-turno | Orquestación de un turno | Dirige el round-robin de tertulianos de un turno, detecta menciones, transmite por SSE y persiste las respuestas. |
| compresion-contexto | Compresión de contexto | Resume mensajes antiguos en un "acta" rodante cuando la conversación supera un umbral, para no desbordar el contexto. |
| sintesis-export | Síntesis y export | Genera el markdown final de un canal (decisiones, posturas) con el perfil Moderador, para exportar a Obsidian. |

## arranque-config — Arranque y configuración
- **Responsabilidad:** Levanta la app FastAPI, carga la configuración desde `.env` y configura el logging JSON centralizado.
- **Ficheros:** `backend/main.py` (`app`, `lifespan()`), `backend/config.py` (`Settings`, `settings`), `backend/logger.py` (`logger`, `_json_sink()`)
- **Habla con:** acceso-datos (el `lifespan()` inicializa el pool al arrancar), api-entidades / orquestacion-turno / sintesis-export (monta sus routers en `app`)
- **Por qué es una pieza aparte:** es infraestructura transversal de proceso (ciclo de vida, config, logs), no lógica de negocio del chat ni del debate.
- **Preguntas para el Lector:**
  - ¿Qué hace exactamente `lifespan()` al arrancar y al parar, más allá de abrir/cerrar el pool?
  - ¿Qué variables de `Settings` son obligatorias y qué pasa si falta alguna en el `.env`?
  - ¿Cómo llega el JSON de `_json_sink()` hasta LogCentral (formato exacto, transporte)?

## acceso-datos — Acceso a base de datos
- **Responsabilidad:** Gestiona el pool de conexiones async a MariaDB y expone las queries CRUD de perfiles, canales, roster, mensajes y resúmenes.
- **Ficheros:** `backend/db/connection.py` (`init_pool()`, `close_pool()`, `get_db()`), `backend/db/queries/profiles.py`, `backend/db/queries/channels.py`, `backend/db/queries/messages.py`
- **Habla con:** arranque-config (lo inicializa), api-entidades, orquestacion-turno, compresion-contexto y sintesis-export (todas leen/escriben a través de estas queries)
- **Por qué es una pieza aparte:** aísla el SQL y el pool de conexiones del resto de la lógica; se entiende sola como "cómo se guarda y se lee todo" en MariaDB.
- **Preguntas para el Lector:**
  - ¿Cómo gestiona el pool errores de conexión o reintentos?
  - ¿Cuándo se invalida o se reusa la caché de `channel_syntheses` (`get_synthesis_cache` / `save_synthesis` / `delete_synthesis_cache`) — el mapa no lo tenía confirmado?
  - ¿Hay transacciones explícitas en operaciones que tocan varias tablas a la vez (p. ej. borrar un canal y su roster y sus mensajes)?

## api-entidades — API CRUD de canales y perfiles
- **Responsabilidad:** Expone y valida por HTTP la gestión de canales, roster (`channel_profiles`) y perfiles, sin lógica de debate.
- **Ficheros:** `backend/api/channels.py`, `backend/api/profiles.py`, `backend/schemas/models.py`
- **Habla con:** acceso-datos (ejecuta las queries), orquestacion-turno (el roster que gestiona aquí es el que recorre el round-robin)
- **Por qué es una pieza aparte:** es la superficie REST de gestión de entidades, autocontenida como un CRUD clásico, separable de la mecánica del debate en vivo.
- **Preguntas para el Lector:**
  - ¿Qué valida cada schema `Patch` (parcial) frente a los `In`/`Out` (completos)?
  - ¿Qué ocurre con mensajes y roster al borrar un canal, y con `archive_profile()` al borrar un perfil (borrado lógico vs físico)?
  - ¿Cómo se usa `speaking_order` al añadir un perfil al roster — se recalcula o lo fija el cliente?

## construccion-prompt — Construcción del prompt (andamio)
- **Responsabilidad:** Decide qué system prompt y qué bloques de contexto recibe cada tertuliano según su tipo de perfil y el modo del canal (debate/crítica).
- **Ficheros:** `backend/services/andamio.py` (`build_context()`, `ANDAMIO_DEBATE`, `ANDAMIO_CRITICA`)
- **Habla con:** orquestacion-turno (quien lo invoca antes de cada llamada), cliente-llm (consume el `(system_prompt, api_messages)` que produce)
- **Por qué es una pieza aparte:** es lógica de "producto" (cómo se le habla a cada rol en cada modo) separable de la mecánica técnica de llamar a la API.
- **Preguntas para el Lector:**
  - ¿En qué difiere en concreto `ANDAMIO_DEBATE` de `ANDAMIO_CRITICA`?
  - ¿Cómo entra el acta/resumen rodante (tabla `summaries`) en el contexto construido?
  - ¿Hay algún límite de mensajes o tokens que respete `build_context()` además del recorte que ya hace compresion-contexto?

## cliente-llm — Cliente del modelo (Anthropic)
- **Responsabilidad:** Llama a la API de Anthropic en streaming para un tertuliano concreto y calcula el coste en USD de cada llamada.
- **Ficheros:** `backend/services/llm.py` (`stream_turn()`, `_COST_PER_TOKEN`, `_MODELS_NO_TEMPERATURE`)
- **Habla con:** construccion-prompt (recibe el prompt ya armado), orquestacion-turno (le entrega tokens en streaming y el dict de `usage`)
- **Por qué es una pieza aparte:** es un cliente técnico (streaming, tablas de coste, particularidades por modelo) independiente de qué se dice o a quién se dice.
- **Preguntas para el Lector:**
  - El mapa indica que no hay validación si el modelo no está en `_COST_PER_TOKEN` o `_MODELS_NO_TEMPERATURE` — ¿qué pasa realmente en ese caso?
  - ¿`compressor.py` y `synthesizer.py` reusan `stream_turn()` para llamar a Anthropic, o hacen su propia llamada directa a la API? (el mapa los lista como llamadores independientes)
  - ¿Cómo se propaga hacia el SSE del frontend un error de la API (rate limit, timeout, contenido bloqueado)?

## orquestacion-turno — Orquestación de un turno
- **Responsabilidad:** Dirige el round-robin de tertulianos de un turno o ronda, detecta menciones `@nombre`, transmite por SSE y persiste las respuestas generadas.
- **Ficheros:** `backend/api/stream.py` (`post_message()`, `post_round()`), `backend/services/orchestrator.py` (`run_turn()`, `parse_mention()`)
- **Habla con:** construccion-prompt (pide el contexto antes de cada llamada), cliente-llm (obtiene el stream de tokens de cada tertuliano), compresion-contexto (dispara la compresión si hace falta), acceso-datos (guarda mensajes, lee roster y contexto)
- **Por qué es una pieza aparte:** es el corazón del producto — el round-robin multiagente con menciones — con lógica de turno que no vive en ningún otro módulo.
- **Preguntas para el Lector:**
  - ¿Cómo decide `run_turn()` el orden exacto de habla (usa `speaking_order` del roster tal cual)?
  - ¿Qué hace `parse_mention()` cuando detecta un `@nombre` — reordena, prioriza o repite turno?
  - El mapa señala que `post_round()` no parece tener tope de rondas — ¿se confirma, y qué pasa si el usuario pide muchas rondas seguidas?
  - ¿En qué punto exacto del flujo de `run_turn()` se llama a `maybe_compress()` (antes o después de construir el contexto)?

## compresion-contexto — Compresión de contexto
- **Responsabilidad:** Cuando la conversación supera un umbral, resume los mensajes antiguos en un "acta" rodante usando Haiku, para no desbordar el contexto del modelo.
- **Ficheros:** `backend/services/compressor.py` (`maybe_compress()`, `_update_acta()`, `_build_user_message()`)
- **Habla con:** acceso-datos (lee mensajes pendientes y guarda el nuevo `summary`), orquestacion-turno (quien dispara `maybe_compress()`), posiblemente cliente-llm (a confirmar, ver pregunta en esa pieza)
- **Por qué es una pieza aparte:** responsabilidad única y acotada de gestión de memoria de la conversación, desacoplable del resto del turno.
- **Preguntas para el Lector:**
  - ¿Cuál es el umbral exacto (nº de mensajes, tokens u otro) que dispara `maybe_compress()`?
  - ¿`_update_acta()` reescribe el acta entera cada vez o la extiende incrementalmente sobre la anterior?
  - ¿Qué pasa si falla la llamada a Haiku — bloquea el turno en curso o el turno sigue sin comprimir?

## sintesis-export — Síntesis y export
- **Responsabilidad:** Genera y expone en streaming el markdown final de un canal (frontmatter, decisiones, posturas) usando el perfil Moderador, para exportar a Obsidian.
- **Ficheros:** `backend/api/synthesize.py` (`synthesize()`), `backend/services/synthesizer.py` (`run_synthesis()`, `get_moderador_profile()`)
- **Habla con:** acceso-datos (transcript completo vía `get_full_transcript()`, caché de síntesis), cliente-llm (a confirmar si reusa `stream_turn()`, ver pregunta en esa pieza)
- **Por qué es una pieza aparte:** es una funcionalidad de salida completamente distinta del chat en vivo, con su propio formato de export y su propia caché.
- **Preguntas para el Lector:**
  - El mapa no tiene confirmado cuándo se invalida o reusa la caché en `channel_syntheses` — ¿se puede precisar leyendo el código?
  - `get_moderador_profile()` busca un perfil `name='Moderador'` que no aparece en `init.sql` — ¿de dónde sale ese perfil en producción?
  - ¿La síntesis se puede forzar a regenerar a demanda, o solo se sirve de caché tras la primera vez que se genera?

## Orden de lectura sugerido
1. **arranque-config** — para situar cómo arranca el proceso y qué infraestructura compartida (config, logging, pool) usan todas las demás piezas.
2. **acceso-datos** — entender el modelo de datos (tablas y queries) ayuda a leer con sentido el resto, que no hace más que leer y escribir aquí.
3. **api-entidades** — la superficie más simple (CRUD clásico) antes de entrar en la lógica de negocio del debate.
4. **construccion-prompt** — qué se le dice a cada tertuliano, antes de ver cómo se le llama técnicamente.
5. **cliente-llm** — cómo se llama de verdad a Anthropic, justo después de ver qué se le envía.
6. **orquestacion-turno** — el corazón del producto, que amarra datos + prompt + cliente LLM en el flujo de un turno real.
7. **compresion-contexto** — mecanismo de soporte del turno, se entiende mejor ya habiendo visto cómo funciona un turno.
8. **sintesis-export** — funcionalidad de salida final, que depende de haber entendido transcript, perfiles y llamadas al modelo.

## Fuera del despiece
- **Frontend (`frontend/src/**`, `frontend/nginx.conf`, `Makefile`)** — excluido explícitamente por consigna: el frontend no es una pieza de back.
- **Seeds de perfiles de producción (perfiles reales como Gilito, Pratchett, Pragmático, Visionario, Moderador, etc.)** — el mapa indica que no están en `init.sql` (que solo siembra a "Sócrates") y no se ha podido determinar dónde viven; es un hueco de datos/despliegue, no un módulo de código identificable.
- **Configuración de nginx como reverse proxy y el servicio systemd** — infraestructura de despliegue (puerto, proxy `/api`), no lógica de negocio del backend.
- **`logs/tertulia.log` como fichero y la integración con LogCentral** — es un efecto del logger ya cubierto en arranque-config; el propio pipeline de LogCentral vive fuera del repo.
