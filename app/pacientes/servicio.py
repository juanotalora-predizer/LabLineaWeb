"""Reglas de pacientes y de la Ley 1581 (spec funcional/0010), sin HTTP.

- Validación de los datos del paciente con la configuración del país (tipos de documento y su expresión,
  mayoría de edad): nada de un país escrito aquí.
- Búsqueda sin enumeración: documento exacto o nombre con al menos 3 caracteres, máximo 20 resultados.
- Autorización versionada, revocación, solicitudes del titular con vencimiento en días hábiles y
  supresión por anonimización.

Todo corre dentro de `sesion_tenant` (RLS). Los errores se devuelven como claves del catálogo de textos,
nunca con el dato que los causó.
"""

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SEXOS = ("F", "M", "I")
MEDIOS = ("FORMATO_FIRMADO", "ACEPTACION_EN_PANTALLA")
TIPOS_SOLICITUD = ("CONSULTA", "ACTUALIZACION", "RECTIFICACION", "SUPRESION", "REVOCACION")
CANALES = ("PRESENCIAL", "CORREO", "TELEFONO", "PORTAL")
# Solicitudes que permiten modificar los datos de un paciente sin autorización vigente.
PARA_EDITAR = ("ACTUALIZACION", "RECTIFICACION")
EDAD_MAXIMA = 150

MAX_RESULTADOS = 20
MIN_BUSQUEDA = 3
MAX_PALABRAS = 4
LIMITE_BUSQUEDAS = 60
VENTANA_BUSQUEDAS_MIN = 5

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
_TELEFONO = re.compile(r"^[0-9+() -]{5,30}$")
_FECHA = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_DOCUMENTO = re.compile(r"^[A-Z0-9-]{3,20}$")
# Marca de un registro suprimido: sin datos personales, con un documento que no choca con ninguno real.
SUPRIMIDO = "-"


@dataclass(frozen=True)
class ConfigPais:
    tipos: dict[str, tuple[str, str]]  # codigo → (nombre, expresión del número)
    paises: dict[str, str]  # codigo → nombre (país de residencia)
    mayoria_edad: int
    plazo_consulta: int
    plazo_reclamo: int


async def config_pais(sesion: AsyncSession, pais: str) -> ConfigPais:
    tipos = (
        await sesion.execute(
            text(
                'SELECT codigo, nombre, patron FROM "global".tipos_documento'
                " WHERE pais = :p AND aplica_a = 'PERSONA' AND activo ORDER BY nombre"
            ),
            {"p": pais},
        )
    ).all()
    paises = (await sesion.execute(text('SELECT codigo, nombre FROM "global".paises ORDER BY nombre'))).all()
    fila = (
        await sesion.execute(
            text('SELECT mayoria_edad, plazo_consulta_dias, plazo_reclamo_dias FROM "global".paises WHERE codigo = :p'),
            {"p": pais},
        )
    ).one()
    return ConfigPais(
        tipos={c: (n, p) for c, n, p in tipos},
        paises=dict(paises),
        mayoria_edad=fila[0],
        plazo_consulta=fila[1],
        plazo_reclamo=fila[2],
    )


def normalizar_documento(numero: str) -> str:
    """Sin espacios ni puntos de miles (1.234.567 → 1234567) y en mayúsculas."""
    return re.sub(r"[\s.]", "", numero).upper()


def edad_anios(nacimiento: date, hoy: date) -> int:
    return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))


def es_menor(nacimiento: date | None, hoy: date, mayoria: int) -> bool:
    return nacimiento is not None and edad_anios(nacimiento, hoy) < mayoria


def validar(datos: dict[str, str], config: ConfigPais, hoy: date) -> tuple[dict, list[str]]:
    """Datos limpios y claves de error de los textos `pacientes.error_*`."""
    errores: list[str] = []
    limpio = {clave: (valor or "").strip() for clave, valor in datos.items()}
    limpio["numero_documento"] = normalizar_documento(limpio.get("numero_documento", ""))
    tipo = config.tipos.get(limpio.get("tipo_documento", ""))
    if tipo is None:
        errores.append("error_tipo_documento")
    elif not re.fullmatch(tipo[1] or _DOCUMENTO.pattern, limpio["numero_documento"]):
        errores.append("error_documento")
    for campo in ("nombres", "apellidos"):
        limpio[campo] = " ".join(limpio.get(campo, "").split())
        if not 1 <= len(limpio[campo]) <= 80:
            errores.append(f"error_{campo}")
    if limpio.get("sexo") not in SEXOS:
        errores.append("error_sexo")
    nacimiento = None
    if _FECHA.fullmatch(limpio.get("fecha_nacimiento", "")):
        try:
            nacimiento = date.fromisoformat(limpio["fecha_nacimiento"])
        except ValueError:
            nacimiento = None
    if nacimiento is None or nacimiento > hoy or edad_anios(nacimiento, hoy) > EDAD_MAXIMA:
        errores.append("error_nacimiento")
    limpio["fecha_nacimiento"] = nacimiento
    if limpio.get("pais") not in config.paises:
        errores.append("error_pais")
    limpio["email"] = limpio.get("email", "").lower() or None
    if limpio["email"] and (len(limpio["email"]) > 254 or not _EMAIL.match(limpio["email"])):
        errores.append("error_email")
    limpio["telefono"] = limpio.get("telefono") or None
    if limpio["telefono"] and not _TELEFONO.match(limpio["telefono"]):
        errores.append("error_telefono")
    limpio["direccion"] = limpio.get("direccion") or None
    if limpio["direccion"] and len(limpio["direccion"]) > 200:
        errores.append("error_direccion")
    return limpio, errores


def validar_representante(datos: dict[str, str], menor: bool) -> tuple[dict, list[str]]:
    """El representante legal es obligatorio para menores de edad (Ley 1581, art. 7) y no aplica a adultos."""
    limpio = {
        "representante_nombre": " ".join((datos.get("representante_nombre") or "").split()) or None,
        "representante_documento": normalizar_documento(datos.get("representante_documento") or "") or None,
        "representante_parentesco": (datos.get("representante_parentesco") or "").strip() or None,
    }
    if not menor:
        return dict.fromkeys(limpio), []
    valido = (
        limpio["representante_nombre"]
        and len(limpio["representante_nombre"]) <= 120
        and limpio["representante_documento"]
        and _DOCUMENTO.match(limpio["representante_documento"])
        and limpio["representante_parentesco"]
        and len(limpio["representante_parentesco"]) <= 40
    )
    return limpio, [] if valido else ["error_representante"]


# --- Búsqueda ---

_SQL_BUSCAR_DOCUMENTO = text(
    "SELECT uuid::text AS uuid, tipo_documento, numero_documento, nombres, apellidos, sexo, fecha_nacimiento,"
    " lab.autorizacion_vigente(id) AS autorizado FROM lab.pacientes"
    " WHERE estado = 'ACTIVO' AND numero_documento = :doc ORDER BY tipo_documento LIMIT :limite"
)
_SQL_BUSCAR_NOMBRE = text(
    "SELECT uuid::text AS uuid, tipo_documento, numero_documento, nombres, apellidos, sexo, fecha_nacimiento,"
    " lab.autorizacion_vigente(id) AS autorizado FROM lab.pacientes"
    " WHERE estado = 'ACTIVO' AND (nombres || ' ' || apellidos) ILIKE :p1"
    "   AND (CAST(:p2 AS text) IS NULL OR (nombres || ' ' || apellidos) ILIKE :p2)"
    "   AND (CAST(:p3 AS text) IS NULL OR (nombres || ' ' || apellidos) ILIKE :p3)"
    "   AND (CAST(:p4 AS text) IS NULL OR (nombres || ' ' || apellidos) ILIKE :p4)"
    " ORDER BY apellidos, nombres LIMIT :limite"
)


def _patron(palabra: str) -> str:
    return "%" + re.sub(r"([%_\\])", r"\\\1", palabra) + "%"


def modo_busqueda(consulta: str) -> str | None:
    """'documento' si parece un número de documento (tiene dígitos), 'nombre' si no; None si es muy corta."""
    consulta = " ".join(consulta.split())
    if len(consulta) < MIN_BUSQUEDA:
        return None
    documento = normalizar_documento(consulta)
    return "documento" if _DOCUMENTO.match(documento) and any(c.isdigit() for c in documento) else "nombre"


async def buscar(sesion: AsyncSession, consulta: str) -> tuple[str | None, list[dict], bool]:
    """(modo, resultados, hay_mas). Documento: coincidencia exacta. Nombre: cada palabra en nombres o apellidos."""
    modo = modo_busqueda(consulta)
    if modo is None:
        return None, [], False
    if modo == "documento":
        parametros = {"doc": normalizar_documento(consulta), "limite": MAX_RESULTADOS + 1}
        filas = (await sesion.execute(_SQL_BUSCAR_DOCUMENTO, parametros)).mappings().all()
    else:
        palabras = consulta.split()[:MAX_PALABRAS]
        parametros = {f"p{i + 1}": None for i in range(MAX_PALABRAS)}
        parametros.update({f"p{i + 1}": _patron(p) for i, p in enumerate(palabras)})
        filas = (
            (await sesion.execute(_SQL_BUSCAR_NOMBRE, {**parametros, "limite": MAX_RESULTADOS + 1})).mappings().all()
        )
    return modo, [dict(f) for f in filas[:MAX_RESULTADOS]], len(filas) > MAX_RESULTADOS


# --- Paciente ---


async def cargar(sesion: AsyncSession, paciente_uuid) -> dict | None:
    fila = (
        (
            await sesion.execute(
                text(
                    "SELECT id, uuid::text AS uuid, tipo_documento, numero_documento, nombres, apellidos, sexo,"
                    " fecha_nacimiento, pais, email, telefono, direccion, estado, creado_en, actualizado_en,"
                    " suprimido_en, lab.autorizacion_vigente(id) AS autorizado"
                    " FROM lab.pacientes WHERE uuid = :u"
                ),
                {"u": paciente_uuid},
            )
        )
        .mappings()
        .first()
    )
    return dict(fila) if fila else None


async def texto_vigente(sesion: AsyncSession) -> dict | None:
    fila = (
        (
            await sesion.execute(
                text(
                    "SELECT id, version, contenido, publicado_en FROM lab.textos_autorizacion"
                    " ORDER BY version DESC LIMIT 1"
                )
            )
        )
        .mappings()
        .first()
    )
    return dict(fila) if fila else None


_SQL_INSERTAR_AUTORIZACION = text(
    "INSERT INTO lab.autorizaciones_datos (paciente_id, texto_id, medio, representante_nombre,"
    " representante_documento, representante_parentesco)"
    " VALUES (:paciente, :texto, :medio, :representante_nombre, :representante_documento,"
    " :representante_parentesco)"
)


async def registrar(sesion: AsyncSession, datos: dict, autorizacion: dict) -> str:
    """Paciente y su autorización en la misma transacción (la base rechaza un paciente sin autorización)."""
    fila = (
        await sesion.execute(
            text(
                "INSERT INTO lab.pacientes (tipo_documento, numero_documento, nombres, apellidos, sexo,"
                " fecha_nacimiento, pais, email, telefono, direccion)"
                " VALUES (:tipo_documento, :numero_documento, :nombres, :apellidos, :sexo, :fecha_nacimiento,"
                " :pais, :email, :telefono, :direccion) RETURNING id, uuid::text"
            ),
            {
                k: datos[k]
                for k in (
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
            },
        )
    ).one()
    await sesion.execute(_SQL_INSERTAR_AUTORIZACION, {"paciente": fila[0], **autorizacion})
    return fila[1]


async def otorgar(sesion: AsyncSession, paciente_id: int, autorizacion: dict) -> None:
    """Autorización nueva (el titular vuelve a otorgarla). Una sola vigente: la base lo garantiza."""
    await sesion.execute(_SQL_INSERTAR_AUTORIZACION, {"paciente": paciente_id, **autorizacion})


async def actualizar(sesion: AsyncSession, paciente_id: int, datos: dict) -> None:
    await sesion.execute(
        text(
            "UPDATE lab.pacientes SET tipo_documento = :tipo_documento, numero_documento = :numero_documento,"
            " nombres = :nombres, apellidos = :apellidos, sexo = :sexo, fecha_nacimiento = :fecha_nacimiento,"
            " pais = :pais, email = :email, telefono = :telefono, direccion = :direccion, actualizado_en = now()"
            " WHERE id = :id AND estado = 'ACTIVO'"
        ),
        {**{k: datos[k] for k in datos if k != "id"}, "id": paciente_id},
    )


async def revocar(sesion: AsyncSession, paciente_id: int, motivo: str) -> bool:
    """Revoca la autorización vigente. False si no había ninguna."""
    revocada = await sesion.scalar(
        text(
            "UPDATE lab.autorizaciones_datos SET revocada_en = now(), motivo_revocacion = :m,"
            " revocada_por = NULLIF(current_setting('app.current_user_id', true), '')::uuid"
            " WHERE paciente_id = :p AND revocada_en IS NULL RETURNING id"
        ),
        {"p": paciente_id, "m": motivo},
    )
    return revocada is not None


# --- Solicitudes del titular ---


async def vencimiento(sesion: AsyncSession, pais: str, zona: str, tipo: str, config: ConfigPais) -> date:
    """Días hábiles del país desde hoy (fecha local del laboratorio): consulta o reclamo (Ley 1581, arts. 14 y 15)."""
    dias = config.plazo_consulta if tipo == "CONSULTA" else config.plazo_reclamo
    return await sesion.scalar(
        text('SELECT "global".sumar_dias_habiles(:pais, (now() AT TIME ZONE :zona)::date, :dias)'),
        {"pais": pais, "zona": zona, "dias": dias},
    )


async def crear_solicitud(
    sesion: AsyncSession,
    paciente_id: int,
    tipo: str,
    canal: str,
    descripcion: str | None,
    vence_en: date,
    *,
    resuelta: str | None = None,
    respuesta: str | None = None,
) -> str:
    """Registra la solicitud; con `resuelta` ('RESUELTA' o 'RECHAZADA') la deja atendida en el acto."""
    return await sesion.scalar(
        text(
            "INSERT INTO lab.solicitudes_titular (paciente_id, tipo, canal, descripcion, vence_en, estado,"
            " respuesta, resuelta_en, resuelta_por)"
            " VALUES (:p, :tipo, :canal, :descripcion, :vence, coalesce(CAST(:estado AS text), 'ABIERTA'),"
            " :respuesta, CASE WHEN CAST(:estado AS text) IS NULL THEN NULL ELSE now() END,"
            " CASE WHEN CAST(:estado AS text) IS NULL THEN NULL"
            "      ELSE NULLIF(current_setting('app.current_user_id', true), '')::uuid END)"
            " RETURNING uuid::text"
        ),
        {
            "p": paciente_id,
            "tipo": tipo,
            "canal": canal,
            "descripcion": descripcion,
            "vence": vence_en,
            "estado": resuelta,
            "respuesta": respuesta,
        },
    )


async def resolver(sesion: AsyncSession, solicitud_id: int, estado: str, respuesta: str | None) -> bool:
    resuelta = await sesion.scalar(
        text(
            "UPDATE lab.solicitudes_titular SET estado = :e, respuesta = :r, resuelta_en = now(),"
            " resuelta_por = NULLIF(current_setting('app.current_user_id', true), '')::uuid"
            " WHERE id = :id AND estado = 'ABIERTA' RETURNING id"
        ),
        {"id": solicitud_id, "e": estado, "r": respuesta},
    )
    return resuelta is not None


async def solicitud_abierta(sesion: AsyncSession, paciente_id: int, solicitud_uuid: str, tipos) -> int | None:
    """Id de una solicitud abierta del paciente con uno de los `tipos`, o None."""
    if not re.fullmatch(r"[0-9a-f-]{36}", solicitud_uuid or ""):
        return None
    return await sesion.scalar(
        text(
            "SELECT id FROM lab.solicitudes_titular WHERE uuid = CAST(:u AS uuid) AND paciente_id = :p"
            " AND estado = 'ABIERTA' AND tipo = ANY(:tipos)"
        ),
        {"u": solicitud_uuid, "p": paciente_id, "tipos": list(tipos)},
    )


async def suprimir(sesion: AsyncSession, paciente: dict, solicitud_id: int, motivos: dict[str, str]) -> bool:
    """Atiende una solicitud de supresión. True si se anonimizó; False si se rechazó por historia clínica.

    `motivos` trae los textos (del idioma del laboratorio) para la revocación y las respuestas: la base no
    guarda textos escritos en el código.
    """
    paciente_id = paciente["id"]
    if await sesion.scalar(text("SELECT lab.paciente_tiene_historia(:p)"), {"p": paciente_id}):
        await revocar(sesion, paciente_id, motivos["revocacion"])
        await resolver(sesion, solicitud_id, "RECHAZADA", motivos["rechazo"])
        return False
    await revocar(sesion, paciente_id, motivos["revocacion"])
    await sesion.execute(
        text(
            "UPDATE lab.autorizaciones_datos SET representante_nombre = NULL, representante_documento = NULL,"
            " representante_parentesco = NULL WHERE paciente_id = :p"
        ),
        {"p": paciente_id},
    )
    await resolver(sesion, solicitud_id, "RESUELTA", motivos["suprimido"])
    await sesion.execute(
        text(
            "UPDATE lab.solicitudes_titular SET descripcion = NULL,"
            " respuesta = CASE WHEN id = :s THEN respuesta ELSE NULL END WHERE paciente_id = :p"
        ),
        {"p": paciente_id, "s": solicitud_id},
    )
    await sesion.execute(
        text(
            "UPDATE lab.pacientes SET nombres = :marca, apellidos = :marca, sexo = 'I', fecha_nacimiento = NULL,"
            " numero_documento = 'SUPRIMIDO-' || uuid::text, email = NULL, telefono = NULL, direccion = NULL,"
            " estado = 'SUPRIMIDO', suprimido_en = now(), actualizado_en = now() WHERE id = :p"
        ),
        {"p": paciente_id, "marca": SUPRIMIDO},
    )
    return True
