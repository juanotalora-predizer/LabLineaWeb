"""E2E del catálogo en Chromium (etapa 6): importar la exportación de Lablinea y revisar un rango."""

import pytest

from scripts.lablinea_sintetico import generar
from tests.ayudas import totp_actual
from tests.conftest import CLAVE

pytestmark = pytest.mark.e2e


def _url(puerto: int, ruta: str) -> str:
    return f"https://lab-a.lablinea.localhost:{puerto}{ruta}"


def test_importar_catalogo_y_completar_un_rango(pagina, servidor, tmp_path):
    archivo = tmp_path / "lablinea.zip"
    archivo.write_bytes(generar())

    pagina.goto(_url(servidor, "/ingresar"))
    pagina.fill("#email", "admin@lab-a.test")
    pagina.fill("#clave", CLAVE)
    pagina.click("button[type=submit]")
    pagina.fill("#codigo", totp_actual("lab_a", "admin@lab-a.test"))
    pagina.click("form[action='/verificar'] button")

    # 1. Subir y revisar la vista previa.
    pagina.click("nav a[href='/catalogo']")
    pagina.click("text=Importar de Lablinea")
    pagina.set_input_files("#archivo", str(archivo))
    pagina.click("form[action='/catalogo/importar'] button[type=submit]")
    assert "/catalogo/importaciones/" in pagina.url
    contenido = pagina.content()
    assert "Vista previa de la importación" in contenido and "por revisar" in contenido

    # 2. Cargar.
    pagina.click("text=Cargar el catálogo")
    assert "quedó cargado" in pagina.content()

    # 3. El catálogo aparece, con su aviso de revisión.
    pagina.goto(_url(servidor, "/catalogo"))
    contenido = pagina.content()
    assert "Hemograma" in contenido and "por revisar" in contenido

    # 4. Revisar la hemoglobina: rango por sexo y edad, y marcar revisado el importado.
    pagina.click("text=Hemograma")
    pagina.click("text=Hemoglobina")
    pagina.select_option("#sexo", "F")
    pagina.fill("#edad_min", "18")
    pagina.fill("#minimo", "12")
    pagina.fill("#maximo", "16")
    pagina.fill("#critico_min", "7")
    pagina.fill("#texto_impreso", "12 - 16 g/dL")
    pagina.click("form[action$='/rangos'] button[type=submit]")
    assert "Femenino" in pagina.content()
    pagina.locator("form[action$='/revisado'] button").first.click()
    pagina.wait_for_load_state()
    assert "Por revisar" not in pagina.locator("table").first.inner_text()
