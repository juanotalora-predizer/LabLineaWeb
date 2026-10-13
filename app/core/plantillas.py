"""Entorno único de plantillas Jinja2, con textos externalizados y fechas locales (app/core/i18n.py)."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.core.i18n import configurar_plantillas

templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
configurar_plantillas(templates.env)
