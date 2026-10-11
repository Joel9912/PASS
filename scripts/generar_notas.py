#!/usr/bin/env python
"""Genera el apartado «Arreglado en esta versión» a partir de ``BUGS.md`` y git.

Uso:
    python scripts/generar_notas.py --desde v0.1-alpha --hasta v0.2

El registro de bugs es la fuente única (R2): este script no copia nada, solo
lee ``BUGS.md``, se queda con los hallazgos en estado ✅ (y con los 🟡
contenidos en una sección aparte) cuyo commit cae dentro del rango de
referencias indicado, y escribe el texto entre marcadores
(``NOTAS:INICIO``/``NOTAS:FIN``), de forma que se puede regenerar sin pisar
el resto del CHANGELOG. Los corregidos sin commit («auditoría anterior») no
salen: se curan a mano.
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: Delimitan el bloque generado dentro del CHANGELOG.
MARCADOR_INICIO = "<!-- NOTAS:INICIO -->"
MARCADOR_FIN = "<!-- NOTAS:FIN -->"

_FILA_BUG = re.compile(r"^\|\s*\*\*([A-Z]-\d{4})\*\*\s*\|(.*)\|\s*$")
_FILA_AREA = re.compile(r"^\|\s*\*\*([A-Z])\*\*\s*\|\s*(.*?)\s*\|")
_COMMIT = re.compile(r"`([0-9a-f]{7,40})`")


@dataclass(frozen=True)
class Hallazgo:
    """Una fila de ``BUGS.md`` ya interpretada."""

    identificador: str
    descripcion: str
    estado: str

    @property
    def area(self) -> str:
        """Letra de área, la primera del identificador."""
        return self.identificador[0]

    @property
    def commits(self) -> list[str]:
        """Commits citados en la columna de estado, en el orden en que aparecen."""
        return _COMMIT.findall(self.estado)


def leer_bugs(ruta: Path) -> list[Hallazgo]:
    """Lee las tablas de ``BUGS.md`` y devuelve sus hallazgos en orden de archivo.

    Solo cuenta una fila cuyo primer formato sea un ID ``X-0000``: cabeceras,
    separadores y la tabla de áreas se descartan solos. De las celdas se usa
    la segunda como descripción y la última como estado, así que la tabla
    admite columnas intermedias (p. ej. evidencia) sin quebrar el parser.
    """
    hallazgos: list[Hallazgo] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        encaje = _FILA_BUG.match(linea)
        if not encaje:
            continue
        identificador, resto = encaje.groups()
        celdas = [celda.strip() for celda in resto.split("|")]
        if len(celdas) < 2:
            continue
        hallazgos.append(Hallazgo(identificador, celdas[0], celdas[-1]))
    return hallazgos


def leer_areas(ruta: Path) -> dict[str, str]:
    """Lee la tabla de áreas de ``BUGS.md`` para titulares cada bloque."""
    areas: dict[str, str] = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        encaje = _FILA_AREA.match(linea)
        if encaje:
            letra, nombre = encaje.groups()
            areas[letra] = nombre.split("(", 1)[0].strip()
    return areas


def commits_del_rango(desde: str, hasta: str) -> set[str]:
    """Commits completos del rango ``desde..hasta``; git manda el error real."""
    try:
        res = subprocess.run(
            ["git", "rev-list", f"{desde}..{hasta}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("No hay `git` en el PATH: no puedo filtrar por rango.") from exc
    except subprocess.CalledProcessError as exc:
        detalle = (exc.stderr or "").strip()
        raise RuntimeError(f"git rev-list {desde}..{hasta} falló: {detalle}") from exc
    return {linea.strip() for linea in res.stdout.splitlines() if linea.strip()}


def filtrar(
    hallazgos: list[Hallazgo],
    rango: set[str],
    *,
    estados: tuple[str, ...] = ("✅",),
) -> list[Hallazgo]:
    """Solo los hallazgos en alguno de los estados dados con commit en el rango."""
    return [
        hallazgo
        for hallazgo in hallazgos
        if any(hallazgo.estado.startswith(estado) for estado in estados)
        and any(
            completo.startswith(commit)
            for completo in rango
            for commit in hallazgo.commits
        )
    ]


def _viñeta(hallazgo: Hallazgo) -> str:
    """Línea markdown de un hallazgo: ID, texto y commits entre paréntesis."""
    commits = ", ".join(f"`{c}`" for c in hallazgo.commits)
    sufijo = f" ({commits})" if commits else ""
    return f"- **{hallazgo.identificador}** — {hallazgo.descripcion.rstrip('.')}.{sufijo}"


def componer(
    corregidos: list[Hallazgo],
    areas: dict[str, str],
    *,
    desde: str,
    hasta: str,
    parciales: list[Hallazgo] | None = None,
) -> str:
    """Texto markdown del bloque generado, agrupado por área y orden por ID.

    Los contenidos a medias (🟡) salen al final en su propia sección para que
    un fix parcial no se olvide al redactar la nota de versión.
    """
    lineas = [
        MARCADOR_INICIO,
        "## Arreglado en esta versión",
        "",
        f"Rango `{desde}..{hasta}`, generado de `BUGS.md`: curar a mano antes de publicar.",
        "",
    ]
    for letra in sorted({hallazgo.area for hallazgo in corregidos}):
        titulo = areas.get(letra, f"Área {letra}")
        lineas.append(f"### {titulo} ({letra})")
        lineas.append("")
        del_area = sorted(
            (h for h in corregidos if h.area == letra),
            key=lambda h: h.identificador,
        )
        lineas.extend(_viñeta(hallazgo) for hallazgo in del_area)
        lineas.append("")
    if parciales:
        lineas.append("### Mejoras parciales")
        lineas.append("")
        lineas.append("Contenidas, aún con trabajo pendiente: revisar en `BUGS.md`.")
        lineas.append("")
        lineas.extend(
            _viñeta(hallazgo)
            for hallazgo in sorted(parciales, key=lambda h: h.identificador)
        )
        lineas.append("")
    lineas.append(MARCADOR_FIN)
    return "\n".join(lineas)


def sustituir_bloque(texto: str, bloque: str) -> str:
    """Reemplaza el bloque entre marcadores, o lo añade al final si no está."""
    if MARCADOR_INICIO in texto and MARCADOR_FIN in texto:
        antes, resto = texto.split(MARCADOR_INICIO, 1)
        _viejo, despues = resto.split(MARCADOR_FIN, 1)
        return antes + bloque + despues
    return texto.rstrip() + "\n\n" + bloque + "\n"


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada: parsea, filtra y escribe en stdout o en un fichero."""
    parser = argparse.ArgumentParser(
        description="Genera las notas de versión desde BUGS.md y git.",
    )
    parser.add_argument("--desde", default="v0.1-alpha", help="referencia inicial del rango")
    parser.add_argument("--hasta", default="HEAD", help="referencia final del rango")
    parser.add_argument("--bugs", type=Path, default=Path("BUGS.md"), help="ruta a BUGS.md")
    parser.add_argument("--salida", type=Path, help="fichero a actualizar; si falta, stdout")
    args = parser.parse_args(argv)

    if not args.bugs.is_file():
        print(f"No encuentro el registro de bugs: {args.bugs}", file=sys.stderr)
        return 1
    try:
        rango = commits_del_rango(args.desde, args.hasta)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    hallazgos = leer_bugs(args.bugs)
    corregidos = filtrar(hallazgos, rango, estados=("✅",))
    parciales = filtrar(hallazgos, rango, estados=("🟡",))
    if not corregidos and not parciales:
        print(
            f"Ningún bug corregido con commit en {args.desde}..{args.hasta}.",
            file=sys.stderr,
        )
        return 1

    bloque = componer(
        corregidos,
        leer_areas(args.bugs),
        desde=args.desde,
        hasta=args.hasta,
        parciales=parciales,
    )
    if args.salida is None:
        print(bloque)
        return 0

    previo = args.salida.read_text(encoding="utf-8") if args.salida.is_file() else ""
    args.salida.write_text(
        sustituir_bloque(previo, bloque), encoding="utf-8", newline="\n"
    )
    total = len(corregidos) + len(parciales)
    print(f"{total} hallazgos escritos en {args.salida}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
