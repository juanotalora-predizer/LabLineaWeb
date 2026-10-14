"""Catálogo de exámenes del laboratorio (spec funcional/0009): consulta, edición, maestros, revisión,
importación desde Lablinea y exportación a CSV.

Permisos del módulo `configuracion`: consultar, crear, modificar y eliminar. Exámenes, parámetros y
rangos se identifican por UUID; los maestros (secciones, unidades, tubos…) por su código, siempre dentro
del laboratorio de la sesión (RLS).
"""

import csv
import hashlib
import io
import json
import re
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth.web import (
    Csrf,
    LaboratorioActual,
    SesionActiva,
    TextoSeguro,
    ip_cliente,
    redirigir,
    render,
    requiere_permiso,
)
from app.catalogo import importador, rangos
from app.core.auditoria import registrar_acceso
from app.core.db import sesion_tenant
from app.core.i18n import t

router = APIRouter(default_response_class=HTMLResponse)
Consultar = Annotated[SesionActiva, Depends(requiere_permiso("configuracion", "consultar"))]
Crear = Annotated[SesionActiva, Depends(requiere_permiso("configuracion", "crear"))]
Modificar = Annotated[SesionActiva, Depends(requiere_permiso("configuracion", "modificar"))]
Eliminar = Annotated[SesionActiva, Depends(requiere_permiso("configuracion", "eliminar"))]

TIPOS_PARAMETRO = ("NUMERICO", "TEXTO", "LISTA", "TITULO")
SEXOS = ("T", "F", "M")
UNIDADES_EDAD = {"anios": 365, "meses": 30, "dias": 1}
LOINC = re.compile(r"^[0-9]{1,7}-[0-9]$")
LIMITE_NUMERO = Decimal("1e10")
MAX_ARCHIVO = importador.MAX_ZIP


def _sesion(request: Request, laboratorio, activa: SesionActiva):
    return sesion_tenant(laboratorio.tenant_id, usuario_id=activa.usuario.uuid, ip=ip_cliente(request))


def _decimal(texto: str) -> Decimal | None:
    """Número opcional del formulario (punto o coma decimal). ValueError si no es válido."""
    valor = importador.leer_decimal(texto)
    if valor is not None and abs(valor) >= LIMITE_NUMERO:
        raise ValueError(texto)
    return valor


async def _opciones(sesion) -> dict:
    async def filas(sql):
        return (await sesion.execute(text(sql))).mappings().all()

    return {
        "secciones": await filas(
            "SELECT uuid::text AS uuid, codigo, nombre FROM lab.secciones WHERE activa ORDER BY orden, nombre"
        ),
        "unidades": await filas("SELECT codigo, nombre, ucum FROM lab.unidades ORDER BY nombre"),
        "tipos_muestra": await filas("SELECT codigo, nombre FROM lab.tipos_muestra ORDER BY nombre"),
        "tipos_tubo": await filas("SELECT codigo, nombre, aditivo, capacidad_ml FROM lab.tipos_tubo ORDER BY nombre"),
        "tecnicas": await filas("SELECT nombre FROM lab.tecnicas ORDER BY nombre"),
        "tarifas": await filas("SELECT codigo, nombre, moneda FROM lab.tarifas WHERE activa ORDER BY nombre"),
        "tipos_codigo": await filas("SELECT codigo, nombre FROM lab.tipos_codigo_alterno ORDER BY nombre"),
    }


async def _terminologia(sesion, laboratorio) -> str:
    """Nombre del sistema de códigos de procedimientos del país (CUPS en Colombia)."""
    nombre = await sesion.scalar(
        text('SELECT terminologia_procedimientos FROM "global".paises WHERE codigo = :p'), {"p": laboratorio.pais}
    )
    return nombre or t("catalogo.codigo_nacional", laboratorio.idioma)


# --- Lista de exámenes ---

_SQL_EXAMENES = text(
    "SELECT e.uuid::text AS uuid, e.codigo, e.nombre, e.codigo_nacional, e.activo, s.nombre AS seccion,"
    " (SELECT count(*) FROM lab.parametros p WHERE p.examen_id = e.id AND p.activo) AS parametros"
    " FROM lab.examenes e JOIN lab.secciones s ON s.id = e.seccion_id"
    " WHERE (CAST(:q AS text) IS NULL OR e.nombre ILIKE :patron OR e.codigo ILIKE :patron"
    "        OR e.codigo_nacional ILIKE :patron)"
    "   AND (CAST(:seccion AS text) IS NULL OR s.uuid::text = :seccion)"
    " ORDER BY s.orden, s.nombre, e.nombre LIMIT 500"
)


@router.get("/catalogo")
async def catalogo(
    request: Request, laboratorio: LaboratorioActual, activa: Consultar, q: TextoSeguro = "", seccion: str = ""
):
    busqueda = q.strip()[:60] or None
    filtro = seccion if re.fullmatch(r"[0-9a-f-]{36}", seccion) else None
    patron = "%" + re.sub(r"([%_\\])", r"\\\1", busqueda or "") + "%"
    async with _sesion(request, laboratorio, activa) as sesion:
        examenes = (
            (await sesion.execute(_SQL_EXAMENES, {"q": busqueda, "patron": patron, "seccion": filtro})).mappings().all()
        )
        opciones = await _opciones(sesion)
        revision = await sesion.scalar(
            text(
                "SELECT (SELECT count(*) FROM lab.rangos_referencia WHERE requiere_revision)"
                " + (SELECT count(*) FROM lab.requisitos_muestra WHERE requiere_revision)"
            )
        )
        terminologia = await _terminologia(sesion, laboratorio)
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "examenes": examenes,
        "q": busqueda or "",
        "seccion": filtro,
        "revision": revision,
        "terminologia": terminologia,
        **opciones,
    }
    return render(request, "catalogo/examenes.html", contexto)


# --- Crear y editar exámenes ---


def _validar_examen(datos: dict, idioma: str) -> list[str]:
    errores = []
    if not 1 <= len(datos["codigo"]) <= 20:
        errores.append(t("catalogo.error_codigo", idioma))
    if not 2 <= len(datos["nombre"]) <= 120:
        errores.append(t("catalogo.error_nombre", idioma))
    if len(datos["codigo_nacional"]) > 20 or len(datos["dias"]) > 30:
        errores.append(t("catalogo.error_largo", idioma))
    if datos["loinc"] and not LOINC.match(datos["loinc"]):
        errores.append(t("catalogo.error_loinc", idioma))
    return errores


_SQL_GUARDAR_EXAMEN = {
    "nuevo": (
        "INSERT INTO lab.examenes (codigo, nombre, seccion_id, tecnica_id, codigo_nacional, loinc,"
        " requiere_autorizacion, dias_procesamiento)"
        " SELECT :codigo, :nombre, s.id, (SELECT id FROM lab.tecnicas WHERE nombre = :tecnica),"
        " NULLIF(:codigo_nacional, ''), NULLIF(:loinc, ''), :autorizacion, NULLIF(:dias, '')"
        " FROM lab.secciones s WHERE s.codigo = :seccion RETURNING uuid::text"
    ),
    "editar": (
        "UPDATE lab.examenes e SET codigo = :codigo, nombre = :nombre, seccion_id = s.id,"
        " tecnica_id = (SELECT id FROM lab.tecnicas WHERE nombre = :tecnica),"
        " codigo_nacional = NULLIF(:codigo_nacional, ''), loinc = NULLIF(:loinc, ''),"
        " requiere_autorizacion = :autorizacion, dias_procesamiento = NULLIF(:dias, '')"
        " FROM lab.secciones s WHERE s.codigo = :seccion AND e.uuid = CAST(:uuid AS uuid) RETURNING e.uuid::text"
    ),
}


async def _formulario_examen(request, laboratorio, activa, *, examen=None, errores=(), estado=200):
    async with _sesion(request, laboratorio, activa) as sesion:
        opciones = await _opciones(sesion)
        terminologia = await _terminologia(sesion, laboratorio)
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "examen": examen or {},
        "errores": list(errores),
        "terminologia": terminologia,
        **opciones,
    }
    return render(request, "catalogo/examen_nuevo.html", contexto, estado)


@router.get("/catalogo/examenes/nuevo")
async def examen_nuevo_formulario(request: Request, laboratorio: LaboratorioActual, activa: Crear):
    return await _formulario_examen(request, laboratorio, activa)


async def _guardar_examen(request, laboratorio, activa, modo, datos, uuid=None):
    errores = _validar_examen(datos, laboratorio.idioma)
    if errores:
        return None, errores
    try:
        async with _sesion(request, laboratorio, activa) as sesion:
            resultado = await sesion.scalar(text(_SQL_GUARDAR_EXAMEN[modo]), {**datos, "uuid": uuid})
    except IntegrityError:
        return None, [t("catalogo.error_examen_repetido", laboratorio.idioma)]
    if resultado is None:
        return None, [t("catalogo.error_seccion", laboratorio.idioma)]
    return resultado, []


def _datos_examen(codigo, nombre, seccion, tecnica, codigo_nacional, loinc, autorizacion, dias) -> dict:
    return {
        "codigo": codigo.strip(),
        "nombre": nombre.strip(),
        "seccion": seccion.strip(),
        "tecnica": tecnica.strip(),
        "codigo_nacional": codigo_nacional.strip(),
        "loinc": loinc.strip(),
        "autorizacion": autorizacion == "si",
        "dias": dias.strip(),
    }


Campo = Annotated[TextoSeguro, Form(max_length=120)]
Corto = Annotated[TextoSeguro, Form(max_length=40)]


@router.post("/catalogo/examenes/nuevo")
async def examen_nuevo(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    activa: Crear,
    codigo: Corto = "",
    nombre: Campo = "",
    seccion: Annotated[TextoSeguro, Form(max_length=50)] = "",
    tecnica: Campo = "",
    codigo_nacional: Corto = "",
    loinc: Corto = "",
    requiere_autorizacion: Corto = "",
    dias_procesamiento: Corto = "",
):
    datos = _datos_examen(
        codigo, nombre, seccion, tecnica, codigo_nacional, loinc, requiere_autorizacion, dias_procesamiento
    )
    uuid, errores = await _guardar_examen(request, laboratorio, activa, "nuevo", datos)
    if errores:
        return await _formulario_examen(request, laboratorio, activa, examen=datos, errores=errores, estado=400)
    return redirigir(request, f"/catalogo/examenes/{uuid}")


async def _cargar_examen(sesion, examen_uuid: UUID) -> dict | None:
    fila = (
        (
            await sesion.execute(
                text(
                    "SELECT e.id, e.uuid::text AS uuid, e.codigo, e.nombre, e.codigo_nacional, e.loinc, e.activo,"
                    " e.requiere_autorizacion AS autorizacion, e.dias_procesamiento AS dias, e.codigo_lablinea,"
                    " s.codigo AS seccion, s.nombre AS seccion_nombre, tc.nombre AS tecnica"
                    " FROM lab.examenes e JOIN lab.secciones s ON s.id = e.seccion_id"
                    " LEFT JOIN lab.tecnicas tc ON tc.id = e.tecnica_id WHERE e.uuid = :u"
                ),
                {"u": examen_uuid},
            )
        )
        .mappings()
        .first()
    )
    return dict(fila) if fila else None


@router.get("/catalogo/examenes/{examen_uuid}")
async def examen(request: Request, laboratorio: LaboratorioActual, examen_uuid: UUID, activa: Consultar):
    return await _detalle_examen(request, laboratorio, activa, examen_uuid)


async def _detalle_examen(request, laboratorio, activa, examen_uuid, *, errores=(), estado=200, examen_editado=None):
    async with _sesion(request, laboratorio, activa) as sesion:
        datos = await _cargar_examen(sesion, examen_uuid)
        if datos is None:
            raise HTTPException(status_code=404)
        parametros = (
            (
                await sesion.execute(
                    text(
                        "SELECT p.uuid::text AS uuid, p.nombre, p.orden, p.tipo, p.activo, u.nombre AS unidad,"
                        " (SELECT count(*) FROM lab.rangos_referencia r WHERE r.parametro_id = p.id) AS rangos,"
                        " (SELECT count(*) FROM lab.rangos_referencia r WHERE r.parametro_id = p.id"
                        "  AND r.requiere_revision) AS por_revisar"
                        " FROM lab.parametros p LEFT JOIN lab.unidades u ON u.id = p.unidad_id"
                        " WHERE p.examen_id = :e ORDER BY p.orden, p.id"
                    ),
                    {"e": datos["id"]},
                )
            )
            .mappings()
            .all()
        )
        requisitos = (
            (
                await sesion.execute(
                    text(
                        "SELECT r.uuid::text AS uuid, m.nombre AS muestra, tt.nombre AS tubo, r.volumen_ml,"
                        " r.requiere_revision FROM lab.requisitos_muestra r"
                        " JOIN lab.tipos_muestra m ON m.id = r.tipo_muestra_id"
                        " LEFT JOIN lab.tipos_tubo tt ON tt.id = r.tipo_tubo_id"
                        " WHERE r.examen_id = :e ORDER BY m.nombre"
                    ),
                    {"e": datos["id"]},
                )
            )
            .mappings()
            .all()
        )
        precios = (
            (
                await sesion.execute(
                    text(
                        "SELECT t.codigo, t.nombre, t.moneda, pe.valor FROM lab.tarifas t"
                        " LEFT JOIN lab.precios_examen pe ON pe.tarifa_id = t.id AND pe.examen_id = :e"
                        " WHERE t.activa ORDER BY t.nombre"
                    ),
                    {"e": datos["id"]},
                )
            )
            .mappings()
            .all()
        )
        codigos = (
            (
                await sesion.execute(
                    text(
                        "SELECT tc.nombre AS tipo, ca.codigo FROM lab.codigos_alternos ca"
                        " JOIN lab.tipos_codigo_alterno tc ON tc.id = ca.tipo_id WHERE ca.examen_id = :e"
                        " ORDER BY tc.nombre"
                    ),
                    {"e": datos["id"]},
                )
            )
            .mappings()
            .all()
        )
        opciones = await _opciones(sesion)
        terminologia = await _terminologia(sesion, laboratorio)
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "examen": {**datos, **(examen_editado or {})},
        "parametros": parametros,
        "requisitos": requisitos,
        "precios": precios,
        "codigos": codigos,
        "errores": list(errores),
        "terminologia": terminologia,
        "tipos_parametro": TIPOS_PARAMETRO,
        **opciones,
    }
    return render(request, "catalogo/examen.html", contexto, estado)


@router.post("/catalogo/examenes/{examen_uuid}")
async def examen_guardar(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    examen_uuid: UUID,
    activa: Modificar,
    codigo: Corto = "",
    nombre: Campo = "",
    seccion: Annotated[TextoSeguro, Form(max_length=50)] = "",
    tecnica: Campo = "",
    codigo_nacional: Corto = "",
    loinc: Corto = "",
    requiere_autorizacion: Corto = "",
    dias_procesamiento: Corto = "",
):
    datos = _datos_examen(
        codigo, nombre, seccion, tecnica, codigo_nacional, loinc, requiere_autorizacion, dias_procesamiento
    )
    uuid, errores = await _guardar_examen(request, laboratorio, activa, "editar", datos, str(examen_uuid))
    if errores:
        return await _detalle_examen(
            request, laboratorio, activa, examen_uuid, errores=errores, estado=400, examen_editado=datos
        )
    return redirigir(request, f"/catalogo/examenes/{examen_uuid}")


@router.post("/catalogo/examenes/{examen_uuid}/estado")
async def examen_estado(
    request: Request, laboratorio: LaboratorioActual, _csrf: Csrf, examen_uuid: UUID, activa: Modificar
):
    async with _sesion(request, laboratorio, activa) as sesion:
        cambiado = await sesion.scalar(
            text("UPDATE lab.examenes SET activo = NOT activo WHERE uuid = :u RETURNING id"), {"u": examen_uuid}
        )
    if cambiado is None:
        raise HTTPException(status_code=404)
    return redirigir(request, f"/catalogo/examenes/{examen_uuid}")


# --- Parámetros ---


def _validar_parametro(nombre: str, tipo: str, orden: str, decimales: str, loinc: str, idioma: str) -> list[str]:
    errores = []
    if not 1 <= len(nombre) <= 120:
        errores.append(t("catalogo.error_nombre", idioma))
    if tipo not in TIPOS_PARAMETRO:
        errores.append(t("catalogo.error_tipo", idioma))
    if not re.fullmatch(r"[0-9]{1,4}", orden) or not re.fullmatch(r"[0-6]", decimales):
        errores.append(t("catalogo.error_orden", idioma))
    if loinc and not LOINC.match(loinc):
        errores.append(t("catalogo.error_loinc", idioma))
    return errores


@router.post("/catalogo/examenes/{examen_uuid}/parametros")
async def parametro_nuevo(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    examen_uuid: UUID,
    activa: Crear,
    nombre: Campo = "",
    tipo: Corto = "NUMERICO",
    unidad: Annotated[TextoSeguro, Form(max_length=50)] = "",
    orden: Corto = "0",
    decimales: Corto = "2",
):
    nombre, orden, decimales = nombre.strip(), orden.strip() or "0", decimales.strip() or "2"
    errores = _validar_parametro(nombre, tipo, orden, decimales, "", laboratorio.idioma)
    if errores:
        return await _detalle_examen(request, laboratorio, activa, examen_uuid, errores=errores, estado=400)
    async with _sesion(request, laboratorio, activa) as sesion:
        uuid = await sesion.scalar(
            text(
                "INSERT INTO lab.parametros (examen_id, nombre, tipo, unidad_id, orden, decimales)"
                " SELECT e.id, :n, :t, (SELECT id FROM lab.unidades WHERE codigo = :u), :o, :d"
                " FROM lab.examenes e WHERE e.uuid = :e RETURNING uuid::text"
            ),
            {
                "n": nombre,
                "t": tipo,
                "u": unidad if tipo == "NUMERICO" else None,
                "o": int(orden),
                "d": int(decimales),
                "e": examen_uuid,
            },
        )
    if uuid is None:
        raise HTTPException(status_code=404)
    return redirigir(request, f"/catalogo/parametros/{uuid}")


async def _cargar_parametro(sesion, parametro_uuid: UUID) -> dict | None:
    fila = (
        (
            await sesion.execute(
                text(
                    "SELECT p.id, p.uuid::text AS uuid, p.nombre, p.orden, p.tipo, p.decimales, p.loinc, p.grafica,"
                    " p.activo, u.codigo AS unidad, u.nombre AS unidad_nombre, e.uuid::text AS examen_uuid,"
                    " e.nombre AS examen FROM lab.parametros p JOIN lab.examenes e ON e.id = p.examen_id"
                    " LEFT JOIN lab.unidades u ON u.id = p.unidad_id WHERE p.uuid = :u"
                ),
                {"u": parametro_uuid},
            )
        )
        .mappings()
        .first()
    )
    return dict(fila) if fila else None


@router.get("/catalogo/parametros/{parametro_uuid}")
async def parametro(request: Request, laboratorio: LaboratorioActual, parametro_uuid: UUID, activa: Consultar):
    return await _detalle_parametro(request, laboratorio, activa, parametro_uuid)


async def _detalle_parametro(request, laboratorio, activa, parametro_uuid, *, errores=(), estado=200, rango=None):
    async with _sesion(request, laboratorio, activa) as sesion:
        datos = await _cargar_parametro(sesion, parametro_uuid)
        if datos is None:
            raise HTTPException(status_code=404)
        filas = (
            (
                await sesion.execute(
                    text(
                        "SELECT uuid::text AS uuid, sexo, edad_min_dias, edad_max_dias, minimo, maximo, critico_min,"
                        " critico_max, valor_esperado, texto_impreso, requiere_revision"
                        " FROM lab.rangos_referencia WHERE parametro_id = :p ORDER BY sexo, edad_min_dias"
                    ),
                    {"p": datos["id"]},
                )
            )
            .mappings()
            .all()
        )
        valores = (
            (
                await sesion.execute(
                    text(
                        "SELECT valor, es_normal FROM lab.valores_lista WHERE parametro_id = :p ORDER BY orden, valor"
                    ),
                    {"p": datos["id"]},
                )
            )
            .mappings()
            .all()
        )
        opciones = await _opciones(sesion)
    advertencias = []
    if datos["tipo"] != "TITULO" and filas:
        advertencias = rangos.analizar([rangos.Rango(f["sexo"], f["edad_min_dias"], f["edad_max_dias"]) for f in filas])
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "parametro": datos,
        "rangos": [
            {**f, "desde": rangos.edad_legible(f["edad_min_dias"]), "hasta": rangos.edad_legible(f["edad_max_dias"])}
            for f in filas
        ],
        "valores": valores,
        "advertencias": [
            {**a.__dict__, "desde": rangos.edad_legible(a.desde_dias), "hasta": rangos.edad_legible(a.hasta_dias)}
            for a in advertencias
        ],
        "errores": list(errores),
        "rango": rango or {},
        "tipos_parametro": TIPOS_PARAMETRO,
        "sexos": SEXOS,
        "unidades_edad": UNIDADES_EDAD,
        **opciones,
    }
    return render(request, "catalogo/parametro.html", contexto, estado)


@router.post("/catalogo/parametros/{parametro_uuid}")
async def parametro_guardar(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    parametro_uuid: UUID,
    activa: Modificar,
    nombre: Campo = "",
    tipo: Corto = "",
    unidad: Annotated[TextoSeguro, Form(max_length=50)] = "",
    orden: Corto = "0",
    decimales: Corto = "2",
    loinc: Corto = "",
    grafica: Corto = "",
    activo: Corto = "",
):
    nombre, orden, decimales, loinc = nombre.strip(), orden.strip(), decimales.strip(), loinc.strip()
    errores = _validar_parametro(nombre, tipo, orden, decimales, loinc, laboratorio.idioma)
    if errores:
        return await _detalle_parametro(request, laboratorio, activa, parametro_uuid, errores=errores, estado=400)
    async with _sesion(request, laboratorio, activa) as sesion:
        cambiado = await sesion.scalar(
            text(
                "UPDATE lab.parametros SET nombre = :n, tipo = :t, orden = :o, decimales = :d, loinc = NULLIF(:l, ''),"
                " unidad_id = (SELECT id FROM lab.unidades WHERE codigo = :u), grafica = :g, activo = :a"
                " WHERE uuid = :p RETURNING id"
            ),
            {
                "n": nombre,
                "t": tipo,
                "o": int(orden),
                "d": int(decimales),
                "l": loinc,
                "u": unidad if tipo == "NUMERICO" else None,
                "g": grafica == "si" and tipo == "NUMERICO",
                "a": activo == "si",
                "p": parametro_uuid,
            },
        )
    if cambiado is None:
        raise HTTPException(status_code=404)
    return redirigir(request, f"/catalogo/parametros/{parametro_uuid}")


# --- Rangos de referencia ---


def _edad_dias(valor: str, unidad: str) -> int:
    if not re.fullmatch(r"[0-9]{1,5}", valor.strip()) or unidad not in UNIDADES_EDAD:
        raise ValueError(valor)
    return int(valor) * UNIDADES_EDAD[unidad]


@router.post("/catalogo/parametros/{parametro_uuid}/rangos")
async def rango_nuevo(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    parametro_uuid: UUID,
    activa: Crear,
    sexo: Corto = "T",
    edad_min: Corto = "0",
    unidad_min: Corto = "anios",
    edad_max: Corto = "150",
    unidad_max: Corto = "anios",
    minimo: Corto = "",
    maximo: Corto = "",
    critico_min: Corto = "",
    critico_max: Corto = "",
    valor_esperado: Campo = "",
    texto_impreso: Annotated[TextoSeguro, Form(max_length=255)] = "",
):
    idioma = laboratorio.idioma
    borrador = {
        "sexo": sexo, "edad_min": edad_min, "unidad_min": unidad_min, "edad_max": edad_max, "unidad_max": unidad_max,
        "minimo": minimo, "maximo": maximo, "critico_min": critico_min, "critico_max": critico_max,
        "valor_esperado": valor_esperado, "texto_impreso": texto_impreso,
    }  # fmt: skip
    errores = []
    try:
        desde, hasta = _edad_dias(edad_min, unidad_min), _edad_dias(edad_max, unidad_max)
        if not (0 <= desde < hasta <= rangos.EDAD_MAXIMA_DIAS):
            raise ValueError
    except ValueError:
        errores.append(t("catalogo.error_edades", idioma))
        desde = hasta = 0
    try:
        valores = {
            c: _decimal(v)
            for c, v in (
                ("minimo", minimo),
                ("maximo", maximo),
                ("critico_min", critico_min),
                ("critico_max", critico_max),
            )
        }
    except ValueError:
        errores.append(t("catalogo.error_numero", idioma))
        valores = {}
    if sexo not in SEXOS:
        errores.append(t("catalogo.error_sexo", idioma))
    if valores:
        mn, mx, cmn, cmx = valores["minimo"], valores["maximo"], valores["critico_min"], valores["critico_max"]
        if (
            (mn is not None and mx is not None and mn > mx)
            or (cmn is not None and mn is not None and cmn > mn)
            or (cmx is not None and mx is not None and cmx < mx)
        ):
            errores.append(t("catalogo.error_limites", idioma))
        if all(v is None for v in valores.values()) and not valor_esperado.strip() and not texto_impreso.strip():
            errores.append(t("catalogo.error_rango_vacio", idioma))
    if errores:
        return await _detalle_parametro(
            request, laboratorio, activa, parametro_uuid, errores=errores, estado=400, rango=borrador
        )
    async with _sesion(request, laboratorio, activa) as sesion:
        creado = await sesion.scalar(
            text(
                "INSERT INTO lab.rangos_referencia (parametro_id, sexo, edad_min_dias, edad_max_dias, minimo, maximo,"
                " critico_min, critico_max, valor_esperado, texto_impreso)"
                " SELECT p.id, :sexo, :desde, :hasta, :minimo, :maximo, :critico_min, :critico_max,"
                " NULLIF(:esperado, ''), NULLIF(:impreso, '') FROM lab.parametros p WHERE p.uuid = :p RETURNING id"
            ),
            {
                **valores,
                "sexo": sexo,
                "desde": desde,
                "hasta": hasta,
                "esperado": valor_esperado.strip(),
                "impreso": texto_impreso.strip(),
                "p": parametro_uuid,
            },
        )
    if creado is None:
        raise HTTPException(status_code=404)
    return redirigir(request, f"/catalogo/parametros/{parametro_uuid}")


async def _accion_rango(request, laboratorio, activa, rango_uuid: UUID, sql: str):
    async with _sesion(request, laboratorio, activa) as sesion:
        parametro_uuid = await sesion.scalar(text(sql), {"r": rango_uuid})
    if parametro_uuid is None:
        raise HTTPException(status_code=404)
    return redirigir(request, f"/catalogo/parametros/{parametro_uuid}")


@router.post("/catalogo/rangos/{rango_uuid}/eliminar")
async def rango_eliminar(
    request: Request, laboratorio: LaboratorioActual, _csrf: Csrf, rango_uuid: UUID, activa: Eliminar
):
    return await _accion_rango(
        request,
        laboratorio,
        activa,
        rango_uuid,
        "DELETE FROM lab.rangos_referencia r USING lab.parametros p WHERE r.uuid = :r AND p.id = r.parametro_id"
        " RETURNING p.uuid::text",
    )


@router.post("/catalogo/rangos/{rango_uuid}/revisado")
async def rango_revisado(
    request: Request, laboratorio: LaboratorioActual, _csrf: Csrf, rango_uuid: UUID, activa: Modificar
):
    return await _accion_rango(
        request,
        laboratorio,
        activa,
        rango_uuid,
        "UPDATE lab.rangos_referencia r SET requiere_revision = false FROM lab.parametros p"
        " WHERE r.uuid = :r AND p.id = r.parametro_id RETURNING p.uuid::text",
    )


# --- Valores de lista ---


@router.post("/catalogo/parametros/{parametro_uuid}/valores")
async def valor_nuevo(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    parametro_uuid: UUID,
    activa: Crear,
    valor: Campo = "",
    es_normal: Corto = "",
):
    valor = valor.strip()
    if not valor:
        return await _detalle_parametro(
            request,
            laboratorio,
            activa,
            parametro_uuid,
            errores=[t("catalogo.error_valor", laboratorio.idioma)],
            estado=400,
        )
    try:
        async with _sesion(request, laboratorio, activa) as sesion:
            creado = await sesion.scalar(
                text(
                    "INSERT INTO lab.valores_lista (parametro_id, valor, es_normal, orden)"
                    " SELECT p.id, :v, :n,"
                    " coalesce((SELECT max(orden) + 1 FROM lab.valores_lista WHERE parametro_id = p.id), 0)"
                    " FROM lab.parametros p WHERE p.uuid = :p RETURNING id"
                ),
                {"v": valor, "n": es_normal == "si", "p": parametro_uuid},
            )
    except IntegrityError:
        return await _detalle_parametro(
            request,
            laboratorio,
            activa,
            parametro_uuid,
            errores=[t("catalogo.error_valor_repetido", laboratorio.idioma)],
            estado=400,
        )
    if creado is None:
        raise HTTPException(status_code=404)
    return redirigir(request, f"/catalogo/parametros/{parametro_uuid}")


@router.post("/catalogo/parametros/{parametro_uuid}/valores/eliminar")
async def valor_eliminar(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    parametro_uuid: UUID,
    activa: Eliminar,
    valor: Campo = "",
):
    async with _sesion(request, laboratorio, activa) as sesion:
        borrado = await sesion.scalar(
            text(
                "DELETE FROM lab.valores_lista v USING lab.parametros p"
                " WHERE p.uuid = :p AND v.parametro_id = p.id AND v.valor = :v RETURNING v.id"
            ),
            {"p": parametro_uuid, "v": valor},
        )
    if borrado is None:
        raise HTTPException(status_code=404)
    return redirigir(request, f"/catalogo/parametros/{parametro_uuid}")


# --- Requisitos de muestra y precios ---


@router.post("/catalogo/examenes/{examen_uuid}/requisitos")
async def requisito_nuevo(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    examen_uuid: UUID,
    activa: Crear,
    tipo_muestra: Annotated[TextoSeguro, Form(max_length=10)] = "",
    tipo_tubo: Annotated[TextoSeguro, Form(max_length=20)] = "",
    volumen_ml: Corto = "",
):
    try:
        volumen = _decimal(volumen_ml)
        if volumen is not None and not Decimal("0") < volumen < Decimal("1000"):
            raise ValueError
    except ValueError:
        return await _detalle_examen(
            request,
            laboratorio,
            activa,
            examen_uuid,
            errores=[t("catalogo.error_volumen", laboratorio.idioma)],
            estado=400,
        )
    try:
        async with _sesion(request, laboratorio, activa) as sesion:
            creado = await sesion.scalar(
                text(
                    "INSERT INTO lab.requisitos_muestra (examen_id, tipo_muestra_id, tipo_tubo_id, volumen_ml)"
                    " SELECT e.id, m.id, (SELECT id FROM lab.tipos_tubo WHERE codigo = :tubo), :v"
                    " FROM lab.examenes e, lab.tipos_muestra m WHERE e.uuid = :e AND m.codigo = :m RETURNING id"
                ),
                {"tubo": tipo_tubo, "v": volumen, "e": examen_uuid, "m": tipo_muestra},
            )
    except IntegrityError:
        return await _detalle_examen(
            request,
            laboratorio,
            activa,
            examen_uuid,
            errores=[t("catalogo.error_requisito_repetido", laboratorio.idioma)],
            estado=400,
        )
    if creado is None:
        raise HTTPException(status_code=404)
    return redirigir(request, f"/catalogo/examenes/{examen_uuid}")


@router.post("/catalogo/requisitos/{requisito_uuid}/eliminar")
async def requisito_eliminar(
    request: Request, laboratorio: LaboratorioActual, _csrf: Csrf, requisito_uuid: UUID, activa: Eliminar
):
    async with _sesion(request, laboratorio, activa) as sesion:
        examen_uuid = await sesion.scalar(
            text(
                "DELETE FROM lab.requisitos_muestra r USING lab.examenes e WHERE r.uuid = :r AND e.id = r.examen_id"
                " RETURNING e.uuid::text"
            ),
            {"r": requisito_uuid},
        )
    if examen_uuid is None:
        raise HTTPException(status_code=404)
    return redirigir(request, f"/catalogo/examenes/{examen_uuid}")


@router.post("/catalogo/examenes/{examen_uuid}/precios")
async def precio_guardar(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    examen_uuid: UUID,
    activa: Modificar,
    tarifa: Annotated[TextoSeguro, Form(max_length=15)] = "",
    valor: Corto = "",
):
    try:
        cantidad = _decimal(valor)
        if cantidad is not None and (cantidad < 0 or cantidad != cantidad.quantize(Decimal("0.01"))):
            raise ValueError
    except ValueError:
        return await _detalle_examen(
            request,
            laboratorio,
            activa,
            examen_uuid,
            errores=[t("catalogo.error_precio", laboratorio.idioma)],
            estado=400,
        )
    async with _sesion(request, laboratorio, activa) as sesion:
        ids = (
            await sesion.execute(
                text("SELECT e.id, t.id FROM lab.examenes e, lab.tarifas t WHERE e.uuid = :e AND t.codigo = :t"),
                {"e": examen_uuid, "t": tarifa},
            )
        ).first()
        if ids is None:
            raise HTTPException(status_code=404)
        if cantidad is None:  # vacío: el examen no tiene precio en esa tarifa
            await sesion.execute(
                text("DELETE FROM lab.precios_examen WHERE examen_id = :e AND tarifa_id = :t"),
                {"e": ids[0], "t": ids[1]},
            )
        else:
            await sesion.execute(
                text(
                    "INSERT INTO lab.precios_examen (examen_id, tarifa_id, valor) VALUES (:e, :t, :v)"
                    " ON CONFLICT (tenant_id, tarifa_id, examen_id) DO UPDATE SET valor = EXCLUDED.valor"
                ),
                {"e": ids[0], "t": ids[1], "v": cantidad},
            )
    return redirigir(request, f"/catalogo/examenes/{examen_uuid}")


# --- Maestros ---

MAESTROS = {
    # tipo: (SQL de inserción, campos obligatorios del formulario)
    "secciones": (
        "INSERT INTO lab.secciones (codigo, nombre, orden)"
        " VALUES (:codigo, :nombre, coalesce(CAST(NULLIF(:extra, '') AS integer), 0))",
        ("codigo", "nombre"),
    ),
    "unidades": (
        "INSERT INTO lab.unidades (codigo, nombre, ucum) VALUES (:codigo, :nombre, NULLIF(:extra, ''))",
        ("codigo", "nombre"),
    ),
    "tipos_muestra": ("INSERT INTO lab.tipos_muestra (codigo, nombre) VALUES (:codigo, :nombre)", ("codigo", "nombre")),
    "tipos_tubo": (
        "INSERT INTO lab.tipos_tubo (codigo, nombre, aditivo, capacidad_ml)"
        " VALUES (:codigo, :nombre, NULLIF(:aditivo, ''), :capacidad)",
        ("codigo", "nombre"),
    ),
    "tecnicas": ("INSERT INTO lab.tecnicas (nombre) VALUES (:nombre)", ("nombre",)),
    "tarifas": (
        "INSERT INTO lab.tarifas (codigo, nombre, moneda) VALUES (:codigo, :nombre, :moneda)",
        ("codigo", "nombre"),
    ),
    "tipos_codigo": (
        "INSERT INTO lab.tipos_codigo_alterno (codigo, nombre) VALUES (:codigo, :nombre)",
        ("codigo", "nombre"),
    ),
}


async def _pagina_maestros(request, laboratorio, activa, *, errores=(), estado=200):
    async with _sesion(request, laboratorio, activa) as sesion:
        opciones = await _opciones(sesion)
        secciones = (
            (await sesion.execute(text("SELECT codigo, nombre, orden FROM lab.secciones ORDER BY orden, nombre")))
            .mappings()
            .all()
        )
    contexto = {"sitio": laboratorio, "activa": activa, "errores": list(errores), **opciones, "secciones": secciones}
    return render(request, "catalogo/maestros.html", contexto, estado)


@router.get("/catalogo/maestros")
async def maestros(request: Request, laboratorio: LaboratorioActual, activa: Consultar):
    return await _pagina_maestros(request, laboratorio, activa)


@router.post("/catalogo/maestros/{tipo}")
async def maestro_nuevo(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    tipo: str,
    activa: Crear,
    codigo: Annotated[TextoSeguro, Form(max_length=50)] = "",
    nombre: Campo = "",
    extra: Corto = "",
    aditivo: Annotated[TextoSeguro, Form(max_length=60)] = "",
    capacidad: Corto = "",
):
    if tipo not in MAESTROS:
        raise HTTPException(status_code=404)
    sql, campos = MAESTROS[tipo]
    datos = {
        "codigo": codigo.strip(),
        "nombre": nombre.strip(),
        "extra": extra.strip(),
        "aditivo": aditivo.strip(),
        "moneda": laboratorio.moneda,
    }
    errores = []
    if ("codigo" in campos and not datos["codigo"]) or not datos["nombre"]:
        errores.append(t("catalogo.error_maestro", laboratorio.idioma))
    if tipo == "secciones" and datos["extra"] and not re.fullmatch(r"[0-9]{1,4}", datos["extra"]):
        errores.append(t("catalogo.error_orden", laboratorio.idioma))
    if tipo == "tipos_tubo":
        try:
            datos["capacidad"] = _decimal(capacidad)
            if datos["capacidad"] is None or not Decimal("0") < datos["capacidad"] < Decimal("1000"):
                raise ValueError
        except ValueError:
            errores.append(t("catalogo.error_volumen", laboratorio.idioma))
    if not errores:
        try:
            async with _sesion(request, laboratorio, activa) as sesion:
                await sesion.execute(text(sql), datos)
        except IntegrityError:
            # Repetido o fuera de los límites de la base (p. ej. un código demasiado largo para ese maestro).
            errores.append(t("catalogo.error_maestro_rechazado", laboratorio.idioma))
    if errores:
        return await _pagina_maestros(request, laboratorio, activa, errores=errores, estado=400)
    return redirigir(request, "/catalogo/maestros")


# --- Revisión ---


@router.get("/catalogo/revision")
async def revision(request: Request, laboratorio: LaboratorioActual, activa: Consultar):
    async with _sesion(request, laboratorio, activa) as sesion:
        pendientes = (
            (
                await sesion.execute(
                    text(
                        "SELECT p.uuid::text AS parametro_uuid, p.nombre AS parametro, e.nombre AS examen,"
                        " r.texto_impreso, r.minimo, r.maximo, r.valor_esperado"
                        " FROM lab.rangos_referencia r JOIN lab.parametros p ON p.id = r.parametro_id"
                        " JOIN lab.examenes e ON e.id = p.examen_id WHERE r.requiere_revision"
                        " ORDER BY e.nombre, p.orden LIMIT 1000"
                    )
                )
            )
            .mappings()
            .all()
        )
        requisitos = (
            (
                await sesion.execute(
                    text(
                        "SELECT e.uuid::text AS examen_uuid, e.nombre AS examen, m.nombre AS muestra"
                        " FROM lab.requisitos_muestra r JOIN lab.examenes e ON e.id = r.examen_id"
                        " JOIN lab.tipos_muestra m ON m.id = r.tipo_muestra_id"
                        " WHERE r.requiere_revision OR r.tipo_tubo_id IS NULL OR r.volumen_ml IS NULL"
                        " ORDER BY e.nombre LIMIT 1000"
                    )
                )
            )
            .mappings()
            .all()
        )
    contexto = {"sitio": laboratorio, "activa": activa, "rangos": pendientes, "requisitos": requisitos}
    return render(request, "catalogo/revision.html", contexto)


# --- Importación desde Lablinea ---


@router.get("/catalogo/importar")
async def importar_formulario(request: Request, laboratorio: LaboratorioActual, activa: Crear):
    async with _sesion(request, laboratorio, activa) as sesion:
        recientes = (
            (
                await sesion.execute(
                    text(
                        "SELECT uuid::text AS uuid, nombre_archivo, estado, creada_en,"
                        " (resumen->>'total_errores')::int AS errores FROM lab.importaciones"
                        " ORDER BY creada_en DESC LIMIT 20"
                    )
                )
            )
            .mappings()
            .all()
        )
    return render(request, "catalogo/importar.html", {"sitio": laboratorio, "activa": activa, "recientes": recientes})


def _nombre_seguro(nombre: str | None) -> str:
    """Nombre del archivo para mostrar: sin rutas ni caracteres de control, máximo 120."""
    base = re.split(r"[\\/]", nombre or "")[-1]
    limpio = "".join(c for c in base if c.isprintable())[:120]
    return limpio or "catalogo.zip"


@router.post("/catalogo/importar")
async def importar(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    activa: Crear,
    archivo: Annotated[UploadFile | None, File()] = None,
):
    datos = await archivo.read(MAX_ARCHIVO + 1) if archivo else b""
    try:
        tablas = importador.leer_paquete(datos)
    except importador.ArchivoRechazado as rechazo:
        contexto = {
            "sitio": laboratorio,
            "activa": activa,
            "recientes": [],
            "rechazo": t(f"importador.rechazo.{rechazo.clave}", laboratorio.idioma, **rechazo.parametros),
        }
        return render(request, "catalogo/importar.html", contexto, 400)
    async with _sesion(request, laboratorio, activa) as sesion:
        plan = importador.analizar(tablas, await importador.existentes(sesion), laboratorio.moneda)
        uuid = await sesion.scalar(
            text(
                "INSERT INTO lab.importaciones (usuario_id, nombre_archivo, sha256, tamano, contenido, resumen)"
                " VALUES (:u, :n, :h, :t, :c, CAST(:r AS jsonb)) RETURNING uuid::text"
            ),
            {
                "u": activa.usuario.id,
                "n": _nombre_seguro(archivo.filename if archivo else None),
                "h": hashlib.sha256(datos).digest(),
                "t": len(datos),
                "c": datos,
                "r": json.dumps(plan.resumen(), default=str),
            },
        )
    return redirigir(request, f"/catalogo/importaciones/{uuid}")


async def _cargar_importacion(sesion, importacion_uuid: UUID) -> dict | None:
    fila = (
        (
            await sesion.execute(
                text(
                    "SELECT id, uuid::text AS uuid, nombre_archivo, estado, resumen, contenido, sha256, creada_en,"
                    " terminada_en FROM lab.importaciones WHERE uuid = :u"
                ),
                {"u": importacion_uuid},
            )
        )
        .mappings()
        .first()
    )
    return dict(fila) if fila else None


@router.get("/catalogo/importaciones/{importacion_uuid}")
async def importacion(request: Request, laboratorio: LaboratorioActual, importacion_uuid: UUID, activa: Crear):
    async with _sesion(request, laboratorio, activa) as sesion:
        datos = await _cargar_importacion(sesion, importacion_uuid)
    if datos is None:
        raise HTTPException(status_code=404)
    datos.pop("contenido")
    return render(
        request,
        "catalogo/importacion.html",
        {
            "sitio": laboratorio,
            "activa": activa,
            "importacion": datos,
            "error": request.query_params.get("error") == "cambio",
        },
    )


@router.post("/catalogo/importaciones/{importacion_uuid}/cargar")
async def importacion_cargar(
    request: Request, laboratorio: LaboratorioActual, _csrf: Csrf, importacion_uuid: UUID, activa: Crear
):
    async with _sesion(request, laboratorio, activa) as sesion:
        datos = await _cargar_importacion(sesion, importacion_uuid)
        if datos is None or datos["estado"] != "PREVISTA" or datos["contenido"] is None:
            raise HTTPException(status_code=404)
        contenido = bytes(datos["contenido"])
        if hashlib.sha256(contenido).digest() != bytes(datos["sha256"]):
            raise HTTPException(status_code=409)  # pragma: no cover — la base no permite cambiar el contenido
        # Se vuelve a analizar contra el catálogo actual: pudo cambiar desde la vista previa.
        plan = importador.analizar(
            importador.leer_paquete(contenido), await importador.existentes(sesion), laboratorio.moneda
        )
        if plan.errores:
            await sesion.execute(
                text("UPDATE lab.importaciones SET resumen = CAST(:r AS jsonb) WHERE id = :i"),
                {"r": json.dumps(plan.resumen(), default=str), "i": datos["id"]},
            )
            cargado = False
        else:
            await importador.cargar(sesion, plan)
            await sesion.execute(
                text(
                    "UPDATE lab.importaciones SET estado = 'CARGADA', contenido = NULL, terminada_en = now(),"
                    " resumen = CAST(:r AS jsonb) WHERE id = :i"
                ),
                {"r": json.dumps(plan.resumen(), default=str), "i": datos["id"]},
            )
            cargado = True
    if not cargado:
        return redirigir(request, f"/catalogo/importaciones/{importacion_uuid}?error=cambio")
    return redirigir(request, f"/catalogo/importaciones/{importacion_uuid}")


@router.post("/catalogo/importaciones/{importacion_uuid}/descartar")
async def importacion_descartar(
    request: Request, laboratorio: LaboratorioActual, _csrf: Csrf, importacion_uuid: UUID, activa: Crear
):
    async with _sesion(request, laboratorio, activa) as sesion:
        descartada = await sesion.scalar(
            text(
                "UPDATE lab.importaciones SET estado = 'DESCARTADA', contenido = NULL, terminada_en = now()"
                " WHERE uuid = :u AND estado = 'PREVISTA' RETURNING id"
            ),
            {"u": importacion_uuid},
        )
    if descartada is None:
        raise HTTPException(status_code=404)
    return redirigir(request, "/catalogo/importar")


# --- Exportación a CSV ---

_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def celda_segura(valor: object) -> str:
    """Neutraliza la inyección CSV: un texto que empieza como fórmula se antepone con un apóstrofo."""
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto.startswith(_FORMULA) else texto


@router.get("/catalogo/exportar.csv")
async def exportar(request: Request, laboratorio: LaboratorioActual, activa: Consultar):
    async with _sesion(request, laboratorio, activa) as sesion:
        tarifas = (await sesion.execute(text("SELECT id, codigo FROM lab.tarifas ORDER BY codigo"))).all()
        examenes = (
            await sesion.execute(
                text(
                    "SELECT e.id, e.codigo, e.nombre, s.nombre AS seccion, e.codigo_nacional, e.loinc, e.activo"
                    " FROM lab.examenes e JOIN lab.secciones s ON s.id = e.seccion_id ORDER BY s.nombre, e.nombre"
                )
            )
        ).all()
        precios = {
            (fila.examen_id, fila.tarifa_id): fila.valor
            for fila in (await sesion.execute(text("SELECT examen_id, tarifa_id, valor FROM lab.precios_examen"))).all()
        }
        terminologia = await _terminologia(sesion, laboratorio)
        await registrar_acceso(
            sesion, "examenes", operacion="EXPORT", detalle={"formato": "csv", "filas": len(examenes)}
        )
    salida = io.StringIO()
    escritor = csv.writer(salida)
    idioma = laboratorio.idioma
    escritor.writerow(
        [
            celda_segura(c)
            for c in (
                t("catalogo.codigo", idioma),
                t("catalogo.nombre", idioma),
                t("catalogo.seccion", idioma),
                terminologia,
                "LOINC",
                t("catalogo.activo", idioma),
                *(codigo for _, codigo in tarifas),
            )
        ]
    )
    for e in examenes:
        escritor.writerow(
            [
                celda_segura(e.codigo),
                celda_segura(e.nombre),
                celda_segura(e.seccion),
                celda_segura(e.codigo_nacional),
                celda_segura(e.loinc),
                "1" if e.activo else "0",
                *("" if precios.get((e.id, tid)) is None else str(precios[(e.id, tid)]) for tid, _ in tarifas),
            ]
        )
    return Response(
        content="﻿" + salida.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"content-disposition": 'attachment; filename="catalogo.csv"'},
    )
