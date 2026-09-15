"""
Outgoing email (SEC-30) - plain SMTP from the standard library.

One kind of message leaves this app: a password-reset link. Nothing from
anyone's budget is ever put in an email - an inbox is outside the encryption
boundary, and every mail server on the way keeps a copy.

When ENVIRONMENT=test, or SMTP is not configured, nothing is sent: the message
is appended to OUTBOX instead. Tests read it there, and no test run can ever
mail a real person.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import List

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str = field(repr=False)
    html: str = field(repr=False)


OUTBOX: List[Message] = []


def can_send() -> bool:
    return settings.email_enabled and settings.ENVIRONMENT != "test"


def send(message: Message) -> bool:
    """Send one message. Never raises - a failure is logged and returns False."""
    if not can_send():
        OUTBOX.append(message)
        logger.info("Email not sent - SMTP is off or this is a test run subject=%r", message.subject)
        return False

    sender = settings.SMTP_FROM.strip() or settings.SMTP_USER
    msg = EmailMessage()
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, sender))
    msg["To"] = message.to
    msg["Subject"] = message.subject
    msg["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2] or None)
    msg.set_content(message.text)
    msg.add_alternative(message.html, subtype="html")
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT_SECONDS) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD.get_secret_value())
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError):
        logger.exception("Email could not be sent subject=%r", message.subject)
        return False
    logger.info("Email sent subject=%r", message.subject)
    return True
