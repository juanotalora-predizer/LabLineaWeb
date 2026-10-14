"""Entorno único de plantillas Jinja2: textos externalizados, fechas locales (app/core/i18n.py) y los
componentes del sistema de diseño (spec funcional/0008): íconos, insignias de estado e iniciales."""

from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup, escape

from app.core.i18n import TextoNoEncontrado, configurar_plantillas, t

SPRITE = "/static/img/iconos.svg"

# Tono de la insignia según el código de estado (spec funcional/0008, sección 2).
TONOS = {
    "exito": {"ACTIVO", "ACTIVA", "PAGADA", "COMPLETADA", "VIGENTE", "VALIDADO", "EN_ATENCION"},
    "alerta": {"PENDIENTE", "INVITACION_PENDIENTE", "PAGADA_PARCIAL", "EN_OBSERVACION", "EN_CURSO", "POR_VENCER"},
    "peligro": {"VENCIDA", "SUSPENDIDA", "SUSPENDIDO", "ANULADA", "FALLIDA", "CRITICO", "SIN_TRIAGE", "REVOCADO"},
    "info": {"EN_PROCESO"},
}
_TONO_POR_ESTADO = {estado: tono for tono, estados in TONOS.items() for estado in estados}


def icono(nombre: str) -> Markup:
    """Ícono del sprite propio. Decorativo: el texto que lo acompaña es el que se lee."""
    return Markup('<svg class="icono" aria-hidden="true" focusable="false"><use href="{}#{}"></use></svg>').format(
        SPRITE, nombre
    )


def tono(estado: str) -> str:
    return _TONO_POR_ESTADO.get(str(estado).upper(), "neutro")


@pass_context
def insignia(contexto, estado: str) -> Markup:
    """Insignia de estado: color según el tono y siempre con texto (el color nunca es la única señal)."""
    sitio = contexto.get("sitio")
    try:
        texto = t(f"estados.{str(estado).lower()}", getattr(sitio, "idioma", None))
    except TextoNoEncontrado:
        texto = str(estado)  # códigos de datos aún sin texto: se muestran tal cual, escapados
    return Markup('<span class="insignia {}">{}</span>').format(tono(estado), escape(texto))


def iniciales(nombre: str) -> str:
    partes = [p for p in str(nombre).split() if p[:1].isalpha()]
    return "".join(p[0] for p in partes[:2]).upper() or "?"


templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
configurar_plantillas(templates.env)
templates.env.globals["icono"] = icono
templates.env.filters["insignia"] = insignia
templates.env.filters["iniciales"] = iniciales
