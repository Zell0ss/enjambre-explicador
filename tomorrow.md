# Sesión siguiente

## Estado

Fase 3 (abordaje) **construida y fusionada en `main`** (H1-H4b, D26-D38). Falta solo la **aceptación (H5), que lanza Josem**.
Lo hecho está en los informes `docs/fase3/H*-informe.md` y en los commits; las decisiones, en el diseño del vault (D26-D38).

## Siguiente

- **H5 (Josem):** encolar `https://github.com/shaven/golden-thread` desde la página (un solo repo: dos "comen tokens a lo burro").
  El timer corre a las 02:30; o `sudo systemctl start enjambre-cola.service` para verlo ya. Se acepta con: nota en
  `Clippings/repo-articles/golden-thread.md` (`generado_por: enjambre`), Telegram de La borracha, repetición en la pantalla y
  noche ≤ 10 $. Si se para por límite de uso, la noche siguiente continúa (D30).
- **Qué mirar en esa aceptación (indicadores de falsación abiertos):** I8 (si el cartógrafo gasta más de la mitad del tope del
  run, falta un filtro de tamaño; el repo pesa ~85 MB de historial) e I7 (si el tope semanal de la suscripción se nota).
- Programador: nada más hasta que salga algo de la aceptación o Josem pida pulido.

## Gotchas

- `/data/enjambre-explicador` arranca el servicio de la noche: **siempre en `main`, limpio**; se trabaja en un worktree (ver `CLAUDE.md`).
- La pantalla real (`100.87.64.121:8790`) hay que **reiniciarla a mano tras cada fusión**: carga el código al arrancar.
  Si no hay proceso, `.venv/bin/python -m enjambre.pantalla`. Decisión pendiente de Josem: hacerle un servicio systemd
  (con `KillMode=process`, o un reinicio mataría los runs lanzados desde la página).
- `/data/github-abordaje/Claude-Fables` es una copia huérfana (de otro proyecto; con D37 la nueva se llamaría `claude-fables`).
  La decide Josem; nunca se toca desde el código (D38).
- Una copia sin marca `.git/enjambre` o con cambios locales da `CopiaAjena`: se borra a mano y se vuelve a clonar.
- Un `cerrojo.lock` huérfano no existe: lo suelta el sistema al morir el proceso.

## Bloqueos / le toca a Josem

Ninguno de código. Aceptación (H5), decidir lo de la copia `Claude-Fables` y si la pantalla pasa a servicio.
