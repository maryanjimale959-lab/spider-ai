"""Identifier helpers."""
from __future__ import annotations

import uuid


def new_id() -> str:
    return uuid.uuid4().hex


def short_hash(text: str, length: int = 10) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:length]
