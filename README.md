# enjambre

Orquestador Python que lanza 7 agentes Claude vía Claude Agent SDK, más una pantalla de píxeles que visualiza la ejecución.

## Instalación

```bash
.venv/bin/pip install -r requirements.txt
```

## Uso

```bash
# Tests
.venv/bin/pytest -v
node --test tests/js/*.mjs

# Ejecutar orquestador (desarrollo)
python -m enjambre.orquestar --repo <ruta> [--falso]

# Continuar un run parado (D24) -- excluye --repo/--run/--falso, salen del propio run
python -m enjambre.orquestar --reanudar <salidas/repo/run> [--tope-usd] [--max-vueltas]

# Arrancar pantalla
python -m enjambre.pantalla
```

La pantalla sirve una lista de runs en `/`; cada uno con un enlace a su
repetición (reproduce `eventos.jsonl` entero, con barra y velocidad) y,
mientras sigue en marcha, otro a verlo en directo (SSE, en vivo, sin barra).

La propia portada tiene un formulario para lanzar un run (D21, D33): un campo
"URL de GitHub o ruta bajo /data", tope en $, vueltas y la casilla "falso (sin
gastar)", con dos botones. **Lanzar ahora** lanza un subproceso
`python -m enjambre.leer <fuente>` aparte (actualiza la copia, orquesta, deja la
nota y avisa) y salta a verlo en directo, con un botón Parar mientras sigue en
marcha; la página espera a que acabe el clon y, si el proceso muere antes de crear
el run (repo privado o inexistente, copia ajena), enseña el error. **Encolar para
esta noche** solo apunta la fuente en la cola (`/api/encolar`); debajo, el bloque
"Esta noche" enseña lo pendiente y lo rendido (`/api/cola`). Si hay otro run en
marcha en la máquina (la cola, una terminal) contesta 409 (D31).

Un run en marcha (directo o repetición) se ve como **la mesa de papeles**
(D22): una rejilla de tarjetas HTML en el orden del flujo (cartógrafo,
despiezador, lectores, trazador, redactor, verificador, novato), cada una
con su sprite animado, lo que lee/escribe ahora y las fichas que deja
(clic abre su contenido). Debajo, el panel "Ahora" (qué lee cada agente
activo), la bitácora y las puertas del guardia, que se encienden en rojo
(ámbar la del verificador) con cada denegado/salto. Ver
`pantalla/mesa.js`. Un enlace "← volver" en la cabecera regresa a la
portada (lista de runs / formulario de lanzar) sin tocar la URL a mano.

Un run parado por cualquier motivo salvo `aprobado` (sobre todo el tope de
coste) se puede **continuar** (D24): la cabecera muestra un botón
"Continuar" (tanto en directo como en repetición) con el tope extra en $ y
las vueltas máximas: salta al mismo directo y sigue exactamente donde se
quedó, sin relanzar lo que ya está hecho ni gastar de más (D25 borra antes
los ficheros que cada paso relanzado va a crear, para que la tool `Write`
real no se encuentre con uno que no ha leído en su sesión). El tope que se
da al continuar es dinero EXTRA, no un total nuevo; el modo (`--falso` o
real) lo decide siempre el propio run, nunca quien lo continúa.

## Fase 3: leer una URL de GitHub (abordaje)

```bash
# Leer una fuente ahora: actualiza la copia en /data/github-abordaje/<repo>,
# orquesta, deja la nota en Clippings/repo-articles/<repo>.md y avisa por Telegram
python -m enjambre.leer https://github.com/<dueño>/<repo> [--tope-usd] [--falso] [--sin-aviso]

# Encolar para la noche (la cola es el directorio cola/, un JSON por petición)
python -c "from enjambre.cola import encolar; print(encolar('https://github.com/<dueño>/<repo>'))"

# La noche, a mano (la misma orden que lanza el timer)
python -m enjambre.cola [--falso] [--techo-usd 10]
```

Un solo run a la vez en la máquina (D31): el cerrojo es `cerrojo.lock`. El aviso lee
`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` de `.env` (D34; fuera de git).

**Las copias de `/data/github-abordaje/<dueño-repo en minúsculas>`** (D37) solo las toca el
enjambre si las clonó él (marca `.git/enjambre`, D38) y siguen intactas: sin cambios ni ficheros
nuevos, una sola rama y `HEAD` en el commit que dejó. Si no, `CopiaAjena`, sin tocar nada: borra la
copia y se volverá a clonar. "Continuar" desde la página no lanza un run nuevo si el repo cambió
desde que se paró (D36): sale con "el repo ha cambiado… lanza uno nuevo"; la cola, en cambio, sí.

Si una lectura de la noche para por el límite de sesión de Claude y el aviso dice cuándo se renueva (`resets 2:40am`), la cola espera a esa hora más un minuto y continúa el mismo run (D39): una sola vez por noche y solo si acaba antes de las 07:00. Durante la espera sigue teniendo el cerrojo, así que no se puede lanzar nada desde la página; el Telegram de la mañana lo cuenta («Esperé al reset de las 02:40»).

### La noche: instalar el timer (lo hace Josem, requiere sudo)

```bash
sudo cp systemd/enjambre-cola.service systemd/enjambre-cola.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now enjambre-cola.timer
systemctl list-timers enjambre-cola.timer     # próxima ejecución: 02:30
```

`Persistent=false` a propósito: si seb01 estaba apagado a las 02:30, no se recupera la noche a
las 9 de la mañana (D30). `HOME` está fijado en la unidad porque el CLI de Claude busca sus
credenciales en `~/.claude`.

**Probarlo sin gastar:**

```bash
# a mano, con el lanzador falso: las notas van a <salida>/nota.md y el aviso se imprime
.venv/bin/python -m enjambre.cola --falso

# o con la unidad: un drop-in temporal que añade --falso
sudo systemctl edit enjambre-cola.service     # pega las dos líneas siguientes y guarda
#   [Service]
#   ExecStart=
#   ExecStart=/data/enjambre-explicador/.venv/bin/python -m enjambre.cola --falso
sudo systemctl start enjambre-cola.service && journalctl -u enjambre-cola.service -n 30
sudo systemctl revert enjambre-cola.service   # quita el drop-in
```

Ver `CLAUDE.md` para contexto arquitectónico.


[Explicacion hecha con el propio enjambre](articulo.md)