# H7 — revisión (publicable: prompts en el repo, configuración por entorno, MIT)

Revisado contra el código (`b963edd`, `562be55`, `7702fab`, `4143135`) y contra la spec (§10, D43-D45). No contra el informe.

## 1. Comprobado

- 376 pruebas de Python y 19 de JS, todas verdes (las ejecutó el arquitecto en el worktree).
- Las **11 pruebas normativas** del anexo son idénticas al plan (comparación de AST).
- D43: los siete `.claude/agents/*.md` son ficheros normales e **idénticos byte a byte** a `01-…07-*.md` del vault (`cmp`, que
  ejecutó el arquitecto).
- D44: `git grep -nE "/data/|100\.87\.|mi-wiki" -- enjambre pantalla` no devuelve nada. Todo se resuelve al llamar. `fuente`, `leer` y `pantalla`
  usan `x or config.x()`. El `conftest` aísla el `.env`, las `ENJAMBRE_*`, las notas y las copias. `.gitignore` incluye `notas/` y `copias/`.
- D45: `LICENSE` (MIT), `.env.example` y `requirements-seb01.txt` están commiteados. `.env` no lo está.

## 2. Desviaciones del informe

| # | Veredicto |
|---|---|
| 1. `check-ignore` ruta a ruta | Aceptada: errata del plan (arquitecto) |
| 2. El respaldo de logging escribe JSON | **Aceptada, y bien encontrada.** El clon limpio era la prueba que hacía falta. Hueco del plan (arquitecto) |
| 3. `ORDEN = ROLES` | Aceptada |
| 4. `aviso.py` reexporta `cargar_env` | Aceptada |
| 5. Texto genérico en el código | Aceptada |
| 6. Valor vacío = no puesto; `[::]`; rango del puerto | Aceptada |
| 7. `--puerto` con `None` por defecto | Aceptada |

## 3. Hallazgos

**R7. `--host 0.0.0.0` a mano se salta D12.** `main` hace `args.host or config.host()`, y la validación solo está en `config.host()`.
Ya pasaba antes de H7. Pero con el repo público, quien quiera ver la pantalla desde otro equipo de su red probará justo eso, y la
página lanza runs que gastan sin más protección que la cabecera anti-CSRF.
**Arreglo:** una sola función de validación (`config.validar_host(h)`), que `config.host()` y `main` usen tanto si el host viene de
`--host` como de `ENJAMBRE_HOST`.
*Prueba de regresión:* `pantalla.main(["--host", "0.0.0.0"])` lanza `ValueError` sin abrir el puerto.
**Atribución:** plan (arquitecto). D12 vivía en el valor por defecto y el anexo no pidió validar `--host`.

**R8 (proceso). El `.env` no se lee, tampoco sus claves.** El informe dice que miraste los nombres de las claves del `.env` real. La
regla es que el `.env` no se lee. Lo que pedía el anexo lo comprueba Josem, y solo él.
**Atribución:** implementación (programador).

## 4. Veredicto

**Aprobado con un retoque.** Haz R7 con su prueba de regresión en esta rama y avisa. No hace falta otra revisión completa: miro solo
ese commit. Gasto: 0.

Después fusiona Josem. Antes de fusionar, Josem comprueba con un comando lo que ha puesto en el `.env`. Lo ejecuta él y ve el
resultado, nadie más:
`cd /data/enjambre-explicador-h7 && .venv/bin/python -c "from enjambre import config; config.RUTA_ENV=__import__('pathlib').Path('/data/enjambre-explicador/.env'); print(config.raiz_notas(), config.raiz_copias(), config.raiz_local(), config.host())"`
Tiene que salir el vault (`…/Clippings/repo-articles`), `/data/github-abordaje`, `/data` y `100.87.64.121`.

Al fusionar, el arquitecto ejecuta `--copiar-a` sobre la carpeta del proyecto en el vault (D43).

## 5. Anexo: R7 (`f41e01b`)

R7 está cerrado. `config.validar_host` es la única validación y la usan `host()` y `pantalla.main`, tanto con `--host` como sin él. La prueba de
regresión comprueba que `crear_servidor` no llega a llamarse con `0.0.0.0`, `::`, `[::]` ni `" 0.0.0.0 "`. Pasan las 381 pruebas (ejecutadas
por el arquitecto). **Listo para fusionar**, después de la comprobación del `.env` (§4).
