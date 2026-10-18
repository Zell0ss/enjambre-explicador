# H6 — revisión (peso y precio, commit fijado, sacar de la cola)

La he hecho contra el código (`e2d4584`, `bb879ff`, `2173973`) y la spec (§9, D40-D42), no contra el informe.

## 1. Comprobado

- 355 pruebas de Python y 19 de JS, todas verdes (las ejecutó el arquitecto en el worktree).
- Las **27 pruebas normativas** del anexo son idénticas al plan: comparé su AST, función a función.
- D40: `peso.py` cumple el contrato (bandas, alerta, formato del texto). `pesar_fuente` clona en un
  `TemporaryDirectory` y no toca `RAIZ_COPIAS`. `leer` solo pesa en un run nuevo, y un fallo da un warning y
  `peso=None`. `/api/pesar` valida igual que `/api/encolar` y pinta el texto con `textContent`, así que no
  hay XSS.
- D41: el sha se valida antes de cualquier `git` y se pasa a `fetch` después de `origin`: no hay inyección de
  opciones. En un clon nuevo, el `fetch` fallido cae dentro del bloque que borra el clon. En una copia
  existente, un `fetch` fallido no toca nada, porque el `reset` va después. Con una ruta local sigue D36.
- D42: el id se valida con `fullmatch` antes de tocar el disco. `id` nunca se escribe en el JSON. «Sacar»
  sale en pendientes y en fallidas.
- Las firmas de la cola ya tienen `raiz_cola=None`.

## 2. Desviaciones del informe

| # | Veredicto |
|---|---|
| 1. «1 ficheros» | Aceptada: se queda como el plan |
| 2. `ficheros()` da `None` dentro de otro repo | Aceptada, y es mejor que el plan |
| 3. `errors="replace"` en `_git` | Aceptada |
| 4. Atajo sin `fetch` si `HEAD == commit` | Aceptada: la copia está intacta, así que su HEAD es el de la marca |
| 5. `import git` en `test_leer.py` | Aceptada |
| 6. id solo en minúsculas | Aceptada (D37) |
| 7. `resolver` con `RAIZ_COPIAS` en la firma | Se arregla en H7 (portabilidad), que cambia esos valores por defecto |

## 3. Hallazgos

**R6 (menor, no bloquea). Queda una ventana pequeña al sacar una petición durante su lectura.** `noche`
comprueba `ruta.exists()` y después hace `_escribir(ruta, pet)`. Si «Sacar» cae entre esas dos líneas
(microsegundos, a las 02:30), la petición reaparece en `pendientes/` y además queda en `retiradas/`. Pasa
algo parecido con el historial: si se saca durante la lectura, la entrada de esa noche (coste y run) no llega
a `retiradas/`, aunque el run sigue en `salidas/`. Hoy no compensa cerrarlo: harían falta un cerrojo de la
cola o que «Sacar» espere a que acabe la noche. *Falsación:* una petición que aparezca a la vez en
`pendientes/` y en `retiradas/`. Si pasa, se hace que `retirar` dé 409 mientras el cerrojo esté tomado.
**Atribución:** plan (arquitecto). El anexo pedía «comprobar y no recrear», que tiene esa ventana.

## 4. Veredicto

**Aprobado.** No hay retoques. Fusiona Josem.

- `README.md` lleva dos líneas nuevas de H6, y la sesión del README (`feature/readme`) lo está reescribiendo.
  Hay que fusionar H6 primero, y que esa rama haga rebase sobre `main` antes de la suya.
- Aceptación de H6 (la hace Josem, como en el anexo): «Pesar» con golden-thread (XL, no cabe) y con repomix
  (M, cabe), y Encolar → Sacar.
