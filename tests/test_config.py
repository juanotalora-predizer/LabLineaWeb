"""Configuración: falla sin secretos y nunca los expone (spec infraestructura/0003, "Secretos")."""

import logging

import pytest
from pydantic import ValidationError

from app.core import db
from app.core.config import Settings, get_settings

pytestmark = pytest.mark.anyio


def test_sin_contrasenas_no_arranca(monkeypatch):
    monkeypatch.delenv("DB_OWNER_PASSWORD", raising=False)
    monkeypatch.delenv("DB_APP_PASSWORD", raising=False)
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)
    faltantes = {e["loc"][0] for e in error.value.errors()}
    assert faltantes == {"db_owner_password", "db_app_password"}


def test_entorno_invalido_no_arranca(monkeypatch):
    monkeypatch.setenv("ENTORNO", "cualquiera")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_owner_password="x", db_app_password="y")


def test_contrasenas_no_aparecen_en_repr_ni_en_logs(caplog):
    # Contraseñas ficticias de la prueba, no secretos reales.
    clave_dueno = "clave-dueno-123"  # gitleaks:allow
    clave_app = "clave-app-456"  # gitleaks:allow
    settings = Settings(_env_file=None, db_owner_password=clave_dueno, db_app_password=clave_app)
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("prueba").info("settings=%s urls=%s %s", settings, settings.url_app(), settings.url_owner())
    texto = repr(settings) + str(settings) + caplog.text
    assert clave_dueno not in texto
    assert clave_app not in texto


def test_urls_usan_el_rol_correcto():
    settings = Settings(_env_file=None, db_owner_password="a", db_app_password="b")
    assert settings.url_app().username == "lablinea_app"
    assert settings.url_owner().username == "lablinea_owner"
    assert settings.url_app("otra_base").database == "otra_base"
    assert settings.url_app().database == settings.db_name


async def test_engine_por_defecto_usa_el_rol_de_la_aplicacion():
    await db.cerrar()
    engine = db.engine_app()
    try:
        assert engine.url.username == get_settings().db_app_user
        assert db.engine_app() is engine  # se reutiliza
    finally:
        await db.cerrar()
    await db.cerrar()  # cerrar dos veces no falla
