from pathlib import Path

from laptopguard import cli


def test_configure_rejects_password_pasted_as_destination(tmp_path, monkeypatch):
    answers = iter(['smtp.gmail.com', '465', 'owner@example.com', 'owner@example.com', 'abcd efgh ijkl mnop'])
    monkeypatch.setattr(cli, '_ask', lambda *a, **k: next(answers))
    monkeypatch.setattr(cli.getpass, 'getpass', lambda *a, **k: 'secret')
    monkeypatch.setattr(cli.os, 'geteuid', lambda: 1000)
    path = tmp_path / 'config.toml'
    assert cli.configure(path) == 2
    assert not path.exists()


def test_configure_tests_smtp_before_writing_config(tmp_path, monkeypatch):
    answers = iter(['smtp.gmail.com', '465', 'owner@example.com', 'owner@example.com', 'alerts@example.com'])
    monkeypatch.setattr(cli, '_ask', lambda *a, **k: next(answers))
    monkeypatch.setattr(cli.getpass, 'getpass', lambda *a, **k: 'secret')
    monkeypatch.setattr(cli.os, 'geteuid', lambda: 1000)
    seen = []
    monkeypatch.setattr(cli, 'probe_mail', lambda settings: seen.append(settings.to_address))
    path = tmp_path / 'config.toml'
    assert cli.configure(path) == 0
    assert seen == ['alerts@example.com']
    assert path.exists()
