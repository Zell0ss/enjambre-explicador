"""
Escritor de eventos.jsonl: una línea JSON por evento, append-only.

Concurrencia (D-pendiente, ver brief Tarea 5): hasta 8 lector-de-pieza corren
en paralelo vía asyncio.gather y emiten por la MISMA instancia de Eventos;
además el hook del SDK (Tarea 7) puede llamar a `emitir` desde un hilo distinto
al del bucle asyncio. Un asyncio.Lock solo serializa dentro del mismo loop, así
que no basta aquí: se usa threading.Lock, que excluye independientemente de
quién (qué hilo/loop) esté llamando. eventos.jsonl se lee en caliente (pantalla,
Tarea 8) mientras se escribe, así que cada `emitir` debe aterrizar como una
única línea completa: se construye la línea entera en memoria y se hace UN
solo `write()` (no acumulable con otra escritura a medias) seguido de
`flush()`, todo bajo el lock.
"""

import json
import threading
from datetime import datetime
from pathlib import Path


class Eventos:
    """Escribe eventos del run como JSON Lines en `ruta`."""

    def __init__(self, ruta: Path, run: str):
        self._run = run
        self._lock = threading.Lock()
        # buffering=1 (line-buffered) + flush() explícito tras cada write:
        # un lector concurrente (tail -f, SSE) ve la línea en cuanto se emite.
        self._fichero = open(ruta, mode="a", encoding="utf-8", buffering=1)

    def emitir(self, tipo: str, agente: str | None = None, **campos) -> dict:
        """Construye, escribe y devuelve un evento."""
        evento = {
            "t": datetime.now().isoformat(timespec="milliseconds"),
            "run": self._run,
            "tipo": tipo,
        }
        if agente is not None:
            evento["agente"] = agente
        evento.update(campos)

        linea = json.dumps(evento, ensure_ascii=False) + "\n"
        with self._lock:
            # Una sola llamada write() con la línea completa: si se escribiera
            # en varias llamadas, otro hilo podría intercalar su propia
            # escritura entre medias y corromper la línea para el lector SSE.
            self._fichero.write(linea)
            self._fichero.flush()
        return evento

    def cerrar(self) -> None:
        with self._lock:
            self._fichero.close()
