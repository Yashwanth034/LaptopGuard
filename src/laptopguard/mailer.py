from __future__ import annotations

from email.message import EmailMessage
import mimetypes
from pathlib import Path
import smtplib

from .config import MailSettings


def build_message(from_address: str, to_address: str, subject: str, body: str, attachments: list[Path]) -> EmailMessage:
    msg = EmailMessage()
    msg['From'] = from_address
    msg['To'] = to_address
    msg['Subject'] = subject
    msg.set_content(body)
    for attachment in attachments:
        path = Path(attachment)
        if not path.is_file():
            continue
        mime, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (mime or 'application/octet-stream').split('/', 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    return msg


def _connect(settings: MailSettings, timeout: float = 15):
    if settings.use_ssl:
        return smtplib.SMTP_SSL(settings.host, settings.port, timeout=timeout)
    smtp = smtplib.SMTP(settings.host, settings.port, timeout=timeout)
    smtp.starttls()
    return smtp


def probe(settings: MailSettings) -> None:
    password = settings.password()
    if not all([settings.host, settings.username, password]):
        raise RuntimeError('mail configuration is incomplete')
    with _connect(settings) as smtp:
        smtp.login(settings.username, password)
        smtp.noop()


def send(settings: MailSettings, subject: str, body: str, attachments: list[Path], timeout: float = 15) -> None:
    password = settings.password()
    if not settings.enabled:
        raise RuntimeError('mail delivery is disabled')
    if not all([settings.host, settings.username, settings.from_address, settings.to_address, password]):
        raise RuntimeError('mail configuration is incomplete')
    msg = build_message(settings.from_address, settings.to_address, subject, body, attachments)
    with _connect(settings, timeout=timeout) as smtp:
        smtp.login(settings.username, password)
        smtp.send_message(msg)
