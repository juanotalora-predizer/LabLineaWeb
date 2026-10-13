# Fuentes

Documentos originales de la descripción funcional del sistema, exportados de los cuadernos de NotebookLM. Son la materia prima de las specs en [funcional/](../funcional/): aquí no se toman decisiones, solo se guarda el material de origen.

## Organización

Una subcarpeta por cuaderno de NotebookLM, con un nombre corto en minúsculas y guiones:

```
fuentes/
├── nombre-cuaderno-1/
│   ├── documento-original.pdf
│   ├── otro-documento.docx
│   └── notas.md          ← notas escritas dentro de NotebookLM
└── nombre-cuaderno-2/
    └── ...
```

- **Fuentes del cuaderno:** el archivo original (PDF, Word, PowerPoint, Excel, texto). Los Google Docs se exportan desde Archivo › Descargar.
- **Notas de NotebookLM:** se copian a un archivo `notas.md` dentro de la carpeta del cuaderno.

## Reglas

- **Sin datos reales de pacientes.** Si un documento trae resultados, informes o datos de pacientes reales, se reemplazan por datos ficticios antes de copiarlo, o el documento no se agrega.
- Los archivos de esta carpeta no se modifican después de agregarse. Si cambia la descripción funcional, se agrega la nueva versión del documento.
- Cuando una fuente ya está incorporada a una spec, la spec la cita en su sección de contexto.

## Inventario y specs derivadas

Las 27 fuentes se incorporaron el 2026-10-12. Cuando una fuente y una spec difieren, **prevalece la spec**.

| Fuentes | Tema | Spec |
|---------|------|------|
| 01, 10, 19, 20, 23, 27, 09 | Laboratorios, licencias, facturación, pasarela, administración SaaS | [funcional/0005](../funcional/0005-plataforma-saas-suscripciones.md) |
| 02 | DDL original de Lablinea (Access) | [funcional/0007](../funcional/0007-alcance-mvp.md) (migración del catálogo) |
| 03, 04, 05, 06, 08 | DDL PostgreSQL, auditoría, inmutabilidad, RLS | [infraestructura/0007](../infraestructura/0007-base-de-datos.md) |
| 07, 21, 23 | Usuarios, roles, login con OTP | [infraestructura/0008](../infraestructura/0008-autenticacion-autorizacion.md) |
| 11, 17, 18 | POS, pre-cierre, convenios, paquetes, caja | [funcional/0002](../funcional/0002-pos-ordenes-caja.md) |
| 14, 15, 26 | Estaciones, muestras, tubos, impresión ZPL | [funcional/0003](../funcional/0003-muestras-impresion.md) |
| 16, 22, 25 | Rangos de referencia, validación, informe, entrega | [funcional/0004](../funcional/0004-resultados-validacion-entrega.md) |
| 12, 13, 24 | Inventarios, costeo, dashboard | [funcional/0006](../funcional/0006-gestion-inventarios-costos-dashboard.md) |
| 21 | Plan de desarrollo por fases | [funcional/0007](../funcional/0007-alcance-mvp.md) |

**Diferencias principales con las fuentes:** interfaz con Jinja2 + htmx en lugar de React; el correo solo avisa y enlaza al portal (no adjunta el PDF); el tenant nunca viaja en la petición; RLS reforzado; la impresión no sale del servidor hacia la IP de la impresora; los valores críticos no se retienen por cartera.
