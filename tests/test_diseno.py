"""Guardianes del sistema de diseño (spec funcional/0008).

- Los colores viven solo como tokens en :root; ninguna regla usa un color escrito directamente.
- Los pares de tokens de texto cumplen el contraste WCAG 2.1 AA (4,5:1).
- Las plantillas no tienen estilos ni scripts en línea y heredan de base.html.
- Todo ícono usado existe en el sprite propio; el sprite solo tiene figuras geométricas.
"""

import re
from pathlib import Path

import pytest
from markupsafe import Markup

from app.core import plantillas
from tests.ayudas import autenticar, cliente

RAIZ = Path(__file__).resolve().parent.parent / "app"
CSS = (RAIZ / "static" / "css" / "styles.css").read_text()
SPRITE = (RAIZ / "static" / "img" / "iconos.svg").read_text()
PLANTILLAS = sorted((RAIZ / "templates").rglob("*.html"))
_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")


def _tokens() -> dict[str, str]:
    raiz = re.search(r":root\s*\{(.*?)\n\}", CSS, re.S).group(1)
    return dict(re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", raiz))


def test_colores_solo_como_tokens():
    fuera_de_root = re.sub(r":root\s*\{.*?\n\}", "", CSS, count=1, flags=re.S)
    assert _COLOR.findall(fuera_de_root) == []


def _luminancia(color: str) -> float:
    color = color.strip().lstrip("#")
    canales = [int(color[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lineal = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
    return 0.2126 * lineal[0] + 0.7152 * lineal[1] + 0.0722 * lineal[2]


def contraste(a: str, b: str) -> float:
    claro, oscuro = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (claro + 0.05) / (oscuro + 0.05)


PARES_DE_TEXTO = [
    ("--color-texto", "--color-fondo"),
    ("--color-texto", "--color-superficie"),
    ("--color-texto-2", "--color-superficie"),
    ("--color-texto-3", "--color-superficie"),
    ("--color-texto-3", "--color-fondo"),
    ("--color-primario", "--color-superficie"),
    ("--color-primario-oscuro", "--color-primario-suave"),
    ("--color-blanco", "--color-primario"),
    ("--color-blanco", "--color-marca-900"),
    ("--color-marca-texto", "--color-marca-900"),
    ("--color-blanco", "--peligro"),
    *[(f"--{estado}", f"--{estado}-fondo") for estado in ("exito", "alerta", "peligro", "info", "neutro")],
]


@pytest.mark.parametrize(("texto", "fondo"), PARES_DE_TEXTO)
def test_contraste_aa_de_los_tokens(texto, fondo):
    tokens = _tokens()
    assert contraste(tokens[texto], tokens[fondo]) >= 4.5, (texto, fondo)


def test_calculo_de_contraste():
    assert round(contraste("#000000", "#ffffff"), 1) == 21.0
    assert contraste("#777777", "#ffffff") < 4.5


@pytest.mark.parametrize("plantilla", PLANTILLAS, ids=lambda p: str(p.relative_to(RAIZ)))
def test_plantillas_sin_estilos_ni_scripts_en_linea(plantilla):
    fuente = plantilla.read_text()
    assert not re.search(r"\sstyle\s*=", fuente)
    assert "<style" not in fuente
    assert not re.search(r"<script(?![^>]*\bsrc=)", fuente)
    assert not re.search(r"\son[a-z]+\s*=", fuente)  # manejadores de eventos en línea


# Los fragmentos que se incluyen (prefijo "_") no son páginas.
@pytest.mark.parametrize(
    "plantilla", [p for p in PLANTILLAS if p.name != "base.html" and not p.name.startswith("_")], ids=lambda p: p.name
)
def test_toda_plantilla_hereda_de_base(plantilla):
    assert plantilla.read_text().startswith('{% extends "base.html" %}')


def test_todo_icono_usado_existe_en_el_sprite():
    simbolos = set(re.findall(r'<symbol id="([a-z0-9-]+)"', SPRITE))
    usados = set()
    for archivo in [*PLANTILLAS, *RAIZ.rglob("*.py")]:
        usados |= set(re.findall(r"""icono\(\s*["']([a-z0-9-]+)["']\s*\)""", archivo.read_text()))
    assert usados and usados <= simbolos, usados - simbolos


def test_el_sprite_solo_tiene_figuras():
    for prohibido in ("<script", "href=", "xlink", "<style", "on", "<foreignObject", "<image"):
        if prohibido == "on":
            assert not re.search(r"\son[a-z]+=", SPRITE)
        else:
            assert prohibido not in SPRITE


def test_recursos_propios_y_licencias():
    estaticos = RAIZ / "static"
    for archivo in ("fonts/inter-latin.woff2", "fonts/inter-latin-ext.woff2", "img/iconos.svg", "LICENCIAS.md"):
        assert (estaticos / archivo).is_file(), archivo
    assert "SIL Open Font License" in (estaticos / "LICENCIAS.md").read_text()
    assert "ISC" in (estaticos / "LICENCIAS.md").read_text()
    assert "http" not in re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)  # sin recursos externos en el CSS


@pytest.mark.parametrize(
    ("estado", "tono", "texto"),
    [
        ("ACTIVA", "exito", "Activa"),
        ("PAGADA_PARCIAL", "alerta", "Pago parcial"),
        ("ANULADA", "peligro", "Anulada"),
        ("INACTIVO", "neutro", "Inactivo"),
        ("DESCONOCIDO", "neutro", "DESCONOCIDO"),
        ("<script>", "neutro", "&lt;script&gt;"),
    ],
)
def test_insignia_con_tono_y_texto(estado, tono, texto):
    html = plantillas.insignia({}, estado)
    assert isinstance(html, Markup)
    assert html == f'<span class="insignia {tono}">{texto}</span>'


def test_icono_y_iniciales():
    assert 'href="/static/img/iconos.svg#users"' in plantillas.icono("users")
    assert 'aria-hidden="true"' in plantillas.icono("users")
    assert plantillas.iniciales("María Fernanda Rodríguez") == "MF"
    assert plantillas.iniciales("  ") == "?"


def test_layout_con_sesion_marca_el_item_activo(buzon):
    c = autenticar(cliente(), "admin@lab-a.test", buzon)
    pagina = c.get("/configuracion/usuarios").text
    assert '<aside class="lateral">' in pagina
    assert 'href="/configuracion/usuarios" aria-current="page"' in pagina
    assert 'href="/panel" aria-current' not in pagina
    assert '<span class="avatar" aria-hidden="true">AA</span>' in pagina


def test_layout_publico_sin_menu():
    pagina = cliente().get("/ingresar").text
    assert 'class="publica"' in pagina and '<aside class="lateral">' not in pagina


def test_fuentes_e_iconos_se_sirven_con_cache():
    for ruta in ("/static/fonts/inter-latin.woff2", "/static/img/iconos.svg", "/static/css/styles.css"):
        respuesta = cliente().get(ruta)
        assert respuesta.status_code == 200, ruta
        assert respuesta.headers["cache-control"].startswith("public")


@pytest.mark.parametrize(
    ("valor", "esperado"), [("12.5000", "12.5"), ("100.0000", "100"), ("0.0010", "0.001"), ("1E+3", "1000"), (None, "")]
)
def test_numero_sin_ceros_sobrantes(valor, esperado):
    from decimal import Decimal

    assert plantillas.numero(Decimal(valor) if valor else None) == esperado
