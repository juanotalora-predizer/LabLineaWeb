from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_index_renderiza_plantilla():
    response = client.get("/")
    assert response.status_code == 200
    assert "Laboratorio en Línea" in response.text


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_static_css():
    response = client.get("/static/css/styles.css")
    assert response.status_code == 200
