"""Cabeceras de seguridad HTTP (spec infraestructura/0003, sección "Protección de la aplicación web")."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Todo se sirve desde el propio origen: sin CDN ni scripts en línea (htmx y Chart.js van en /static).
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

CABECERAS = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    # same-origin y no no-referrer: con no-referrer los navegadores envían "Origin: null" en los POST y la
    # verificación CSRF de origen no podría distinguir el propio sitio. Hacia otros sitios no se envía nada.
    "referrer-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}

HSTS = "max-age=63072000; includeSubDomains"

# Las respuestas pueden contener datos de salud: por defecto nada se guarda en caché.
# Solo los estáticos (CSS, JS, imágenes propias) se pueden cachear.
CACHE_DINAMICO = "no-store"
CACHE_ESTATICO = "public, max-age=3600"


class CabecerasSeguridad:
    """Middleware ASGI que agrega las cabeceras de seguridad a toda respuesta HTTP."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        es_estatico = scope["path"].startswith("/static/")
        es_https = scope.get("scheme") == "https"

        async def enviar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                cabeceras = [(k, v) for k, v in mensaje.get("headers", []) if k.lower() != b"cache-control"]
                for nombre, valor in CABECERAS.items():
                    cabeceras.append((nombre.encode(), valor.encode()))
                cache = CACHE_ESTATICO if es_estatico else CACHE_DINAMICO
                cabeceras.append((b"cache-control", cache.encode()))
                if es_https:
                    cabeceras.append((b"strict-transport-security", HSTS.encode()))
                mensaje["headers"] = cabeceras
            await send(mensaje)

        await self.app(scope, receive, enviar)
