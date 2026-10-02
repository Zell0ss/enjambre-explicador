# Ficha: Compresión de contexto

## Qué hace

Cuando la conversación de un canal supera 30 mensajes sin comprimir, resume los más antiguos en un "acta" rodante usando Haiku. El acta se guarda como un `summary` en la BD, cubriendo hasta el último mensaje procesado. Así, el contexto enviado al modelo siguiente no crece indefinidamente y se mantiene una memoria resumida de lo que ha pasado en la tertulia. Si la compresión falla, el turno continúa sin bloqueo.

## Ficheros

- `backend/services/compressor.py` — lógica de compresión: detección de umbral, construcción del prompt a Haiku, actualización del acta y persistencia.

## Funciones tronco

### `maybe_compress(channel_id: int, mode: str = "debate")` — `backend/services/compressor.py:126`
- **Recibe:**
  - `channel_id`: identificador del canal
  - `mode`: modo del canal ("debate" o "critica"), para elegir el formato del acta
- **Devuelve:** nada (void); efecto es persistir un nuevo `summary` en BD o no hacer nada
- **Qué hace, paso a paso:**
  1. Obtiene del BD el último `summary` (acta anterior) del canal, si existe
  2. Cuenta cuántos mensajes hay sin comprimir (posteriores al último `summary`)
  3. Si hay menos de 30 mensajes, retorna sin hacer nada
  4. Si hay 30 o más, obtiene los primeros 20 nuevos mensajes como chunk
  5. Llama a `_update_acta()` para que Haiku regenere el acta completa incorporando el chunk
  6. Si Haiku devuelve un acta válida, la guarda en la BD con `insert_summary()`, marcando hasta qué mensaje cubre
  7. Si falla en cualquier punto (excepción), registra el error en logs y retorna sin bloquear el turno
- **Llama a:**
  - `get_latest_summary()` (acceso-datos)
  - `count_messages_after()` (acceso-datos)
  - `get_messages_chunk()` (acceso-datos)
  - `_update_acta()` (esta pieza)
  - `insert_summary()` (acceso-datos)
  - `logger.error()`, `logger.warning()`, `logger.info()` (arranque-config)

### `_update_acta(previous_acta: str | None, chunk: list[dict], mode: str)` — `backend/services/compressor.py:110`
- **Recibe:**
  - `previous_acta`: contenido markdown del acta anterior (o None si es la primera compresión)
  - `chunk`: lista de 20 mensajes nuevos, cada uno con `id`, `role`, `profile_id`, `content`, `profile_name`
  - `mode`: "debate" o "critica", para determinar el formato del acta
- **Devuelve:** string con el acta completa actualizada en markdown
- **Qué hace, paso a paso:**
  1. Construye el mensaje de usuario para Haiku usando `_build_user_message()`
  2. Llama a la API de Anthropic (Haiku) en modo síncrono (no streaming) con:
     - `temperature=0.2` (bajo, para respuestas deterministas)
     - `max_tokens=1200` (margen sobre el límite de 800 del acta)
     - System prompt que instruye a Haiku a ser el "actualizador del acta"
  3. Retorna el texto del acta generada (primer `content` de la respuesta)
- **Llama a:**
  - `_build_user_message()` (esta pieza)
  - `_client.messages.create()` (cliente-llm / Anthropic API)

### `_build_user_message(previous_acta: str | None, chunk: list[dict], mode: str)` — `backend/services/compressor.py:82`
- **Recibe:**
  - `previous_acta`: contenido del acta anterior (o None)
  - `chunk`: lista de mensajes nuevos
  - `mode`: "debate" o "critica"
- **Devuelve:** string con el prompt completo para Haiku (instrucciones + acta anterior + mensajes nuevos + formato)
- **Qué hace, paso a paso:**
  1. Extrae de cada mensaje del chunk el nombre del hablante (`profile_name` o `role`) y su contenido
  2. Formatea línea por línea como "Nombre: contenido" (excluyendo mensajes con `role="system"`)
  3. Si hay acta anterior, la incluye en un bloque XML `<acta_anterior>...</acta_anterior>`
  4. Si no hay acta anterior, instruye "Genera el acta desde cero"
  5. Construye el prompt con: instrucciones generales + bloque de acta anterior + bloque de mensajes nuevos + formato específico (debate o crítica)
  6. Retorna todo concatenado como un único string que será el user message para Haiku
- **Llama a:** nada (función pura de construcción de strings)

## Datos que toca

- **Lee de BD (acceso-datos):**
  - Tabla `summaries`: última entrada por `channel_id` → fields: `id`, `created_at`, `content`, `covers_up_to_msg_id`
  - Tabla `messages`: cuenta y chunk de mensajes nuevos → fields: `id`, `role`, `profile_id`, `content`, `created_at`
  - Tabla `profiles` (join): nombre del hablante (`name`)

- **Escribe en BD (acceso-datos):**
  - Tabla `summaries`: un nuevo `INSERT` con `(channel_id, content, covers_up_to_msg_id)` cada vez que se comprime

- **En memoria:**
  - Módulo: `_client` (AsyncAnthropic singleton, instanciado al cargar el módulo con la API key de settings)
  - Constantes de control: `COMPRESSION_THRESHOLD=30`, `COMPRESSION_CHUNK=20`, `ACTA_MAX_TOKENS=800`

## Entradas y salidas de la pieza

- **Quién la llama:**
  - `orquestacion-turno` (`run_turn()`) — línea 40 de orchestrator.py, justo al inicio de cada turno, antes de guardar el mensaje humano
  - También accesible vía test (`backend/tests/test_compressor.py`)

- **A quién llama:**
  - `acceso-datos`: `get_latest_summary()`, `count_messages_after()`, `get_messages_chunk()`, `insert_summary()`
  - `cliente-llm` (Anthropic API): a través del `AsyncAnthropic` client, modelo Haiku 4.5
  - `arranque-config`: logger para error, warning e info

## Lo no obvio

1. **Reescritura completa, no delta:** Aunque se llama "actualizar acta", Haiku regenera el acta completa cada vez (no solo las líneas nuevas). Esto asegura coherencia narrativa y permite que viejas entradas cambien si la conversación nueva las resuelve o vuelve irrelevantes. La acta anterior se pasa como contexto, y las instrucciones piden conservar "TODAS las entradas del acta anterior salvo que los mensajes nuevos las modifiquen, las resuelvan o las vuelvan irrelevantes."

2. **El chunk es fijo a 20, pero el umbral es 30:** Se comprime cuando hay 30+ mensajes sin comprimir, pero solo se procesa el chunk de los 20 primeros. Esto deja 10+ mensajes aún sin comprimir, que se volverán a procesar en la siguiente compresión. Permite procesamiento incremental y reduce el tamaño de cada llamada a Haiku.

3. **Formato bifurcado:** El acta tiene dos formatos distintos (`ANDAMIO_DEBATE` y `ANDAMIO_CRITICA`) con secciones diferentes. En debate: "Tema y arranque", "Posiciones por hablante", "Desacuerdos abiertos", "Concesiones y giros", etc. En crítica: "Texto y objetivo", "Observaciones por crítico", "Sugerencias sobre la mesa", etc.

4. **Fallo silencioso:** Si Haiku falla (excepción, timeout, rate limit, etc.), se registra en logs pero el turno **no se bloquea**. El turno continúa con mensajes no comprimidos, y en el próximo turno se reintentará la compresión. Así se prioriza disponibilidad sobre garantía de compresión.

5. **Acta vacía es descartada:** Si Haiku devuelve un string vacío o solo whitespace, se descarta con warning (líneas 149-154) y no se persiste en BD. Evita corrupción silenciosa del estado.

6. **Límite soft de tokens:** `ACTA_MAX_TOKENS=800` es una instrucción a Haiku, no un hard limit. `_ACTA_GEN_TOKENS=1200` es el headroom para la generación. Las instrucciones piden condensar en "Temas cerrados" y "Datos y referencias clave" si hace falta, pero nunca recortar "Posiciones por hablante" ni "Desacuerdos abiertos".

7. **Mensajes sin nombre de perfil:** Si un mensaje tiene `profile_id=None`, se usa `role` en lugar de nombre (línea 88: `profile_name or m["role"]`). Incluye mensajes humanos y de sistema, aunque las instrucciones excluyen los de sistema (línea 90).

## Respuestas a las preguntas del Despiezador

**¿Cuál es el umbral exacto que dispara `maybe_compress()`?**

30 mensajes sin comprimir (`COMPRESSION_THRESHOLD = 30`, línea 12). La condición es `count < COMPRESSION_THRESHOLD` (línea 130): si hay menos de 30, no hace nada. Una vez alcanzados 30+, toma los primeros 20 (`COMPRESSION_CHUNK = 20`) y comprime.

**¿`_update_acta()` reescribe el acta entera cada vez o la extiende incrementalmente sobre la anterior?**

Reescribe la acta **entera**, pero usando la anterior como entrada para mantener contexto. Haiku recibe las instrucciones "Devuelve el acta completa actualizada (no un delta, no un resumen del chunk)" (línea 32) y "Conserva TODAS las entradas del acta anterior salvo que los mensajes nuevos las modifiquen..." (línea 30-31). El prompt incluye `<acta_anterior>...</acta_anterior>` y `<mensajes_nuevos>...</mensajes_nuevos>` como bloques separados para que Haiku entienda qué es viejo y qué es nuevo, y genere una acta coherente completa.

**¿Qué pasa si falla la llamada a Haiku — bloquea el turno en curso o el turno sigue sin comprimir?**

El turno sigue sin comprimir. `maybe_compress()` está envuelta en try-except (líneas 139-147): si hay excepción (timeout, rate limit, modelo no disponible, etc.), se registra error en logs y la función retorna silenciosamente con `return` (línea 147). No re-levanta la excepción. El turno continúa normalmente en `run_turn()` con mensajes no comprimidos, y en el próximo turno se reintentará la compresión.

## Dudas

Ninguna. El código es claro y autoexplicativo. Las preguntas del Despiezador han sido resueltas por lectura directa.
