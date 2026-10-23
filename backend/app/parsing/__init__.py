"""Parser dispatch plus upload validation helpers."""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.config import settings
from app.parsing.base import ParsedDocument
from app.parsing.docx import parse_docx
from app.parsing.pdf import parse_pdf
from app.parsing.text import parse_csv, parse_html, parse_markdown, parse_txt

# extension -> normalized format key
FORMAT_BY_EXT = {
    ".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".text": "txt",
    ".md": "markdown", ".markdown": "markdown", ".html": "html", ".htm": "html",
    ".csv": "csv", ".tsv": "csv",
}


class DocumentFormatError(ValueError):
    """Raised for unsupported, corrupt, or oversized uploads."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_upload(filename: str, size_bytes: int, head: bytes) -> str:
    """Return the normalized format key or raise DocumentFormatError."""
    ext = Path(filename).suffix.lower()
    if ext not in settings.allowed_upload_extensions:
        supported = ", ".join(sorted(e.lstrip(".") for e in settings.allowed_upload_extensions))
        raise DocumentFormatError(f"Unsupported file type '{ext or 'none'}'. Supported: {supported}.")
    if size_bytes <= 0:
        raise DocumentFormatError("The uploaded file is empty.")
    if size_bytes > settings.max_upload_bytes:
        raise DocumentFormatError(f"File is larger than {settings.max_upload_bytes // (1024 * 1024)} MB.")
    # Trust but verify: the magic bytes must agree with the claimed extension.
    if ext == ".pdf" and not head.startswith(b"%PDF-"):
        raise DocumentFormatError("The file claims to be a PDF but its contents are not a PDF.")
    if ext == ".docx" and not head.startswith(b"PK\x03\x04"):
        raise DocumentFormatError("The file claims to be a DOCX but it is not a valid Word package.")
    if b"\x00" in head[:512] and ext not in (".pdf", ".docx"):
        raise DocumentFormatError("Binary content is not supported for this format.")
    return FORMAT_BY_EXT[ext]


def parse_document(path: Path, fmt: str, rendered_dir: Path) -> ParsedDocument:
    if fmt == "pdf":
        return parse_pdf(path, rendered_dir)
    if fmt == "docx":
        return parse_docx(path)
    if fmt == "markdown":
        return parse_markdown(path)
    if fmt == "html":
        return parse_html(path)
    if fmt == "csv":
        return parse_csv(path)
    if fmt == "txt":
        return parse_txt(path)
    raise DocumentFormatError(f"No parser is registered for format '{fmt}'.")
