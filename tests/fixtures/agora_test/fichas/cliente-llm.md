# Ficha: cliente-llm

## Qué hace

Maneja la conexión técnica a la API de Anthropic para un tertuliano en un turno: llama a Claude en modo streaming para que devuelva tokens en tiempo real, y calcula automáticamente el coste en USD de cada llamada según los tokens consumidos (entrada, salida, cache). Abstrae las particularidades del modelo elegido (qué parámetros acepta, tabla de precios).

## Ficheros

- `backend/services/llm.py` — cliente async a Anthropic, tablas de coste por modelo, función generadora que yield tokens y stats

## Funciones tronco

### `stream_turn(system: str, messages: list[dict], model: str, temperature: float)` — `backend/services/llm.py`

- **Recibe:**
  - `system`: string del system prompt ya armado por construccion-prompt
  - `messages`: lista de dicts con `{"role": "...", "content": "..."}` del contexto armado
  - `model`: nombre del modelo Claude (p. ej. `"claude-haiku-4-5-20251001"`)
  - `temperature`: valor entre 0 y 1 (ignorado si el modelo no lo acepta)

- **Devuelve:** AsyncGenerator que yield:
  - (iteración por iteración) strings individuales de tokens conforme llegan de Anthropic (streaming)
  - (al final, una sola vez) dict con: `{"tokens_in": int, "tokens_out": int, "cost_usd": Decimal, "cache_write": int, "cache_read": int}`

- **Qué hace, paso a paso:**
  1. Arma un dict `kwargs` con el modelo, max_tokens (hardcodeado a 1024), system y messages
  2. Si el modelo está en `_MODELS_NO_TEMPERATURE`, omite añadir `temperature` (modelos 4.x no lo aceptan)
  3. Abre un stream async a `client.messages.stream()` (cliente Anthropic singleton ya inicializado)
  4. Itera sobre `stream.text_stream` y yield cada token de texto
  5. Llama a `stream.get_final_message()` para obtener el conteo de tokens final (input, output, cache_write, cache_read)
  6. Busca el modelo en la tabla `_COST_PER_TOKEN` para obtener precios unitarios; si no está, usa `{"in": 0.0, "out": 0.0}` (sin error)
  7. Calcula coste: `tokens_in * precio_in + cache_write * precio_in * 1.25 + cache_read * precio_in * 0.1 + tokens_out * precio_out`
  8. Yield el dict de stats (cost como Decimal redondeado a 8 decimales, tokens_in incluye cache_write + cache_read)

- **Llama a:** `client.messages.stream()` (cliente Anthropic en `backend/config.py`)

### Global data

- **`_COST_PER_TOKEN`** (`dict[str, dict[str, float]]`): mapeo hardcodeado de modelo → `{"in": USD/token, "out": USD/token}`. Actualmente: `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-opus-4-8`. Actualizar manualmente cuando Anthropic cambie precios.

- **`_MODELS_NO_TEMPERATURE`** (`set[str]`): lista de modelos que no aceptan el parámetro `temperature` (los 4.x de Anthropic). Usado para decidir si pasar ese parámetro o no.

- **`client`** (único por módulo): `AsyncAnthropic(api_key=...)` inicializado con la clave de `settings.anthropic_api_key`. Se reutiliza en todas las llamadas.

## Datos que toca

- **No toca BD:** solo lee configuración (modelo, temperatura de cada perfil) pasada como parámetros
- **Sí toca:** la API de Anthropic (streaming y bloqueo de rate limits)
- **Cost tracking:** calcula el coste en memoria y lo devuelve; quien la llama es responsable de guardarlo en la BD (ver orquestacion-turno, que persiste el dict de stats)

## Entradas y salidas de la pieza

- **Quién la llama:**
  - `orquestacion-turno` (`run_turn()` en `orchestrator.py`) — para cada tertuliano de un turno
  - `sintesis-export` (`run_synthesis()` en `synthesizer.py`) — para generar síntesis con Moderador

- **A quién llama:**
  - Anthropic API (directamente: `client.messages.stream()`)
  - No llama a otras piezas del repo (es un cliente técnico puro)

## Lo no obvio

1. **Modelo no encontrado en tabla de precios:** si el modelo no está en `_COST_PER_TOKEN`, no lanza error. Usa `.get(model, {"in": 0.0, "out": 0.0})`, así que calcula coste = 0.0. Esto es silencioso y incorrecto: un modelo nuevo en la API sin entrada en la tabla se reportaría como gratuito.

2. **Manejo de caché de contexto:** Anthropic devuelve `cache_creation_input_tokens` y `cache_read_input_tokens` en el usage final. El código usa `getattr(..., 0)` para evitar error si no existen (versiones viejas de la API). Los tokens de caché se facturan a tasa diferente (1.25x para escritura, 0.1x para lectura) y se suman al count de `tokens_in` en el resultado.

3. **Max tokens hardcodeado:** `max_tokens=1024` está fijo en el código. No es configurable por perfil ni por turno. Todas las respuestas se truncan a 1024 tokens.

4. **Temperature inaplicable sin aviso:** si el usuario pasa `temperature=0.7` para un modelo `claude-opus-4-8` (que está en `_MODELS_NO_TEMPERATURE`), el parámetro se omite silenciosamente. No hay aviso en logs ni en el resultado: la API simplemente usa su default (probablemente 1.0 o no configurable).

5. **Error propagation asimétrica:**
   - En **synthesizer.py** (sintesis-export), excepciones de `stream_turn()` se capturan (try/except, línea 125) y se convierten en mensajes SSE `{'type': 'error', ...}` que llegan al frontend.
   - En **orchestrator.py** (orquestacion-turno), excepciones de `stream_turn()` se capturan, loguean y se **re-lanzan** (línea 97). FastAPI interrumpe la conexión SSE: el frontend recibe un cierre abrupto, no un mensaje de error.
   - **compressor.py** no usa `stream_turn()`: hace su propia llamada directa a `AsyncAnthropic.messages.create()` (no streaming), captura excepciones y loguea, pero continúa sin comprimir (no bloquea ni interrumpe el turno).

6. **Coste como Decimal:** la salida usa `Decimal` (no float) para evitar problemas de precisión. Se redondea a 8 decimales. Esto es importante porque fluye a la BD.

## Respuestas a las preguntas del Despiezador

**P1: El mapa indica que no hay validación si el modelo no está en `_COST_PER_TOKEN` o `_MODELS_NO_TEMPERATURE` — ¿qué pasa realmente en ese caso?**

Respuesta:
- **Para `_COST_PER_TOKEN`:** línea 50 usa `.get(model, {"in": 0.0, "out": 0.0})`. Si el modelo no existe en la tabla, no hay error, pero el coste calculado es 0.0 (incorrecto). Es un fallo silencioso.
- **Para `_MODELS_NO_TEMPERATURE`:** línea 38 verifica `if model not in _MODELS_NO_TEMPERATURE`. Si el modelo no está en el conjunto, asume que sí acepta `temperature` y lo pasa. Si es un modelo que no lo acepta pero no está en la lista, Anthropic rechazará la llamada con un error de API (no es silencioso en ese caso).

**P2: ¿`compressor.py` y `synthesizer.py` reusan `stream_turn()` para llamar a Anthropic, o hacen su propia llamada directa a la API?**

Respuesta:
- **synthesizer.py (línea 13):** importa `stream_turn` de `llm.py` y lo **reutiliza** (líneas 116-121). Llama a stream_turn con el system prompt del Moderador y el prompt de síntesis, obtiene tokens en streaming y SSE.
- **compressor.py (línea 18):** crea su propio cliente `AsyncAnthropic(...)` y hace una **llamada directa** a `_client.messages.create()` (no streaming, no reutiliza `stream_turn()`). Usa Haiku, max_tokens=1200, temperature=0.2.

**P3: ¿Cómo se propaga hacia el SSE del frontend un error de la API (rate limit, timeout, contenido bloqueado)?**

Respuesta:
- **En synthesizer.py** (sintesis-export): líneas 115-127 envuelven `stream_turn()` en try/except. Si hay error, yielda un SSE message: `{'type': 'error', 'message': str(exc)}`. El frontend lo recibe como un evento SSE normal (graceful).
- **En orchestrator.py** (orquestacion-turno): líneas 81-97 envuelven `stream_turn()` en try/except. Si hay error, lo loguea (línea 91-96) y lo **re-lanza** (línea 97). FastAPI interrumpe la conexión SSE: el frontend pierde la conexión (no recibe un mensaje de error estructurado, sino un cierre abrupto de red).
- **En compressor.py**: línea 141 captura excepciones de Haiku y loguea, pero **no interrumpe** el turno. El compressor continúa (simplemente sin actualizar el acta). El error no se propaga al frontend porque `maybe_compress()` se ejecuta internamente, no en el endpoint SSE.

## Dudas

(Ninguna detectada al leer el código. El comportamiento es claro una vez se sigue el flujo.)
