from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import get_settings
from app.core.seguridad import CabecerasSeguridad
from app.core.tenancy import Laboratorio, ResolverLaboratorio, laboratorio_actual

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
# El último middleware agregado es el primero en ejecutarse:
#   1. CabecerasSeguridad: envuelve todo, también los 400 y 404 de los demás.
#   2. TrustedHostMiddleware: solo el dominio propio; un Host ajeno no llega a la aplicación.
#   3. ResolverLaboratorio: el laboratorio sale del subdominio, nunca de la petición.
app.add_middleware(ResolverLaboratorio)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[settings.dominio_base, f"*.{settings.dominio_base}"],
)
app.add_middleware(CabecerasSeguridad)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, laboratorio: Annotated[Laboratorio, Depends(laboratorio_actual)]):
    return templates.TemplateResponse(
        request, "index.html", {"titulo": "Laboratorio en Línea", "laboratorio": laboratorio}
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
