from __future__ import annotations

import re

_EMAIL = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


def valid_email(value: str) -> bool:
    return bool(_EMAIL.fullmatch(value.strip()))
