"""Resolución del laboratorio por subdominio (spec infraestructura/0005, etapa 1)."""

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from app.core import tenancy
from app.core.tenancy import extraer_subdominio
from app.main import app

DOMINIO = "lablinea.localhost"


def cliente(subdominio: str | None = None, esquema: str = "http") -> TestClient:
    host = f"{subdominio}.{DOMINIO}" if subdominio else DOMINIO
    return TestClient(app, base_url=f"{esquema}://{host}")


# --- extraer_subdominio (sin base de datos) ---


@pytest.mark.parametrize(
    ("host", "esperado"),
    [
        ("lab-a.lablinea.localhost", "lab-a"),
        ("LAB-A.LabLinea.Localhost", "lab-a"),
        ("lab-a.lablinea.localhost:8443", "lab-a"),
        ("lablinea.localhost", ""),
        ("lablinea.localhost:8443", ""),
        ("admin.lablinea.localhost", "admin"),
        ("x.lab-a.lablinea.localhost", None),  # dos niveles
        ("-lab.lablinea.localhost", None),
        ("lab-.lablinea.localhost", None),
        ("lab_a.lablinea.localhost", None),  # guion bajo no es válido en DNS
        ("lab-a'--.lablinea.localhost", None),
        ("lab-a%27.lablinea.localhost", None),
        (("a" * 64) + ".lablinea.localhost", None),  # etiqueta DNS de más de 63
        ("lablinea.localhost.atacante.example", None),
        ("atacantelablinea.localhost", None),
        (".lablinea.localhost", None),
        ("", None),
    ],
)
def test_extraer_subdominio(host, esperado):
    assert extraer_subdominio(host, DOMINIO) == esperado


@given(st.text(max_size=80))
def test_extraer_subdominio_nunca_devuelve_etiquetas_invalidas(etiqueta):
    resultado = extraer_subdominio(f"{etiqueta}.{DOMINIO}", DOMINIO)
    if resultado:
        assert "." not in resultado
        assert len(resultado) <= 63
        assert resultado == resultado.lower()
        assert all(c.isascii() and (c.isalnum() or c == "-") for c in resultado)


# --- Middleware contra la base de prueba ---


def test_cada_subdominio_ve_su_laboratorio():
    pagina_a = cliente("lab-a").get("/").text
    pagina_b = cliente("lab-b").get("/").text
    assert "Laboratorio A Sintético" in pagina_a
    assert "Laboratorio B Sintético" not in pagina_a
    assert "Laboratorio B Sintético" in pagina_b
    assert "Laboratorio A Sintético" not in pagina_b


def test_mayusculas_en_el_host_resuelven_el_mismo_laboratorio():
    respuesta = TestClient(app, base_url="http://LAB-A.lablinea.localhost").get("/")
    assert "Laboratorio A Sintético" in respuesta.text


@pytest.mark.parametrize("subdominio", ["no-existe", "lab-canc", "x.lab-a", "lab_a"])
def test_subdominio_inexistente_cancelado_o_invalido_da_el_mismo_404(subdominio):
    respuesta = cliente(subdominio).get("/")
    assert respuesta.status_code == 404
    assert respuesta.text == "No encontrado"


def test_laboratorio_suspendido_se_resuelve():
    # La suspensión limita operaciones (etapa 5), pero el laboratorio debe poder consultar sus resultados.
    respuesta = cliente("lab-susp").get("/")
    assert respuesta.status_code == 200
    assert "Laboratorio Suspendido" in respuesta.text


def test_dominio_base_no_tiene_laboratorio():
    assert cliente(None).get("/").status_code == 404


def test_inicio_del_admin_hub_lleva_al_panel():
    respuesta = cliente("admin").get("/", follow_redirects=False)
    assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/panel")


@pytest.mark.parametrize(
    "intento",
    [
        {"params": {"tenant": "lab_b", "tenant_id": "lab_b", "laboratorio": "lab-b"}},
        {"headers": {"x-tenant": "lab_b", "x-tenant-id": "lab_b", "x-forwarded-host": "lab-b.lablinea.localhost"}},
        {"cookies": {"tenant": "lab_b", "tenant_id": "lab_b"}},
    ],
)
def test_la_peticion_no_puede_cambiar_el_laboratorio(intento):
    c = cliente("lab-a")
    for nombre, valor in intento.get("cookies", {}).items():
        c.cookies.set(nombre, valor)
    respuesta = c.get("/", params=intento.get("params"), headers=intento.get("headers"))
    assert "Laboratorio A Sintético" in respuesta.text
    assert "Laboratorio B Sintético" not in respuesta.text


def test_las_cabeceras_de_seguridad_cubren_el_404_de_tenancy():
    respuesta = cliente("no-existe").get("/")
    assert respuesta.headers["x-frame-options"] == "DENY"
    assert respuesta.headers["cache-control"] == "no-store"


def test_estaticos_y_health_no_consultan_la_base(monkeypatch):
    async def falla(_):
        raise AssertionError("no debería consultar la base")

    monkeypatch.setattr(tenancy, "buscar_laboratorio", falla)
    assert cliente("lab-a").get("/health").status_code == 200
    assert cliente("lab-a").get("/static/css/styles.css").status_code == 200


# --- La función de resolución en la base ---


pytestmark_anyio = pytest.mark.anyio


@pytestmark_anyio
async def test_buscar_laboratorio_con_entradas_maliciosas_no_encuentra_nada(engine_app):
    for intento in ["lab-a' OR '1'='1", "lab-a; SELECT 1", "%", "_", "lab-%", "LAB-A' --"]:
        assert await tenancy.buscar_laboratorio(intento) is None


@pytestmark_anyio
async def test_buscar_laboratorio_devuelve_solo_lo_necesario(engine_app):
    laboratorio = await tenancy.buscar_laboratorio("lab-a")
    assert laboratorio.tenant_id == "lab_a"
    assert laboratorio.zona_horaria == "America/Bogota"
    assert laboratorio.idioma == "es-CO"
    assert laboratorio.moneda == "COP"
    assert not hasattr(laboratorio, "identificador_fiscal")
