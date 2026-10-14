# H3 — informe (la cola y la noche)

Incluye los retoques R3 de la revisión de H2 (`283c241`) y D35 (`leer` salta con `salidas/`, no con la nota).

## Hecho

- **R3** (`283c241`): `nota.comprobar(raiz, nombre, fuente)`, llamada en `leer` antes de `actualizar`/`orquestar`
  salvo con `falso`; `escribir` la sigue usando. Regresión: nota humana → `NotaAjena`, `lanzar` sin llamar,
  sin `salidas/proyecto/`.
- **D35** (de la sección 6 de la revisión de H2, aprobada por Josem): `leer(saltar_si_igual=True)` mira el run más
  reciente **acabado** (`FINALES`) de esa fuente en `salidas/` y salta si su `run_inicio.commit` es el actual;
  `nota` es la ruta si existe, `None` si no. Las tres regresiones del §6 (a, b, c) más una mía: **los runs
  `--falso` no cuentan**, o la demo de Claude-Fables que hice en H2 (mismo fuente y commit) habría hecho saltar
  su primera lectura real. (`7dbb628` + commit de D35.)
- **Tarea 23**: `enjambre/cola.py` (`encolar`, `pendientes`, `fallidas`, `noche`, `main`).
  `tests/test_cola.py`: las 10 normativas tal cual + 3 añadidas (cola vacía → 0 y en silencio; cerrojo ocupado →
  aviso y código 3 con la petición intacta; `--falso` de punta a punta con una fuente local).
- **Tarea 24**: `systemd/enjambre-cola.service` y `.timer` (copiados del plan; `systemd-analyze calendar` da la
  próxima ejecución a las 02:30) y la sección "Fase 3" del `README.md` con la instalación para Josem, el `--falso`
  a mano y el drop-in para probar la unidad sin gastar.
- Pruebas: **258 Python** (239 de antes + 19) y 19/19 JS. Las pruebas no crean `cola/` ni `cerrojo.lock`.

## Gasto

0. No he ejecutado la prueba [API] del plan (`python -m enjambre.cola` real con un repo pequeño): espera el "sí" de Josem.

## Desviaciones

1. **`main` de la cola gana `--raiz-cola` y `--salidas`** (el plan lista `--falso`, `--cerrojo`, `--techo-usd`):
   hacen falta para probar `main` sin tocar el `cola/` real.
2. **Modo del run al continuar.** En `leer_fn`, un run parado solo se continúa si su modo (`params.falso`) coincide
   con el de la noche; si no, se ignora y se lanza uno nuevo. Si no, `--falso` escribiría ficheros de pega en un run
   real parado, y la noche real gastaría para seguir una demo. El plan no lo dice.
3. **Código de salida de `cola.main`:** 0 normal o `parada="techo"`; **1** si la noche paró por un fallo/interrupción
   (`fallo:`, `excepcion:`, `interrumpido`) para que `systemctl status` lo marque; 3 con el cerrojo ocupado.
4. Un JSON ilegible en `pendientes/` se salta con un aviso al log, no tumba la noche.
5. El nombre del fichero de una petición lleva un sufijo `-2`, `-3` si coincide en segundo y nombre de repo (otro dueño).

## Decisiones que necesito

1. **La prueba [API] de H3 (la decide Josem).** Con `.env` creado (ya existe, según la revisión) y el timer sin
   instalar, `python -m enjambre.cola` a mano con **un** repo pequeño en cola y el tope por defecto (5 $ por
   run, techo 10 $) confirmaría el Telegram real y que `HOME` da acceso a las credenciales del CLI. No la lanzo sin su "sí".
2. **Instalar el timer** (`sudo`) lo hace Josem con los comandos del README.
