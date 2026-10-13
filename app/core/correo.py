"""Envío de correo (spec infraestructura/0003: nunca datos clínicos en el correo).

En local apunta a un servidor de captura (python -m aiosmtpd -n -l 127.0.0.1:1025).
El transporte cifrado y autenticado del proveedor se configura en la etapa de publicación.
"""

import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


def _enviar_sync(mensaje: EmailMessage) -> None:
    settings = get_settings()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as servidor:
        servidor.send_message(mensaje)


async def enviar(destinatario: str, asunto: str, cuerpo: str) -> None:
    mensaje = EmailMessage()
    mensaje["From"] = get_settings().smtp_remitente
    mensaje["To"] = destinatario  # EmailMessage rechaza saltos de línea: sin inyección de cabeceras
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)
    await asyncio.to_thread(_enviar_sync, mensaje)
