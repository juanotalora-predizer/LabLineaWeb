"""Sprite SVG propio (app/static/img/iconos.svg) a partir de íconos de Lucide (spec funcional/0008).

Solo copia figuras y atributos geométricos (lista blanca): un SVG descargado no puede colar scripts,
enlaces ni estilos. Descargar los íconos en una carpeta aparte y pasarla como origen:

    python3 -I scripts/construir_iconos.py <carpeta con los .svg de lucide-static> app/static/img/iconos.svg
"""

import re
import sys
import xml.etree.ElementTree as ET  # nosec B405 (sin DTD ni entidades: se rechazan antes de parsear)
from pathlib import Path

ELEMENTOS = {"path", "circle", "rect", "line", "polyline", "polygon", "ellipse"}
ATRIBUTOS = {"d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2", "width", "height", "points"}
VALOR = re.compile(r"^[0-9a-zA-Z .,\-]*$")

origen, destino = Path(sys.argv[1]), Path(sys.argv[2])
simbolos = []
for archivo in sorted(origen.glob("*.svg")):
    contenido = archivo.read_text()
    # Sin DTD ni entidades (evita la expansión de entidades) y tamaño acotado antes de parsear.
    if "<!DOCTYPE" in contenido or "<!ENTITY" in contenido or len(contenido) > 10_000:
        raise SystemExit(f"{archivo.name}: contenido no permitido")
    raiz = ET.fromstring(contenido)  # noqa: S314 # nosec B314
    figuras = []
    for hijo in raiz:
        etiqueta = hijo.tag.split("}")[-1]
        if etiqueta not in ELEMENTOS:
            raise SystemExit(f"{archivo.name}: elemento no permitido {etiqueta}")
        atributos = []
        for k, v in hijo.attrib.items():
            if k == "fill" and v in ("currentColor", "none"):
                atributos.append(f'{k}="{v}"')
                continue
            if k not in ATRIBUTOS or not VALOR.match(v):
                raise SystemExit(f"{archivo.name}: atributo no permitido {k}={v!r}")
            atributos.append(f'{k}="{v}"')
        figuras.append(f"<{etiqueta} {' '.join(atributos)}/>")
    simbolos.append(f'  <symbol id="{archivo.stem}" viewBox="0 0 24 24">{"".join(figuras)}</symbol>')
destino.write_text(
    "<!-- Íconos Lucide (ISC, https://lucide.dev), subconjunto del proyecto. Ver LICENCIAS.md -->\n"
    '<svg xmlns="http://www.w3.org/2000/svg">\n' + "\n".join(simbolos) + "\n</svg>\n"
)
print(len(simbolos), "íconos")
