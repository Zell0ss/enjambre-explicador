"""
El muro de permisos del enjambre (D8): decide si un rol puede leer o escribir
una ruta dada.

`permitido()` es una función pura: la única E/S que hace es `Path.resolve()`,
necesaria para que `..` y los symlinks no salten el muro — resolver antes de
comparar es lo que impide que una ruta relativa o un enlace dentro de `salida`
escapen hacia fuera (D8, foco de revisión §"Escapar del muro").

Se usa como hook `PreToolUse` del Agent SDK (tarea 7): por cada llamada a una
tool se calcula su ruta con `ruta_de()` y se consulta `permitido()` antes de
dejarla pasar.

Tabla de permisos (spec §3.3):

- cartografo, despiezador, lector-de-pieza, trazador, verificador:
  leer repo y salida; escribir solo salida.
- redactor: leer y escribir solo salida.
- novato: leer solo salida/articulo.md; escribir solo salida/dudas.md
  (en ambos casos, igualdad exacta de ruta resuelta, no "estar bajo").

Glob/Grep sin ruta explícita (`ruta=None`) se evalúan sobre `cwd` (= `salida`).
Una herramienta que no está en la tabla (p.ej. `Bash`) se deniega siempre.

Endurecido tras revisión (D8): cualquier ruta con un segmento literal `~` se
deniega sin resolver (evita que el guardia y la tool que de verdad toca
disco interpreten rutas distintas si esa tool expande `~` a `$HOME`); y
cualquier error al construir/resolver la ruta (byte nulo, bucle de
symlinks, entrada con un tipo inesperado) se traduce a una denegación en
vez de propagar la excepción — este guardia corre dentro de un hook
`PreToolUse`, donde una excepción sin capturar tiraría el run entero.

Parche de seguimiento a la revisión de la tarea 3: `eventos.jsonl` y
`vueltas/` (los registros autoritativos del orquestador bajo `salida`,
D13) son de solo lectura para todo rol, aunque su regla de muro le dé
escritura en `salida` entera; los objetivos protegidos también se resuelven
antes de comparar, por si `salida/vueltas` fuera algún día un symlink. Y el
`pattern` de `Glob` (parámetro opcional `patron`, aún no conectado a ningún
hook real) se deniega si es absoluto o contiene el substring `..` o `~` en
cualquier posición — substring y no segmento exacto, para que una llave sin
expandir (p.ej. `"{..,x}/etc/*"`) no se salte el chequeo si el motor de
glob real expande llaves antes de comparar — con independencia del rol.
"""

from pathlib import Path

# Tools de lectura y de escritura (spec §3.3). Cualquier otra tool se deniega.
LECTURAS = frozenset({"Read", "Glob", "Grep"})
ESCRITURAS = frozenset({"Write", "Edit"})

# Campo de la entrada de la tool donde viene la ruta.
_CAMPO_RUTA = {
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "Glob": "path",
    "Grep": "path",
}

# Regla de muro por rol: "ambos" = repo o salida; "salida" = solo salida;
# "exacto" = igualdad exacta con un fichero concreto de salida (solo novato).
MURO: dict[str, tuple[str, str]] = {
    # (regla de lectura, regla de escritura)
    "cartografo": ("ambos", "salida"),
    "despiezador": ("ambos", "salida"),
    "lector-de-pieza": ("ambos", "salida"),
    "trazador": ("ambos", "salida"),
    "verificador": ("ambos", "salida"),
    "redactor": ("salida", "salida"),
    "novato": ("exacto", "exacto"),
}

# Los únicos ficheros exactos que puede tocar el novato (relativos a salida).
NOVATO_LEER = "articulo.md"
NOVATO_ESCRIBIR = "dudas.md"


def ruta_de(herramienta: str, entrada: dict) -> str | None:
    """Saca la ruta de la entrada de una tool, o None si no aplica/falta/no es texto."""
    campo = _CAMPO_RUTA.get(herramienta)
    if campo is None:
        return None
    valor = entrada.get(campo)
    # Un valor no-string (entrada malformada) se trata como "sin ruta", no
    # como un TypeError que tumbe a permitido() más adelante.
    return valor if isinstance(valor, str) else None


def permitido(
    rol: str,
    herramienta: str,
    ruta: str | None,
    repo: Path,
    salida: Path,
    patron: str | None = None,
) -> tuple[bool, str]:
    """
    Decide si `rol` puede usar `herramienta` sobre `ruta`.

    `ruta=None` (Glob/Grep sin ruta explícita) se evalúa sobre `salida`, que
    es el cwd del agente. Las rutas relativas se resuelven contra `salida`.
    Siempre se resuelve (`Path.resolve()`) antes de comparar con
    `is_relative_to`, para que `..` y los symlinks no se salten el muro.

    `patron` es el `pattern` de un `Glob` (opcional, keyword): se deniega si
    es absoluto o si contiene el substring `..` o `~` en cualquier
    posición (substring, no segmento exacto tras partir por "/": una llave
    sin expandir como `"{..,x}/etc/*"` no debe colarse si el motor de glob
    real expande llaves antes de comparar), con independencia del rol — es
    una comprobación sobre la forma del patrón, no sobre quién pregunta
    (mismo espíritu que la denegación de `..`/absolutas/`~` de más abajo).
    No se toca `ruta_de()` ni ningún hook real: eso es tarea aparte de
    `lanzador.py`.

    Devuelve (ok, motivo); motivo es una frase corta en español, vacía si ok.
    """
    if herramienta in LECTURAS:
        categoria = "leer"
    elif herramienta in ESCRITURAS:
        categoria = "escribir"
    else:
        return False, f"herramienta '{herramienta}' fuera de la tabla de permisos"

    regla_lectura, regla_escritura = MURO.get(rol, (None, None))
    regla = regla_lectura if categoria == "leer" else regla_escritura
    if regla is None:
        return False, f"rol '{rol}' desconocido"

    try:
        # Forma del patrón de Glob, independiente del rol: un patrón
        # absoluto o con ".." lista fuera del muro aunque ruta=None lo
        # evaluara sobre cwd/salida (ese es un chequeo distinto, de más
        # abajo). Entrada malformada (no string) cae al except general.
        #
        # ".." se busca como substring, no como segmento exacto tras
        # partir por "/": un motor de glob que expanda llaves antes de
        # comparar (node-glob/minimatch y similares) convertiría algo como
        # "{..,x}/etc/*" en "../etc/*" sin que ningún segmento literal sea
        # "..". Ningún patrón legítimo necesita el substring "..", así que
        # denegarlo siempre es estrictamente más seguro y además cubre sin
        # chequeo aparte el caso ".." a mitad de patrón. Mismo razonamiento
        # para "~": si el motor real lo expande a $HOME, el guardia estaría
        # juzgando un patrón distinto del que se usa de verdad (D8).
        if herramienta == "Glob" and patron is not None:
            if patron.startswith("/") or ".." in patron or "~" in patron:
                return False, "patrón de Glob fuera del muro"

        # "~" se deniega sin más, antes de tocar nada: no es absoluta, así
        # que sin este chequeo se compondría como el directorio literal
        # "salida/~/..." (que SÍ cae bajo salida) y se aprobaría. Si el SDK
        # real expande "~" a $HOME antes de tocar disco (habitual en
        # shells/CLIs), el guardia estaría juzgando una ruta distinta de la
        # que realmente se toca. Ningún uso legítimo del enjambre necesita
        # "~", así que fail-closed.
        if ruta is not None and "~" in Path(ruta).parts:
            return False, "ruta con '~' no permitida"

        # Ruta efectiva: sin ruta explícita, se evalúa el cwd (= salida).
        objetivo = Path(ruta) if ruta is not None else salida
        if not objetivo.is_absolute():
            objetivo = salida / objetivo

        resuelta = objetivo.resolve()
        repo_r = repo.resolve()
        salida_r = salida.resolve()

        # eventos.jsonl y vueltas/ son los registros autoritativos del
        # orquestador (D13), no artefactos de un agente: ningún rol escribe
        # ahí, aunque su regla de muro le dé "salida" entero (cartografo,
        # verificador...) o incluso cuando su regla "exacto" coincidiera por
        # casualidad de nombre. Se comprueba contra la ruta ya resuelta, y
        # también se resuelven los propios objetivos protegidos (mismo
        # patrón que usa la regla "exacto" de novato más abajo): si
        # "salida/vueltas" fuera alguna vez un symlink, comparar contra la
        # ruta sin resolver dejaría pasar una escritura que en disco cae
        # fuera de "salida/vueltas" tal cual.
        eventos_r = (salida_r / "eventos.jsonl").resolve()
        vueltas_r = (salida_r / "vueltas").resolve()
        if categoria == "escribir" and (
            resuelta == eventos_r or resuelta.is_relative_to(vueltas_r)
        ):
            return False, "eventos.jsonl y vueltas/ son de solo lectura para los agentes"

        if regla == "exacto":
            nombre = NOVATO_LEER if categoria == "leer" else NOVATO_ESCRIBIR
            permitido_ok = resuelta == (salida_r / nombre).resolve()
        elif regla == "salida":
            permitido_ok = resuelta.is_relative_to(salida_r)
        elif regla == "ambos":
            permitido_ok = resuelta.is_relative_to(repo_r) or resuelta.is_relative_to(salida_r)
        else:  # pragma: no cover - defensivo, MURO no produce otros valores
            permitido_ok = False
    except (OSError, ValueError, RuntimeError, TypeError, AttributeError):
        # Ruta malformada (byte nulo, bucle de symlinks, tipo inesperado...):
        # denegar en vez de propagar. Este guardia se usa como hook
        # PreToolUse (tarea 7); una excepción sin capturar aquí tiraría toda
        # la ejecución del agente en vez de bloquear solo esa tool call.
        return False, "ruta no válida"

    if permitido_ok:
        return True, ""
    return False, f"ruta fuera del muro permitido para '{rol}'"
