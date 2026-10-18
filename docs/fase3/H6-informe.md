# H6 — informe (Tareas 28, 29 y 30: peso y precio, commit fijado, sacar de la cola)

Rama `feature/h6`, worktree `/data/enjambre-explicador-h6` (`.venv` propio). `/data/enjambre-explicador` sigue en `main`, limpio.
Gasto: **0**. No hay paso [API]. No he tocado el vault, `/data/github-abordaje` ni el `cola/` real, ni he pesado ninguna URL real
(eso lo prueba Josem tras fusionar, como dice el anexo).

## Hecho

- **Tarea 28, D40** (`e2d4584`): `enjambre/peso.py` (`pesar`, `estimar`, `texto`, `pesar_fuente`, `como_dict`, CLI) y, en `fuente.py`,
  `ficheros()` (`ls-files -z`, `None` si no es la raíz de un repo) y `clonar()` (clon `--depth 1` a un temporal, sin marca D38).
  `leer` pesa en un **run nuevo** (no al continuar ni en `sin_cambios`) y lo pasa a `orquestar` → `run_inicio.peso`; un fallo
  (`OSError`/`GitFallo`) solo da un warning y `peso=None`. `POST /api/pesar` (mismas cabeceras y validación que `/api/encolar`;
  200 / 400 / 502; sin cerrojo ni subprocesos) y `crear_servidor(..., pesar=None)`. Botón **«Pesar»** en el formulario, en rojo si
  `no cabe`.
- **Tarea 29, D41** (`bb879ff`): `actualizar(..., commit=<40 hex>)` fija la copia de una URL en ese commit (`fetch --depth 1 origin <sha>` +
  `reset --hard FETCH_HEAD`, tras las comprobaciones D38; marca con ese commit); sin copia, clona y fija **dentro del bloque que borra
  el clon si falla**. `leer` con `reanudar` y URL usa el commit del `run_inicio`; con `saltar_si_igual`, si el último run acabado
  tiene ese commit, `sin_cambios` sin llamar a `git`. Con ruta local, todo sigue como en D36. `raiz_copias` pasa a `None` en la firma.
- **Tarea 30, D42** (`2173973`): `cola.retirar(id)` (regex del id, `pendientes/` y `fallidas/` → `retiradas/`, entrada `retirada` en el
  historial, atómico). `pendientes()`/`fallidas()` devuelven `id` (nunca se escribe en el JSON). `noche` salta lo que ya no está y no
  recrea lo que se sacó durante su lectura (log `info`; el gasto cuenta). `raiz_cola=None` en `pendientes`, `fallidas`, `encolar` y `noche`
  (el arreglo de paso). `POST /api/retirar` (200/404/400) y botón **«Sacar»** con `confirm()`.
- `CLAUDE.md` y `README.md` con las tres reglas nuevas. Captura: `docs/capturas/h6-portada.png` (Pesar, Encolar, «Esta noche» con «Sacar»).
- Pruebas: **355 Python** (308 de antes + 47) y 19/19 JS. Todas las del anexo, tal cual; añadidas: 8 de `peso`/`pantalla`/`cola`/`fuente`
  más las de abajo.

### Comprobado a mano (sin gastar, sin red)

- `python -m enjambre.peso` sobre repos locales: agora `101 ficheros, 888 kB · código 199 kB (~49k tokens) · S · 1-3 $ · cabe en 5 $`,
  enjambre-explicador `184 ficheros, 1,9 MB · código 447 kB (~111k tokens) · M · 3,5-5 $ · cabe en 5 $`. **Coinciden con los 49k y 111k
  tokens que el anexo usa para calibrar las bandas.**
- Servidor efímero (puerto 8802, cola/cerrojo en el scratchpad, ya parado): `/api/pesar` con una ruta (200, «justo para 4 $» con tope 4) y
  con una URL no GitHub (400); encolar dos, retirar uno (200; otra vez 404; `../../x` 400) y la entrada `retirada` en el JSON de `retiradas/`.
- No he hecho clic en un navegador dirigido (no hay CDP en esta sesión); el flujo de «Pesar» y «Sacar» lo cubre la aceptación.

## Gasto

0.

## Desviaciones

1. **«1 ficheros» sin singular**: dejé el texto como el plan (las pruebas normativas lo piden así). Si prefieres «1 fichero», cambian dos pruebas.
2. **`ficheros()` también devuelve `None` si `ruta` está dentro de otro repo** (no es su raíz), no solo si no tiene `.git`: `git` actuaría sobre
   el de arriba, que es el mismo riesgo que D38 evita. Recorre el disco en ese caso (lo que dice el anexo para «sin git»).
3. **`_git` decodifica con `errors="replace"`**: un nombre de fichero que no sea UTF-8 (`ls-files`) no debe tumbar el peso.
4. **D41, atajo sin red:** con la copia intacta y `HEAD == commit`, `actualizar(commit=...)` no hace `fetch`: no hay nada que traer.
5. **`test_leer.py` importa `git`** de `tests/gitutil.py` (el anexo avisa de que viene de ahí): una línea.
6. **`id` solo en minúsculas** (D37): una petición con mayúsculas en el nombre no se podría sacar. `encolar` ya normaliza a minúsculas, así
   que las de la cola actual valen; una creada a mano con mayúsculas daría 400.
7. **`resolver` sigue con `raiz_copias: Path = RAIZ_COPIAS` en la firma** (es el mismo patrón que el anexo manda arreglar en la cola): no
   está en el contrato de H6 y no lo he tocado. Dímelo si lo quieres igual.

## Decisiones que necesito

Ninguna. Fusiona Josem: `git merge --ff-only feature/h6` desde `/data/enjambre-explicador`, reiniciar la pantalla (hay página y endpoints nuevos) y
`git worktree remove ../enjambre-explicador-h6`. Después, la aceptación del anexo: «Pesar» con golden-thread (esperado `XL` / `no cabe en 5 $`;
**clona unos 126 MB en un temporal y lo borra**, y no debe aparecer nada en `/data/github-abordaje/`), con repomix (`M` / `cabe en 5 $`) y
Encolar → Sacar.
