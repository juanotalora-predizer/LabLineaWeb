"""E2E de la etapa 5 en Chromium: acceso de soporte autorizado y registro de un pago."""

import pytest
from sqlalchemy import text

from tests.ayudas import nuevo_laboratorio, totp_actual
from tests.conftest import CLAVE, correr, ejecutar_en_plataforma

pytestmark = pytest.mark.e2e

TECNICO = "tecnico@plataforma.test"
FINANCIERO = "financiero@plataforma.test"


def _url(puerto: int, sub: str, ruta: str = "/") -> str:
    return f"https://{sub}.lablinea.localhost:{puerto}{ruta}"


def _ingresar(pagina, puerto: int, sub: str, email: str, laboratorio: str) -> None:
    pagina.goto(_url(puerto, sub, "/ingresar"))
    pagina.fill("#email", email)
    pagina.fill("#clave", CLAVE)
    pagina.click("button[type=submit]")
    pagina.fill("#codigo", totp_actual(laboratorio, email))
    pagina.click("form[action='/verificar'] button")
    assert pagina.url.endswith("/panel"), pagina.url


def test_soporte_autorizado_de_punta_a_punta(navegador, servidor):
    contextos = [navegador.new_context(ignore_https_errors=True) for _ in range(2)]
    laboratorio, plataforma = (c.new_page() for c in contextos)
    try:
        _flujo_de_soporte(laboratorio, plataforma, servidor)
    finally:
        for contexto in contextos:
            contexto.close()


def _flujo_de_soporte(laboratorio, plataforma, servidor):

    # 1. El administrador de lab-a autoriza el soporte por 1 hora.
    _ingresar(laboratorio, servidor, "lab-a", "admin@lab-a.test", "lab_a")
    laboratorio.click("nav a[href='/configuracion/soporte']")
    laboratorio.fill("#horas", "1")
    laboratorio.fill("#motivo", "Caso E2E: revisar configuración")
    laboratorio.click("form[action='/configuracion/soporte'] button")
    assert "Caso E2E" in laboratorio.content()

    # 2. El técnico de la plataforma ve la autorización y entra.
    _ingresar(plataforma, servidor, "admin", TECNICO, "plataforma")
    plataforma.click("nav a[href='/soporte']")
    assert "Caso E2E" in plataforma.content()
    plataforma.click("text=Entrar como soporte")
    plataforma.click("text=Continuar al laboratorio")  # enlace al subdominio del laboratorio
    assert "/soporte/entrar/" in plataforma.url and "lab-a.lablinea.localhost" in plataforma.url
    plataforma.click("form button[type=submit]")
    assert plataforma.url.endswith("/panel")
    assert "Sesión de soporte de la plataforma" in plataforma.content()

    # 3. El laboratorio revoca: la sesión de soporte termina.
    laboratorio.reload()
    with laboratorio.expect_navigation():
        # Todas las autorizaciones vigentes de lab-a (otras pruebas pudieron dejar alguna).
        laboratorio.locator("form[action$='/revocar'] button").first.click()
    assert "Revocado" in laboratorio.content()
    plataforma.goto(_url(servidor, "lab-a", "/panel"))
    assert plataforma.url.endswith("/ingresar")


def test_registro_de_un_pago_en_el_admin_hub(pagina, servidor):
    lab = nuevo_laboratorio("MENSUAL")

    async def factura_pendiente(sesion):
        from app.admin import facturacion

        await sesion.execute(
            text(
                "INSERT INTO plataforma.precios (pais, plan_id, tipo_licencia, moneda, valor, vigente_desde)"
                " SELECT 'COL', id, 'MENSUAL', 'COP', 100000, DATE '2026-01-01' FROM plataforma.planes"
                " WHERE codigo = 'COMPLETO' ON CONFLICT DO NOTHING"
            )
        )
        return await facturacion.generar_factura(sesion, lab["uuid"], "MENSUAL")

    factura = correr(ejecutar_en_plataforma(factura_pendiente))
    _ingresar(pagina, servidor, "admin", FINANCIERO, "plataforma")
    pagina.goto(_url(servidor, "admin", f"/facturas/{factura}"))
    assert "COP 119.000,00" in pagina.content()
    pagina.fill("#valor", "119000")
    pagina.fill("#referencia", "TRX-E2E")
    pagina.click("form[action$='/pagos'] button[type=submit]")
    contenido = pagina.content()
    assert "PAGADA" in contenido and "TRX-E2E" in contenido
