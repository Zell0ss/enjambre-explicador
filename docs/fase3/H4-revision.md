# H4 — revisión (la página)

Revisado contra el código de la rama `feature/fase3-h4` (`474aeae`, `f169749`, `4dc8843`, `5fe6091`),
en el worktree `/data/enjambre-explicador-h4`, y contra la spec (§8, D31, D33). No contra el informe.

## 1. Comprobado

- 273 pruebas de Python y 19 de JS en el worktree, todas verdes (ejecutadas por el arquitecto).
- **R4 y R5 de H3, cerrados** (`b7db79d`, en `main`).
- El servidor valida con `fuente.resolver` (una sola definición de fuente válida). Contesta 409 por
  cerrojo en `/api/lanzar` y en `/api/reanudar`. `/api/encolar` y `/api/cola` usan las mismas
  cabeceras anti-CSRF. `crear_servidor` resuelve sus valores por defecto al llamarse, sin repetir R2.
- Desviación 1 (el hijo recibe el mismo `--cerrojo`): **buena captura.** Sin ella, D31 no protegía nada
  en cuanto el servidor y el hijo mirasen ficheros distintos.
- Desviaciones 2, 3 y 5: aceptadas.
- `mesa.js` pinta todo lo que viene del servidor con `textContent` (los errores de `git` incluidos);
  el único `innerHTML` es para vaciar. Sin XSS.
- La URL inexistente probada a mano muere en el acto con `terminal prompts disabled`. Eso confirma en
  real el foco 1 del plan.
- El flujo de clics sin probar en un navegador: lo cubre la aceptación (H5), en el navegador de Josem.

## 2. Hallazgos

Ninguno de implementación. Los dos puntos abiertos son decisiones de Josem (§3).

## 3. Decisiones que pedía el informe: van a Josem

1. **"Continuar" cuando el repo ha cambiado.** Recomendación del arquitecto: que **no lance un run
   nuevo**. "Continuar" promete seguir con lo ya pagado, y lanzar un run entero nuevo sería gastar
   sin que se haya pedido. `leer --reanudar` saldría con código 2: `el repo ha cambiado desde que se
   paró (<viejo> → <nuevo>): lanza uno nuevo`. La página lo enseñaría con el mecanismo de error que ya
   existe: `/api/lanzador` daría `codigo`/`error` siempre que el proceso acabe con código 2, aunque el
   run exista. La cola se queda como está (run nuevo, D30), porque allí sí se pidió leer el repo.
2. **Las mayúsculas del nombre del repo.** Recomendación del arquitecto: **todo en minúsculas** en
   `resolver` (dueño y repo; `nombre` también). Una sola identidad por repo, sin copias ni notas dobles.
   La prueba normativa `test_url_se_normaliza` la cambia el arquitecto (`claude-fables`). Coste: la copia
   actual `/data/github-abordaje/Claude-Fables` queda huérfana (se borra a mano) y las notas salen en
   minúsculas (`claude-fables.md`). El título del artículo, dentro, conserva el nombre bonito.

**No hagas nada sobre 1 y 2 hasta que llegue la resolución en este fichero (§5).**

## 4. Veredicto

**Aprobado.** La fusión (`--ff-only` desde `/data/enjambre-explicador`), el reinicio de la pantalla
real y `git worktree remove` los hace Josem, **después** de los retoques del §5 si los aprueba, para
fusionar una sola vez. Gasto autorizado: **0**.

## 5. Resolución de Josem (2026-10-15): sí a las dos

Registradas como **D36** y **D37** en el diseño (D26 queda revisada por D37). Lo que pide, en esta misma rama:

**1. D36: "Continuar" no lanza un run nuevo si el repo ha cambiado.**
- `leer(..., si_cambio: Literal["nuevo", "error"] = "nuevo")`. Con `"error"`, si el commit actual
  no es el del run que se continúa (o no hay commit con qué comparar), lanza
  `RepoCambiado(ValueError)` **antes de lanzar nada**, con el mensaje
  `el repo ha cambiado desde que se paró (<viejo7> → <nuevo7>): lanza uno nuevo`.
- `leer --reanudar` (la CLI, lo que usa la página) pasa `si_cambio="error"` y sale con código 2. La
  cola no cambia: sigue con `"nuevo"` (D30).
- `/api/lanzador` devuelve `codigo`/`error` siempre que el proceso haya acabado con un código distinto
  de 0, de 1 y de 130, **aunque el run exista**, y la página lo enseña en el directo.
- *Pruebas de regresión:* (a) `leer(reanudar=..., si_cambio="error")` con un commit nuevo lanza
  `RepoCambiado`, el `lanzar` no se llama y no se crea ningún run; (b) `main(["--reanudar", ...])` en
  ese caso devuelve 2 y el mensaje va a stderr; (c) `/api/lanzador` con un proceso de mentira que sale con
  2 sobre un run que existe devuelve `codigo: 2` y `error`.

**2. D37: la identidad de un repo de GitHub va en minúsculas.**
- `resolver` pasa a minúsculas el dueño **y el repo**, en `texto`, `url` y `nombre`. Las rutas locales
  no cambian: un directorio de `/data` se queda como está.
- **Cambio de la prueba normativa** (lo decide el arquitecto, así que puedes aplicarlo):
  en `tests/test_fuente.py`, `CANON = "https://github.com/henrik-thevibe/claude-fables"` y
  `f.nombre == "claude-fables"`. Las entradas de `test_url_se_normaliza` que escriben `Claude-Fables` a mano se
  quedan, y se añade la entrada `"https://github.com/Henrik-TheVibe/CLAUDE-FABLES"`.
  El arquitecto aplica el mismo cambio en el plan.
- El arreglo de mayúsculas de `encolar` (`4dc8843`) sobra. Puedes dejarlo: no estorba.
- `/data/github-abordaje/Claude-Fables` queda huérfana. **No la borres tú:** es de Josem.

Después, `docs/fase3/H4b-informe.md` corto y para. Gasto: **0**.

## 6. Incidente (2026-10-15): `actualizar()` borró trabajo de otro proyecto

**Qué pasó.** Lo informa el proyecto claude-fables. El 2026-10-14 a las 22:38, una lectura de
Claude-Fables ejecutó `fetch` + `reset --hard` + `clean -fdx` sobre `/data/github-abordaje/Claude-Fables`.
Esa copia tenía 9 commits locales en `fase1-motor` y un `articulo.md` sin commitear de ese proyecto.
Se pudo recuperar: había una rama de rescate y `articulo.md` estaba en `salidas/`. Salió bien por
suerte, no por diseño.

**Atribución: arquitecto.** D27 dio por hecho que todo lo que hubiera bajo `raiz_copias` era una
caché desechable. Las comprobaciones de H1 (ruta, raíz del repo, `origin`) demuestran *de qué URL* es
la copia, no *que sea desechable*. Además, en la revisión de H2 vi el `articulo.md` suelto, comprobé
que el fichero estaba duplicado y no miré las ramas. El otro proyecto ya se ha ido a `/data/claude-fables`.

**Propuesta del arquitecto (D38, pendiente de Josem). No la implementes hasta que llegue la resolución aquí.**

1. **Marca de propiedad.** Tras un `clone` propio, `actualizar` escribe `.git/enjambre`, dentro de
   `.git` para que `clean -fdx` no la borre, con el commit que ha dejado. Una copia **sin marca** es
   `CopiaAjena`, y el mensaje dice cómo resolverlo: borrar la copia para que el enjambre la vuelva a
   clonar.
2. **Una copia marcada también tiene que estar intacta** antes de `reset`/`clean`, porque una persona
   puede ponerse a trabajar en ella después:
   - `git status --porcelain --ignored` vacío;
   - exactamente una rama local (`for-each-ref refs/heads`);
   - `rev-parse HEAD` igual al commit de la marca (cualquier commit local lo cambia).

   Si falla cualquiera de las tres, `CopiaAjena` («la copia tiene trabajo local: …») y no se toca nada.
3. Después de actualizar, la marca se reescribe con el commit nuevo.
4. *Pruebas normativas de falsación* (todas con `tmp_path`; si no se pueden probar así, la defensa no existe):
   a. copia sin marca → `CopiaAjena`, sin cambios en disco;
   b. marcada + rama local nueva → `CopiaAjena`, la rama sigue;
   c. marcada + fichero sin seguimiento → `CopiaAjena`, el fichero sigue;
   d. marcada + commit local → `CopiaAjena`, el commit sigue;
   e. marcada + fichero ignorado por `.gitignore` → `CopiaAjena`;
   f. marcada e intacta + commit nuevo en el remoto → se actualiza y la marca lleva el commit nuevo;
   g. `clone` nuevo → deja la marca con el commit clonado.
   El plan y las pruebas de H1 que esperaban "lo local sucio se descarta" (`test_actualiza_y_descarta_lo_local`)
   quedan **superados**: el arquitecto los cambia por (c) y (f).
5. Migración: `/data/github-abordaje/repomix` no tiene marca. Josem la borra y el enjambre la vuelve a
   clonar, o se queda como ajena. `/data/github-abordaje/Claude-Fables` **no se toca**: es del otro proyecto
   hasta que diga que se ha ido.
