"""SPIDER AI backend application."""
from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app import services
from app.api import auth, documents, investigations, reviews
from app.core.config import settings
from app.core.database import Base, engine, session_scope
from app.models import Document
from app.parsing import DocumentFormatError  # noqa: F401  (kept for the error handler below)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("spider.api")

app = FastAPI(
    title="SPIDER AI",
    version="0.1.0",
    description=(
        "SPIDER AI reads a document line by line and reports what it finds. "
        "Results come from the built-in analysis engine and every quotation is validated against the source text."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REJECTED_STATUSES = {}


@app.on_event("startup")
def on_startup() -> None:
    # The prototype creates tables directly so it runs with zero setup; Alembic
    # (`alembic upgrade head`) is the path for PostgreSQL deployments.
    Base.metadata.create_all(bind=engine)
    _enforce_retention()
    log.info("SPIDER AI ready. AI provider: %s", settings.ai_provider if settings.ai_enabled else "disabled (local engine)")


@app.on_event("shutdown")
def on_shutdown() -> None:
    from app.worker import _executor

    _executor.shutdown(wait=False)


def _enforce_retention() -> None:
    """Deleted documents older than the retention window are purged from disk and the database."""
    days = 30
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with session_scope() as db:
            stale = db.scalars(select(Document).where(Document.deleted_at.is_not(None),
                                                       Document.deleted_at < cutoff)).all()
            for document in stale:
                for version in document.versions:
                    Path(version.storage_path).unlink(missing_ok=True)
                    shutil.rmtree(settings.rendered_dir / version.id, ignore_errors=True)
                db.delete(document)
            if stale:
                log.info("Purged %d expired documents (retention %d days)", len(stale), days)
    except Exception:  # retention must never block startup
        log.exception("retention sweep failed")


@app.exception_handler(services.AccessDenied)
async def access_denied_handler(_: Request, exc: services.AccessDenied):
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


@app.exception_handler(DocumentFormatError)
async def format_error_handler(_: Request, exc: DocumentFormatError):
    return JSONResponse(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, content={"detail": str(exc)})


@app.middleware("http")
async def add_request_timing(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
    return response


app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(investigations.router)
app.include_router(reviews.router)


@app.get("/api/health", tags=["meta"])
def health():
    from app.ai.provider import status as ai_status

    return {
        "app": settings.app_name,
        "status": "ok",
        "engine": "local analysis engine (always active)",
        "ai": ai_status(),
        "formats": sorted(e.lstrip(".") for e in settings.allowed_upload_extensions),
        "positioning": {
            "pdf": "text bounding boxes from the file (PDF points)",
            "docx": "rendered paragraph elements",
            "txt_markdown_html": "rendered paragraph elements",
            "csv": "rendered row elements",
        },
    }


@app.get("/api/limits", tags=["meta"])
def limits():
    return {
        "max_upload_bytes": settings.max_upload_bytes,
        "supported_extensions": list(settings.allowed_upload_extensions),
        "ocr": "requires an external OCR engine; scanned PDFs are reported as needs_ocr rather than guessed",
        "privacy": (
            "Documents stay in this server's private storage directory. Nothing is sent to an external provider "
            "unless SPIDER_AI_PROVIDER and SPIDER_AI_API_KEY are configured; when they are, question answering and "
            "keyword enrichment send the relevant passages to that provider under its own retention terms."
        ),
    }


# --------------------------------------------------------------------- the interface
# When frontend/dist exists, one process serves the API and the built single-page
# interface from the same origin - which is all a hosted deployment needs.

DIST = settings.frontend_dist.resolve()

if settings.serve_frontend and (DIST / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="spa-assets")

    @app.get("/{requested_path:path}", include_in_schema=False)
    async def spa(requested_path: str):
        if requested_path.startswith("api/"):
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Not found"})
        candidate = (DIST / requested_path).resolve()
        if requested_path and candidate.is_file() and candidate.is_relative_to(DIST):
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")

    log.info("Serving the built interface from %s", DIST)
