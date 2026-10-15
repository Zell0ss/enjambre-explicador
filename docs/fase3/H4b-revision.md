# H4b — revisión (D38, D37 y D36)

Revisado contra el código (`e99bc8e`, `c35a8d9`, `1efb85c`, `fc38e0c`) y el registro (D36-D38). No contra el informe.

## 1. Comprobado

- 290 pruebas de Python y 19 de JS en el worktree, todas verdes (ejecutadas por el arquitecto). Las
  pruebas (a)-(g) de D38 están en `tests/test_fuente.py` con su nombre y comprueban que lo local sigue en disco.
- **D38:** `_comprobar_intacta` va después de las comprobaciones de URL y antes de cualquier `fetch`/`reset`.
  La marca se escribe al clonar y al actualizar, siempre dentro de `.git`. Si la marca falla tras un clon
  propio, se borra ese clon: correcto, porque el directorio no existía antes. El caso del incidente
  (rama `fase1-motor` con commits y `articulo.md` sin guardar) da `CopiaAjena` por tres vías: ramas, `HEAD` y `status`.
- Repasado sin prueba: un `stash` (no está en `refs/heads`) sobrevive al `reset`. Un `worktree` con rama
  se ve en el recuento de ramas. Que la copia siga intacta durante un run lo garantiza el guardia, porque
  nadie escribe en el repo (D8). Si no fuera así, cada noche dejaría la copia "con trabajo local" para la siguiente.
- **D37:** dueño y repo en minúsculas antes de quitar `.git`. La prueba normativa está cambiada como se pidió.
- **D36:** `RepoCambiado` antes de lanzar nada. `--reanudar` sale con 2. `/api/lanzador` da el error con códigos
  distintos de 0, 1 y 130, y la página lo consulta mientras el directo está abierto.

## 2. Desviaciones

| # | Veredicto |
|---|---|
| 1. Fuera `clean -fdx` | **Aceptada.** Con D38 no hay nada que limpiar. Un comando destructivo de menos es justo el espíritu de D38 |
| 2. Prueba propia ajustada a D37 | Aceptada |
| 3. Orden D38 → D37 → D36 | Aceptada: no se tocan entre sí |
| 4. Copias sin marca | Es la migración prevista. `repomix` ya está borrada (Josem, 2026-10-15) |
| 5. El texto lista todas las ramas | Aceptada |

## 3. Hallazgos

Ninguno.

## 4. Veredicto

**Aprobado. H4 completo (H4 + H4b) listo para fusionar.** Lo hace Josem:
`git merge --ff-only feature/fase3-h4` desde `/data/enjambre-explicador`, reinicio de la pantalla real
y `git worktree remove ../enjambre-explicador-h4`. Después, H5 (la aceptación) la lanza Josem. Programador:
nada más en esta fase salvo lo que salga de la aceptación.
