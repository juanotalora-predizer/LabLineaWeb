# 0001. Stack base: FastAPI + Jinja2

- **Estado:** Aceptada
- **Fecha:** 2026-10-12
- **Responsable:** Juan Otálora

## Contexto

Se necesita definir la base técnica para construir LabLineaWeb, una aplicación web para consultar resultados de laboratorio en línea.

## Decisión

- **Backend:** FastAPI (Python 3.14), servido con Uvicorn.
- **Vistas:** renderizado en servidor con plantillas Jinja2 (`app/templates/`), heredando de `base.html`.
- **Estáticos:** servidos por FastAPI desde `app/static/` en la ruta `/static`.
- **Dependencias:** `venv` + `requirements.txt` (producción) y `requirements-dev.txt` (desarrollo y pruebas).
- **Pruebas:** pytest con `TestClient` de FastAPI.

Estructura:

```
app/
├── main.py          # aplicación FastAPI y rutas
├── templates/       # plantillas Jinja2
└── static/          # CSS, JS, imágenes
tests/               # pruebas con pytest
```

## Alternativas consideradas

- **FastAPI + frontend SPA (React/Vue):** más interactividad, pero exige dos proyectos, build de frontend y una API separada. Excesivo para la etapa actual.
- **Django:** trae admin, ORM y autenticación incluidos, pero es más pesado y con más convenciones de las que se necesitan hoy.
- **Flask + Jinja2:** similar en simplicidad, pero sin validación con tipos, async nativo ni documentación OpenAPI automática.

## Consecuencias

- Una sola aplicación y un solo despliegue; las páginas se renderizan en el servidor.
- Si más adelante se necesita interactividad en el cliente, se puede agregar htmx o JS puntual sin cambiar el stack.
- **Ratificada el 2026-10-12** frente a las fuentes de NotebookLM, que asumían React + Vite + Tailwind: se mantiene Jinja2 y se adoptan **htmx** para la interactividad (colas de trabajo, POS, validación) y **Chart.js** para gráficas. Ambas se sirven como archivos estáticos propios, sin CDN, para cumplir la política de seguridad de contenido.
- Base de datos y acceso a datos: ver [0007](0007-base-de-datos.md).
- Los endpoints JSON conviven con las vistas HTML, lo que deja abierta una API para integraciones futuras.
- Base de datos y autenticación definidas en [0007](0007-base-de-datos.md) y [0008](0008-autenticacion-autorizacion.md). Pendiente: hosting.
