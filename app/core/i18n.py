"""Textos externalizados y fechas locales (specs infraestructura/0004 y 0013).

- Los textos viven en app/locales/<idioma>.toml (p. ej. es-CO.toml), nunca en el HTML ni en el
  código. Se buscan en el idioma del laboratorio, luego en el idioma base ("es") y por último en
  el idioma por defecto. Una clave inexistente es un error: las pruebas lo detectan.
- Las fechas se guardan en UTC y solo se convierten a la zona del laboratorio al mostrarlas.
"""

import re
import tomllib
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, pass_context

CARPETA = Path(__file__).resolve().parent.parent / "locales"
IDIOMA_POR_DEFECTO = "es-CO"
ZONA_POR_DEFECTO = "UTC"
_IDIOMA = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")


class TextoNoEncontrado(KeyError):
    """La clave no existe en ningún catálogo de la cadena de idiomas."""


def _aplanar(datos: dict, prefijo: str = "") -> dict[str, str]:
    plano: dict[str, str] = {}
    for clave, valor in datos.items():
        ruta = f"{prefijo}{clave}"
        if isinstance(valor, dict):
            plano.update(_aplanar(valor, ruta + "."))
        else:
            plano[ruta] = str(valor)
    return plano


@lru_cache
def catalogo(idioma: str) -> dict[str, str]:
    """Textos de un idioma; vacío si no existe el archivo (o el código de idioma no es válido)."""
    if not _IDIOMA.match(idioma):
        return {}
    archivo = CARPETA / f"{idioma}.toml"
    if not archivo.is_file():
        return {}
    with archivo.open("rb") as f:
        return _aplanar(tomllib.load(f))


def cadena_de_idiomas(idioma: str | None) -> list[str]:
    cadena = []
    for candidato in (idioma, (idioma or "").split("-")[0], IDIOMA_POR_DEFECTO):
        if candidato and candidato not in cadena:
            cadena.append(candidato)
    return cadena


def t(clave: str, idioma: str | None = None, **parametros: object) -> str:
    """Texto de `clave` en `idioma`, con los marcadores {nombre} reemplazados por los parámetros."""
    for candidato in cadena_de_idiomas(idioma):
        texto = catalogo(candidato).get(clave)
        if texto is not None:
            return texto.format(**parametros) if parametros else texto
    raise TextoNoEncontrado(clave)


def fecha_local(
    valor: datetime, zona: str = ZONA_POR_DEFECTO, idioma: str | None = None, formato: str = "fecha_hora"
) -> str:
    """Muestra un instante (con zona, normalmente UTC desde la base) en la zona local."""
    if valor.tzinfo is None:
        raise ValueError("fecha sin zona horaria: en la base todo instante es TIMESTAMPTZ")
    return valor.astimezone(ZoneInfo(zona)).strftime(t(f"formato.{formato}", idioma))


def dinero(valor: Decimal, moneda: str, idioma: str | None = None, decimales: int = 2) -> str:
    """Valor monetario con los separadores del idioma (p. ej. "COP 1.234.567,50"). Nunca usa float."""
    cuanto = Decimal(10) ** -decimales
    texto = f"{Decimal(valor).quantize(cuanto, rounding=ROUND_HALF_UP):,.{decimales}f}"
    miles, decimal = t("formato.miles", idioma), t("formato.decimal", idioma)
    texto = texto.replace(",", "\0").replace(".", decimal).replace("\0", miles)
    return f"{moneda} {texto}"


# --- Plantillas ---


def _sitio(contexto) -> object | None:
    """Laboratorio o Admin Hub de la página: de él salen el idioma y la zona horaria."""
    return contexto.get("sitio")


@pass_context
def _t_plantilla(contexto, clave: str, **parametros: object) -> str:
    sitio = _sitio(contexto)
    return t(clave, getattr(sitio, "idioma", None), **parametros)


@pass_context
def _idioma_plantilla(contexto) -> str:
    return getattr(_sitio(contexto), "idioma", None) or IDIOMA_POR_DEFECTO


@pass_context
def _dinero_plantilla(contexto, valor: Decimal, moneda: str) -> str:
    return dinero(valor, moneda, getattr(_sitio(contexto), "idioma", None))


@pass_context
def _fecha_plantilla(contexto, valor: datetime, formato: str = "fecha_hora") -> str:
    sitio = _sitio(contexto)
    zona = getattr(sitio, "zona_horaria", None) or ZONA_POR_DEFECTO
    return fecha_local(valor, zona, getattr(sitio, "idioma", None), formato)


def configurar_plantillas(entorno: Environment) -> None:
    """Expone t(), idioma() y el filtro |fecha a las plantillas. El idioma y la zona salen del sitio."""
    entorno.globals["t"] = _t_plantilla
    entorno.globals["idioma"] = _idioma_plantilla
    entorno.filters["fecha"] = _fecha_plantilla
    entorno.filters["dinero"] = _dinero_plantilla
