"""Textos externalizados, zona horaria por país y fechas en UTC (specs infraestructura/0004 y 0013)."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jinja2 import Environment
from sqlalchemy import text

from app.core import i18n
from app.core.db import sesion_tenant
from app.core.i18n import TextoNoEncontrado, catalogo, fecha_local, t
from app.core.plantillas import templates
from app.core.tenancy import Laboratorio
from tests.ayudas import cliente

RAIZ_APP = Path(__file__).resolve().parent.parent / "app"
PLANTILLAS = sorted((RAIZ_APP / "templates").rglob("*.html"))
LAB = Laboratorio("lab_x", "Laboratorio X", "COL", "ACTIVO", "America/Bogota", "es-CO", "COP")


# --- Catálogo ---


def test_texto_con_parametros():
    assert t("panel.saludo", "es-CO", nombre="Ana") == "Hola, Ana"
    assert t("menu.salir") == "Salir"  # idioma por defecto


@pytest.mark.parametrize("idioma", ["es-MX", "es", None, "pt-BR", "../../etc/passwd", "ES_co"])
def test_idioma_sin_catalogo_usa_la_cadena_hasta_el_idioma_por_defecto(idioma):
    assert t("menu.salir", idioma) == "Salir"


def test_codigo_de_idioma_invalido_no_lee_archivos():
    assert catalogo("../locales/es-CO") == {}
    assert catalogo("es-CO")


def test_clave_inexistente_es_un_error():
    with pytest.raises(TextoNoEncontrado):
        t("no.existe")


def test_cadena_de_idiomas():
    assert i18n.cadena_de_idiomas("es-MX") == ["es-MX", "es", "es-CO"]
    assert i18n.cadena_de_idiomas("es-CO") == ["es-CO", "es"]
    assert i18n.cadena_de_idiomas(None) == ["es-CO"]


def _claves_usadas() -> set[str]:
    patron = re.compile(r"""\bt\(\s*f?["']([a-z0-9_.]+)["']""")
    claves = set()
    for archivo in [*RAIZ_APP.rglob("*.py"), *PLANTILLAS]:
        claves.update(patron.findall(archivo.read_text()))
    return claves


def test_toda_clave_usada_existe_en_el_catalogo_por_defecto():
    usadas = _claves_usadas()
    assert len(usadas) > 30
    # Prefijos de claves compuestas en la plantilla (p. ej. "usuarios.tipo_" ~ tipo) y formatos de fecha.
    dinamicas = {c for c in usadas if c.endswith(("_", ".")) or c.startswith("formato.")}
    faltan = {c for c in usadas - dinamicas if c not in catalogo(i18n.IDIOMA_POR_DEFECTO)}
    assert faltan == set()


# --- Plantillas sin textos escritos directamente (guardián) ---

_ETIQUETA = re.compile(r"<[^>]*>")
_LETRA = "A-Za-zÁÉÍÓÚáéíóúñÑ"
_ATRIBUTO_VISIBLE = re.compile(rf"""\b(?:title|alt|placeholder|aria-label)\s*=\s*["']([^"']*[{_LETRA}][^"']*)["']""")
_EXPRESION = "§"


def _textos_literales(fuente: str) -> list[str]:
    """Texto visible escrito en la plantilla: lo que queda al quitar expresiones de Jinja y etiquetas HTML,
    más los atributos que el usuario ve (title, alt, placeholder, aria-label)."""
    partes = []
    for _, tipo, valor in Environment(autoescape=True).lex(fuente):
        if tipo == "data":
            partes.append(valor)
        elif tipo in ("variable_begin", "block_begin"):
            partes.append(_EXPRESION)
    enmascarada = "".join(partes)
    hallados = _ATRIBUTO_VISIBLE.findall(enmascarada)
    # Separadores y signos tipográficos (·, paréntesis) no son texto traducible.
    hallados += re.findall(rf"[{_LETRA}]{{2,}}", _ETIQUETA.sub(" ", enmascarada))
    return hallados


@pytest.mark.parametrize("plantilla", PLANTILLAS, ids=lambda p: str(p.relative_to(RAIZ_APP)))
def test_plantillas_sin_textos_escritos_directamente(plantilla):
    assert _textos_literales(plantilla.read_text()) == []


def test_el_guardian_detecta_textos_escritos():
    assert _textos_literales("<p>Hola</p>") == ["Hola"]
    assert _textos_literales('<img alt="Logo del lab">') == ["Logo del lab"]
    assert _textos_literales('<p>{{ t("x") }}</p><input placeholder="{{ t(\'y\') }}">') == []


# --- Fechas y zonas horarias ---


def test_fecha_local_convierte_desde_utc():
    instante = datetime(2026, 10, 13, 3, 30, tzinfo=UTC)
    assert fecha_local(instante, "America/Bogota") == "12/10/2026 22:30"
    assert fecha_local(instante, "America/Bogota", formato="fecha") == "12/10/2026"
    assert fecha_local(instante) == "13/10/2026 03:30"


def test_fecha_sin_zona_se_rechaza():
    with pytest.raises(ValueError):
        fecha_local(datetime(2026, 10, 13, 3, 30))  # noqa: DTZ001


def test_filtro_de_plantilla_usa_la_zona_del_laboratorio():
    plantilla = templates.env.from_string("{{ instante | fecha }} · {{ t('menu.panel') }} · {{ idioma() }}")
    instante = datetime(2026, 1, 1, 2, 0, tzinfo=UTC)
    assert plantilla.render(sitio=LAB, instante=instante) == "31/12/2025 21:00 · Panel · es-CO"
    assert plantilla.render(instante=instante) == "01/01/2026 02:00 · Panel · es-CO"  # sin laboratorio: UTC


@pytest.mark.anyio
async def test_sesion_de_base_de_datos_en_utc(engine_app):
    async with sesion_tenant("lab_a") as sesion:
        assert await sesion.scalar(text("SHOW timezone")) == "UTC"
        ahora = await sesion.scalar(text("SELECT now()"))
    assert ahora.utcoffset().total_seconds() == 0


def test_paginas_declaran_el_idioma_del_laboratorio():
    respuesta = cliente().get("/ingresar")
    assert '<html lang="es-CO">' in respuesta.text
    assert "Correo electrónico" in respuesta.text


def test_mensajes_fuera_del_laboratorio_salen_del_catalogo():
    assert cliente("no-existe").get("/").text == t("error.no_encontrado")
