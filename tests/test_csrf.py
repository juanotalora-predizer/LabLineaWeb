"""Protección CSRF (spec infraestructura/0003 y 0008)."""

import pytest
from fastapi.routing import APIRoute

from app.auth.web import verificar_csrf
from app.main import app
from tests.ayudas import autenticar, cliente, csrf
from tests.conftest import CLAVE

METODOS_QUE_CAMBIAN_ESTADO = {"POST", "PUT", "PATCH", "DELETE"}


def _dependencias(dependant):
    for d in dependant.dependencies:
        yield d.call
        yield from _dependencias(d)


def test_toda_ruta_que_cambia_estado_exige_csrf():
    """Guardián: una ruta POST/PUT/PATCH/DELETE nueva sin verificar_csrf hace fallar la suite."""
    sin_csrf = [
        f"{sorted(r.methods)} {r.path}"
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.methods & METODOS_QUE_CAMBIAN_ESTADO
        and verificar_csrf not in set(_dependencias(r.dependant))
    ]
    assert sin_csrf == []


def _datos(c):
    return {"email": "paciente@lab-a.test", "clave": CLAVE}


@pytest.mark.parametrize(
    ("descripcion", "preparar"),
    [
        ("sin token", lambda c: ({}, {})),
        ("token inventado", lambda c: ({"csrf": "x" * 43}, {})),
        ("token de otra cookie", lambda c: ({"csrf": csrf(cliente())}, {})),
        ("origen ajeno", lambda c: ({"csrf": csrf(c)}, {"origin": "https://atacante.example"})),
        ("origen de otro laboratorio", lambda c: ({"csrf": csrf(c)}, {"origin": "https://lab-b.lablinea.localhost"})),
        ("sec-fetch-site cross-site", lambda c: ({"csrf": csrf(c)}, {"sec-fetch-site": "cross-site"})),
        ("sec-fetch-site same-site", lambda c: ({"csrf": csrf(c)}, {"sec-fetch-site": "same-site"})),
    ],
)
def test_ingreso_rechaza_peticiones_falsificadas(descripcion, preparar, buzon):
    c = cliente()
    csrf(c)  # el cliente tiene su cookie CSRF
    extra, cabeceras = preparar(c)
    respuesta = c.post("/ingresar", data={**_datos(c), **extra}, headers=cabeceras)
    assert respuesta.status_code == 403, descripcion
    assert buzon == []


def test_ingreso_acepta_mismo_origen():
    c = cliente()
    token = csrf(c)
    respuesta = c.post(
        "/ingresar",
        data={**_datos(c), "csrf": token},
        headers={"origin": "https://lab-a.lablinea.localhost", "sec-fetch-site": "same-origin"},
    )
    assert respuesta.status_code == 303


def test_salir_sin_csrf_no_cierra_la_sesion(buzon):
    c = autenticar(cliente(), "paciente@lab-a.test", buzon)
    assert c.post("/salir", data={}).status_code == 403
    assert c.get("/panel").status_code == 200


def test_cookie_csrf_con_atributos_seguros():
    respuesta = cliente().get("/ingresar")
    cookie = next(v for v in respuesta.headers.get_list("set-cookie") if v.startswith("__Host-csrf=")).lower()
    for atributo in ("secure", "httponly", "samesite=strict", "path=/"):
        assert atributo in cookie
    assert "domain=" not in cookie


def test_token_csrf_cambia_al_ingresar(buzon):
    c = cliente()
    antes = csrf(c)
    autenticar(c, "paciente@lab-a.test", buzon)
    assert csrf(c, "/panel") != antes
