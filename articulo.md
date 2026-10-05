# enjambre-explicador: cómo funciona por dentro

## En dos minutos

`enjambre-explicador` es un orquestador en Python que lanza siete agentes Claude, uno detrás de otro, para que lean un repositorio y escriban un artículo que explique cómo funciona su código. Los agentes se ejecutan con el Claude Agent SDK (`claude_agent_sdk`). Además hay un servidor web, la «pantalla», que enseña la ejecución en tiempo real y deja lanzar, parar y reanudar runs.

Un «run» es una ejecución completa sobre un repo. Cada run tiene su carpeta `salidas/<repo>/<run>/`, y ahí dejan sus ficheros los agentes.

Los siete agentes, en el orden en que se lanzan:

1. `cartografo`: mira el repo y escribe `mapa.md`.
2. `despiezador`: parte el repo en piezas y escribe `piezas.md`.
3. `lector-de-pieza`: hay uno por pieza, en paralelo. Cada uno escribe `fichas/<id>.md`.
4. `trazador`: sigue los flujos de extremo a extremo y escribe `flujos.md`.
5. `redactor`: escribe `articulo.md`. Primero en modo `borrador` y después, si hace falta, en modo `revision`.
6. `verificador`: contrasta el artículo y escribe `verificacion.md`.
7. `novato`: lee solo el artículo, apunta lo que no entiende en `dudas.md` y da un veredicto.

La idea central es que **ningún LLM decide el flujo**. El orquestador es código normal. Solo comprueba tres cosas: si el agente terminó bien, si existe el fichero que debía escribir, y los números que unos parsers sacan de los markdown (cuántos fallos, qué veredicto). Con eso decide si sigue, si repite o si para.

```
                 python -m enjambre.orquestar --repo <ruta>
                               │
                        ┌──────▼───────┐        ┌──────────────────┐
                        │ orquestador  │───────▶│ lanzador (SDK    │──▶ API de Anthropic
                        │ (orquestar.py)│       │  o falso)        │
                        └──┬────────┬──┘        └────────┬─────────┘
                           │        │                    │ hook PreToolUse
              lee markdown │        │ emite eventos      ▼
                  ┌────────▼──┐     │             ┌─────────────┐
                  │ parsers   │     │             │ guardia     │
                  └───────────┘     │             │ (muro)      │
                                    ▼             └─────────────┘
                     salidas/<repo>/<run>/eventos.jsonl
                                    ▲
                                    │ lee (repetición y SSE en directo)
                        ┌───────────┴──────┐
        navegador ◀────▶│ pantalla.py      │──── Popen / SIGINT ───▶ orquestador (otro proceso)
                        └──────────────────┘
```

## Las piezas

Hay siete piezas:

- **orquestador** (`enjambre/orquestar.py`, `enjambre/tipos.py`): el guion fijo. Lanza los agentes, decide cuándo parar, aplica los topes de coste y de vueltas, y sabe reanudar.
- **lanzador-sdk** (`enjambre/lanzador.py`, `enjambre/agentes.py`): arranca un agente de verdad con el SDK y traduce sus mensajes a eventos.
- **muro-permisos** (`enjambre/guardia.py`, más el cableado en `lanzador.py`): decide qué rol puede leer o escribir qué ruta.
- **artefactos-parsers** (`enjambre/parsers.py`): convierte en datos los markdown que dejan los agentes.
- **eventos-log** (`enjambre/eventos.py`, `enjambre/registro.py`): el registro del run en `eventos.jsonl` y el log central.
- **servidor-pantalla** (`enjambre/pantalla.py`): el servidor HTTP. Es un proceso aparte.
- **lanzador-falso** (`enjambre/falso.py`): sustituto del lanzador real para probar sin tokens.

El orquestador manda. Para ejecutar un agente llama a «un lanzador», que es el SDK real o el falso, según el flag `--falso`. Para decidir, lee ficheros con los parsers. Para dejar constancia, emite eventos. El lanzador real consulta al muro antes de cada herramienta que pide el modelo. La pantalla no importa nada del orquestador: se hablan solo por línea de comandos, por el fichero `eventos.jsonl` y por una señal.

## Orquestador

**Qué problema resuelve.** Hace falta un único sitio donde viva el orden de los agentes y las condiciones de parada, y que no dependa de lo que opine un modelo. Todo lo demás son herramientas que este módulo usa.

**Cómo lo resuelve.** `orquestar()` (en `enjambre/orquestar.py`) prepara el run: crea `salidas/<repo>/<run>/`, abre el `Eventos` de `eventos.jsonl`, carga los siete agentes con `cargar(rol)`, emite `run_inicio` y llama a `_ejecutar()`. Esta última función es el guion fijo. Cada lanzamiento pasa por `_paso()`, que hace lo siguiente:

1. Llama a `_comprueba_tope()`.
2. Emite `lanzado`.
3. Ejecuta el lanzador con `asyncio.wait_for` y el timeout configurado. Un timeout o una excepción se convierten en un `Resultado` de estado `timeout` o `error`, más un evento `aviso`.
4. Suma el coste del `Resultado` a `coste.total`.
5. Emite `respuesta` y `fin_agente`.

Los tres eventos `lanzado`, `respuesta` y `fin_agente` los emite siempre `_paso()`. El lanzador nunca los emite.

Entre agente y agente, `_ejecutar()` comprueba que el estado final fuera `terminado` y que existiera el fichero esperado. Si no, para el run con un motivo (`fallo:<instancia>:<estado>` o `falta:<ruta>`). Tras el despiezador llama a `ids_de_piezas()` y lanza un `lector-de-pieza` por cada id con `asyncio.gather`. A cada uno le pasa `PIEZA=<id>` en el encargo.

El encargo es un texto con líneas `CLAVE=valor`, construido por `_encargo()`. Siempre lleva `SALIDA=`. Lleva `REPO=` salvo para `redactor` y `novato`, que no deben ver el repo.

El `redactor` se lanza de dos maneras. Con `MODO=borrador` escribe `articulo.md` desde cero, una sola vez, justo después del trazador. Con `MODO=revision` corrige ese artículo a partir de `verificacion.md` y `dudas.md`, y solo se lanza dentro del bucle de vueltas, una vez por vuelta que no aprueba. Tras el borrador viene ese bucle, con `n` empezando en 1:

1. `_comprueba_tope()` y evento `vuelta`.
2. `verificador` y `novato` en paralelo (`VUELTA=n`).
3. Se copian `verificacion.md` y `dudas.md` a `vueltas/<n>/`.
4. Se llama a `fallos(verificacion.md)` y a `veredicto(dudas.md)`.
5. Si `n_fallos == 0` y el veredicto es `listo`, el run para con motivo `aprobado`. Si `n > max_vueltas`, para con `tope_vueltas`. Si no, lanza al `redactor` con `MODO=revision`, hace `n += 1` y repite.

Para parar desde dentro se usa una excepción interna, `_ParaRun`. Los envoltorios `orquestar()` y `reanudar()` la capturan para fijar el motivo. En su `finally` emiten siempre `run_fin` (motivo, vueltas, `coste_total_usd`, duración) y cierran el `Eventos`. Gracias a eso el `eventos.jsonl` siempre queda cerrado, incluso con un fallo inesperado.

`main()` elige el lanzador. Sin `--falso` hace `from enjambre.lanzador import lanzar` dentro de la función, no a nivel de módulo. Así importar `enjambre.orquestar` en las pruebas no carga el SDK. El código de salida es 0 si el run se aprueba, 1 por cualquier otro motivo, 2 por error de argumentos y 130 si lo interrumpen.

**Tipos compartidos.** `enjambre/tipos.py` define el contrato con el lanzador:

- `Contexto` agrupa `repo`, `salida`, `eventos`, `timeout_s` (600 por defecto) y `max_turns` (60).
- `Resultado` es lo que devuelve un lanzamiento: `estado_final` (`terminado`, `bloqueado`, `error` o `timeout`), `respuesta`, `modelo_real`, `duracion_s`, `tokens_in`, `tokens_out`, `coste_usd`, `num_herramientas` y `num_turns`.
- `Lanzar` es el alias del callable `(agente, instancia, encargo, ctx) -> Resultado`.

**Lo no obvio.**

- **Los topes.** `_comprueba_tope()` lanza `_ParaRun("tope_coste")` si `coste.total > tope_usd`. Se llama antes de cada paso y antes de cada vuelta. Por eso un paso que no llega a intentarse no deja evento `lanzado`.
- **El tope de vueltas cuenta una de más.** El chequeo `n > max_vueltas` va después de verificar la vuelta `n`. Con `max_vueltas=2` se ejecutan tres vueltas de verificación y dos revisiones del redactor. El run para en `tope_vueltas` solo si la tercera tampoco aprueba. La ficha del orquestador decía lo contrario y manda el código.
- **Reanudar.** `reanudar()` reconstruye el estado leyendo `eventos.jsonl`. Del `run_inicio` anterior saca el repo y los parámetros. Con `_lanzamientos_hechos()` busca parejas `lanzado` → `fin_agente` con estado `terminado` cuyo fichero siga en disco, y las guarda en el diccionario `hechos`. Suma el `coste_previo_usd` de los `fin_agente` anteriores. Luego reabre el mismo fichero en append, emite `reanudado` (no otro `run_inicio`) y llama a `_ejecutar()` con `hechos`.
- **Saltar pasos ya hechos.** La función anidada `lanza()` consulta `hechos`. Si el paso ya está hecho, devuelve `Resultado("terminado")` sin llamar al lanzador y sin emitir nada. Si no, borra antes los ficheros que ese paso va a crear (`_ficheros_de_paso`). El motivo es que el SDK real no sobrescribe un fichero que el agente no ha leído en su sesión. Una vuelta de verificación con los dos agentes hechos y copiada en `vueltas/<n>/` se restaura copiando a la raíz y no se relanza.
- **El tope de USD en una reanudación** cuenta solo lo gastado en ese tramo. El `run_fin` final sí suma lo previo.
- **Un run no se pisa.** Si `salidas/<repo>/<run>` ya existe, `orquestar()` lanza `FileExistsError` antes de abrir ningún evento. Ese caso no deja `run_fin`.
- **`orquestar()` emite `estado: esperando`** para seis roles (todos menos `lector-de-pieza`) justo después de `run_inicio`.

## Lanzador del SDK

**Qué problema resuelve.** Aísla el contacto con el SDK y con la API de Anthropic. El resto del código ve una función `Lanzar` que recibe un agente y un encargo y devuelve un `Resultado`.

**Cómo lo resuelve.** Primero hay que cargar al agente. `cargar(rol)` en `enjambre/agentes.py` lee `.claude/agents/<rol>.md`. Comprueba que el fichero empiece con `---`, parsea a mano el frontmatter (la cabecera de metadatos del fichero, entre dos líneas `---`, con líneas `clave: valor`), exige los campos `model` y `tools`, trocea `tools` por comas y toma como prompt todo lo que hay tras el cierre del frontmatter. Devuelve un dataclass `Agente(rol, modelo, tools, prompt)`.

Luego `lanzar()` en `enjambre/lanzador.py` hace lo siguiente:

1. Crea un conjunto `denegados` y un `Traductor`.
2. Fabrica el hook con `hacer_hook()` y las opciones con `opciones()`. El hook es una función que el SDK llama antes de cada herramienta que pide el modelo, y puede vetarla; es el punto donde se conecta el muro de permisos, que se explica en la sección siguiente.
3. Itera sobre `query(prompt=encargo, options=opts)`, el stream de mensajes del SDK.
4. Pasa cada mensaje a `Traductor.procesar()`.
5. Devuelve `Traductor.resultado()`.

`opciones()` construye un `ClaudeAgentOptions` con:

- `tools` y `system_prompt` tomados del `Agente`.
- `model`, que es `haiku` o `sonnet` según el frontmatter.
- `cwd=ctx.salida` y `max_turns`.
- `permission_mode="bypassPermissions"`.
- `setting_sources=[]`.
- `strict_mcp_config=True`.
- El hook `PreToolUse`, envuelto en un `HookMatcher` sin matcher para que se aplique siempre.

**El traductor.** `Traductor.procesar()` convierte mensajes del SDK en eventos. Los tipos que aparecen a continuación (`AssistantMessage`, `UserMessage`, `SystemMessage`, `ResultMessage`, `ToolUseBlock`, `ToolResultBlock`) son tipos del propio SDK, no del proyecto. Un `AssistantMessage` es un turno del modelo y contiene bloques; un `ToolUseBlock` es el bloque en que el modelo pide una herramienta. Un `UserMessage` lleva de vuelta los resultados, como `ToolResultBlock`. Un `SystemMessage` es un aviso del sistema, como el `init` del arranque, y el `ResultMessage` cierra la conversación con el coste y el estado. Su estructura interna completa no se ha documentado (véase el final del artículo).

- Un `ToolUseBlock` dentro de un `AssistantMessage` emite `herramienta` y un `estado` (`leyendo` para Read, Glob y Grep). Si la herramienta es Write o Edit, apunta el `tool_use_id` y su ruta en `_escrituras_en_vuelo`.
- Un `ToolResultBlock` dentro de un `UserMessage`, de un id que sea una escritura en vuelo, emite `fichero` si no hay error. Si hay error, emite `aviso`, salvo que el id esté en `denegados`.
- Un `SystemMessage` de tipo `init` se compara con `agente.tools`. Si aparecen herramientas inesperadas (por ejemplo, un MCP no aprobado), emite `aviso`.
- El `ResultMessage` final fija el estado.

`Traductor.resultado()` monta el `Resultado`. `tokens_in` es `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`, y `tokens_out` es `output_tokens`. La duración sale de `duration_ms / 1000`. El coste sale tal cual de `ResultMessage.total_cost_usd`, sin calcularlo aquí.

**Lo no obvio.**

- **`bypassPermissions` con hook.** Como `setting_sources=[]` no carga reglas `allow`, `bypassPermissions` hace que todo se apruebe por defecto, y el hook es la única autoridad. Con `dontAsk` se denegaría también lo que el guardia permite.
- **`setting_sources=[]`** impide que el agente vea el `~/.claude/CLAUDE.md` global de la máquina. Es aislamiento obligatorio.
- **`fichero` solo sale con el resultado real.** El hook no emite `fichero` al permitir una escritura. Se espera el `ToolResultBlock` sin error, para no anunciar escrituras que luego fallan.
- **El estado `bloqueado` sale de una regex.** Cada agente puede terminar en `bloqueado` cuando no puede continuar (por ejemplo, le falta un fichero de entrada) y lo dice con esa palabra en su respuesta. El lanzador la detecta con una regex sobre el texto (`\bbloquead[oa]\b`, con exclusiones para «no» y «desbloqueado»); si no encaja, usa `is_error` y `subtype` del `ResultMessage`.
- **Qué emite el lanzador.** Solo emite `estado`, `herramienta`, `denegado`, `fichero` y `aviso`. No emite `error`: los fallos salen como `aviso`.
- **Glob y Grep llevan `patron`.** Los eventos `herramienta` y `denegado` de estas dos herramientas llevan el campo `patron`, además de `detalle`.

## Muro de permisos

**Qué problema resuelve.** Los agentes tienen herramientas de lectura y escritura sobre el disco. Sin límites, el `novato` podría leer el repo y no tendría sentido que solo juzgue el artículo. El muro es la garantía de aislamiento entre roles.

**Cómo lo resuelve.** `enjambre/guardia.py` contiene una tabla `MURO` que asigna a cada rol una regla de lectura y otra de escritura:

| Rol | Lectura | Escritura |
|-----|---------|-----------|
| `cartografo`, `despiezador`, `lector-de-pieza`, `trazador`, `verificador` | `ambos` (bajo `repo/` o bajo `salida/`) | `salida` (bajo `salida/`) |
| `redactor` | `salida` | `salida` |
| `novato` | `exacto`: solo `articulo.md` | `exacto`: solo `dudas.md` |

Dos funciones forman el tronco:

- `ruta_de(herramienta, entrada)` saca la ruta de la llamada: `file_path` para Read, Write y Edit, y `path` para Glob y Grep. Devuelve `None` para cualquier otra herramienta o si el valor no es un string.
- `permitido(rol, herramienta, ruta, repo, salida, patron=None)` devuelve `(ok, motivo)`.

`permitido()` aplica estos pasos:

1. Deniega herramientas fuera de las de lectura y escritura conocidas, y roles que no estén en `MURO`.
2. Deniega patrones de Glob absolutos o que contengan `..` o `~`.
3. Deniega rutas con un segmento `~`.
4. Resuelve la ruta con `Path.resolve()`.
5. Protege `eventos.jsonl` y `vueltas/` de escritura para todos los roles.
6. Aplica la regla del rol.

**Cableado.** El muro se conecta al SDK con `hacer_hook()` en `enjambre/lanzador.py`. Esa función devuelve una función asíncrona `hook(entrada, tool_use_id, contexto)` que el SDK llama antes de cada herramienta. El hook hace esto:

1. Saca `tool_name` y `tool_input` de `entrada`. Para Glob saca también `pattern`.
2. Llama a `ruta_de()` y luego a `permitido()`.
3. Si permite, devuelve `{}` y la herramienta se ejecuta.
4. Si deniega, añade el `tool_use_id` a `denegados`, emite un evento `denegado` y devuelve el diccionario de denegación del SDK. El valor está anidado: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": motivo}}`.

**Lo no obvio.**

- **Resolver antes de comparar.** `Path.resolve()` va antes de `is_relative_to`. Sin eso, un symlink dentro de `salida` que apunte fuera pasaría por estar «bajo salida».
- **`~` se deniega sin resolver.** La herramienta real expandiría `~` a `$HOME`, y guardia y herramienta estarían juzgando rutas distintas.
- **`..` en el patrón de Glob se busca como subcadena**, no como segmento. Así se cubren motores de glob que expanden llaves, como `{..,x}/etc/*`.
- **Todo falla cerrado.** Cualquier excepción en `permitido()` devuelve denegado con «ruta no válida». El cuerpo entero del hook va en un `try`, y un error se convierte en denegación con «error interno del hook». Esto es importante porque, con `bypassPermissions`, una excepción sin capturar dejaría pasar la herramienta sin comprobar nada.
- **El conjunto `denegados`** lo crea `lanzar()` y lo comparten el hook y el `Traductor` del mismo lanzamiento. La CLI sigue devolviendo al modelo un `ToolResultBlock` de error tras una denegación. El traductor lo descarta si el id está en `denegados`, para no avisar dos veces.

## Parsers de artefactos

**Qué problema resuelve.** El orquestador tiene que entender lo que escribieron los agentes sin preguntarle a un LLM. Para eso `enjambre/parsers.py` define el formato contractual entre agentes y código. Si un agente escribe fuera de formato, la lectura falla aquí.

**Cómo lo resuelve.** Son tres funciones y una excepción:

- `ids_de_piezas(texto)` lee `piezas.md`. Busca la línea `## Resumen`, recorre las filas de la tabla que viene después, salta cabecera y separador, toma el id de cada fila (sin backticks) y valida que cumpla `^[a-z0-9-]+$`. Si no hay `## Resumen`, no hay filas o un id no vale, lanza `SalidaIlegible` (que hereda de `ValueError`).
- `fallos(texto)` lee `verificacion.md`. Busca con la regex `Fallos:?\**:?\s*(\d+)` y devuelve el entero, o `None` si no aparece. Acepta `Fallos: 3`, `**Fallos:** 5` o `Fallos 2`.
- `veredicto(texto)` lee `dudas.md`. Busca `## Veredicto`, toma la primera línea no vacía que haya debajo (sin backticks) y devuelve `"listo"` o `"necesita otra vuelta"` solo si coincide exactamente. En cualquier otro caso devuelve `None`.

**Lo no obvio.**

- **La tolerancia es asimétrica.** `ids_de_piezas()` es estricta porque sin ids no hay lectores que lanzar. El orquestador la captura solo alrededor de esa llamada y para el run con `piezas_ilegibles`. `fallos()` y `veredicto()` devuelven `None` y no paran el run.
- **Un `None` provoca otra revisión.** Si el novato escribe `Veredicto: listo` en una línea, en lugar de `## Veredicto` y luego `listo`, `veredicto()` devuelve `None`. El run nunca llega a `aprobado` y sigue revisando hasta el tope de vueltas.
- **Quién escribe qué.** `verificacion.md` lo escribe el verificador y `dudas.md` lo escribe el novato.

## Eventos y log

**Qué problema resuelve.** El run tiene que dejar un registro que la pantalla pueda leer mientras se escribe, y que sirva además para reanudar. Ese registro es `eventos.jsonl`: un evento JSON por línea, solo se añade al final.

**Cómo lo resuelve.** La clase `Eventos` de `enjambre/eventos.py` abre el fichero en modo append con `buffering=1` y guarda un `threading.Lock`. `Eventos.emitir(tipo, agente=None, **campos)` construye un diccionario con `t` (timestamp ISO), `run`, `tipo`, `agente` (si hay) y los campos extra. Lo serializa a JSON con salto de línea y, bajo el lock, lo escribe en una sola llamada `write()` seguida de `flush()`. Así un lector que lea el fichero en vivo nunca ve una línea a medias. `Eventos.cerrar()` cierra el fichero bajo el lock.

El lock es de `threading` y no de `asyncio` porque el hook del SDK puede llegar desde un hilo distinto al del bucle asyncio, y un lock de `asyncio` no lo cubriría.

Los tipos de evento que aparecen en las fuentes:

| Tipo | Quién lo emite | Campos principales |
|------|----------------|-------------------|
| `run_inicio` | orquestador | `repo`, `salida`, `params` (incluye `falso`), `roles` |
| `reanudado` | `reanudar()` | parámetros efectivos |
| `estado` | orquestador, lanzador | `estado`, `detalle` |
| `lanzado` | `_paso()` | `rol`, `modelo_pedido`, `encargo` |
| `herramienta` | lanzador | `herramienta`, `detalle` (y `patron` en Glob y Grep) |
| `denegado` | hook del lanzador | herramienta, `detalle`, `motivo` |
| `fichero` | lanzador | `ruta` |
| `aviso` | orquestador, lanzador | `texto` |
| `respuesta` | `_paso()` | `texto` |
| `fin_agente` | `_paso()` | `estado_final`, `modelo_real`, `duracion_s`, `tokens_in`, `tokens_out`, `coste_usd`, `num_herramientas`, `num_turns` |
| `vuelta` | orquestador | `n` |
| `run_fin` | orquestador | `motivo`, `vueltas`, `coste_total_usd`, `duracion_s` |

`enjambre/registro.py` tiene `obtener_log()`, que crea el directorio `logs/` y devuelve un logger del cliente local `logcentral_client` con nombre `enjambre`. Solo recibe excepciones imprevistas del orquestador. Todo lo demás, incluidos los fallos de los agentes, va a `eventos.jsonl`.

## Servidor de la pantalla

**Qué problema resuelve.** Ver un run en directo, repetirlo después y gobernarlo desde el navegador, sin que el navegador sea parte de la ejecución. El run sigue aunque se cierre la pestaña.

**Cómo lo resuelve.** `enjambre/pantalla.py` es un `ThreadingHTTPServer` que crea `crear_servidor()`. Es un proceso aparte del orquestador y no importa nada de `enjambre.*`. El servidor guarda en memoria un `lock` y un único subproceso en marcha: `proc`, `proc_repo`, `proc_run` y `proc_lanzado_en`. Solo conoce un run vivo a la vez.

El manejador `_ManejadorPantalla` enruta con `_despacha()` (GET) y `_despacha_post()` (POST):

| Método y ruta | Qué hace |
|---------------|----------|
| `GET /`, `/static/<archivo>` | Sirve la página y los estáticos (`_servir_simple`) |
| `GET /api/runs` | Lista los runs (`_servir_runs`) |
| `GET /api/lanzador` | Informa de `en_marcha`, `repo` y `run` (`_servir_lanzador`) |
| `GET /api/eventos/<repo>/<run>.jsonl` | Devuelve el `eventos.jsonl` entero: la repetición |
| `GET /api/directo/<repo>/<run>` | Flujo SSE en vivo |
| `GET /api/fichero/<repo>/<run>/<ruta>` | Sirve un fichero de salida |
| `POST /api/lanzar`, `/api/parar`, `/api/reanudar` | Gobierno del run |

`_despacha_post()` exige `Content-Type: application/json` y la cabecera `X-Enjambre: 1`. Si falta algo responde 403, como protección anti-CSRF.

**Lanzar.** `_lanzar()` valida el cuerpo con `_valida_lanzar()`. El `repo` debe ser un directorio existente bajo la raíz permitida (`raiz_repos`, por defecto `/data`). `tope_usd` debe estar en (0, 10] y `max_vueltas` en [0, 3]. Los booleanos se descartan antes que los números, porque en Python `bool` es subclase de `int`. Con el `lock` comprueba que no haya otro proceso vivo (409 si lo hay). Genera el nombre del run, `<repo>-<YYYYmmdd-HHMMSS>`, y lanza con `subprocess.Popen` el comando `python -m enjambre.orquestar --repo ... --run <run> [--falso]`. El `Popen` va con `start_new_session=True` (el hijo arranca en una sesión propia; el material no explica el motivo exacto) y `cwd` en la raíz del enjambre, y su salida se redirige a `logs/lanzamientos/<run>.log`. Responde 202 con `{repo, run}`.

**Parar.** `_parar()` comprueba que el proceso siga vivo (409 si no) y le manda `SIGINT`. Antes espera hasta 0,2 s desde el arranque, para que un proceso recién lanzado tenga tiempo de armar su manejo de la interrupción.

**Reanudar.** `_reanudar()` valida solo el formato con `_valida_reanudar_campos()` (400). Resuelve el run con `_resuelve_dentro` (404 si no existe) y lee su `eventos.jsonl`. Exige que el último evento sea `run_fin` y que el motivo no sea `aprobado` (409), y que `run_inicio` lleve `params.falso` (409 si no lo lleva, porque el run es anterior a ese campo). Lanza `--reanudar <salida> --tope-usd ... --max-vueltas ...` y añade `--falso` según el run, no según quien llama. El log se abre en modo append.

**El directo.** `_servir_directo()` abre `eventos.jsonl` en binario, lee a trozos, corta por `b"\n"` y emite cada línea como `data: <línea>\n\n`. Sondea cada 0,5 s, y si no hay datos escribe un comentario SSE cada ~1 s, que sirve para notar que el cliente se ha ido. Leer en binario evita que un carácter UTF-8 partido entre dos lecturas rompa el flujo; el trozo incompleto se guarda para la siguiente lectura. Si el `(repo, run)` coincide con el proceso en marcha, espera hasta 30 s a que aparezca el fichero. Si no, responde 404 de inmediato. Al ver `run_fin`, cierra la conexión, salvo que el proceso en marcha sea para ese mismo run, porque entonces es una reanudación y el fichero va a seguir creciendo.

**Lo no obvio.**

- **`_resuelve_dentro(base, ruta_relativa)`** es el único punto de autorización de rutas que vienen del usuario. La URL se decodifica antes de trocearla. Luego construye el candidato segmento a segmento, lo resuelve contra el disco real y exige que quede dentro de `base`. Devuelve `None` si se escapa, y el resultado es siempre 404, nunca 403 ni una excepción.
- **Un run a la vez**, y solo en memoria. Si se reinicia la pantalla, olvida el proceso: `/api/lanzador` dirá `en_marcha=false` aunque el hijo siga vivo.
- **El comando se puede inyectar.** `crear_servidor()` acepta un parámetro `comando`. Las pruebas lo sustituyen por un proceso falso.
- **Corrección respecto a una ficha.** El orquestador no lo arranca `_servir_lanzador`, que solo informa. Lo arrancan `_lanzar()` y `_reanudar()` con `Popen`.

## Lanzador falso

**Qué problema resuelve.** Probar el flujo completo y enseñar la pantalla sin gastar tokens ni llamar a la API.

**Cómo lo resuelve.** `hacer_lanzar_falso(guion=None, retardo_s=...)` en `enjambre/falso.py` devuelve una función `lanzar` con la misma firma que el lanzador real. Se activa con el flag `--falso`. La pantalla usa `retardo_s=0.5` para que la demo no sea instantánea. Esa función simula las lecturas del rol (`_lecturas_de_pega()`), emite eventos `estado`, `herramienta` y `fichero`, escribe los ficheros de pega con `_escribir_de_pega()` y devuelve un `Resultado` con estado `terminado`, 100 tokens de entrada, 50 de salida y coste fijo de 0,01.

Los ficheros de pega son lo mínimo para que los parsers los acepten:

| Rol | Fichero | Contenido |
|-----|---------|-----------|
| `cartografo` | `mapa.md` | título ficticio |
| `despiezador` | `piezas.md` | `## Resumen` con tres piezas: `a-uno`, `b-dos`, `c-tres` |
| `lector-de-pieza` | `fichas/<PIEZA>.md` | título |
| `trazador` | `flujos.md` | título |
| `redactor` | `articulo.md` (y `cambios.md` en revisión) | título; en revisión, añade una línea a `cambios.md` |
| `verificador` | `verificacion.md` | `Fallos: 0` |
| `novato` | `dudas.md` | `## Veredicto` y `` `listo` `` |

**Lo no obvio.**

- **El guion.** `guion` es un diccionario `instancia → lista de Resultado o callables`. Cada llamada consume la primera entrada, y cuando se agota, la instancia vuelve al comportamiento de pega. Un callable puede ser síncrono o asíncrono. Sirve para simular un fallo o una vuelta extra. No puede simular `timeout` ni `bloqueado` de forma natural.
- **Los `denegado` son teatro.** `_denegado_de_pega()` emite el evento (el redactor en borrador «lee» el repo y el novato en la vuelta 1 «lee» una ficha) sin consultar a `permitido()`. Una denegación vista en una demo `--falso` no demuestra que el muro funcione.
- **Tampoco emite** `lanzado`, `respuesta` ni `fin_agente`. Eso es del orquestador, igual que con el lanzador real.

## Todo junto: un run completo por línea de comandos

Es el caso para el que existe el sistema: `python -m enjambre.orquestar --repo <ruta>`.

1. `main()` parsea los argumentos y elige el lanzador real, con la importación diferida del SDK. Llama a `asyncio.run(orquestar(...))` con `max_vueltas=2` si no se indicó otro valor.
2. `orquestar()` calcula la carpeta `salidas/<repo>/<run>/`, la crea, abre `Eventos`, carga los siete agentes con `cargar()` y emite `run_inicio` y los `estado: esperando`. Entonces llama a `_ejecutar()`.
3. Por cada agente, `lanza()` construye el encargo con `_encargo()`, borra los ficheros que el paso va a crear y llama a `_paso()`. Esta comprueba el tope, emite `lanzado` y llama al lanzador.
4. El lanzador, `lanzar()`, monta hook y opciones y consume `query()`. Cada mensaje pasa por `Traductor.procesar()`, que va emitiendo `herramienta`, `estado` y `fichero`. Al terminar devuelve el `Resultado`.
5. De vuelta en `_paso()`, se suma el coste y se emiten `respuesta` y `fin_agente`. `_ejecutar()` comprueba `terminado` y que exista el fichero.
6. Tras el despiezador, `ids_de_piezas()` da los ids. Si falla, el run para con `piezas_ilegibles`. Si no, se lanzan los lectores en paralelo, luego el trazador y luego el redactor en modo borrador.
7. Empieza el bucle de vueltas. Se comprueba el tope, se emite `vuelta`, se lanzan verificador y novato en paralelo y se copian sus ficheros a `vueltas/<n>/`. `fallos()` y `veredicto()` dan los números.
8. Con 0 fallos y veredicto `listo`, el run para con `aprobado`. Si `n > max_vueltas`, para con `tope_vueltas`. En otro caso, el redactor revisa, `n` sube y se repite.
9. El `finally` de `orquestar()` emite `run_fin` y cierra el fichero. `main()` imprime el resumen y devuelve el código de salida.

El orquestador solo mira tres cosas: el estado del `Resultado`, si el fichero existe y los números de los parsers. Esa es la razón de que el formato de `verificacion.md` y `dudas.md` sea el contrato entre agentes y código.

## Todo junto: lanzar desde la pantalla, verlo en directo, pararlo y reanudarlo

Este recorrido cruza el servidor, el orquestador, el lanzador y los eventos. Las dos mitades solo se hablan por tres canales: los argumentos de `Popen`, el fichero `eventos.jsonl` y la señal SIGINT.

1. El navegador hace `POST /api/lanzar`. `_despacha_post()` comprueba las cabeceras anti-CSRF. `_lanzar()` valida el cuerpo, toma el `lock`, comprueba que no hay otro run vivo y lanza el orquestador como subproceso. Responde 202 con `{repo, run}`.
2. En el proceso hijo, `main()` → `orquestar()` → `_ejecutar()` se comportan como en el recorrido anterior. Reciben `--run`, así que escriben en la carpeta que la pantalla ya ha anunciado. Con `--falso` usan `hacer_lanzar_falso(retardo_s=0.5)`.
3. El navegador abre `GET /api/directo/<repo>/<run>`. `_servir_directo()` espera a que exista `eventos.jsonl`, y luego sondea y reenvía cada línea nueva como un evento SSE.
4. El usuario pulsa parar: `POST /api/parar`. `_parar()` manda SIGINT al hijo. El hijo debería convertir la interrupción en una cancelación de la tarea principal. `orquestar()` fija el motivo `interrumpido` y su `finally` emite `run_fin`. `main()` devuelve 130.
5. `_servir_directo()` ve `run_fin`. Como el proceso ya no corre, cierra el SSE.
6. El usuario pulsa reanudar: `POST /api/reanudar`. `_reanudar()` comprueba que el run acabó en `run_fin`, que no estaba aprobado y que `run_inicio` lleva `params.falso`. Lanza otro `Popen` con `--reanudar <salida>` y actualiza `proc_repo` y `proc_run` al mismo run.
7. En el hijo, la rama `--reanudar` de `main()` vuelve a leer `params.falso` con `_falso_del_run()` y elige el lanzador. Un run `--falso` se reanuda siempre como `--falso`, y uno real como real.
8. `reanudar()` relee `eventos.jsonl`, recupera los parámetros, calcula `hechos` y el coste previo, y emite `reanudado`. `_ejecutar()` salta los pasos hechos sin emitir nada y relanza el resto. El `finally` emite un nuevo `run_fin` con `coste_total_usd = coste_previo_usd + coste.total`.
9. Si el SSE seguía abierto, no se cerró en el primer `run_fin`, porque `_reanudar` ya había dejado `proc_repo` y `proc_run` apuntando al mismo run. Ve crecer el mismo fichero hasta el segundo `run_fin`. Esto solo ocurre si `_reanudar` actualizó ese estado antes de que el SSE leyera el primer `run_fin`.

Consecuencia: `eventos.jsonl` guarda todo el estado de un run, y con él se reconstruyen el repo, los parámetros, el modo `falso`, los pasos hechos y el coste previo.

## Todo junto: un agente intenta salirse de su muro

Este flujo no lo dispara ningún usuario, sino el modelo dentro de un run, cada vez que pide una herramienta.

1. El modelo pide una herramienta. Por ejemplo, el `novato` pide un `Read` sobre un fichero del repo.
2. El SDK dispara `PreToolUse` y llama a `hook(entrada, tool_use_id, contexto)`, creado por `hacer_hook()` en `enjambre/lanzador.py`.
3. El hook saca la ruta con `ruta_de()` y consulta `permitido()` en `enjambre/guardia.py`, que devuelve `(ok, motivo)`.
4. **Si `ok`**, el hook devuelve `{}` y la herramienta se ejecuta. El `Traductor` emite `herramienta` y `estado`. Para Write o Edit, el evento `fichero` llega más tarde, con el `ToolResultBlock` sin error.
5. **Si no `ok`**, el hook añade el `tool_use_id` a `denegados`, emite `denegado` en `eventos.jsonl` y devuelve la decisión `deny` anidada en `hookSpecificOutput`. La herramienta no se ejecuta.
6. La CLI devuelve al modelo un `ToolResultBlock` de error. `Traductor.procesar()` ve que el id está en `denegados` y no emite `aviso`.
7. La pantalla recibe `denegado` por el SSE y pinta la puerta del guardia.

El muro está repartido en tres sitios: `guardia.py` decide, el hook de `lanzador.py` lo conecta con el SDK y emite `denegado`, y el `Traductor` evita avisar dos veces. El conjunto `denegados` es la costura entre los tres.

## Lo que este artículo no cubre

- **El frontend.** `static/` y `index.html` quedaron fuera del despiece. Solo se describe qué rutas sirve el back.
- **Los prompts de los agentes.** `.claude/agents/<rol>.md` son el prompt y el frontmatter de cada rol. El despiece los trata como symlinks a un vault de Obsidian fuera del repo, así que su contenido no se ha podido leer ni se ha podido confirmar su ubicación en disco. Por eso no se sabe qué instrucciones concretas recibe cada agente.
- **Detalles de `ToolResultBlock`.** No se conoce su modelo de datos completo. Solo se sabe cómo lo usa `Traductor`.
- **Argumentos CLI.** Solo se conocen los usados en los flujos (`--repo`, `--reanudar`, `--run`, `--salidas`, `--tope-usd`, `--max-vueltas`, `--falso`). No se ha determinado si hay más ni sus valores por defecto, salvo `max_vueltas=2` y `tope_usd=5.0` en `orquestar()`.
- **`registro.py`.** No se sabe si tiene más que `obtener_log()` ni en qué módulos se usa. Tampoco se ha visto qué hace `logcentral_client` por dentro.
- **SIGINT en el hijo.** Que `asyncio.run` convierta SIGINT en `CancelledError` y luego en `KeyboardInterrupt` depende de la versión de Python. Queda sin confirmar; el comentario de `_parar` dice que se comprobó contra una ejecución real.
- **Una duda de diseño.** `tipos.py` usa `TYPE_CHECKING` para importar `Agente` en la firma de `Lanzar`, y nadie ha determinado si ese patrón es deliberado respecto a la separación de piezas.
- **El SDK y la API.** Lo que ocurre dentro de `query()` y en la CLI que hay detrás es externo y no se ha seguido.

## Dónde mirar en el código

| Si quieres entender… | Abre… |
|----------------------|-------|
| El orden de los siete agentes y las condiciones de parada | `enjambre/orquestar.py`, `_ejecutar()` |
| Cómo se ejecuta un solo agente y se mide su coste | `enjambre/orquestar.py`, `_paso()` |
| Qué lleva el encargo que recibe cada agente | `enjambre/orquestar.py`, `_encargo()` |
| El tope de coste | `enjambre/orquestar.py`, `_comprueba_tope()` |
| Cómo se reanuda un run | `enjambre/orquestar.py`, `reanudar()` y `_lanzamientos_hechos()` |
| Argumentos y códigos de salida | `enjambre/orquestar.py`, `main()` |
| Qué devuelve un lanzamiento | `enjambre/tipos.py`, `Resultado` y `Contexto` |
| Cómo se llama al SDK | `enjambre/lanzador.py`, `lanzar()` y `opciones()` |
| Cómo se traducen los mensajes del SDK a eventos | `enjambre/lanzador.py`, `Traductor.procesar()` y `Traductor.resultado()` |
| Cómo se carga un agente desde su `.md` | `enjambre/agentes.py`, `cargar()` |
| Qué puede leer y escribir cada rol | `enjambre/guardia.py`, `MURO` y `permitido()` |
| Cómo se conecta el muro al SDK | `enjambre/lanzador.py`, `hacer_hook()` |
| Qué formato exigen los markdown de los agentes | `enjambre/parsers.py`, `ids_de_piezas()`, `fallos()`, `veredicto()` |
| Cómo se escribe `eventos.jsonl` sin líneas a medias | `enjambre/eventos.py`, `Eventos.emitir()` |
| Cómo arranca, para y reanuda runs la pantalla | `enjambre/pantalla.py`, `_lanzar()`, `_parar()`, `_reanudar()` |
| El directo por SSE | `enjambre/pantalla.py`, `_servir_directo()` |
| La protección contra rutas fuera de `salidas/` | `enjambre/pantalla.py`, `_resuelve_dentro()` |
| Cómo funciona la demo sin API | `enjambre/falso.py`, `hacer_lanzar_falso()` y `_escribir_de_pega()` |
