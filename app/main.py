from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import get_settings
from app.core.seguridad import CabecerasSeguridad

BASE_DIR = Path(__file__).resolve().parent
settings = get_settings()

# Sin documentación interactiva: Swagger UI carga scripts de un CDN externo (lo prohíbe la CSP)
# y no debe existir en producción. El esquema OpenAPI solo se expone fuera de producción.
app = FastAPI(
    title="LabLineaWeb",
    docs_url=None,
    redoc_url=None,
    openapi_url=None if settings.entorno == "produccion" else "/openapi.json",
)
app.add_middleware(CabecerasSeguridad)
# Solo se atienden peticiones para el dominio propio: evita que una cabecera Host falsificada
# termine en redirecciones, enlaces de correos o cachés. Se agrega al final para ejecutarse primero.
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[settings.dominio_base, f"*.{settings.dominio_base}"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"titulo": "Laboratorio en Línea"})


@app.get("/health")
async def health():
    return {"status": "ok"}
