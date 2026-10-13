from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.auth.rutas import router as rutas_auth
from app.auth.web import InscripcionTotpPendiente, NoAutenticado, SegundoFactorPendiente
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
app.include_router(rutas_auth)


@app.exception_handler(NoAutenticado)
async def _no_autenticado(request: Request, _exc: NoAutenticado):
    return RedirectResponse("/ingresar", status_code=303)


@app.exception_handler(SegundoFactorPendiente)
async def _segundo_factor(request: Request, _exc: SegundoFactorPendiente):
    return RedirectResponse("/verificar", status_code=303)


@app.exception_handler(InscripcionTotpPendiente)
async def _inscripcion_totp(request: Request, _exc: InscripcionTotpPendiente):
    return RedirectResponse("/seguridad/totp", status_code=303)


@app.exception_handler(RequestValidationError)
async def _validacion(request: Request, _exc: RequestValidationError):
    # El manejador por defecto devuelve el valor recibido (podría ser una contraseña): respuesta genérica.
    return PlainTextResponse("Solicitud inválida", status_code=400)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, laboratorio: Annotated[Laboratorio, Depends(laboratorio_actual)]):
    return templates.TemplateResponse(
        request, "index.html", {"titulo": "Laboratorio en Línea", "laboratorio": laboratorio}
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
