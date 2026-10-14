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

## 5. Resolución de Josem

*(pendiente)*
