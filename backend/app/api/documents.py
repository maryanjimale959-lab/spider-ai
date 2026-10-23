"""Document upload, retrieval, page images, and access grants."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services, worker
from app.core.config import settings
from app.core.database import get_db
from app.models import AccessGrant, Document, DocumentPage, DocumentVersion, Section, User, Passage
from app.parsing import DocumentFormatError
from app.schemas import DocumentOut, GrantRequest, PageOut, PassageOut, SectionOut, VersionContentOut
from app.security import CurrentUser, require_roles

router = APIRouter(prefix="/api", tags=["documents"])

_recent: dict[str, deque[float]] = defaultdict(deque)


def rate_limit(key: str, limit: int = 20, window: int = 60) -> None:
    """Small in-memory limiter: protects upload and heavy analysis endpoints."""
    now = time.monotonic()
    hits = _recent[key]
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Too many requests. Wait {window} seconds and try again.")
    hits.append(now)


def _sniff(file: UploadFile, max_bytes: int) -> bytes:
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"File is larger than the {max_bytes // (1024 * 1024)} MB limit.")
    return data


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    rate_limit(f"upload:{user.id}:{request.client.host if request.client else 'local'}", limit=15, window=60)
    data = _sniff(file, settings.max_upload_bytes)
    try:
        document, version = services.store_upload(db, user, file.filename or "document.txt", data)
    except DocumentFormatError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    worker.submit("extraction", version.id)
    return _document_out(db, document)


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    user: CurrentUser,
    db: Session = Depends(get_db),
    scope: str | None = None,
):
    """Own documents, or (for teachers) the documents they are authorised to review."""
    if user.role in ("teacher", "admin") and scope == "assigned":
        grants = db.scalars(select(AccessGrant).where(AccessGrant.teacher_id == user.id)).all()
        ids = [g.document_id for g in grants]
        documents = db.scalars(select(Document).where(Document.id.in_(ids), Document.deleted_at.is_(None))) if ids else []
        return [_document_out(db, d) for d in documents]
    if user.role == "admin":
        documents = db.scalars(select(Document).where(Document.deleted_at.is_(None)).order_by(Document.created_at.desc()))
    else:
        documents = db.scalars(
            select(Document).where(Document.owner_id == user.id, Document.deleted_at.is_(None))
            .order_by(Document.created_at.desc())
        )
    return [_document_out(db, d) for d in documents]


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    try:
        document = services.accessible_document(db, user, document_id)
    except services.AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return _document_out(db, document)


@router.get("/versions/{version_id}/content", response_model=VersionContentOut)
def get_version_content(version_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    """Everything the viewer needs: passages, sections, pages, and coordinate honesty."""
    try:
        version = services.accessible_version(db, user, version_id)
    except services.AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    document = db.get(Document, version.document_id)
    passages = db.scalars(
        select(Passage).where(Passage.version_id == version.id).order_by(Passage.sort_index)
    ).all()
    sections = db.scalars(select(Section).where(Section.version_id == version.id).order_by(Section.index)).all()
    pages = db.scalars(select(DocumentPage).where(DocumentPage.version_id == version.id).order_by(DocumentPage.number)).all()
    section_titles = {s.id: s.title for s in sections}

    return VersionContentOut(
        version_id=version.id,
        document_id=version.document_id,
        title=document.title if document else version.filename,
        file_format=version.file_format,
        language=version.language,
        language_confidence=version.language_confidence,
        positioning_quality=version.positioning_quality,
        extraction_status=version.extraction_status,
        extraction_error=version.extraction_error,
        ocr_needed=version.ocr_needed,
        word_count=version.word_count,
        page_count=version.page_count,
        page_geometry=version.page_geometry or [],
        notes=version.parsing_notes or [],
        sections=[SectionOut.model_validate(s, from_attributes=True) for s in sections],
        passages=[_passage_out(p, section_titles.get(p.section_id)) for p in passages],
        pages=[
            PageOut(number=p.number, width=p.width, height=p.height, image_scale=p.image_scale,
                    has_text=p.has_text, image_url=f"/api/versions/{version.id}/pages/{p.number}.png")
            for p in pages
        ],
    )


@router.get("/versions/{version_id}/pages/{page_number}.png")
def get_page_image(version_id: str, page_number: int, user: CurrentUser, db: Session = Depends(get_db)):
    try:
        version = services.accessible_version(db, user, version_id)
    except services.AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    page = db.scalar(select(DocumentPage).where(DocumentPage.version_id == version.id, DocumentPage.number == page_number))
    if page is None or not page.image_path or not Path(page.image_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No rendered page image for this page")
    return FileResponse(page.image_path, media_type="image/png")


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, user: CurrentUser, db: Session = Depends(get_db), purge: bool = True):
    try:
        document = services.accessible_document(db, user, document_id)
    except services.AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    if user.role != "admin" and document.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner or an administrator can delete a document")
    services.delete_document(db, user, document, purge_files=purge)
    return None


@router.post("/documents/{document_id}/access", status_code=status.HTTP_201_CREATED)
def grant_teacher_access(
    document_id: str,
    payload: GrantRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    """The owner decides which teacher may review their document. Access is explicit."""
    try:
        document = services.accessible_document(db, user, document_id)
    except services.AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    if user.role != "admin" and document.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can authorise a reviewer")
    teacher = db.scalar(select(User).where(User.email == payload.teacher_email.lower()))
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No account with that email")
    if teacher.role not in ("teacher", "admin"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That account is not registered as a teacher")
    existing = db.scalar(
        select(AccessGrant).where(AccessGrant.document_id == document.id, AccessGrant.teacher_id == teacher.id)
    )
    if existing is not None:
        existing.scope = payload.scope
        existing.note = payload.note
        db.commit()
        return {"status": "updated", "teacher_id": teacher.id, "scope": existing.scope}
    db.add(AccessGrant(document_id=document.id, teacher_id=teacher.id, granted_by=user.id,
                       scope=payload.scope, note=payload.note))
    db.commit()
    services.audit(db, user.id, "access.granted", "document", document.id, {"teacher": teacher.email,
                                                                           "scope": payload.scope})
    return {"status": "created", "teacher_id": teacher.id, "scope": payload.scope}


@router.get("/documents/{document_id}/access")
def list_access(document_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    try:
        document = services.accessible_document(db, user, document_id)
    except services.AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    grants = db.scalars(select(AccessGrant).where(AccessGrant.document_id == document.id)).all()
    return [
        {"teacher_id": g.teacher_id, "name": db.get(User, g.teacher_id).full_name if db.get(User, g.teacher_id) else None,
         "scope": g.scope, "note": g.note, "created_at": g.created_at}
        for g in grants
    ]


def _passage_out(passage: Passage, section_title: str | None = None) -> PassageOut:
    bbox = None
    if None not in (passage.bbox_x, passage.bbox_y, passage.bbox_w, passage.bbox_h):
        bbox = {"x": passage.bbox_x, "y": passage.bbox_y, "w": passage.bbox_w, "h": passage.bbox_h}
    return PassageOut(
        id=passage.id, sort_index=passage.sort_index, kind=passage.kind, text=passage.text,
        page_number=passage.page_number, bbox=bbox, coordinate_source=passage.coordinate_source,
        section_id=passage.section_id, section_title=section_title, char_start=passage.char_start,
        char_end=passage.char_end, words=passage.words, source_lines=passage.source_lines or [],
    )


def _document_out(db: Session, document: Document) -> DocumentOut:
    version = db.get(DocumentVersion, document.current_version_id) if document.current_version_id else None
    owner = db.get(User, document.owner_id)
    passage_count = None
    if version is not None:
        passage_count = len(db.scalars(select(Passage.id).where(Passage.version_id == version.id)).all())
    return DocumentOut(
        id=document.id, title=document.title, owner_id=document.owner_id,
        owner_name=owner.full_name if owner else None, created_at=document.created_at,
        current_version_id=document.current_version_id, file_format=version.file_format if version else None,
        filename=version.filename if version else None, extraction_status=version.extraction_status if version else None,
        language=version.language if version else None, word_count=version.word_count if version else None,
        page_count=version.page_count if version else None, passage_count=passage_count,
    )
