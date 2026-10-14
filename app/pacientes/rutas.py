"""Pacientes y derechos del titular (spec funcional/0010, Ley 1581).

Permisos del módulo `pacientes`: consultar (buscar, ficha, informe del titular), crear (registrar y
autorizar), modificar (editar, revocar, solicitudes) y eliminar (suprimir). El texto de la autorización
lo publica quien tiene `configuracion.modificar`.

Sin datos personales en URLs: la búsqueda es un POST y los pacientes se identifican por UUID. Toda ficha,
búsqueda e informe queda auditado con conteos, nunca con el texto buscado ni los datos.
"""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth import repositorio
from app.auth.web import (
    Csrf,
    LaboratorioActual,
    SesionActiva,
    TextoMultilinea,
    TextoSeguro,
    ip_cliente,
    redirigir,
    render,
    requiere_permiso,
)
from app.core.auditoria import registrar_acceso
from app.core.db import sesion_tenant
from app.core.i18n import t
from app.pacientes import servicio

router = APIRouter(default_response_class=HTMLResponse)
Consultar = Annotated[SesionActiva, Depends(requiere_permiso("pacientes", "consultar"))]
Crear = Annotated[SesionActiva, Depends(requiere_permiso("pacientes", "crear"))]
Modificar = Annotated[SesionActiva, Depends(requiere_permiso("pacientes", "modificar"))]
Eliminar = Annotated[SesionActiva, Depends(requiere_permiso("pacientes", "eliminar"))]
ConsultarConfiguracion = Annotated[SesionActiva, Depends(requiere_permiso("configuracion", "consultar"))]
ModificarConfiguracion = Annotated[SesionActiva, Depends(requiere_permiso("configuracion", "modificar"))]

Corto = Annotated[TextoSeguro, Form(max_length=40)]
Nombre = Annotated[TextoSeguro, Form(max_length=120)]
Largo = Annotated[TextoMultilinea, Form(max_length=2000)]

CAMPOS = (
    "tipo_documento",
    "numero_documento",
    "nombres",
    "apellidos",
    "sexo",
    "fecha_nacimiento",
    "pais",
    "email",
    "telefono",
    "direccion",
)


def _sesion(request: Request, laboratorio, activa: SesionActiva):
    return sesion_tenant(laboratorio.tenant_id, usuario_id=activa.usuario.uuid, ip=ip_cliente(request))


def _hoy(laboratorio) -> date:
    return datetime.now(ZoneInfo(laboratorio.zona_horaria)).date()


def _textos(claves, idioma) -> list[str]:
    return [t(f"pacientes.{c}", idioma) for c in dict.fromkeys(claves)]


# --- Búsqueda ---


async def _pagina_busqueda(request, laboratorio, activa, *, resultados=None, hay_mas=False, error=None, estado=200):
    async with _sesion(request, laboratorio, activa) as sesion:
        vencen = await sesion.scalar(
            text(
                "SELECT count(*) FROM lab.solicitudes_titular WHERE estado = 'ABIERTA'"
                " AND vence_en <= (now() AT TIME ZONE :z)::date + 2"
            ),
            {"z": laboratorio.zona_horaria},
        )
        sin_texto = await servicio.texto_vigente(sesion) is None
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "resultados": resultados,
        "hay_mas": hay_mas,
        "error": error,
        "vencen": vencen,
        "sin_texto": sin_texto,
        "maximo": servicio.MAX_RESULTADOS,
        "hoy": _hoy(laboratorio),
    }
    return render(request, "pacientes/buscar.html", contexto, estado)


@router.get("/pacientes")
async def pacientes(request: Request, laboratorio: LaboratorioActual, activa: Consultar):
    return await _pagina_busqueda(request, laboratorio, activa)


@router.post("/pacientes/buscar")
async def buscar(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    activa: Consultar,
    consulta: Annotated[TextoSeguro, Form(max_length=80)] = "",
):
    clave_limite = f"busqueda_pacientes:{activa.usuario.uuid}"
    async with _sesion(request, laboratorio, activa) as sesion:
        cuenta = await repositorio.limite_sumar(sesion, clave_limite, servicio.VENTANA_BUSQUEDAS_MIN)
    if cuenta > servicio.LIMITE_BUSQUEDAS:
        error = t("pacientes.error_demasiadas_busquedas", laboratorio.idioma)
        return await _pagina_busqueda(request, laboratorio, activa, error=error, estado=429)
    async with _sesion(request, laboratorio, activa) as sesion:
        modo, resultados, hay_mas = await servicio.buscar(sesion, consulta)
        if modo is not None:
            # Se audita la búsqueda (modo y cantidad), nunca el texto buscado.
            await registrar_acceso(
                sesion, "pacientes", detalle={"vista": "busqueda", "modo": modo, "filas": len(resultados)}
            )
    if modo is None:
        error = t("pacientes.error_busqueda_corta", laboratorio.idioma, minimo=servicio.MIN_BUSQUEDA)
        return await _pagina_busqueda(request, laboratorio, activa, error=error, estado=400)
    return await _pagina_busqueda(request, laboratorio, activa, resultados=resultados, hay_mas=hay_mas)


# --- Registro ---


async def _formulario(request, laboratorio, activa, *, datos=None, errores=(), estado=200):
    async with _sesion(request, laboratorio, activa) as sesion:
        config = await servicio.config_pais(sesion, laboratorio.pais)
        texto = await servicio.texto_vigente(sesion)
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "config": config,
        "texto": texto,
        "datos": datos or {"pais": laboratorio.pais},
        "errores": list(errores),
        "sexos": servicio.SEXOS,
        "medios": servicio.MEDIOS,
        "hoy": _hoy(laboratorio),
    }
    return render(request, "pacientes/nuevo.html", contexto, estado)


@router.get("/pacientes/nuevo")
async def paciente_nuevo_formulario(request: Request, laboratorio: LaboratorioActual, activa: Crear):
    return await _formulario(request, laboratorio, activa)


def _autorizacion(medio: str, acepto: str, texto: dict | None, representante: dict) -> tuple[dict, list[str]]:
    errores = []
    if texto is None:
        errores.append("error_sin_texto")
    if medio not in servicio.MEDIOS:
        errores.append("error_medio")
    if acepto != "si":
        errores.append("error_sin_aceptacion")
    return {"texto": texto["id"] if texto else None, "medio": medio, **representante}, errores


@router.post("/pacientes/nuevo")
async def paciente_nuevo(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    activa: Crear,
    tipo_documento: Corto = "",
    numero_documento: Corto = "",
    nombres: Nombre = "",
    apellidos: Nombre = "",
    sexo: Corto = "",
    fecha_nacimiento: Corto = "",
    pais: Corto = "",
    email: Annotated[TextoSeguro, Form(max_length=254)] = "",
    telefono: Corto = "",
    direccion: Annotated[TextoSeguro, Form(max_length=200)] = "",
    medio: Corto = "",
    acepto: Corto = "",
    representante_nombre: Nombre = "",
    representante_documento: Corto = "",
    representante_parentesco: Corto = "",
    texto_version: Corto = "",
):
    formulario = dict(zip(CAMPOS, (tipo_documento, numero_documento, nombres, apellidos, sexo, fecha_nacimiento,
                                   pais, email, telefono, direccion), strict=True))  # fmt: skip
    representante_form = {
        "representante_nombre": representante_nombre,
        "representante_documento": representante_documento,
        "representante_parentesco": representante_parentesco,
    }
    async with _sesion(request, laboratorio, activa) as sesion:
        config = await servicio.config_pais(sesion, laboratorio.pais)
        texto = await servicio.texto_vigente(sesion)
    datos, errores = servicio.validar(formulario, config, _hoy(laboratorio))
    menor = servicio.es_menor(datos["fecha_nacimiento"], _hoy(laboratorio), config.mayoria_edad)
    representante, errores_rep = servicio.validar_representante(representante_form, menor)
    autorizacion, errores_aut = _autorizacion(medio, acepto, texto, representante)
    errores += errores_rep + errores_aut
    # El texto pudo cambiar mientras se llenaba el formulario: se acepta la versión que se mostró.
    if texto and texto_version and texto_version != str(texto["version"]):
        errores.append("error_texto_cambio")
    uuid = None
    if not errores:
        try:
            async with _sesion(request, laboratorio, activa) as sesion:
                uuid = await servicio.registrar(sesion, datos, autorizacion)
        except IntegrityError:
            errores.append("error_duplicado")
    if errores:
        formulario.update(representante_form, medio=medio)
        textos = _textos(errores, laboratorio.idioma)
        return await _formulario(request, laboratorio, activa, datos=formulario, errores=textos, estado=400)
    return redirigir(request, f"/pacientes/{uuid}")


# --- Ficha ---


async def _cargar_o_404(sesion, paciente_uuid: UUID) -> dict:
    paciente = await servicio.cargar(sesion, paciente_uuid)
    if paciente is None:
        raise HTTPException(status_code=404)
    return paciente


_SQL_AUTORIZACIONES = text(
    "SELECT a.uuid::text AS uuid, a.medio, a.otorgada_en, a.revocada_en, a.motivo_revocacion,"
    " a.representante_nombre, a.representante_documento, a.representante_parentesco, ta.version,"
    " ur.nombre AS registrada_por, uv.nombre AS revocada_por"
    " FROM lab.autorizaciones_datos a JOIN lab.textos_autorizacion ta ON ta.id = a.texto_id"
    " LEFT JOIN lab.usuarios ur ON ur.uuid = a.registrada_por"
    " LEFT JOIN lab.usuarios uv ON uv.uuid = a.revocada_por"
    " WHERE a.paciente_id = :p ORDER BY a.otorgada_en DESC"
)
_SQL_SOLICITUDES = text(
    "SELECT s.uuid::text AS uuid, s.tipo, s.canal, s.descripcion, s.recibida_en, s.vence_en, s.estado,"
    " s.respuesta, s.resuelta_en, u.nombre AS resuelta_por"
    " FROM lab.solicitudes_titular s LEFT JOIN lab.usuarios u ON u.uuid = s.resuelta_por"
    " WHERE s.paciente_id = :p ORDER BY s.recibida_en DESC"
)


RESULTADOS = {"suprimido": "pacientes.resultado_suprimido", "rechazado": "pacientes.resultado_rechazado"}


async def _ficha(request, laboratorio, activa, paciente_uuid: UUID, *, errores=(), estado=200, resultado=""):
    async with _sesion(request, laboratorio, activa) as sesion:
        paciente = await _cargar_o_404(sesion, paciente_uuid)
        autorizaciones = (await sesion.execute(_SQL_AUTORIZACIONES, {"p": paciente["id"]})).mappings().all()
        solicitudes = (await sesion.execute(_SQL_SOLICITUDES, {"p": paciente["id"]})).mappings().all()
        config = await servicio.config_pais(sesion, laboratorio.pais)
        texto = await servicio.texto_vigente(sesion)
        await registrar_acceso(sesion, "pacientes", registro_id=paciente["id"], detalle={"vista": "ficha"})
    hoy = _hoy(laboratorio)
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "paciente": paciente,
        "edad": servicio.edad_anios(paciente["fecha_nacimiento"], hoy) if paciente["fecha_nacimiento"] else None,
        "menor": servicio.es_menor(paciente["fecha_nacimiento"], hoy, config.mayoria_edad),
        "tipo_nombre": config.tipos.get(paciente["tipo_documento"], (paciente["tipo_documento"],))[0],
        "pais_nombre": config.paises.get(paciente["pais"], paciente["pais"]),
        "autorizaciones": autorizaciones,
        "solicitudes": solicitudes,
        "abiertas": [s for s in solicitudes if s["estado"] == "ABIERTA"],
        "texto": texto,
        "tipos_solicitud": servicio.TIPOS_SOLICITUD,
        "canales": servicio.CANALES,
        "medios": servicio.MEDIOS,
        "errores": list(errores),
        "aviso": t(RESULTADOS[resultado], laboratorio.idioma) if resultado in RESULTADOS else None,
        "hoy": hoy,
    }
    return render(request, "pacientes/ficha.html", contexto, estado)


@router.get("/pacientes/{paciente_uuid}")
async def ficha(
    request: Request, laboratorio: LaboratorioActual, paciente_uuid: UUID, activa: Consultar, resultado: str = ""
):
    return await _ficha(request, laboratorio, activa, paciente_uuid, resultado=resultado)


# --- Edición (actualizar y rectificar) ---


async def _pagina_edicion(request, laboratorio, activa, paciente_uuid, *, datos=None, errores=(), estado=200):
    async with _sesion(request, laboratorio, activa) as sesion:
        paciente = await _cargar_o_404(sesion, paciente_uuid)
        config = await servicio.config_pais(sesion, laboratorio.pais)
        abiertas = (
            (
                await sesion.execute(
                    text(
                        "SELECT uuid::text AS uuid, tipo, recibida_en FROM lab.solicitudes_titular"
                        " WHERE paciente_id = :p AND estado = 'ABIERTA' AND tipo = ANY(:tipos) ORDER BY recibida_en"
                    ),
                    {"p": paciente["id"], "tipos": list(servicio.PARA_EDITAR)},
                )
            )
            .mappings()
            .all()
        )
    if paciente["estado"] != "ACTIVO":
        raise HTTPException(status_code=404)
    datos = datos or {c: paciente[c] for c in CAMPOS}
    if isinstance(datos.get("fecha_nacimiento"), date):
        datos["fecha_nacimiento"] = datos["fecha_nacimiento"].isoformat()
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "paciente": paciente,
        "datos": datos,
        "config": config,
        "abiertas": abiertas,
        "errores": list(errores),
        "sexos": servicio.SEXOS,
        "hoy": _hoy(laboratorio),
    }
    return render(request, "pacientes/editar.html", contexto, estado)


@router.get("/pacientes/{paciente_uuid}/editar")
async def editar_formulario(request: Request, laboratorio: LaboratorioActual, paciente_uuid: UUID, activa: Modificar):
    return await _pagina_edicion(request, laboratorio, activa, paciente_uuid)


@router.post("/pacientes/{paciente_uuid}/editar")
async def editar(
    request: Request,
    laboratorio: LaboratorioActual,
    paciente_uuid: UUID,
    _csrf: Csrf,
    activa: Modificar,
    tipo_documento: Corto = "",
    numero_documento: Corto = "",
    nombres: Nombre = "",
    apellidos: Nombre = "",
    sexo: Corto = "",
    fecha_nacimiento: Corto = "",
    pais: Corto = "",
    email: Annotated[TextoSeguro, Form(max_length=254)] = "",
    telefono: Corto = "",
    direccion: Annotated[TextoSeguro, Form(max_length=200)] = "",
    solicitud: Corto = "",
):
    formulario = dict(zip(CAMPOS, (tipo_documento, numero_documento, nombres, apellidos, sexo, fecha_nacimiento,
                                   pais, email, telefono, direccion), strict=True))  # fmt: skip
    errores: list[str] = []
    try:
        async with _sesion(request, laboratorio, activa) as sesion:
            paciente = await _cargar_o_404(sesion, paciente_uuid)
            if paciente["estado"] != "ACTIVO":
                raise HTTPException(status_code=404)
            config = await servicio.config_pais(sesion, laboratorio.pais)
            datos, errores = servicio.validar(formulario, config, _hoy(laboratorio))
            solicitud_id = None
            if solicitud:
                solicitud_id = await servicio.solicitud_abierta(sesion, paciente["id"], solicitud, servicio.PARA_EDITAR)
                if solicitud_id is None:
                    errores.append("error_solicitud")
            # Sin autorización vigente, los datos solo cambian para atender una solicitud del titular.
            if not paciente["autorizado"] and solicitud_id is None and "error_solicitud" not in errores:
                errores.append("error_editar_sin_autorizacion")
            if not errores:
                await servicio.actualizar(sesion, paciente["id"], datos)
                if solicitud_id is not None:
                    respuesta = t("pacientes.respuesta_actualizado", laboratorio.idioma)
                    await servicio.resolver(sesion, solicitud_id, "RESUELTA", respuesta)
    except IntegrityError:
        errores.append("error_duplicado")
    if errores:
        textos = _textos(errores, laboratorio.idioma)
        formulario["solicitud"] = solicitud
        return await _pagina_edicion(
            request, laboratorio, activa, paciente_uuid, datos=formulario, errores=textos, estado=400
        )
    return redirigir(request, f"/pacientes/{paciente_uuid}")


# --- Autorización: otorgar de nuevo y revocar ---


@router.post("/pacientes/{paciente_uuid}/autorizacion")
async def otorgar(
    request: Request,
    laboratorio: LaboratorioActual,
    paciente_uuid: UUID,
    _csrf: Csrf,
    activa: Crear,
    medio: Corto = "",
    acepto: Corto = "",
    representante_nombre: Nombre = "",
    representante_documento: Corto = "",
    representante_parentesco: Corto = "",
):
    errores: list[str] = []
    try:
        async with _sesion(request, laboratorio, activa) as sesion:
            paciente = await _cargar_o_404(sesion, paciente_uuid)
            config = await servicio.config_pais(sesion, laboratorio.pais)
            texto = await servicio.texto_vigente(sesion)
            menor = servicio.es_menor(paciente["fecha_nacimiento"], _hoy(laboratorio), config.mayoria_edad)
            representante, errores = servicio.validar_representante(
                {
                    "representante_nombre": representante_nombre,
                    "representante_documento": representante_documento,
                    "representante_parentesco": representante_parentesco,
                },
                menor,
            )
            autorizacion, errores_aut = _autorizacion(medio, acepto, texto, representante)
            errores += errores_aut
            if paciente["estado"] != "ACTIVO":
                errores.append("error_suprimido")
            elif paciente["autorizado"]:
                errores.append("error_ya_autorizado")
            if not errores:
                await servicio.otorgar(sesion, paciente["id"], autorizacion)
    except IntegrityError:
        errores.append("error_ya_autorizado")  # dos registros simultáneos: la base deja uno
    if errores:
        textos = _textos(errores, laboratorio.idioma)
        return await _ficha(request, laboratorio, activa, paciente_uuid, errores=textos, estado=400)
    return redirigir(request, f"/pacientes/{paciente_uuid}")


@router.post("/pacientes/{paciente_uuid}/revocar")
async def revocar(
    request: Request,
    laboratorio: LaboratorioActual,
    paciente_uuid: UUID,
    _csrf: Csrf,
    activa: Modificar,
    canal: Corto = "",
    motivo: Annotated[TextoSeguro, Form(max_length=500)] = "",
):
    errores = []
    if canal not in servicio.CANALES:
        errores.append("error_canal")
    if not motivo.strip():
        errores.append("error_motivo")
    if not errores:
        async with _sesion(request, laboratorio, activa) as sesion:
            paciente = await _cargar_o_404(sesion, paciente_uuid)
            if await servicio.revocar(sesion, paciente["id"], motivo.strip()):
                # La revocación es una solicitud del titular atendida en el acto.
                config = await servicio.config_pais(sesion, laboratorio.pais)
                vence = await servicio.vencimiento(
                    sesion, laboratorio.pais, laboratorio.zona_horaria, "REVOCACION", config
                )
                await servicio.crear_solicitud(
                    sesion,
                    paciente["id"],
                    "REVOCACION",
                    canal,
                    motivo.strip(),
                    vence,
                    resuelta="RESUELTA",
                    respuesta=t("pacientes.respuesta_revocada", laboratorio.idioma),
                )
            else:
                errores.append("error_sin_autorizacion_vigente")
    if errores:
        textos = _textos(errores, laboratorio.idioma)
        return await _ficha(request, laboratorio, activa, paciente_uuid, errores=textos, estado=400)
    return redirigir(request, f"/pacientes/{paciente_uuid}")


# --- Solicitudes del titular ---


@router.post("/pacientes/{paciente_uuid}/solicitudes")
async def solicitud_nueva(
    request: Request,
    laboratorio: LaboratorioActual,
    paciente_uuid: UUID,
    _csrf: Csrf,
    activa: Modificar,
    tipo: Corto = "",
    canal: Corto = "",
    descripcion: Largo = "",
):
    errores = []
    # La revocación tiene su propio formulario (se atiende en el acto).
    if tipo not in servicio.TIPOS_SOLICITUD or tipo == "REVOCACION":
        errores.append("error_tipo_solicitud")
    if canal not in servicio.CANALES:
        errores.append("error_canal")
    if not errores:
        async with _sesion(request, laboratorio, activa) as sesion:
            paciente = await _cargar_o_404(sesion, paciente_uuid)
            if paciente["estado"] != "ACTIVO":
                errores.append("error_suprimido")
            else:
                config = await servicio.config_pais(sesion, laboratorio.pais)
                vence = await servicio.vencimiento(sesion, laboratorio.pais, laboratorio.zona_horaria, tipo, config)
                await servicio.crear_solicitud(sesion, paciente["id"], tipo, canal, descripcion.strip() or None, vence)
    if errores:
        textos = _textos(errores, laboratorio.idioma)
        return await _ficha(request, laboratorio, activa, paciente_uuid, errores=textos, estado=400)
    return redirigir(request, f"/pacientes/{paciente_uuid}")


@router.post("/pacientes/solicitudes/{solicitud_uuid}/resolver")
async def solicitud_resolver(
    request: Request,
    laboratorio: LaboratorioActual,
    solicitud_uuid: UUID,
    _csrf: Csrf,
    activa: Modificar,
    estado: Corto = "",
    respuesta: Largo = "",
):
    async with _sesion(request, laboratorio, activa) as sesion:
        fila = (
            await sesion.execute(
                text(
                    "SELECT s.id, s.tipo, p.uuid::text FROM lab.solicitudes_titular s"
                    " JOIN lab.pacientes p ON p.id = s.paciente_id WHERE s.uuid = :u"
                ),
                {"u": solicitud_uuid},
            )
        ).first()
        if fila is None:
            raise HTTPException(status_code=404)
        solicitud_id, tipo, paciente_uuid = fila
    errores = []
    # La supresión se atiende con su propio flujo (anonimiza o rechaza por historia clínica).
    if estado not in ("RESUELTA", "RECHAZADA") or (tipo == "SUPRESION" and estado == "RESUELTA"):
        errores.append("error_estado_solicitud")
    if not respuesta.strip():
        errores.append("error_respuesta")
    if not errores:
        async with _sesion(request, laboratorio, activa) as sesion:
            if not await servicio.resolver(sesion, solicitud_id, estado, respuesta.strip()):
                errores.append("error_solicitud")
    if errores:
        textos = _textos(errores, laboratorio.idioma)
        return await _ficha(request, laboratorio, activa, UUID(paciente_uuid), errores=textos, estado=400)
    return redirigir(request, f"/pacientes/{paciente_uuid}")


@router.get("/pacientes/solicitudes/abiertas")
async def solicitudes_abiertas(request: Request, laboratorio: LaboratorioActual, activa: Consultar):
    async with _sesion(request, laboratorio, activa) as sesion:
        filas = (
            (
                await sesion.execute(
                    text(
                        "SELECT s.tipo, s.canal, s.recibida_en, s.vence_en, p.uuid::text AS paciente,"
                        " p.nombres, p.apellidos FROM lab.solicitudes_titular s"
                        " JOIN lab.pacientes p ON p.id = s.paciente_id"
                        " WHERE s.estado = 'ABIERTA' ORDER BY s.vence_en, s.recibida_en LIMIT 500"
                    )
                )
            )
            .mappings()
            .all()
        )
        await registrar_acceso(sesion, "solicitudes_titular", detalle={"vista": "abiertas", "filas": len(filas)})
    contexto = {"sitio": laboratorio, "activa": activa, "solicitudes": filas, "hoy": _hoy(laboratorio)}
    return render(request, "pacientes/solicitudes.html", contexto)


# --- Supresión ---


@router.post("/pacientes/{paciente_uuid}/suprimir")
async def suprimir(
    request: Request,
    laboratorio: LaboratorioActual,
    paciente_uuid: UUID,
    _csrf: Csrf,
    activa: Eliminar,
    solicitud: Corto = "",
    confirmacion: Corto = "",
):
    idioma = laboratorio.idioma
    errores = []
    if confirmacion.strip().upper() != t("pacientes.palabra_suprimir", idioma).upper():
        errores.append("error_confirmacion")
    suprimido = None
    if not errores:
        async with _sesion(request, laboratorio, activa) as sesion:
            paciente = await _cargar_o_404(sesion, paciente_uuid)
            solicitud_id = await servicio.solicitud_abierta(sesion, paciente["id"], solicitud, ("SUPRESION",))
            if paciente["estado"] != "ACTIVO":
                errores.append("error_suprimido")
            elif solicitud_id is None:
                errores.append("error_solicitud")
            else:
                motivos = {
                    "revocacion": t("pacientes.motivo_supresion", idioma),
                    "rechazo": t("pacientes.respuesta_rechazo_historia", idioma),
                    "suprimido": t("pacientes.respuesta_suprimido", idioma),
                }
                suprimido = await servicio.suprimir(sesion, paciente, solicitud_id, motivos)
    if errores:
        textos = _textos(errores, idioma)
        return await _ficha(request, laboratorio, activa, paciente_uuid, errores=textos, estado=400)
    return redirigir(request, f"/pacientes/{paciente_uuid}?resultado={'suprimido' if suprimido else 'rechazado'}")


# --- Informe para el titular (derecho de consulta) ---


@router.get("/pacientes/{paciente_uuid}/datos")
async def datos_titular(request: Request, laboratorio: LaboratorioActual, paciente_uuid: UUID, activa: Consultar):
    async with _sesion(request, laboratorio, activa) as sesion:
        paciente = await _cargar_o_404(sesion, paciente_uuid)
        autorizaciones = (await sesion.execute(_SQL_AUTORIZACIONES, {"p": paciente["id"]})).mappings().all()
        solicitudes = (await sesion.execute(_SQL_SOLICITUDES, {"p": paciente["id"]})).mappings().all()
        config = await servicio.config_pais(sesion, laboratorio.pais)
        textos = (
            (
                await sesion.execute(
                    text(
                        "SELECT DISTINCT ta.version, ta.contenido FROM lab.textos_autorizacion ta"
                        " JOIN lab.autorizaciones_datos a ON a.texto_id = ta.id WHERE a.paciente_id = :p"
                        " ORDER BY ta.version DESC"
                    ),
                    {"p": paciente["id"]},
                )
            )
            .mappings()
            .all()
        )
        await registrar_acceso(
            sesion,
            "pacientes",
            operacion="EXPORT",
            registro_id=paciente["id"],
            detalle={"vista": "datos_titular", "autorizaciones": len(autorizaciones), "solicitudes": len(solicitudes)},
        )
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "paciente": paciente,
        "tipo_nombre": config.tipos.get(paciente["tipo_documento"], (paciente["tipo_documento"],))[0],
        "pais_nombre": config.paises.get(paciente["pais"], paciente["pais"]),
        "autorizaciones": autorizaciones,
        "solicitudes": solicitudes,
        "textos": textos,
        "generado": datetime.now(ZoneInfo("UTC")),
    }
    return render(request, "pacientes/datos_titular.html", contexto)


# --- Texto de la autorización (configuración del laboratorio) ---


async def _pagina_texto(request, laboratorio, activa, *, borrador=None, errores=(), estado=200):
    async with _sesion(request, laboratorio, activa) as sesion:
        versiones = (
            (
                await sesion.execute(
                    text(
                        "SELECT t.version, t.contenido, t.publicado_en, u.nombre AS publicado_por"
                        " FROM lab.textos_autorizacion t LEFT JOIN lab.usuarios u ON u.uuid = t.publicado_por"
                        " ORDER BY t.version DESC"
                    )
                )
            )
            .mappings()
            .all()
        )
        modelo = await sesion.scalar(
            text("SELECT contenido FROM \"global\".textos_legales WHERE pais = :p AND tipo = 'AUTORIZACION_DATOS'"),
            {"p": laboratorio.pais},
        )
    if borrador is None:
        borrador = (
            versiones[0]["contenido"]
            if versiones
            else (modelo or "").replace("{laboratorio}", laboratorio.nombre_comercial)
        )
    contexto = {
        "sitio": laboratorio,
        "activa": activa,
        "versiones": versiones,
        "borrador": borrador,
        "errores": list(errores),
    }
    return render(request, "pacientes/texto_autorizacion.html", contexto, estado)


@router.get("/configuracion/autorizacion")
async def texto_autorizacion(request: Request, laboratorio: LaboratorioActual, activa: ConsultarConfiguracion):
    return await _pagina_texto(request, laboratorio, activa)


@router.post("/configuracion/autorizacion")
async def publicar_texto(
    request: Request,
    laboratorio: LaboratorioActual,
    _csrf: Csrf,
    activa: ModificarConfiguracion,
    contenido: Annotated[TextoMultilinea, Form(max_length=20000)] = "",
):
    contenido = contenido.strip().replace("\r\n", "\n")
    errores = []
    if not 50 <= len(contenido) <= 20000:
        errores.append("error_texto_largo")
    if "{laboratorio}" in contenido or "[" in contenido:
        errores.append("error_texto_incompleto")
    if not errores:
        try:
            async with _sesion(request, laboratorio, activa) as sesion:
                actual = await servicio.texto_vigente(sesion)
                if actual and actual["contenido"] == contenido:
                    errores.append("error_texto_igual")
                else:
                    await sesion.execute(
                        text(
                            "INSERT INTO lab.textos_autorizacion (version, contenido)"
                            " VALUES (coalesce((SELECT max(version) FROM lab.textos_autorizacion), 0) + 1, :c)"
                        ),
                        {"c": contenido},
                    )
        except IntegrityError:
            errores.append("error_texto_concurrente")  # dos publicaciones simultáneas: gana una
    if errores:
        textos = _textos(errores, laboratorio.idioma)
        return await _pagina_texto(request, laboratorio, activa, borrador=contenido, errores=textos, estado=400)
    return redirigir(request, "/configuracion/autorizacion")
