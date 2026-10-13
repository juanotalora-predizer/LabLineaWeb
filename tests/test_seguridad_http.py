"""Cabeceras de seguridad y superficie expuesta (spec infraestructura/0003)."""

import importlib

import pytest
from fastapi.testclient import TestClient

import app.main
from app.core.config import get_settings
from app.core.seguridad import CABECERAS, CACHE_DINAMICO, CACHE_ESTATICO, HSTS

cliente = TestClient(app.main.app, base_url="http://lab-a.lablinea.localhost")
cliente_https = TestClient(app.main.app, base_url="https://lab-a.lablinea.localhost")

RUTAS = ["/", "/health", "/no-existe", "/static/css/styles.css"]


@pytest.mark.parametrize("ruta", RUTAS)
def test_cabeceras_de_seguridad_en_toda_respuesta(ruta):
    respuesta = cliente.get(ruta)
    for nombre, valor in CABECERAS.items():
        assert respuesta.headers.get(nombre) == valor, nombre


@pytest.mark.parametrize("ruta", ["/", "/health", "/no-existe"])
def test_respuestas_dinamicas_no_se_guardan_en_cache(ruta):
    assert cliente.get(ruta).headers["cache-control"] == CACHE_DINAMICO


def test_estaticos_se_pueden_cachear():
    assert cliente.get("/static/css/styles.css").headers["cache-control"] == CACHE_ESTATICO


def test_hsts_solo_sobre_https():
    assert cliente_https.get("/health").headers.get("strict-transport-security") == HSTS
    assert "strict-transport-security" not in cliente.get("/health").headers


def test_csp_prohibe_scripts_externos_y_marcos():
    csp = CABECERAS["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp


@pytest.mark.parametrize("ruta", ["/docs", "/redoc", "/docs/oauth2-redirect"])
def test_sin_documentacion_interactiva(ruta):
    assert cliente.get(ruta).status_code == 404


def test_openapi_oculto_en_produccion(monkeypatch):
    monkeypatch.setenv("ENTORNO", "produccion")
    get_settings.cache_clear()
    try:
        modulo = importlib.reload(app.main)
        prod = TestClient(modulo.app, base_url="https://lab-a.lablinea.localhost")
        assert prod.get("/openapi.json").status_code == 404
    finally:
        monkeypatch.delenv("ENTORNO")
        get_settings.cache_clear()
        importlib.reload(app.main)


def test_rutas_no_permitidas_no_revelan_detalles():
    respuesta = cliente.post("/health")
    assert respuesta.status_code == 405
    assert "Traceback" not in respuesta.text


# --- Cabecera Host (hallazgo de la etapa 0: se reflejaba en las redirecciones) ---


@pytest.mark.parametrize(
    "host",
    [
        "atacante.example",
        "lablinea.localhost.atacante.example",
        "atacantelablinea.localhost",
        "127.0.0.1",
        "localhost",
        "",
    ],
)
def test_host_ajeno_es_rechazado(host):
    respuesta = cliente.get("/health", headers={"host": host})
    assert respuesta.status_code == 400


@pytest.mark.parametrize("host", ["lab-a.lablinea.localhost", "admin.lablinea.localhost", "lablinea.localhost:8443"])
def test_host_propio_es_aceptado(host):
    assert cliente.get("/health", headers={"host": host}).status_code == 200


def test_redireccion_no_refleja_host_ajeno():
    respuesta = cliente.get("/static", headers={"host": "atacante.example"}, follow_redirects=False)
    assert respuesta.status_code == 400
    assert "location" not in respuesta.headers


def test_redireccion_usa_el_host_propio():
    respuesta = cliente.get("/static", follow_redirects=False)
    assert respuesta.headers["location"].startswith("http://lab-a.lablinea.localhost/")


def test_x_forwarded_host_es_ignorado():
    respuesta = cliente.get("/static", headers={"x-forwarded-host": "atacante.example"}, follow_redirects=False)
    assert "atacante.example" not in respuesta.headers.get("location", "")
