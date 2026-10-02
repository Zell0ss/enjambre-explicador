# Ficha: api-entidades

## Qué hace
Expone tres routers REST para gestionar canales, perfiles y roster (membresía de perfiles en canales). Valida entrada con Pydantic, ejecuta operaciones CRUD sobre la base de datos y asegura que nunca haya más de 3 perfiles simultáneos en un canal. No contiene lógica de debate; es un CRUD clásico de entidades desacoplado de la orquestación de turnos.

## Ficheros
- `backend/api/channels.py` — router de canales, roster y mensajes (10 endpoints)
- `backend/api/profiles.py` — router de perfiles (5 endpoints)
- `backend/schemas/models.py` — schemas Pydantic para validación de entrada/salida

## Funciones tronco

### `list_channels_endpoint()` — `backend/api/channels.py`
- **Recibe:** nada
- **Devuelve:** list[ChannelOut]
- **Qué hace, paso a paso:**
  1. Llama a `list_channels()` de acceso-datos
  2. Devuelve la lista de canales con sus metadatos (title, mode, incognito, base_text, timestamps)
- **Llama a:** `list_channels()` (acceso-datos)

### `create_channel(body: ChannelIn)` — `backend/api/channels.py`
- **Recibe:** ChannelIn (title requerido; mode="debate"|"critica" default, incognito=False, base_text=None)
- **Devuelve:** ChannelOut (con id, timestamps)
- **Qué hace, paso a paso:**
  1. Inserta el canal en BD con `insert_channel(title, mode, incognito, base_text)`
  2. Lee el canal recién creado con `get_channel(id)` para devolver su estado completo
- **Llama a:** `insert_channel()`, `get_channel()` (acceso-datos)

### `patch_channel(channel_id: int, body: ChannelPatch)` — `backend/api/channels.py`
- **Recibe:** channel_id, ChannelPatch (title, mode, incognito, base_text; todos opcionales)
- **Devuelve:** ChannelOut actualizado
- **Qué hace, paso a paso:**
  1. Valida que el canal exista, si no → 404
  2. Extrae los campos no-None de ChannelPatch
  3. Si se modificó `base_text`, **invalida la caché de síntesis** llamando a `delete_synthesis_cache()`
  4. Actualiza el canal con `update_channel()`
  5. Lee y devuelve el estado final
- **Llama a:** `get_channel()`, `delete_synthesis_cache()`, `update_channel()` (acceso-datos)

### `delete_channel_endpoint(channel_id: int)` — `backend/api/channels.py`
- **Recibe:** channel_id
- **Devuelve:** 204 (sin contenido)
- **Qué hace, paso a paso:**
  1. Valida que el canal exista, si no → 404
  2. Borra el canal de BD (y posiblemente su roster, mensajes en cascada según la BD)
- **Llama a:** `get_channel()`, `delete_channel()` (acceso-datos)

### `add_profile_to_channel(channel_id: int, body: RosterAddIn)` — `backend/api/channels.py`
- **Recibe:** channel_id, RosterAddIn (profile_id requerido, speaking_order=0)
- **Devuelve:** RosterEntry (201)
- **Qué hace, paso a paso:**
  1. Valida que el canal exista, si no → 404
  2. Cuenta perfiles activos en ese canal
  3. Si ≥ 3, rechaza con 400 "Channel already has 3 active profiles"
  4. Añade el perfil al roster con `add_to_roster(channel_id, profile_id, speaking_order)`
  5. Lee y devuelve la entrada del roster recién creada
- **Llama a:** `get_channel()`, `count_active_roster()`, `add_to_roster()`, `get_roster_entry()` (acceso-datos)

### `patch_roster_entry(channel_id: int, profile_id: int, body: RosterPatch)` — `backend/api/channels.py`
- **Recibe:** channel_id, profile_id, RosterPatch (speaking_order: int | None, active: bool | None)
- **Devuelve:** RosterEntry actualizado
- **Qué hace, paso a paso:**
  1. Valida que el canal exista, si no → 404
  2. Valida que el perfil esté en el roster de ese canal, si no → 404
  3. Extrae los campos no-None de RosterPatch (puede cambiar speaking_order, active o ambos)
  4. Actualiza la entrada del roster
  5. Lee y devuelve el estado final
- **Llama a:** `get_channel()`, `get_roster_entry()`, `update_roster_entry()` (acceso-datos)

### `create_profile(body: ProfileIn)` — `backend/api/profiles.py`
- **Recibe:** ProfileIn (name, funcion, system_prompt requeridos; tipo="tertuliano", model="claude-sonnet-4-6", temperature=0.7, color=None con defaults)
- **Devuelve:** ProfileOut (201, con id, archived=False, timestamps)
- **Qué hace, paso a paso:**
  1. Inserta el perfil en BD con `insert_profile(name, tipo, model, temperature, color, funcion, system_prompt)`
  2. Lee el perfil recién creado con `get_profile(id)` para devolver su estado completo
- **Llama a:** `insert_profile()`, `get_profile()` (acceso-datos)

### `patch_profile(profile_id: int, body: ProfilePatch)` — `backend/api/profiles.py`
- **Recibe:** profile_id, ProfilePatch (name, model, temperature, color, funcion, system_prompt; todos opcionales)
- **Devuelve:** ProfileOut actualizado
- **Qué hace, paso a paso:**
  1. Valida que el perfil exista, si no → 404
  2. Extrae los campos no-None de ProfilePatch (nota: `tipo` NO se puede cambiar)
  3. Actualiza el perfil con `update_profile()`
  4. Lee y devuelve el estado final
- **Llama a:** `get_profile()`, `update_profile()` (acceso-datos)

### `delete_profile(profile_id: int)` — `backend/api/profiles.py`
- **Recibe:** profile_id
- **Devuelve:** 204 (sin contenido)
- **Qué hace, paso a paso:**
  1. Valida que el perfil exista, si no → 404
  2. Llama a `archive_profile()` — **borrado lógico**, no físico; marca archived=True
- **Llama a:** `get_profile()`, `archive_profile()` (acceso-datos)

## Datos que toca
- **Tabla `channels`:** lee y escribe (CRUD completo)
- **Tabla `profiles`:** lee y escribe (CRUD, con borrado lógico vía `archived`)
- **Tabla `channel_profiles`:** lee, escribe, borra (roster: membresía de perfiles en canales)
- **Tabla `messages`:** solo lee (para listar mensajes de un canal)
- **Caché `channel_syntheses`:** solo escribe para invalidar (cuando se modifica `base_text` de un canal)

## Entradas y salidas de la pieza
- **Quién la llama:** Cliente HTTP (frontend u otros), a través de los endpoints REST del router
- **A quién llama:** 
  - acceso-datos (para todas las operaciones de BD)
  - arranque-config (monta el router en la app FastAPI durante el lifespan)
  - orquestacion-turno (el roster que crea/modifica aquí es el que recorre el round-robin)

## Lo no obvio
1. **Límite de 3 perfiles activos por canal:** no es sugerencia, es validación dura. Si se intenta añadir un 4º se rechaza con status 400, incluso si el cliente intenta contravenir.

2. **Invalidación de síntesis:** solo ocurre al modificar `base_text`. Cambiar title, mode o incognito no invalida la caché de síntesis (solo el cambio del contexto base lo justifica).

3. **Tipo de perfil es inmodificable:** `ProfilePatch` excluye `tipo`. Una vez creado un perfil como "tertuliano" o "facilitador", no se puede cambiar. Quien lo use de otra forma debe crearlo de nuevo.

4. **speaking_order lo fija el cliente, no el backend:** Al añadir un perfil con `RosterAddIn`, se puede especificar `speaking_order` (default 0). El backend lo guarda tal cual; **no recalcula ni valida el orden**. Quien lo usa (orquestacion-turno) lo interpreta para determinar el orden de turnos.

5. **Borrado lógico de perfiles, físico de canales:** 
   - `delete_profile()` → `archive_profile()` → marca `archived=True` (el perfil sigue en BD)
   - `delete_channel()` → borra físicamente (o cascada de BD si la FK lo hace)

6. **RosterEntry no incluye timestamps:** es ligera, solo lo necesario para saber quién habla en qué orden (profile_id, name, tipo, speaking_order, active).

7. **Active flag en roster:** un perfil puede estar `active=False` pero seguir siendo miembro del canal. Quien lo usa debe validar si `active` antes de incluirlo en el round-robin.

## Respuestas a las preguntas del Despiezador

**P1: ¿Qué valida cada schema `Patch` (parcial) frente a los `In`/`Out` (completos)?**

- **ProfilePatch:** solo permite modificar name, model, temperature, color, funcion, system_prompt. **NO incluye `tipo`** porque cambiar el tipo de un perfil (de tertuliano a facilitador o viceversa) es una operación conceptualmente fuerte que se desaconseja; fuerza a crear un perfil nuevo. Los otros campos son parámetros de personalización.

- **ChannelPatch:** permite cualquier campo de ChannelOut (title, mode, incognito, base_text).

- **RosterPatch:** solo speaking_order e active (los dos únicos campos de una entrada del roster que tiene sentido cambiar después de añadir el perfil).

**P2: ¿Qué ocurre con mensajes y roster al borrar un canal, y con `archive_profile()` al borrar un perfil?**

- **Al borrar un canal:** `delete_channel()` borra el registro (el código no muestra cascada explícita, pero la BD probablemente tiene FK con ON DELETE CASCADE para roster y mensajes). La respuesta HTTP es 204, sin detalles de qué más se limpió.

- **Al borrar un perfil:** **Borrado lógico.** `archive_profile()` marca `archived=True` en la tabla `profiles`. El perfil sigue en BD, sigue siendo miembro de canales (si los hay). Quien lo lea debería filtrar `archived=False` si quiere verlo como "activo". No hay eliminación de roster ni mensajes.

**P3: ¿Cómo se usa `speaking_order` al añadir un perfil al roster — se recalcula o lo fija el cliente?**

- **El cliente lo fija.** `RosterAddIn` acepta `speaking_order: int = 0`. Si no envía nada, toma 0. El backend lo guarda sin validar ni recalcular. 

- **Quien lo usa es orquestacion-turno:** lee el roster de un canal, ordena por `speaking_order`, y recorre ese orden en el round-robin. Si dos perfiles tienen el mismo `speaking_order`, el comportamiento no está definido en esta pieza (depende de cómo lo maneje el query de acceso-datos y luego la orquestación).

## Dudas
- ¿La tabla `channel_profiles` tiene índice en `speaking_order` o se ordena a nivel de aplicación al leer el roster?
- ¿Qué ocurre si dos perfiles tienen el mismo `speaking_order` en un canal — hay algoritmo de desempate o es indeterminado?
- ¿El campo `archived` en profiles se usa en los queries de acceso-datos, o siempre devuelven todos los registros sin filtrar?
