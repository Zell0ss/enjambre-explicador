# Ficha: acceso-datos

## Qué hace

Expone un pool de conexiones async a MariaDB y centraliza todas las queries CRUD de la aplicación. Gestiona perfiles de tertulianos, canales de debate, roster (quién participa en cada canal), mensajes, resúmenes rodantes, y caché de síntesis de canales. Aísla la lógica SQL del resto del backend.

## Ficheros

- `backend/db/connection.py` — Pool async y context manager para obtener cursores
- `backend/db/queries/channels.py` — Queries sobre canales, roster y síntesis
- `backend/db/queries/profiles.py` — Queries sobre perfiles
- `backend/db/queries/messages.py` — Queries sobre mensajes y resúmenes
- `backend/db/init.sql` — Schema SQL y seed inicial

## Funciones tronco

### `init_pool()` — `backend/db/connection.py`
- **Recibe:** nada (lee `settings.db_host`, `settings.db_port`, etc.)
- **Devuelve:** nada (modifica `_pool` global)
- **Qué hace, paso a paso:**
  1. Crea un pool async aiomysql con rango minsize=1, maxsize=10
  2. Conecta a host, puerto, usuario, contraseña y base de datos desde `settings`
  3. Establece charset utf8mb4
  4. Activa `autocommit=True` (cada statement se commitea solo, sin transacciones multi-statement)
- **Llama a:** (ninguna de esta pieza)

### `close_pool()` — `backend/db/connection.py`
- **Recibe:** nada
- **Devuelve:** nada (modifica `_pool` global)
- **Qué hace, paso a paso:**
  1. Verifica que `_pool` no sea None
  2. Cierra el pool de forma segura
  3. Espera a que se cierren todas las conexiones pendientes
  4. Anula `_pool`
- **Llama a:** (ninguna de esta pieza)

### `get_db()` — `backend/db/connection.py`
- **Recibe:** nada
- **Devuelve:** async context manager que yield un cursor (aiomysql.DictCursor)
- **Qué hace, paso a paso:**
  1. Verifica que el pool esté inicializado (levanta RuntimeError si no)
  2. Adquiere una conexión del pool
  3. Crea un cursor DictCursor (filas como diccionarios, no tuplas)
  4. Yield el cursor al contexto
  5. Al salir del contexto, libera la conexión de vuelta al pool
- **Llama a:** (ninguna de esta pieza)

### `get_channel(channel_id)` — `backend/db/queries/channels.py`
- **Recibe:** `channel_id: int`
- **Devuelve:** `dict | None` (row de channels o None)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor via `get_db()`
  2. Ejecuta SELECT * FROM channels WHERE id = ?
  3. Devuelve una fila (o None)
- **Llama a:** `get_db()` (esta pieza)

### `list_channels()` — `backend/db/queries/channels.py`
- **Recibe:** nada
- **Devuelve:** `list[dict]` (todas las filas de channels)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta SELECT * FROM channels ORDER BY id
  3. Devuelve todas las filas
- **Llama a:** `get_db()`

### `insert_channel(title, mode, incognito, base_text)` — `backend/db/queries/channels.py`
- **Recibe:** `title: str`, `mode: str` ('debate' o 'critica'), `incognito: bool`, `base_text: str | None`
- **Devuelve:** `int` (id del canal creado, lastrowid)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta INSERT INTO channels (title, mode, incognito, base_text) VALUES (?, ?, ?, ?)
  3. Devuelve cur.lastrowid (MariaDB genera el id automáticamente)
- **Llama a:** `get_db()`

### `update_channel(channel_id, fields)` — `backend/db/queries/channels.py`
- **Recibe:** `channel_id: int`, `fields: dict` (ej: `{'title': 'Nuevo título', 'mode': 'critica'}`)
- **Devuelve:** nada
- **Qué hace, paso a paso:**
  1. Si `fields` está vacío, retorna sin hacer nada
  2. Construye dinámicamente un SET clause: "title = %s, mode = %s, ..."
  3. Adquiere un cursor
  4. Ejecuta UPDATE channels SET ... WHERE id = ?
- **Llama a:** `get_db()`

### `delete_channel(channel_id)` — `backend/db/queries/channels.py`
- **Recibe:** `channel_id: int`
- **Devuelve:** nada
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta DELETE FROM summaries WHERE channel_id = ? **primero** (para evitar conflicto con RESTRICT en FK)
  3. Ejecuta DELETE FROM channels WHERE id = ?
  4. Los mensajes y channel_profiles se borran en cascada (ON DELETE CASCADE en sus FKs)
- **Llama a:** `get_db()`
- **Nota importante:** No es una transacción atómica. Pool está configurado con autocommit=True.

### `get_active_roster(channel_id)` — `backend/db/queries/channels.py`
- **Recibe:** `channel_id: int`
- **Devuelve:** `list[dict]` (perfiles activos con sus `speaking_order`)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta JOIN entre channel_profiles y profiles
  3. Filtra: `cp.active = TRUE AND p.archived = FALSE`
  4. Ordena por `cp.speaking_order`
  5. Devuelve todas las filas (perfil completo + speaking_order)
- **Llama a:** `get_db()`

### `get_full_roster(channel_id)` — `backend/db/queries/channels.py`
- **Recibe:** `channel_id: int`
- **Devuelve:** `list[dict]` (campos: profile_id, name, tipo, speaking_order, active)
- **Qué hace, paso a paso:**
  1. Similar a `get_active_roster`, pero selecciona campos específicos
  2. Igual filtro: activos y no archivados
  3. Devuelve lista ordenada
- **Llama a:** `get_db()`

### `get_roster_entry(channel_id, profile_id)` — `backend/db/queries/channels.py`
- **Recibe:** `channel_id: int`, `profile_id: int`
- **Devuelve:** `dict | None` (un entry del roster)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta JOIN similar pero con WHERE channel_id = ? AND profile_id = ?
  3. Devuelve una fila
- **Llama a:** `get_db()`

### `add_to_roster(channel_id, profile_id, speaking_order)` — `backend/db/queries/channels.py`
- **Recibe:** `channel_id: int`, `profile_id: int`, `speaking_order: int`
- **Devuelve:** nada
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta INSERT INTO channel_profiles (channel_id, profile_id, speaking_order) VALUES (?, ?, ?)
  3. **Estrategia importante:** ON DUPLICATE KEY UPDATE active = TRUE, speaking_order = ? permite re-añadir un perfil ya removido (activa su entry previa)
- **Llama a:** `get_db()`

### `remove_from_roster(channel_id, profile_id)` — `backend/db/queries/channels.py`
- **Recibe:** `channel_id: int`, `profile_id: int`
- **Devuelve:** nada
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta UPDATE channel_profiles SET active = FALSE (borrado lógico, no físico)
  3. La entrada sigue existiendo pero marcada como inactiva
- **Llama a:** `get_db()`

### `get_synthesis_cache(channel_id)` — `backend/db/queries/channels.py`
- **Recibe:** `channel_id: int`
- **Devuelve:** `dict | None` (con keys `content` y `up_to_msg_id`)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta SELECT content, up_to_msg_id FROM channel_syntheses WHERE channel_id = ?
  3. Devuelve una fila (la más reciente síntesis caché) o None
- **Llama a:** `get_db()`

### `save_synthesis(channel_id, content, up_to_msg_id)` — `backend/db/queries/channels.py`
- **Recibe:** `channel_id: int`, `content: str`, `up_to_msg_id: int`
- **Devuelve:** nada
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta INSERT INTO channel_syntheses (channel_id, content, up_to_msg_id) VALUES (?, ?, ?)
  3. **ON DUPLICATE KEY UPDATE:** si ya existe una síntesis para ese canal, reemplaza content y up_to_msg_id
- **Llama a:** `get_db()`

### `delete_synthesis_cache(channel_id)` — `backend/db/queries/channels.py`
- **Recibe:** `channel_id: int`
- **Devuelve:** nada
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta DELETE FROM channel_syntheses WHERE channel_id = ?
- **Llama a:** `get_db()`

### `get_profile(profile_id)` — `backend/db/queries/profiles.py`
- **Recibe:** `profile_id: int`
- **Devuelve:** `dict | None` (row de profiles)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta SELECT * FROM profiles WHERE id = ? AND archived = FALSE
  3. Devuelve una fila (solo si no está archivado)
- **Llama a:** `get_db()`

### `list_profiles()` — `backend/db/queries/profiles.py`
- **Recibe:** nada
- **Devuelve:** `list[dict]` (todas las filas de profiles no archivadas)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta SELECT * FROM profiles WHERE archived = FALSE ORDER BY id
  3. Devuelve todas las filas
- **Llama a:** `get_db()`

### `insert_profile(name, tipo, model, temperature, color, funcion, system_prompt)` — `backend/db/queries/profiles.py`
- **Recibe:** `name: str`, `tipo: str` ('tertuliano' o 'facilitador'), `model: str`, `temperature: float`, `color: str | None`, `funcion: str`, `system_prompt: str`
- **Devuelve:** `int` (id del perfil creado)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta INSERT INTO profiles (name, tipo, model, temperature, color, funcion, system_prompt) VALUES (?, ?, ?, ?, ?, ?, ?)
  3. Devuelve cur.lastrowid
- **Llama a:** `get_db()`

### `update_profile(profile_id, fields)` — `backend/db/queries/profiles.py`
- **Recibe:** `profile_id: int`, `fields: dict`
- **Devuelve:** nada
- **Qué hace, paso a paso:**
  1. Si `fields` vacío, retorna
  2. Construye dinámicamente SET clause
  3. Adquiere un cursor
  4. Ejecuta UPDATE profiles SET ... WHERE id = ?
- **Llama a:** `get_db()`

### `get_moderador_profile()` — `backend/db/queries/profiles.py`
- **Recibe:** nada
- **Devuelve:** `dict | None` (row de profiles)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta SELECT * FROM profiles WHERE LOWER(funcion) LIKE '%moderador%' AND archived = FALSE LIMIT 1
  3. Busca el primer perfil cuyo campo `funcion` contenga "moderador" (case-insensitive)
  4. Devuelve una fila (el perfil Moderador especial usado para síntesis)
- **Llama a:** `get_db()`
- **Nota:** Busca por `funcion`, no por `name`. El perfil Moderador no aparece en `init.sql`, por lo que probablemente se cargue en producción desde otra fuente.

### `archive_profile(profile_id)` — `backend/db/queries/profiles.py`
- **Recibe:** `profile_id: int`
- **Devuelve:** nada
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta UPDATE profiles SET archived = TRUE WHERE id = ?
  3. Borrado lógico: el perfil sigue en BD pero se oculta de listas (archived = TRUE)
- **Llama a:** `get_db()`

### `insert_message(channel_id, role, content, profile_id, tokens_in, tokens_out, cost_usd)` — `backend/db/queries/messages.py`
- **Recibe:** `channel_id: int`, `role: str` ('human'/'persona'/'system'), `content: str`, `profile_id: int | None`, `tokens_in: int | None`, `tokens_out: int | None`, `cost_usd: Decimal | None`
- **Devuelve:** `int` (id del mensaje, lastrowid)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta INSERT INTO messages (channel_id, role, profile_id, content, tokens_in, tokens_out, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?)
  3. Devuelve cur.lastrowid
- **Llama a:** `get_db()`

### `get_context_messages(channel_id, after_msg_id)` — `backend/db/queries/messages.py`
- **Recibe:** `channel_id: int`, `after_msg_id: int | None` (opcional: solo mensajes posteriores a este id)
- **Devuelve:** `list[dict]` (todas las filas de messages)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Si `after_msg_id` es None: SELECT * FROM messages WHERE channel_id = ? ORDER BY created_at
  3. Si `after_msg_id` no es None: SELECT * ... WHERE channel_id = ? AND id > ? ORDER BY created_at
  4. Devuelve todas las filas (usada para construir el contexto del turno)
- **Llama a:** `get_db()`

### `get_latest_summary(channel_id)` — `backend/db/queries/messages.py`
- **Recibe:** `channel_id: int`
- **Devuelve:** `dict | None` (row de summaries más reciente)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta SELECT * FROM summaries WHERE channel_id = ? ORDER BY created_at DESC LIMIT 1
  3. Devuelve el resumen más reciente (acta rodante)
- **Llama a:** `get_db()`

### `get_total_cost_usd(channel_id)` — `backend/db/queries/messages.py`
- **Recibe:** `channel_id: int`
- **Devuelve:** `Decimal` (suma total de costos en USD)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta SELECT COALESCE(SUM(cost_usd), 0) AS total FROM messages WHERE channel_id = ?
  3. Convierte el resultado a Decimal (para precisión monetaria)
  4. Devuelve el total
- **Llama a:** `get_db()`

### `get_full_transcript(channel_id)` — `backend/db/queries/messages.py`
- **Recibe:** `channel_id: int`
- **Devuelve:** `list[dict]` (filas con role, content, speaker)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta SELECT m.role, m.content, p.name AS speaker FROM messages m LEFT JOIN profiles p WHERE channel_id = ? AND role IN ('human', 'persona') ORDER BY id ASC
  3. Devuelve solo mensajes de humano y personajes (no 'system'), con nombre del hablante
  4. Usado para síntesis y export a Obsidian
- **Llama a:** `get_db()`

### `insert_summary(channel_id, content, covers_up_to_msg_id)` — `backend/db/queries/messages.py`
- **Recibe:** `channel_id: int`, `content: str`, `covers_up_to_msg_id: int`
- **Devuelve:** `int` (id del summary, lastrowid)
- **Qué hace, paso a paso:**
  1. Adquiere un cursor
  2. Ejecuta INSERT INTO summaries (channel_id, content, covers_up_to_msg_id) VALUES (?, ?, ?)
  3. Devuelve cur.lastrowid (crea una nueva entrada en el acta rodante)
- **Llama a:** `get_db()`

## Datos que toca

**Lectura y escritura:**
- **profiles** — todas las funciones que tratan perfiles (get, list, insert, update, archive)
- **channels** — todas las funciones que tratan canales (get, list, insert, update, delete)
- **channel_profiles** — roster: add_to_roster, remove_from_roster, get_active_roster, get_full_roster, get_roster_entry
- **messages** — todos los mensajes: insert_message, get_context_messages, get_full_transcript, get_total_cost_usd
- **summaries** — actas rodantes: get_latest_summary, insert_summary, y borrado en cascada al eliminar canal
- **channel_syntheses** — caché de síntesis por canal: get_synthesis_cache, save_synthesis, delete_synthesis_cache

## Entradas y salidas de la pieza

**Quién la llama:**
- `arranque-config` — en lifespan(), llama a `init_pool()` y `close_pool()`
- `api-entidades` — llama a query functions para CRUD de canales, perfiles, roster
- `orquestacion-turno` — llama a query functions para obtener roster, insertar mensajes, leer contexto
- `compresion-contexto` — llama a query functions para leer mensajes, insertar summaries
- `sintesis-export` — llama a query functions para obtener transcript completo, caché de síntesis

**A quién llama:**
- `aiomysql` (librería externa) — crea y gestiona el pool
- `backend.config.settings` — lee configuración de base de datos (host, port, user, password, db_name)

## Lo no obvio

1. **Autocommit y falta de transacciones explícitas:** El pool se crea con `autocommit=True`, lo que significa que cada statement es una transacción autónoma. No hay soporte para transacciones multi-statement en Fase 1 (ver comentario en `connection.py`). Esto puede causar inconsistencias: en `delete_channel()`, si falla entre el DELETE de summaries y el DELETE de channels, quedarán en estado inconsistente.

2. **Workaround de borrado en cascada:** `delete_channel()` borra summaries primero y después channels, porque la FK `summaries.covers_up_to_msg_id → messages` tiene `ON DELETE RESTRICT`. Esto evita un error de constraint, pero no es una solución atómica.

3. **Borrado lógico vs físico:** 
   - Perfiles: `archive_profile()` marca como `archived = TRUE`, no borra físicamente
   - Roster: `remove_from_roster()` marca como `active = FALSE`, no borra físicamente
   - Esto permite recuperar o reutilizar entries sin perder datos

4. **Búsqueda del perfil Moderador:** `get_moderador_profile()` busca por `funcion LIKE '%moderador%'`, no por nombre. El perfil Moderador no está en `init.sql` (que solo tiene a Sócrates), por lo que probablemente se cargue en producción de otra forma. El mapa no especifica dónde.

5. **Caché de síntesis con upsert:** `save_synthesis()` usa `ON DUPLICATE KEY UPDATE` para reemplazar la síntesis previa (mariadb/mysql). Un canal solo puede tener una síntesis caché a la vez. La invalidación se hace explícitamente con `delete_synthesis_cache()`, pero el código de esta pieza no decide cuándo hacerlo — eso depende de las piezas que la llaman (probablemente `sintesis-export`).

6. **Pool con tamaño fijo:** minsize=1, maxsize=10. Si más de 10 conexiones concurrentes piden al pool, se encolarán esperando. Esto es un cuello de botella potencial bajo alta concurrencia.

7. **DictCursor:** Todas las queries usan `aiomysql.DictCursor`, que devuelve filas como diccionarios (`{'id': 1, 'name': 'Sócrates'}` en lugar de tuplas). Esto facilita el acceso por nombre de columna pero consume más memoria.

## Respuestas a las preguntas del Despiezador

**¿Cómo gestiona el pool errores de conexión o reintentos?**

No hay reintentos explícitos en este módulo. La función `init_pool()` solo crea el pool con `aiomysql.create_pool()`. Si la conexión falla, lanza una excepción sin reintentar. El `get_db()` context manager tampoco implementa reintentos: simplemente adquiere una conexión del pool (que ya debe estar inicializado) o levanta `RuntimeError` si no existe.

**¿Cuándo se invalida o se reusa la caché de `channel_syntheses`?**

Del código SQL:
- `get_synthesis_cache(channel_id)` — obtiene la síntesis caché actual (si existe)
- `save_synthesis(channel_id, content, up_to_msg_id)` — crea o reemplaza la síntesis caché con `INSERT ... ON DUPLICATE KEY UPDATE`
- `delete_synthesis_cache(channel_id)` — borra la síntesis caché explícitamente

La caché es una sola entrada por canal (PRIMARY KEY es channel_id). El patrón de invalidación no está definido en esta pieza: depende de quién llame a `delete_synthesis_cache()`. Probablemente sea `sintesis-export` la que decide cuándo invalidar (ej: después de que cambie el transcript, o después de N nuevos mensajes), pero eso está fuera de este módulo.

**¿Hay transacciones explícitas en operaciones que tocan varias tablas a la vez?**

NO. El pool está configurado con `autocommit=True`, lo que desactiva las transacciones multi-statement. El caso más crítico es `delete_channel()`, que ejecuta:
1. `DELETE FROM summaries WHERE channel_id = ?`
2. `DELETE FROM channels WHERE id = ?`

Sin transacción explícita. Esto es un workaround para evitar el error de constraint `ON DELETE RESTRICT` en la FK de summaries. Si falla entre los dos DELETEs, quedaría inconsistente. Las cascadas `ON DELETE CASCADE` se aplicarán a messages y channel_profiles automáticamente en el motor, pero no hay control transaccional desde Python.

## Dudas

- ¿Desde dónde se carga el perfil Moderador en producción? No está en `init.sql` y `get_moderador_profile()` solo busca por `funcion LIKE '%moderador%'`.
- ¿Quién llama explícitamente a `delete_synthesis_cache()`? El código de esta pieza no lo hace automáticamente. Probablemente lo haga `sintesis-export` o una lógica de invalidación en otra pieza, pero no está documentado aquí.
- ¿Qué pasa si `init_pool()` falla al conectar? Se lanza excepción directamente. ¿Se reintenía desde `arranque-config` o fallaba la app directamente?
