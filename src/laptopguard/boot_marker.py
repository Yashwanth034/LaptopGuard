from __future__ import annotations

from pathlib import Path

from .platform_support import boot_identifier


class BootMarker:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def is_new(self, boot_id: str) -> bool:
        current = self.path.read_text(encoding='utf-8').strip() if self.path.is_file() else ''
        if current == boot_id:
            return False
        self.path.write_text(boot_id, encoding='utf-8')
        return True


def current_boot_id() -> str:
    return boot_identifier()
