# Mapa de Agora

## Qué es

Agora es un chat web multiagente alojado en seb01 (acceso solo por Tailscale) donde los "tertulianos" son instancias de Claude API, cada una con su propia personalidad y rol. El usuario crea canales (conversaciones), elige 1–3 tertulianos y debate ideas o textos; todos participan en round-robin secuencial sobre un contexto compartido, reaccionando entre ellos. Dos superficies: chat con streaming y export MD (Obsidian), y editor de perfiles.

## Procesos y puntos de entrada

| Proceso | Cómo arranca | Fichero |
|---|---|---|
| Backend (API) | `systemctl start agora-backend` → uvicorn en 127.0.0.1:8001 | `backend/main.py` (línea 21: `app = FastAPI()`) |
| Frontend (dev) | `systemctl start agora-frontend` → script Vite en :5173 | `frontend/src/main.jsx` (entrapoint app) |
| Frontend (prod) | nginx en :5151 sirve contenido estático de `frontend/dist/` | `Makefile` (línea 100: `npm run build`) |

**Servicios systemd:** `agora-backend.service` (activo), `agora-frontend.service` (deshabilitado en prod).

## Rutas de API

| Método | Ruta | Función | Fichero |
|---|---|---|---|
| GET | `/channels` | lista_channels_endpoint | backend/api/channels.py:32 |
| POST | `/channels` | create_channel | backend/api/channels.py:37 |
| GET | `/channels/{id}` | get_channel_endpoint | backend/api/channels.py:48 |
| PATCH | `/channels/{id}` | patch_channel | backend/api/channels.py:56 |
| DELETE | `/channels/{id}` | delete_channel_endpoint | backend/api/channels.py:68 |
| GET | `/channels/{id}/messages` | list_channel_messages | backend/api/channels.py:77 |
| GET | `/channels/{id}/profiles` | list_roster | backend/api/channels.py:85 |
| POST | `/channels/{id}/profiles` | add_profile_to_channel | backend/api/channels.py:93 |
| DELETE | `/channels/{id}/profiles/{profile_id}` | remove_profile_from_channel | backend/api/channels.py:111 |
| PATCH | `/channels/{id}/profiles/{profile_id}` | patch_roster_entry | backend/api/channels.py:125 |
| POST | `/channels/{id}/messages` | post_message (SSE) | backend/api/stream.py:12 |
| POST | `/channels/{id}/rounds` | post_round (SSE) | backend/api/stream.py:28 |
| POST | `/channels/{id}/synthesize` | synthesize (SSE) | backend/api/synthesize.py:10 |
| GET | `/profiles` | list_profiles_endpoint | backend/api/profiles.py:16 |
| POST | `/profiles` | create_profile | backend/api/profiles.py:21 |
| GET | `/profiles/{id}` | get_profile_endpoint | backend/api/profiles.py:35 |
| PATCH | `/profiles/{id}` | patch_profile | backend/api/profiles.py:43 |
| DELETE | `/profiles/{id}` | delete_profile | backend/api/profiles.py:53 |

**Streaming:** Las rutas de `stream.py` y `synthesize.py` usan `StreamingResponse` con media type `text/event-stream` (SSE). El frontend consume tokens en tiempo real.

## Módulos de back

| Fichero | Qué parece hacer | Funciones o clases principales |
|---|---|---|
| backend/main.py | Punto de entrada FastAPI, lifespan, inicializa pool DB | `app` (FastAPI), `lifespan()` (asynccontextmanager) |
| backend/config.py | Carga configuración de .env | `Settings` (Pydantic model), `settings` (instancia global) |
| backend/logger.py | Configura loguru para escribir JSON a `logs/tertulia.log` | `logger` (loguru instance), `_json_sink()` |
| backend/api/channels.py | CRUD de canales y roster (channel_profiles) | `create_channel()`, `get_channel()`, `list_channels()`, `patch_channel()`, `delete_channel()`, `list_roster()`, `add_profile_to_channel()`, `remove_profile_from_channel()`, `patch_roster_entry()` |
| backend/api/profiles.py | CRUD de perfiles (tertulianos y facilitadores) | `list_profiles_endpoint()`, `create_profile()`, `get_profile_endpoint()`, `patch_profile()`, `delete_profile()` |
| backend/api/stream.py | Rutas que disparan turnos de debate (SSE) | `post_message()`, `post_round()` |
| backend/api/synthesize.py | Ruta que genera resumen del canal (export Obsidian) | `synthesize()` |
| backend/db/connection.py | Pool de conexiones async aiomysql | `init_pool()`, `close_pool()`, `get_db()` (context manager) |
| backend/db/queries/profiles.py | Queries CRUD para tabla `profiles` | `get_profile()`, `list_profiles()`, `insert_profile()`, `update_profile()`, `archive_profile()`, `get_moderador_profile()` |
| backend/db/queries/channels.py | Queries CRUD para `channels` y `channel_profiles` | `get_channel()`, `list_channels()`, `insert_channel()`, `update_channel()`, `get_active_roster()`, `get_full_roster()`, `add_to_roster()`, `remove_from_roster()`, `count_active_roster()`, `delete_channel()`, `get_synthesis_cache()`, `save_synthesis()`, `delete_synthesis_cache()` |
| backend/db/queries/messages.py | Queries para `messages` y `summaries` (contexto y compresión) | `insert_message()`, `get_context_messages()`, `get_latest_summary()`, `get_total_cost_usd()`, `count_messages_after()`, `get_messages_chunk()`, `get_full_transcript()`, `insert_summary()`, `get_last_human_message()`, `get_last_message_id()` |
| backend/services/orchestrator.py | Orquesta un turno: round-robin de tertulianos, streaming, guarda respuestas | `run_turn()` (AsyncGenerator), `parse_mention()` (detecta @nombre) |
| backend/services/andamio.py | Construye system prompt y context blocks para API (matriz tipo perfil × modo canal) | `build_context()` (devuelve tuple(system_prompt, api_messages)), `ANDAMIO_DEBATE`, `ANDAMIO_CRITICA` (constantes) |
| backend/services/llm.py | Llama a Anthropic API con streaming, calcula coste | `stream_turn()` (AsyncGenerator, yield tokens → yield usage dict), `_COST_PER_TOKEN` (dict), `_MODELS_NO_TEMPERATURE` (set) |
| backend/services/compressor.py | Comprime mensajes antiguos a "acta" (resumen rodante) antes de superar umbral | `maybe_compress()`, `_update_acta()` (llama Haiku), `_build_user_message()` |
| backend/services/synthesizer.py | Genera markdown final con frontmatter + decisiones + posturas (export) | `run_synthesis()` (AsyncGenerator), `get_moderador_profile()` (usa perfil Moderador) |
| backend/schemas/models.py | Pydantic models para validación entrada/salida API | `TurnRequest`, `ProfileIn/Out/Patch`, `ChannelIn/Out/Patch`, `MessageOut`, `RosterAddIn/Patch/Entry` |

**Frontend (solo orientación, no entra en detalle):** React 18 + Vite + Tailwind. Carpeta `frontend/src/` contiene componentes de chat, editor de perfiles, stores (estado), servicios (SSE, API calls). El frontend habla con backend en `/api` (proxy nginx).

## Almacenamiento

| Tipo | Nombre | Quién lo usa |
|---|---|---|
| MariaDB table | `profiles` | CRUD profiles; FK en channel_profiles, messages |
| MariaDB table | `channels` | CRUD channels; contiene title, mode (debate/critica), incognito, base_text |
| MariaDB table | `channel_profiles` | Roster: qué perfiles están en cada canal, speaking_order, active flag |
| MariaDB table | `messages` | Todos los mensajes: role (human/persona/system), content, tokens_in/out, cost_usd, created_at(3) |
| MariaDB table | `summaries` | Resúmenes rodantes: content (acta markdown), covers_up_to_msg_id, created_at |
| MariaDB table | `channel_syntheses` | Cache de síntesis (export final): content, up_to_msg_id, created_at |
| Fichero | `logs/tertulia.log` | JSON línea a línea (loguru sink) registrado con LogCentral source `tertulia` |
| Fichero | `.env` | Variables: `ANTHROPIC_API_KEY`, `db_host`, `db_user`, `db_password`, `db_name` |

## Dependencias externas

| Servicio | Para qué | Desde dónde se llama |
|---|---|---|
| Anthropic API (Claude modelos) | Llamadas LLM para tertulianos, compresor, moderador | `backend/services/llm.py::stream_turn()` (participantes), `compressor.py::_update_acta()` (Haiku), `synthesizer.py::run_synthesis()` (Moderador) |
| MariaDB 10.x (seb01) | Persistencia: perfiles, canales, mensajes, resúmenes, síntesis | `backend/db/connection.py::init_pool()` (aiomysql async pool) |
| nginx (seb01) | Reverse proxy (frontend :5151 → backend :8001 en /api) | Configuración: `frontend/nginx.conf` (symlinkado en `/etc/nginx/sites-enabled/agora`) |
| LogCentral (seb01) | Centralización de logs JSON | `backend/logger.py::_json_sink()` (escribe a `tertulia.log`) |

## Lo que no he podido determinar

- **Ubicación exacta de fixtures/perfiles semilla de producción:** El `init.sql` siembra solo a "Sócrates" + 1 canal de prueba. Los otros perfiles (Gilito, Pratchett, Pragmático, Visionario, RUIZ Moderador, etc.) mencionados en `agora-perfiles-semilla.md` no aparecen en el DDL — podrían estar en otro script de seed o volcarse a mano. `get_moderador_profile()` busca un perfil con `name='Moderador'` que no veo en init.sql.
- **Caché de síntesis en detail:** Existe tabla `channel_syntheses` con PK simple en `channel_id`, pero las queries `get_synthesis_cache()`, `save_synthesis()`, `delete_synthesis_cache()` usan nombres genéricos; no confirmé la lógica exact de cuándo se invalida vs reusa.
- **Tope duro para "otra ronda":** `post_round()` permite N rondas sin límite visible; el CLAUDE.md menciona recomendación de "una vuelta en MVP, N-rondas detrás de tope duro a futuro" pero no veo ese tope implementado.
- **Versioning de prompts (D7 futuro):** No existe tabla `profile_versions` — los perfiles se sobrescriben en vivo (D7 MVP). Versionado deliberado queda para después.
- **Validación de limits de modelo:** No encontré checks que rechacen modelos no válidos en `_COST_PER_TOKEN` o `_MODELS_NO_TEMPERATURE` — si se pasa un modelo no listado, cae la función.
- **Puerto exacto de producción:** CLAUDE.md dice "verificar `stack.md`" pero ese fichero no está en el repo (es del proyecto Josem, global).
