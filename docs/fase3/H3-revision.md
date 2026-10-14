# H3 — revisión (la cola y la noche)

Revisado contra el código (`283c241`, `fc24d4e`, `08b6a4a`, `15c00f7`) y la spec (§8, D24, D29-D31,
D35), no contra el informe.

## 1. Comprobado

- 258 pruebas de Python y 19 de JS, todas verdes (ejecutadas por el arquitecto). Las normativas de
  `test_cola.py` coinciden con el plan. Las pruebas no crean `cola/`. El `cerrojo.lock` que hay en la
  raíz es del paso manual de H2, y está en `.gitignore`.
- **R3 cerrado:** `nota.comprobar` va antes de `actualizar`/`orquestar`, con su prueba.
- **D35 cerrado:** el salto lo decide `_ultimo_acabado` en `salidas/`. Que los runs `--falso` no
  cuenten es una buena adición: sin eso, la demo de Claude-Fables de H2 habría hecho saltar su
  primera lectura real.
- Reglas de `noche`: techo, `min(tope, disponible)`, `sin_cambios` a `hechas/`, intentos, `fallidas/`,
  `historial`, y para la noche ante `fallo:`/`interrumpido`. Todo como el plan.
- He contrastado la regla de parada con los runs reales que hay en `salidas/`. Los cortes por límite
  de uso de Claude-Fables salieron como `fallo:cartografo:error` y `fallo:redactor:error`, así que
  la cola habría parado bien.
- Las unidades systemd son las del plan.

## 2. Desviaciones del informe

| # | Veredicto |
|---|---|
| 1. `--raiz-cola`, `--salidas` | Aceptada |
| 2. Solo se continúa un parado del mismo modo | Aceptada en la idea; incompleta, ver R4 |
| 3. Código 1 si la noche paró por fallo | Aceptada: `systemctl status` lo enseñará |
| 4. JSON ilegible se salta | Aceptada |
| 5. Sufijo `-2` | Aceptada |

## 3. Hallazgos

**R4. Una demo `--falso` tapa un run real parado.** `ultimo_parado` mira el run más reciente de
la fuente sin fijarse en el modo, y `leer_fn` lo descarta *después* si no coincide. Josem hace demos
`--falso` sobre los mismos repos que lee de verdad, como ya pasó con Claude-Fables. Si después de un
run real parado por coste hay una demo `--falso` (parada o acabada), la noche no ve el real: lanza
uno nuevo y paga otra vez el mapa, las piezas y las fichas.
**Arreglo:** `ultimo_parado(salidas, fuente, *, falso: bool = False)` considera solo los runs con
ese `params.falso`. `leer_fn` le pasa el modo de la noche y deja de filtrar a posteriori.
*Prueba de regresión:* run real `tope_coste` a las 02:30 y demo `--falso` aprobada a las 10:00 →
`ultimo_parado(..., falso=False)` devuelve el real.
**Atribución:** plan (arquitecto). La firma de `ultimo_parado` no preveía el modo.

**R5. Una excepción desconocida no para la noche.** `noche` trata cualquier excepción de `leer_fn`
como un problema de ese repo y sigue con el siguiente. Pero `orquestar` relanza todo lo que no es
una parada normal, después de apuntar `excepcion:<tipo>` en el `run_fin`. Por eso la comprobación
`motivo.startswith("excepcion:")` de la cola nunca se cumple, y algo que no es del repo (SDK roto,
disco lleno) consumiría esa noche un intento de cada petición. Solo las excepciones conocidas de un
repo deben seguir la noche: `FuenteInvalida`, `CopiaAjena`, `GitFallo` y `NotaAjena`. Cualquier
otra se apunta en `errores` y en el historial igual, pero **para la noche**
(`parada="excepcion:<Tipo>"`) y va a LogCentral con la traza.
*Prueba de regresión:* `leer_fn` que lanza `RuntimeError` en A, con B detrás → B no se llama,
`parada == "excepcion:RuntimeError"`, A con un intento más.
**Atribución:** plan (arquitecto). La regla "excepción = problema del repo" era mía.

## 4. Las decisiones que pedía el informe

Las dos son de Josem y se las ha pedido el arquitecto. **Una corrección a la prueba [API]
propuesta:** ejecutar `python -m enjambre.cola` a mano no prueba el `HOME` de systemd, porque corre
con el entorno de la sesión de Josem. La prueba buena es la unidad de verdad: instalar el timer,
encolar un repo pequeño y lanzar `sudo systemctl start enjambre-cola.service`. Así se comprueban a
la vez las credenciales bajo systemd, el Telegram real y el código de salida. La hace Josem, con los
comandos del README. Tú no lances nada [API].

## 5. Veredicto

**Aprobado con retoques.** Haz R4 y R5 con su prueba de regresión y sigue con **H4 (Tarea 25)**. Los
retoques los miro en la revisión de H4. Gasto autorizado: **0**. La pantalla real la reinicia Josem
al aprobar H4, no tú.
