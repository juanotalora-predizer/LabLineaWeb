"""Acceso a datos de autenticación de los dos sitios: laboratorios y Admin Hub.

Todas las funciones reciben una sesión abierta con `sesion_tenant` (esquema lab, bajo RLS: cada
consulta queda limitada al laboratorio de la petición) o con `sesion_plataforma` (esquema plataforma).
Los nombres de tabla van sin esquema: los resuelve el search_path que fija la sesión."""

import secrets
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import contrasenas
from app.core import cripto

CODIGO_VIGENCIA_MIN = 5
CODIGO_MAX_INTENTOS = 5
CODIGOS_POR_HORA = 5


@dataclass(frozen=True)
class Usuario:
    id: int
    uuid: str
    ambito: str  # laboratorio (tenant_id) o 'plataforma'
    email: str
    nombre: str
    tipo: str
    password_hash: str
    totp_secreto_cifrado: bytes | None
    totp_confirmado: bool
    totp_ultimo_contador: int | None
    tarjeta_profesional: str | None

    @property
    def usa_totp(self) -> bool:
        return self.tipo == "PERSONAL" and self.totp_confirmado

    @property
    def debe_inscribir_totp(self) -> bool:
        return self.tipo == "PERSONAL" and not self.totp_confirmado

    def contexto_totp(self) -> str:
        return f"{self.ambito}:{self.uuid}:totp"


@dataclass(frozen=True)
class Permisos:
    roles: tuple[str, ...] = ()
    modulos: dict[str, frozenset[str]] = field(default_factory=dict)
    acciones: frozenset[str] = frozenset()

    def puede(self, modulo: str, operacion: str) -> bool:
        return operacion in self.modulos.get(modulo, frozenset())


# SQL literal completo (sin interpolar): el analizador de seguridad no admite consultas armadas con f-strings.
_SQL_USUARIO_POR_EMAIL = text(
    "SELECT id, uuid::text AS uuid, ambito_actual() AS ambito, email::text AS email, nombre, tipo, password_hash,"
    " totp_secreto_cifrado, totp_confirmado, totp_ultimo_contador, tarjeta_profesional"
    " FROM usuarios WHERE email = :e AND estado = 'ACTIVO'"
)
_SQL_USUARIO_POR_ID = text(
    "SELECT id, uuid::text AS uuid, ambito_actual() AS ambito, email::text AS email, nombre, tipo, password_hash,"
    " totp_secreto_cifrado, totp_confirmado, totp_ultimo_contador, tarjeta_profesional"
    " FROM usuarios WHERE id = :i AND estado = 'ACTIVO'"
)


async def buscar_usuario_por_email(sesion: AsyncSession, email: str) -> Usuario | None:
    fila = (await sesion.execute(_SQL_USUARIO_POR_EMAIL, {"e": email})).mappings().first()
    return Usuario(**fila) if fila else None


async def buscar_usuario(sesion: AsyncSession, usuario_id: int) -> Usuario | None:
    fila = (await sesion.execute(_SQL_USUARIO_POR_ID, {"i": usuario_id})).mappings().first()
    return Usuario(**fila) if fila else None


async def crear_usuario(
    sesion: AsyncSession,
    *,
    email: str,
    nombre: str,
    tipo: str,
    clave: str | None,
    roles: tuple[str, ...] = (),
    tarjeta_profesional: str | None = None,
) -> int:
    usuario_id = await sesion.scalar(
        text(
            "INSERT INTO usuarios (email, nombre, tipo, password_hash, tarjeta_profesional)"
            " VALUES (:e, :n, :t, :h, :tp) RETURNING id"
        ),
        {
            "e": email,
            "n": nombre,
            "t": tipo,
            # Sin contraseña: la crea el propio usuario con su invitación (app/auth/invitaciones.py).
            "h": contrasenas.hashear(clave, email) if clave is not None else None,
            "tp": tarjeta_profesional,
        },
    )
    for codigo in roles:
        await sesion.execute(
            text("INSERT INTO usuario_roles (usuario_id, rol_id) SELECT :u, id FROM roles WHERE codigo = :c"),
            {"u": usuario_id, "c": codigo},
        )
    return usuario_id


async def actualizar_hash(sesion: AsyncSession, usuario_id: int, nuevo_hash: str) -> None:
    await sesion.execute(
        text("UPDATE usuarios SET password_hash = :h WHERE id = :i"), {"h": nuevo_hash, "i": usuario_id}
    )


async def marcar_bloqueo(sesion: AsyncSession, usuario_id: int, minutos: int) -> None:
    await sesion.execute(
        text("UPDATE usuarios SET bloqueado_hasta = now() + make_interval(mins => :m) WHERE id = :i"),
        {"m": minutos, "i": usuario_id},
    )


# --- Eventos de seguridad (solo inserción) ---


async def registrar_evento(
    sesion: AsyncSession, tipo: str, *, usuario_id: int | None = None, email: str | None = None, ip: str | None = None
) -> None:
    await sesion.execute(
        text("INSERT INTO eventos_seguridad (tipo, usuario_id, email, ip) VALUES (:t, :u, :e, CAST(:ip AS inet))"),
        {"t": tipo, "u": usuario_id, "e": email, "ip": ip},
    )


# --- Límites por ventana de tiempo ---


async def limite_contar(sesion: AsyncSession, clave: str, ventana_min: int) -> int:
    valor = await sesion.scalar(
        text("SELECT contador FROM limites WHERE clave = :c AND ventana_desde > now() - make_interval(mins => :v)"),
        {"c": clave, "v": ventana_min},
    )
    return valor or 0


async def limite_sumar(sesion: AsyncSession, clave: str, ventana_min: int) -> int:
    """Suma uno al contador de la ventana vigente (o abre una nueva) y devuelve el total."""
    return await sesion.scalar(
        text(
            "INSERT INTO limites (clave, ventana_desde, contador) VALUES (:c, now(), 1)"
            " ON CONFLICT ON CONSTRAINT limites_pkey DO UPDATE SET"
            "  contador = CASE WHEN limites.ventana_desde <= now() - make_interval(mins => :v)"
            "             THEN 1 ELSE limites.contador + 1 END,"
            "  ventana_desde = CASE WHEN limites.ventana_desde <= now() - make_interval(mins => :v)"
            "                  THEN now() ELSE limites.ventana_desde END"
            " RETURNING contador"
        ),
        {"c": clave, "v": ventana_min},
    )


async def limite_reiniciar(sesion: AsyncSession, clave: str) -> None:
    await sesion.execute(text("UPDATE limites SET contador = 0 WHERE clave = :c"), {"c": clave})


# --- Sesiones ---


@dataclass(frozen=True)
class FilaSesion:
    id: int
    usuario_id: int
    segundo_factor_ok: bool


async def crear_sesion(
    sesion: AsyncSession, usuario_id: int, *, segundo_factor_ok: bool, minutos: int, ip: str | None, agente: str | None
) -> str:
    token = cripto.token_aleatorio()
    await sesion.execute(
        text(
            "INSERT INTO sesiones (usuario_id, token_hash, segundo_factor_ok, expira_en, ip, agente)"
            " VALUES (:u, :h, :f, now() + make_interval(mins => :m), CAST(:ip AS inet), :a)"
        ),
        {"u": usuario_id, "h": cripto.hash_token(token), "f": segundo_factor_ok, "m": minutos, "ip": ip, "a": agente},
    )
    return token


async def obtener_sesion(sesion: AsyncSession, token: str, inactividad_min: int) -> FilaSesion | None:
    fila = (
        (
            await sesion.execute(
                text(
                    "UPDATE sesiones s SET ultima_actividad = now()"
                    " FROM usuarios u"
                    " WHERE s.token_hash = :h AND u.id = s.usuario_id AND u.estado = 'ACTIVO'"
                    "   AND s.revocada_en IS NULL AND s.expira_en > now()"
                    "   AND s.ultima_actividad > now() - make_interval(mins => :i)"
                    " RETURNING s.id, s.usuario_id, s.segundo_factor_ok"
                ),
                {"h": cripto.hash_token(token), "i": inactividad_min},
            )
        )
        .mappings()
        .first()
    )
    return FilaSesion(**fila) if fila else None


async def revocar_sesion(sesion: AsyncSession, sesion_id: int) -> None:
    await sesion.execute(text("UPDATE sesiones SET revocada_en = now() WHERE id = :i"), {"i": sesion_id})


async def revocar_sesiones_de(sesion: AsyncSession, usuario_id: int) -> None:
    await sesion.execute(
        text("UPDATE sesiones SET revocada_en = now() WHERE usuario_id = :u AND revocada_en IS NULL"),
        {"u": usuario_id},
    )


# --- Códigos por correo ---


def _contexto_codigo(usuario: Usuario) -> str:
    return f"{usuario.ambito}:{usuario.uuid}:codigo"


async def crear_codigo(sesion: AsyncSession, usuario: Usuario) -> str | None:
    """Genera un código de 6 dígitos; None si ya se enviaron demasiados en la última hora."""
    enviados = await sesion.scalar(
        text(
            "SELECT count(*) FROM codigos_verificacion WHERE usuario_id = :u AND creado_en > now() - interval '1 hour'"
        ),
        {"u": usuario.id},
    )
    if enviados >= CODIGOS_POR_HORA:
        return None
    # Un código nuevo invalida los anteriores.
    await sesion.execute(
        text("UPDATE codigos_verificacion SET usado_en = now() WHERE usuario_id = :u AND usado_en IS NULL"),
        {"u": usuario.id},
    )
    codigo = f"{secrets.randbelow(10**6):06d}"
    await sesion.execute(
        text(
            "INSERT INTO codigos_verificacion (usuario_id, codigo_hmac, expira_en)"
            " VALUES (:u, :h, now() + make_interval(mins => :m))"
        ),
        {"u": usuario.id, "h": cripto.hmac_valor(codigo, _contexto_codigo(usuario)), "m": CODIGO_VIGENCIA_MIN},
    )
    return codigo


async def verificar_codigo(sesion: AsyncSession, usuario: Usuario, codigo: str) -> bool:
    fila = (
        (
            await sesion.execute(
                text(
                    "UPDATE codigos_verificacion SET intentos = intentos + 1"
                    " WHERE id = (SELECT id FROM codigos_verificacion WHERE usuario_id = :u AND usado_en IS NULL"
                    "             AND expira_en > now() AND intentos < :max ORDER BY creado_en DESC LIMIT 1"
                    "             FOR UPDATE)"
                    " RETURNING id, codigo_hmac"
                ),
                {"u": usuario.id, "max": CODIGO_MAX_INTENTOS},
            )
        )
        .mappings()
        .first()
    )
    if fila is None or not secrets.compare_digest(
        bytes(fila["codigo_hmac"]), cripto.hmac_valor(codigo.strip(), _contexto_codigo(usuario))
    ):
        return False
    await sesion.execute(text("UPDATE codigos_verificacion SET usado_en = now() WHERE id = :i"), {"i": fila["id"]})
    return True


# --- TOTP ---


async def guardar_totp(sesion: AsyncSession, usuario: Usuario, secreto: str) -> None:
    await sesion.execute(
        text("UPDATE usuarios SET totp_secreto_cifrado = :s, totp_confirmado = false WHERE id = :i"),
        {"s": cripto.cifrar(secreto.encode(), usuario.contexto_totp()), "i": usuario.id},
    )


async def confirmar_totp(sesion: AsyncSession, usuario_id: int, contador: int) -> None:
    await sesion.execute(
        text("UPDATE usuarios SET totp_confirmado = true, totp_ultimo_contador = :c WHERE id = :i"),
        {"c": contador, "i": usuario_id},
    )


async def registrar_contador_totp(sesion: AsyncSession, usuario_id: int, contador: int) -> bool:
    """Guarda el último contador usado; False si el código ya se había usado (repetición)."""
    actualizado = await sesion.scalar(
        text(
            "UPDATE usuarios SET totp_ultimo_contador = :c"
            " WHERE id = :i AND (totp_ultimo_contador IS NULL OR totp_ultimo_contador < :c) RETURNING id"
        ),
        {"c": contador, "i": usuario_id},
    )
    return actualizado is not None


# --- Permisos ---


async def cargar_permisos(sesion: AsyncSession, usuario_id: int) -> Permisos:
    roles = (
        await sesion.execute(
            text(
                "SELECT r.codigo FROM usuario_roles ur JOIN roles r ON r.id = ur.rol_id"
                " WHERE ur.usuario_id = :u ORDER BY r.codigo"
            ),
            {"u": usuario_id},
        )
    ).scalars()
    modulos: dict[str, set[str]] = {}
    filas = await sesion.execute(
        text(
            "SELECT rp.modulo, bool_or(rp.consultar) AS consultar, bool_or(rp.crear) AS crear,"
            " bool_or(rp.modificar) AS modificar, bool_or(rp.eliminar) AS eliminar"
            " FROM usuario_roles ur JOIN rol_permisos rp ON rp.rol_id = ur.rol_id"
            " WHERE ur.usuario_id = :u GROUP BY rp.modulo"
        ),
        {"u": usuario_id},
    )
    for fila in filas.mappings():
        modulos[fila["modulo"]] = {op for op in ("consultar", "crear", "modificar", "eliminar") if fila[op]}
    acciones = (
        await sesion.execute(
            text(
                "SELECT DISTINCT ra.accion FROM usuario_roles ur JOIN rol_acciones ra ON ra.rol_id = ur.rol_id"
                " WHERE ur.usuario_id = :u"
            ),
            {"u": usuario_id},
        )
    ).scalars()
    return Permisos(
        roles=tuple(roles),
        modulos={m: frozenset(ops) for m, ops in modulos.items()},
        acciones=frozenset(acciones),
    )
