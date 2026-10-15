# H4b — informe (D38, D36 y D37)

Rama `feature/fase3-h4`, worktree `/data/enjambre-explicador-h4`. Orden pedido: D38, D36, D37 (D37 después de
D38; D36 en medio, ver abajo). Gasto: 0. No he tocado `/data/github-abordaje/` (ni `Claude-Fables` ni `repomix`),
el vault, el `cola/` real ni la pantalla real.

## Hecho

- **D38** (`e99bc8e`, `enjambre/fuente.py`): `actualizar` solo toca una copia **marcada e intacta**.
  - Tras un `clone` propio escribe `.git/enjambre` con el commit (dentro de `.git`, fuera del alcance de `clean`).
    Si no se puede escribir la marca, se borra el clon recién hecho (sin marca sería "ajena" para siempre).
  - Una copia existente, tras las comprobaciones de siempre (ruta, raíz del repo, `origin`), tiene que llevar la
    marca y cumplir las tres: `status --porcelain --ignored` vacío, exactamente una rama local, y `HEAD` igual al
    commit de la marca. Si no, `CopiaAjena` con lo que encontró y «si es una copia del enjambre, bórrala y se
    volverá a clonar».
  - Tras actualizar, la marca se reescribe con el commit nuevo.
  - Pruebas normativas (a)-(g) en `tests/test_fuente.py`, cada una comprobando también que lo local sigue en disco
    tras el `CopiaAjena`. Sustituyen a `test_actualiza_y_descarta_lo_local` (superada).
- **D37** (`c35a8d9`): `resolver` pasa a minúsculas dueño y repo (`texto`, `url` y `nombre`) en las URLs de GitHub; las rutas
  locales no cambian. `test_url_se_normaliza` cambiada como pedías (`CANON` y `nombre` en minúsculas, más la
  entrada `Henrik-TheVibe/CLAUDE-FABLES`).
- **D36** (commit siguiente): `leer(..., si_cambio: Literal["nuevo", "error"] = "nuevo")`. Con `"error"`, si el commit
  de ahora no es el del run (o no hay commit), lanza `RepoCambiado(ValueError)` antes de lanzar nada, con
  `el repo ha cambiado desde que se paró (<viejo7> → <nuevo7>): lanza uno nuevo`. La CLI `leer --reanudar` pasa
  `"error"` y sale con 2; la cola no cambia. `/api/lanzador` da `codigo`/`error` cuando el proceso sale con un código
  que no es 0, 1 ni 130, aunque el run exista. La página lo enseña: mientras el directo está abierto consulta el
  lanzador cada 2 s.
- Pruebas: **289 Python** (273 de antes + 16) y 19/19 JS. Las de D36 son las (a), (b) y (c) pedidas más tres mías
  (mismo commit sigue continuando, sin commit también es error, el valor por defecto es `"nuevo"`) y las
  variantes de código de salida 0/1/130 del lanzador.

### Prueba manual (sin tocar `/data/github-abordaje`)

Con un remoto `file://` y copias en el scratchpad: el clon deja la marca (`b545024`); con un `articulo.md` y una rama
`fase1-motor` añadidos, `actualizar` lanza `CopiaAjena: la copia tiene trabajo local en …: ficheros sin guardar o
ignorados: ?? articulo.md; ramas locales: fase1-motor, trunk; si es una copia del enjambre, bórrala y se volverá a
clonar`, y los dos siguen en disco. Una copia sin marca da `… no tiene la marca del enjambre (no la clonó él); …`.

## Gasto

0.

## Desviaciones

1. **Sin `clean -fdx`.** D27 lo tenía tras el `reset --hard`; con D38 la copia está intacta (nada que limpiar), así que lo quité:
   un comando destructivo menos. Si prefieres mantenerlo, es una línea.
2. **Un cambio de una prueba mía, no normativa:** `test_duenio_en_mayusculas_se_normaliza` (de `test_fuente_seguridad.py`)
   esperaba que el repo conservara las mayúsculas; ahora comprueba D37 (`…/Claude-Fables.GIT` → `…/claude-fables`, nombre
   `claude-fables`), más una prueba nueva de que una ruta local las conserva. Ninguna de mis pruebas contaba con que lo
   local se descartara.
3. **D36 antes de D37.** Hice D38 → D37 → D36 en commits, no D38 → D36 → D37: D36 y D37 no se tocan entre sí. Dímelo si el orden importa.
4. **La marca ocupa `.git/enjambre` también en copias existentes del enjambre antes de D38:** no la tienen, así que son
   `CopiaAjena` hasta que se borren (la migración del §6: `repomix`). `/data/github-abordaje/Claude-Fables` sigue huérfana por D37.
5. **Un aviso del texto de `CopiaAjena`:** la mención de "ramas locales: fase1-motor, trunk" incluye la rama normal del clon,
   no solo la nueva: dice todas las ramas, no cuál sobra.

## Decisiones que necesito

Ninguna. Para fusionar: `git merge --ff-only feature/fase3-h4` desde `/data/enjambre-explicador`, reinicio de la pantalla real y
`git worktree remove`, los haces tú. Recuerda que `/data/github-abordaje/repomix` y `Claude-Fables` hay que borrarlas a mano
(o dejarlas como ajenas) antes de que la cola lea esos repos: con D37 la segunda se llamaría `claude-fables`.
