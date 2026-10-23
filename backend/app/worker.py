"""Background job runner for extraction and investigation.

Real state machine, no simulated progress:
queued -> extracting -> analyzing -> validating -> building_graph -> completed | failed | cancelled
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.core.database import session_scope
from app.models import DocumentVersion, Investigation

log = logging.getLogger("spider.worker")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="spider-job")


def submit(kind: str, identifier: str) -> None:
    if kind == "extraction":
        _executor.submit(_run_extraction, identifier)
    elif kind == "investigation":
        _executor.submit(_run_investigation, identifier)
    else:  # pragma: no cover
        raise ValueError(f"unknown job kind {kind}")


def _set(db, investigation: Investigation, status: str, detail: str) -> None:
    investigation.status = status
    investigation.stage = status
    investigation.detail = detail
    db.commit()


def _run_extraction(version_id: str) -> None:
    from app.services import extract_version

    with session_scope() as db:
        version = db.get(DocumentVersion, version_id)
        if version is None or version.extraction_status in ("ready", "needs_ocr"):
            return
    try:
        with session_scope() as db:
            version = db.get(DocumentVersion, version_id)
            if version is not None:
                extract_version(db, version)
    except Exception as exc:  # keep the worker alive; failure is visible in the DB state
        log.exception("extraction failed")
        with session_scope() as db:
            version = db.get(DocumentVersion, version_id)
            if version is not None:
                version.extraction_status = "failed"
                version.extraction_error = f"{type(exc).__name__}: {exc}"
                version.extracted_at = datetime.now(timezone.utc)
                db.commit()


def _run_investigation(investigation_id: str) -> None:
    from app.services import execute_investigation

    with session_scope() as db:
        investigation = db.get(Investigation, investigation_id)
        if investigation is None:
            return
        if investigation.status == "cancelled":
            return
        _set(db, investigation, "extracting", "Reading the document passages")

    try:
        with session_scope() as db:
            investigation = db.get(Investigation, investigation_id)
            if investigation is None or investigation.status == "cancelled":
                return
            version = db.get(DocumentVersion, investigation.version_id)
            if version is None:
                investigation.status = "failed"
                investigation.error = "Document version missing"
                db.commit()
                return
            _set(db, investigation, "analyzing", "Reading the document: subject, figures, language and reasoning")
            execute_investigation(db, investigation)
    except Exception as exc:
        log.exception("investigation failed")
        with session_scope() as db:
            investigation = db.get(Investigation, investigation_id)
            if investigation is not None:
                investigation.status = "failed"
                investigation.error = f"{type(exc).__name__}: {exc}"
                investigation.finished_at = datetime.now(timezone.utc)
                db.commit()
