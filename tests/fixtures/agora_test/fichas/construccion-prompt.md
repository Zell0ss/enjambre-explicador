# Ficha: construccion-prompt

## Qué hace

Arma el system prompt y la estructura de bloques de contenido que irán a la API de Anthropic en cada turno. Decide si el tertuliano recibe el andamio (scaffold) de "debate" o de "crítica" según el modo del canal, o ninguno si es facilitador. Luego organiza los bloques: texto base del canal, acta de resumen rodante, y el historial de mensajes, con marcas de cache estratégicas.

## Ficheros

- `backend/services/andamio.py` — Dos constantes de system prompt (`ANDAMIO_DEBATE`, `ANDAMIO_CRITICA`) y una función (`build_context()`)

## Funciones tronco

### `build_context(profile, channel, messages, profile_names, summary=None)` — `backend/services/andamio.py`

- **Recibe:**
  - `profile: dict` — perfil del tertuliano (campos: `tipo`, `system_prompt`)
  - `channel: dict` — canal en el que ocurre el turno (campos: `mode`, `base_text` opcional)
  - `messages: list[dict]` — historial de mensajes (cada uno con `role`, `content`, opcionalemente `profile_id`)
  - `profile_names: dict[int, str]` — mapeo de profile_id → nombre mostrable
  - `summary: dict | None` — el acta rodante si existe (campo: `content`)

- **Devuelve:** `tuple[str, list[dict]]`
  - Primer elemento: system_prompt (string)
  - Segundo elemento: lista con un dict de usuario para Anthropic: `[{"role": "user", "content": [blocks]}]`

- **Qué hace, paso a paso:**
  1. Decide el system prompt según el rol del perfil y el modo del canal:
     - Si `profile["tipo"] == "facilitador"`: usa solo `profile["system_prompt"]`
     - Si `channel["mode"] == "critica"`: concatena `ANDAMIO_CRITICA` + `profile["system_prompt"]`
     - Otro caso (debate o modo por defecto): concatena `ANDAMIO_DEBATE` + `profile["system_prompt"]`
  2. Construye una lista de bloques de contenido para la API, en orden:
     - **Bloque 1** (si existe `base_text`): el texto objeto de crítica, etiquetado, con cache ephemeral
     - **Bloque 2** (si existe `summary`): el acta rodante, etiquetado, sin cache breakpoint
     - **Bloques 3…N**: cada mensaje del historial como texto etiquetado ("Josem:", nombre del tertuliano, etc.)
       - Mensajes con `role == "human"` → "Josem: contenido"
       - Mensajes con `role == "persona"` y `profile_id` válido → "Nombre: contenido"
       - Mensajes con `role == "system"` → ignorados
       - El último bloque del transcript recibe cache ephemeral; los anteriores no
     - **Bloque por defecto** (si no hay mensajes): "(La conversación acaba de comenzar.)"
  3. Devuelve el sistema y la lista de mensajes lista para pasar a Anthropic

- **Llama a:** ninguna función de este código; usa datos de perfiles y canales pasados como parámetros

## Datos que toca

- **Lee:**
  - `profile["tipo"]` — determina si es facilitador o tertuliano
  - `profile["system_prompt"]` — instrucciones personalizadas del perfil
  - `channel["mode"]` — "debate" o "critica"
  - `channel["base_text"]` — texto sobre el que debatir/criticar (opcional)
  - `messages` lista completa — solo mensajes que le pasan
  - `profile_names` dict — traducción de IDs a nombres
  - `summary["content"]` si existe — acta ya generada

- **Escribe:** nada; solo prepara la estructura para enviar a Anthropic

## Entradas y salidas de la pieza

- **Quién la llama:**
  - `orquestacion-turno` — antes de cada llamada a Anthropic, solicita el contexto armado

- **A quién llama:**
  - `cliente-llm` (indirectamente) — quien consume el `(system_prompt, api_messages)` que produce

## Lo no obvio

1. **Matrix de andamios:** No hay un solo "system prompt por perfil". Se decide en tiempo de turno según el modo del canal. El mismo "Sócrates" recibe `ANDAMIO_DEBATE` en un canal de debate y `ANDAMIO_CRITICA` en uno de crítica. Los facilitadores son la excepción: no reciben andamio.

2. **Cache blocks estratégicos:** El diseño usa bloques de caché del modelo:
   - Block 1 (`base_text`): ephemeral, porque es estable y se reutiliza en muchos turnos
   - Bloques 2 del transcript: sin marca de caché (los intermedios), para que la API amortice el costo
   - Último bloque del transcript: ephemeral, porque es el más nuevo y no se reutiliza todavía
   - Esto aprovecha el mecanismo de prompt caching de Anthropic

3. **Generación de nombres:** Si un mensaje tiene `profile_id` pero ese ID no está en `profile_names`, se genera un nombre fallback (`"Participante {id}"`).

4. **Mensaje de inicio:** Cuando no hay mensajes en el historial, se inserta un bloque neutro ("La conversación acaba de comenzar."). Así la API nunca recibe un transcript vacío.

## Respuestas a las preguntas del Despiezador

**¿En qué difiere en concreto `ANDAMIO_DEBATE` de `ANDAMIO_CRITICA`?**

`ANDAMIO_DEBATE` (27 líneas) instruye al tertuliano a ser un participante auténtico en una conversación grupal: reaccionar a otros, discrepar, ser breve, mantener su sesgo, adaptarse al ritmo. Enfatiza la dinámica conversacional, el desacuerdo argumentado, y las reacciones nombradas.

`ANDAMIO_CRITICA` (14 líneas) es más enfocado: instruye a analizar un texto concreto. El objeto cambia del "debate de ideas" a "análisis de la página". Exige citas, señalar qué funciona/falla, ser concreto. Omite reglas sobre ritmo conversacional y cierre de tertulia, porque el contexto es distinto.

Ambas comparten tono (breve, punzante, rol propio) y respuesta en español.

**¿Cómo entra el acta/resumen rodante (tabla `summaries`) en el contexto construido?**

El acta entra como un bloque de contenido (Block 2) entre el `base_text` y el transcript. Se recibe como `summary: dict | None` con un campo `content` (el resumen en texto). Si existe, se inserta como:
```
{
  "type": "text",
  "text": "[Acta de la conversación]\n{summary['content']}\n[Fin del acta]"
}
```
Sin `cache_control`, para que se recompute cada turno si el acta cambia. Su posición es fija: después del base_text (si existe) y antes del transcript.

**¿Hay algún límite de mensajes o tokens que respete `build_context()` además del recorte que ya hace compresion-contexto?**

No. `build_context()` recibe una lista de mensajes y los arma todos sin filtro. No valida longitud, no cuenta tokens, no rechaza listas largas. Quien la invoca (presumiblemente `orquestacion-turno` tras llamar a `compresion-contexto` si es necesario) es responsable de pasar solo los mensajes que caben.

## Dudas

Ninguna. El código es autoexplicativo y las preguntas de `piezas.md` se responden completamente leyendo la implementación.
