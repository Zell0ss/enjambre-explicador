"""
Peso y precio de una fuente, antes de gastar (D40). Solo informativo: no decide nada.

Cuenta lo que sigue git (sin directorios de terceros) y los bytes de código;
tokens ≈ bytes de código / 4, y de ahí una banda de coste calibrada con los runs
reales (§9.1 del diseño). Existió porque golden-thread gastó 8 $ sin dar nota y
su tamaño se sabía gratis antes de empezar.

Solo `fuente.py` llama a `git`: aquí se pide la lista de ficheros a `fuente.ficheros`.
"""

import argparse
import os
import stat
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from enjambre import fuente as fuente_mod
from enjambre.fuente import Fuente, FuenteInvalida, GitFallo, resolver

CODIGO = frozenset({".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt",
                    ".rb", ".php", ".c", ".h", ".cpp", ".hpp", ".cs", ".swift", ".sh", ".sql", ".vue",
                    ".svelte", ".css", ".scss", ".html", ".toml", ".yaml", ".yml"})
EXCLUIDOS = frozenset({"node_modules", "vendor", "third_party", "dist", "build", ".venv", "venv",
                       "__pycache__", ".git"})
MAX_FICHERO = 200_000  # bytes; más grande = generado o minificado: cuenta en el total, no como código
# (banda, tokens hasta (exclusivo), usd_min, usd_max) — calibrado con §9.1; L y XL con un solo dato (D40 tentativa)
BANDAS = (("S", 75_000, 1.0, 3.0), ("M", 1_500_000, 3.5, 5.0), ("L", 6_000_000, 5.0, 8.0), ("XL", None, 7.0, 12.0))


@dataclass(frozen=True)
class Peso:
    ficheros: int
    bytes: int
    ficheros_codigo: int
    bytes_codigo: int

    @property
    def tokens(self) -> int:
        return self.bytes_codigo // 4


@dataclass(frozen=True)
class Estimacion:
    banda: str
    usd_min: float
    usd_max: float
    tope_usd: float
    alerta: Literal["cabe", "justo", "no cabe"]


def _recorrer(ruta: Path) -> list[str]:
    """Carpeta sin git: todo lo que hay, sin entrar en los excluidos ni seguir symlinks."""
    rutas = []
    for raiz, dirs, nombres in os.walk(ruta, followlinks=False):
        dirs[:] = [d for d in dirs if d not in EXCLUIDOS]
        rutas.extend(str((Path(raiz) / n).relative_to(ruta)) for n in nombres)
    return rutas


def _es_binario(ruta: Path) -> bool:
    try:
        with ruta.open("rb") as f:
            return b"\0" in f.read(8192)
    except OSError:
        return True


def pesar(ruta: Path) -> Peso:
    lista = fuente_mod.ficheros(ruta)
    if lista is None:
        lista = _recorrer(ruta)
    n = total = n_codigo = codigo = 0
    for rel in lista:
        p = Path(rel)
        if any(seg in EXCLUIDOS for seg in p.parts):
            continue
        try:
            st = (ruta / p).lstat()
        except OSError:
            continue  # en el índice pero ya no en disco
        if not stat.S_ISREG(st.st_mode):  # symlinks (no se siguen), submódulos, carpetas
            continue
        n += 1
        total += st.st_size
        if p.suffix.lower() in CODIGO and st.st_size <= MAX_FICHERO and not _es_binario(ruta / p):
            n_codigo += 1
            codigo += st.st_size
    return Peso(ficheros=n, bytes=total, ficheros_codigo=n_codigo, bytes_codigo=codigo)


def estimar(p: Peso, tope_usd: float = 5.0) -> Estimacion:
    for banda, hasta, usd_min, usd_max in BANDAS:
        if hasta is None or p.tokens < hasta:
            break
    if usd_max <= tope_usd:
        alerta = "cabe"
    elif usd_min > tope_usd:
        alerta = "no cabe"
    else:
        alerta = "justo"
    return Estimacion(banda=banda, usd_min=usd_min, usd_max=usd_max, tope_usd=float(tope_usd), alerta=alerta)


def _num(x: float) -> str:
    """Sin «,0» sobrante y con coma decimal: 5.0 → «5», 3.5 → «3,5»."""
    return f"{x:g}".replace(".", ",")


def _tamano(b: int) -> str:
    if b < 1_000_000:
        return f"{b // 1000} kB"
    return f"{b / 1_000_000:.1f}".replace(".", ",") + " MB"


def _tokens(t: int) -> str:
    if t < 1_000_000:
        return f"~{t // 1000}k"
    return "~" + f"{t / 1_000_000:.1f}".replace(".", ",") + "M"


def texto(p: Peso, e: Estimacion) -> str:
    alerta = {"cabe": "cabe en", "justo": "justo para", "no cabe": "no cabe en"}[e.alerta]
    return (
        f"{p.ficheros:,}".replace(",", ".") + f" ficheros, {_tamano(p.bytes)} · "
        f"código {_tamano(p.bytes_codigo)} ({_tokens(p.tokens)} tokens) · {e.banda} · "
        f"{_num(e.usd_min)}-{_num(e.usd_max)} $ · {alerta} {_num(e.tope_usd)} $"
    )


def pesar_fuente(f: Fuente, *, remoto: str | None = None, tmp: Path | None = None) -> Peso:
    """Una URL se clona en un temporal que se borra siempre: **nunca toca
    `RAIZ_COPIAS`** (pesar no debe dejar una copia ni mover la de nadie). Una
    ruta local se pesa en su sitio."""
    if f.url is None:
        return pesar(Path(f.texto))
    with tempfile.TemporaryDirectory(dir=tmp) as td:
        destino = Path(td) / "repo"
        fuente_mod.clonar(f, destino, remoto=remoto)
        return pesar(destino)


def como_dict(p: Peso, e: Estimacion) -> dict:
    """Lo que va a `run_inicio.peso`: los dos `asdict` juntos, más `tokens`."""
    return {**asdict(p), "tokens": p.tokens, **asdict(e)}


def main(argv: list[str] | None = None) -> int:
    a = argparse.ArgumentParser(prog="python -m enjambre.peso")
    a.add_argument("fuente", help="URL de GitHub o ruta bajo ENJAMBRE_RAIZ_LOCAL")
    a.add_argument("--tope-usd", type=float, default=5.0)
    args = a.parse_args(argv)
    try:
        p = pesar_fuente(resolver(args.fuente))
    except FuenteInvalida as e:
        print(f"FuenteInvalida: {e}", file=sys.stderr)
        return 2
    except GitFallo as e:
        print(f"GitFallo: {e}", file=sys.stderr)
        return 1
    print(texto(p, estimar(p, args.tope_usd)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
