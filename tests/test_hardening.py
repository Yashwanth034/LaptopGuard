from laptopguard.hardening import parse_secure_boot, lsblk_has_crypt


def test_parse_secure_boot_enabled():
    assert parse_secure_boot('SecureBoot enabled') is True
    assert parse_secure_boot('SecureBoot disabled') is False


def test_lsblk_has_crypt_in_parent_chain():
    assert lsblk_has_crypt('part\ncrypt\nlvm\n') is True
    assert lsblk_has_crypt('disk\npart\nlvm\n') is False


def test_audit_detects_grub_password_in_01_users(monkeypatch):
    import laptopguard.hardening as hardening

    files = {
        '/etc/grub.d/01_users': 'set superusers="grubadmin"\npassword_pbkdf2 grubadmin grub.pbkdf2.sha512.10000.TEST\n',
    }

    class FakePath:
        def __init__(self, value):
            self.value = str(value)

        def exists(self):
            return self.value == '/sys/firmware/efi'

        def is_file(self):
            return self.value in files

        def read_text(self, **_kwargs):
            return files[self.value]

    monkeypatch.setattr(hardening, 'Path', FakePath)
    monkeypatch.setattr(hardening.shutil, 'which', lambda _name: None)

    grub = next(check for check in hardening.audit() if check.name == 'GRUB password')
    assert grub.ok is True
    assert grub.detail == 'GRUB password entry detected'
