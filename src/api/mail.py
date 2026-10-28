"""
Outgoing email.

IDS_MAIL_BACKEND=smtp sends through IDS_SMTP_HOST: any SMTP service works (Gmail with an app
password, Resend, Brevo, or the Mailpit catcher of the Compose profile `mail`). The default, console,
only writes the message to the log, for development without a mail server.

Messages go out after the response (FastAPI BackgroundTasks), so a slow or failing mail server never
holds up a request; a failure is logged and the user can ask for another email.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid

from src.api.settings import get_settings

log = logging.getLogger("ids.mail")
SMTP_TIMEOUT = 15     # seconds per SMTP command


@dataclass
class Message:
    to: str
    subject: str
    text: str
    html: str


def send(message: Message) -> None:
    """Send now (raises on failure)."""
    settings = get_settings()
    if settings.mail_backend == "console":
        log.warning("Email not sent (IDS_MAIL_BACKEND=console): %s", message.subject,
                    extra={"to": message.to, "body": message.text})
        return

    email = EmailMessage()
    email["From"] = settings.mail_from
    email["To"] = message.to
    email["Subject"] = message.subject
    email["Message-ID"] = make_msgid(domain=settings.mail_from.rpartition("@")[2].strip("> ") or None)
    email.set_content(message.text)
    email.add_alternative(message.html, subtype="html")

    context = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT, context=context)
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT)
    with smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls(context=context)
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(email)
    log.info("Email sent: %s", message.subject, extra={"to": message.to})


def send_quietly(message: Message) -> None:
    """send() for a background task: a failure is logged, never raised."""
    try:
        send(message)
    except Exception:
        log.exception("Could not send email: %s", message.subject, extra={"to": message.to})
