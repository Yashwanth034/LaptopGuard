from pathlib import Path
from laptopguard.mailer import build_message


def test_build_message_has_attachment(tmp_path: Path):
    photo = tmp_path / 'photo.jpg'
    photo.write_bytes(b'jpegbytes')
    msg = build_message('from@example.com', 'to@example.com', 'Alert', 'Body', [photo])
    assert msg['Subject'] == 'Alert'
    assert any(part.get_filename() == 'photo.jpg' for part in msg.iter_attachments())


def test_send_honors_explicit_timeout(monkeypatch, tmp_path: Path):
    from laptopguard.config import MailSettings
    from laptopguard.mailer import send
    import laptopguard.mailer as mailer

    secret = tmp_path / 'smtp-password'
    secret.write_text('pw', encoding='utf-8')
    settings = MailSettings(
        enabled=True,
        host='smtp.example.com',
        port=465,
        use_ssl=True,
        username='u',
        from_address='from@example.com',
        to_address='to@example.com',
        password_file=str(secret),
    )

    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            seen['timeout'] = timeout
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def login(self, username, password):
            pass
        def send_message(self, msg):
            pass

    monkeypatch.setattr(mailer.smtplib, 'SMTP_SSL', FakeSMTP)
    send(settings, 'subject', 'body', [], timeout=2.0)
    assert seen['timeout'] == 2.0
