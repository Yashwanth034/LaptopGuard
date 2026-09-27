from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import time
import zipfile

from cryptography.fernet import Fernet


class EncryptedQueue:
    def __init__(self, directory: Path, key_path: Path, max_items: int = 200, max_bytes: int = 256 * 1024 * 1024):
        self.directory = Path(directory)
        self.key_path = Path(key_path)
        self.max_items = max(10, int(max_items))
        self.max_bytes = max(10 * 1024 * 1024, int(max_bytes))
        self.corrupt_dir = self.directory / 'corrupt'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.corrupt_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        os.chmod(self.corrupt_dir, 0o700)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
            os.chmod(self.key_path, 0o600)
        self.fernet = Fernet(self.key_path.read_bytes().strip())

    def _archive(self, payload: dict, attachments: list[Path]) -> bytes:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('payload.json', json.dumps(payload, separators=(',', ':')))
            for attachment in attachments:
                path = Path(attachment)
                if path.is_file():
                    archive.writestr(f'files/{path.name}', path.read_bytes())
        return self.fernet.encrypt(buffer.getvalue())

    def enqueue(self, payload: dict, attachments: list[Path]) -> Path:
        encrypted = self._archive(payload, attachments)
        fd, temp_name = tempfile.mkstemp(prefix='.queue-', suffix='.tmp', dir=self.directory)
        target = self.directory / f'{time.time_ns()}.lgq'
        try:
            with os.fdopen(fd, 'wb') as fh:
                fh.write(encrypted)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, target)
            dir_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            Path(temp_name).unlink(missing_ok=True)
        self.enforce_limits()
        return target

    def update(self, item: Path, payload: dict, attachments: list[Path]) -> Path:
        """Atomically replace an existing queued alert in-place.

        This is used by time-critical shutdown capture: a minimal encrypted
        alert is persisted first, then enriched evidence replaces it without
        creating duplicate queue items.
        """
        target = Path(item)
        if target.parent != self.directory or not target.is_file():
            raise FileNotFoundError(target)
        encrypted = self._archive(payload, attachments)
        fd, temp_name = tempfile.mkstemp(prefix='.queue-update-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as fh:
                fh.write(encrypted)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, target)
            dir_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            Path(temp_name).unlink(missing_ok=True)
        return target

    def read(self, item: Path) -> tuple[dict, dict[str, bytes]]:
        raw = self.fernet.decrypt(Path(item).read_bytes())
        with zipfile.ZipFile(BytesIO(raw), 'r') as archive:
            payload = json.loads(archive.read('payload.json'))
            files = {name.split('/', 1)[1]: archive.read(name) for name in archive.namelist() if name.startswith('files/') and not name.endswith('/')}
        return payload, files

    def items(self) -> list[Path]:
        return sorted(p for p in self.directory.glob('*.lgq') if p.is_file())

    def quarantine(self, item: Path) -> Path:
        item = Path(item)
        target = self.corrupt_dir / item.name
        if target.exists():
            target = self.corrupt_dir / f'{item.stem}-{time.time_ns()}{item.suffix}'
        os.replace(item, target)
        return target

    def readable_items(self) -> list[Path]:
        good = []
        for item in self.items():
            try:
                self.read(item)
                good.append(item)
            except Exception:
                self.quarantine(item)
        return good


    def prune_oldest(self, count: int = 1) -> None:
        for item in self.items()[:max(0, int(count))]:
            item.unlink(missing_ok=True)

    def enforce_limits(self) -> None:
        items = self.items()
        total = sum(p.stat().st_size for p in items)
        while items and (len(items) > self.max_items or total > self.max_bytes):
            oldest = items.pop(0)
            try:
                size = oldest.stat().st_size
            except OSError:
                size = 0
            oldest.unlink(missing_ok=True)
            total -= size

    def remove(self, item: Path) -> None:
        Path(item).unlink(missing_ok=True)

    def remove_events(self, events: set[str]) -> int:
        """Remove readable queued alerts whose metadata event is in ``events``.

        Corrupt items are left to the normal quarantine path; unrelated security
        alerts are preserved. This is used during policy migrations to discard
        legacy boot/resume alerts that are no longer considered suspicious.
        """
        wanted = {str(event) for event in events}
        removed = 0
        for item in self.items():
            try:
                payload, _ = self.read(item)
            except Exception:
                continue
            metadata = payload.get('metadata') if isinstance(payload, dict) else None
            event = metadata.get('event') if isinstance(metadata, dict) else None
            if event in wanted:
                item.unlink(missing_ok=True)
                removed += 1
        return removed
