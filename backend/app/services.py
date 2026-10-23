"""Service layer: storage, extraction persistence, investigation execution, authorization.

Authorization rule used everywhere: a document is reachable by its owner, by an admin,
or by a teacher holding an explicit AccessGrant for that document. There is no implicit
"teachers can see all submissions" shortcut.
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.engine import InvestigationEngine, build_context
from app.analysis.graph import build_graph
from app.analysis.language import detect_language
from app.analysis.types import FindingDraft, GOALS, DEFAULT_GOALS
from app.core.config import settings
from app.core.ids import new_id
from app.models import (
    AccessGrant, AuditEvent, Document, DocumentPage, DocumentQuestion, DocumentVersion, EvidenceReference,
    Finding, GraphEdge, GraphNode, Investigation, Keyword, Passage, Recommendation, Section, User,
)
from app.parsing import DocumentFormatError, parse_document, sha256_of, validate_upload

UPLOAD_DIR = settings.storage_dir / "uploads"
RENDERED_DIR = settings.storage_dir / "rendered"


class AccessDenied(Exception):
    pass


def audit(db: Session, user_id: str | None, action: str, target_type: str | None = None,
          target_id: str | None = None, detail: dict[str, Any] | None = None) -> None:
    db.add(AuditEvent(user_id=user_id, action=action, target_type=target_type, target_id=target_id, detail=detail or {}))
    db.commit()


# --------------------------------------------------------------------------- upload
def store_upload(db: Session, user: User, filename: str, data: bytes) -> tuple[Document, DocumentVersion]:
    size = len(data)
    fmt = validate_upload(filename, size, data[:1024])

    digest = hashlib.sha256(data).hexdigest()
    owner_dir = UPLOAD_DIR / user.id
    owner_dir.mkdir(parents=True, exist_ok=True)
    file_id = new_id()
    safe_name = "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in ("-", "_", ".", " "))[:80] or "document"
    target = owner_dir / f"{file_id}{Path(safe_name).suffix.lower()}"
    target.write_bytes(data)

    document = Document(owner_id=user.id, title=Path(safe_name).stem[:400] or "Untitled document")
    version = DocumentVersion(
        document_id="", filename=safe_name, storage_path=str(target), media_type=_media_type(fmt),
        file_format=fmt, size_bytes=size, sha256=digest, version_no=1, extraction_status="pending",
    )
    db.add(document)
    db.flush()
    version.document_id = document.id
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    db.commit()
    audit(db, user.id, "document.upload", "document", document.id,
          {"format": fmt, "size_bytes": size, "filename": safe_name})
    return document, version


def _media_type(fmt: str) -> str:
    return {
        "pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain", "markdown": "text/markdown", "html": "text/html", "csv": "text/csv",
    }.get(fmt, "application/octet-stream")


def add_version(db: Session, document: Document, data: bytes, filename: str) -> DocumentVersion:
    fmt = validate_upload(filename, len(data), data[:1024])
    version_no = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id))
    next_no = len(document.versions) + 1
    owner_dir = UPLOAD_DIR / document.owner_id
    owner_dir.mkdir(parents=True, exist_ok=True)
    file_id = new_id()
    target = owner_dir / f"{file_id}{Path(filename).suffix.lower()}"
    target.write_bytes(data)
    version = DocumentVersion(
        document_id=document.id, version_no=next_no, filename=filename[:200], storage_path=str(target),
        media_type=_media_type(fmt), file_format=fmt, size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(), extraction_status="pending",
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    db.commit()
    audit(db, document.owner_id, "document.version_added", "document_version", version.id, {"version_no": next_no})
    return version


# --------------------------------------------------------------------------- extraction
def extract_version(db: Session, version: DocumentVersion) -> DocumentVersion:
    version.extraction_status = "extracting"
    db.commit()
    try:
        path = Path(version.storage_path)
        if not path.exists():
            raise FileNotFoundError("The stored file is no longer present on disk.")
        render_dir = RENDERED_DIR / version.id
        render_dir.mkdir(parents=True, exist_ok=True)
        parsed = parse_document(path, version.file_format, render_dir)

        language, confidence = detect_language(parsed.full_text[:120_000])
        version.parser = parsed.parser
        version.language = language if parsed.passages else "unknown"
        version.language_confidence = confidence
        version.word_count = parsed.word_count
        version.char_count = parsed.char_count
        version.page_count = len(parsed.pages)
        version.page_geometry = [
            {"number": page.number, "width": page.width, "height": page.height, "image_scale": page.image_scale,
             "has_text": page.has_text}
            for page in parsed.pages
        ]
        version.positioning_quality = parsed.positioning_quality
        version.ocr_needed = parsed.needs_ocr
        version.parsing_notes = parsed.notes
        version.extracted_at = datetime.now(timezone.utc)
        version.extraction_error = None

        section_id_map: dict[str, str] = {}
        for parsed_section in parsed.sections:
            row = Section(
                id=new_id(), version_id=version.id, index=parsed_section.index, level=parsed_section.level,
                title=parsed_section.title, kind=parsed_section.kind,
            )
            db.add(row)
            section_id_map[parsed_section.id] = row.id

        for parsed_passage in parsed.passages:
            bbox = parsed_passage.bbox or {}
            db.add(
                Passage(
                    id=parsed_passage.id, version_id=version.id,
                    section_id=section_id_map.get(parsed_passage.section_id or ""),
                    sort_index=parsed_passage.sort_index, kind=parsed_passage.kind, text=parsed_passage.text,
                    char_start=parsed_passage.char_start, char_end=parsed_passage.char_end,
                    page_number=parsed_passage.page_number,
                    bbox_x=bbox.get("x"), bbox_y=bbox.get("y"), bbox_w=bbox.get("w"), bbox_h=bbox.get("h"),
                    coordinate_source=parsed_passage.coordinate_source, words=parsed_passage.words,
                    source_lines=parsed_passage.lines,
                )
            )

        for page in parsed.pages:
            db.add(
                DocumentPage(version_id=version.id, number=page.number, width=page.width, height=page.height,
                             image_path=page.image_path, image_scale=page.image_scale, has_text=page.has_text)
            )
        db.flush()

        document = db.get(Document, version.document_id)
        if document and (not document.title or document.title.startswith("Untitled")) and parsed.title:
            document.title = parsed.title[:400]
        version.extraction_status = "needs_ocr" if parsed.needs_ocr and not parsed.passages else "ready"
        db.commit()
        audit(db, document.owner_id if document else None, "document.extracted", "document_version", version.id,
              {"passages": len(parsed.passages), "words": parsed.word_count, "language": version.language})
        return version
    except Exception as exc:  # surfaced to the user as an honest failure state
        db.rollback()
        version = db.get(DocumentVersion, version.id)
        version.extraction_status = "failed"
        version.extraction_error = f"{type(exc).__name__}: {exc}"
        db.commit()
        return version


# --------------------------------------------------------------------------- authorization
def accessible_version(db: Session, user: User, version_id: str, require_review: bool = False) -> DocumentVersion:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise AccessDenied("Document version not found")
    document = db.get(Document, version.document_id)
    if document is None or document.deleted_at is not None:
        raise AccessDenied("This document is no longer available")
    if user.role == "admin" or document.owner_id == user.id:
        return version
    if user.role in ("teacher", "admin") or require_review:
        grant = db.scalar(
            select(AccessGrant).where(AccessGrant.document_id == document.id, AccessGrant.teacher_id == user.id)
        )
        if grant is not None:
            return version
    raise AccessDenied("You are not authorised to review this document")


def accessible_document(db: Session, user: User, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise AccessDenied("Document not found")
    if user.role == "admin" or document.owner_id == user.id:
        return document
    if user.role in ("teacher", "admin"):
        grant = db.scalar(
            select(AccessGrant).where(AccessGrant.document_id == document.id, AccessGrant.teacher_id == user.id)
        )
        if grant is not None:
            return document
    raise AccessDenied("You are not authorised to open this document")


# --------------------------------------------------------------------------- investigation
def version_payload(db: Session, version: DocumentVersion) -> dict[str, Any]:
    passages = db.scalars(
        select(Passage).where(Passage.version_id == version.id).order_by(Passage.sort_index)
    ).all()
    sections = {s.id: s for s in db.scalars(select(Section).where(Section.version_id == version.id)).all()}
    return {
        "passages": [
            {
                "id": p.id, "text": p.text, "kind": p.kind, "page_number": p.page_number,
                "char_start": p.char_start, "char_end": p.char_end, "section_id": p.section_id,
                "section_title": sections[p.section_id].title if p.section_id in sections else None,
                "coordinate_source": p.coordinate_source, "words": p.words,
            }
            for p in passages
        ],
        "sections": [
            {"id": s.id, "title": s.title, "level": s.level, "index": s.index, "kind": s.kind}
            for s in sorted(sections.values(), key=lambda x: x.index)
        ],
        "full_text": "\n\n".join(p.text for p in passages),
    }


def normalise_goals(goals: list[str] | None) -> tuple[str, ...]:
    if not goals:
        return DEFAULT_GOALS
    selected = tuple(goal for goal in GOALS if goal in set(goals))
    return selected or DEFAULT_GOALS


def create_investigation(db: Session, version: DocumentVersion, user: User, goals: list[str] | None) -> Investigation:
    investigation = Investigation(
        version_id=version.id, created_by=user.id, goals=list(normalise_goals(goals)),
        status="queued", stage="queued", detail="Waiting to start", engine="local",
    )
    db.add(investigation)
    db.commit()
    audit(db, user.id, "investigation.created", "investigation", investigation.id, {"goals": investigation.goals})
    return investigation


def execute_investigation(db: Session, investigation: Investigation) -> Investigation:
    version = db.get(DocumentVersion, investigation.version_id)
    if version is None:
        investigation.status = "failed"
        investigation.error = "Document version is missing"
        db.commit()
        return investigation

    investigation.status = "extracting"
    investigation.stage = "extracting"
    investigation.detail = "Reading the extracted passages"
    investigation.started_at = datetime.now(timezone.utc)
    db.commit()

    if version.extraction_status not in ("ready", "needs_ocr"):
        extract_version(db, version)
        version = db.get(DocumentVersion, version.id)
    if version.extraction_status == "failed":
        investigation.status = "failed"
        investigation.error = version.extraction_error or "The document could not be extracted"
        db.commit()
        return investigation

    payload = version_payload(db, version)
    document_title = (db.get(Document, version.document_id).title if version.document_id else "") or ""

    def progress(status: str, detail: str, passage_id: str | None) -> None:
        if status == "completed":
            return
        investigation.status = status
        investigation.stage = status
        investigation.detail = detail
        investigation.current_passage_id = passage_id or investigation.current_passage_id
        db.commit()

    context = build_context(
        passages=payload["passages"], full_text=payload["full_text"], language=version.language,
        language_confidence=version.language_confidence, title=document_title, file_format=version.file_format,
        goals=investigation.goals or list(DEFAULT_GOALS),
    )
    # The analyzer rule-sets are installed as separate modules; if any is missing the
    # investigation fails loudly rather than silently reporting nothing.
    engine = InvestigationEngine(context, progress=progress)
    result = engine.run()
    return persist_investigation_result(db, investigation, version, payload, result, context)


def persist_investigation_result(
    db: Session, investigation: Investigation, version: DocumentVersion, payload: dict[str, Any],
    result, context,
) -> Investigation:
    passages_by_id = {p["id"]: _SimplePassage(**p) for p in payload["passages"]}
    events = [dict(event) for event in result.events]

    # Persist findings + evidence, remembering draft_key -> finding id for the graph.
    finding_rows: list[dict[str, Any]] = []
    finding_key_map: dict[str, str] = {}
    for draft in result.findings:
        finding = Finding(
            investigation_id=investigation.id, kind=draft.kind, category=draft.category, title=draft.title,
            body=draft.body, suggestion=draft.suggestion, severity=draft.severity, confidence=draft.confidence,
            primary_passage_id=draft.primary_passage_id, extra={k: v for k, v in (draft.extra or {}).items()},
        )
        db.add(finding)
        db.flush()
        evidence_rows = []
        for item in draft.evidence:
            mode = "normalized" if item.note else "verbatim"
            reference = EvidenceReference(
                finding_id=finding.id, passage_id=item.passage_id, quote=item.quote,
                char_start=item.char_start, char_end=item.char_end, validation=mode, note=item.note,
            )
            db.add(reference)
            evidence_rows.append(
                {"passage_id": item.passage_id, "quote": item.quote, "char_start": item.char_start,
                 "char_end": item.char_end, "validation": mode}
            )
        row = {
            "id": finding.id, "kind": draft.kind, "category": draft.category, "title": draft.title,
            "body": draft.body, "severity": draft.severity, "primary_passage_id": draft.primary_passage_id,
            "evidence": evidence_rows, "passage_ids": [e["passage_id"] for e in evidence_rows],
            "extra": dict(draft.extra or {}),
        }
        finding_rows.append(row)
        draft_key = (draft.extra or {}).get("draft_key")
        if draft_key:
            finding_key_map[draft_key] = finding.id

    keyword_rows: list[dict[str, Any]] = []
    for draft in result.keywords:
        keyword = Keyword(
            investigation_id=investigation.id, term=draft.term, normalized=draft.normalized, category=draft.category,
            explanation=draft.explanation, occurrences=draft.occurrences, in_document=draft.in_document,
            related_terms=draft.related_terms, passage_ids=draft.passage_ids[:40], score=draft.score,
        )
        db.add(keyword)
        db.flush()
        keyword_rows.append(
            {"id": keyword.id, "term": keyword.term, "category": keyword.category, "explanation": keyword.explanation,
             "occurrences": keyword.occurrences, "in_document": keyword.in_document, "passage_ids": draft.passage_ids[:40]}
        )

    recommendation_rows: list[dict[str, Any]] = []
    for draft in result.recommendations:
        target = draft.finding
        finding_id = None
        if target is not None:
            key = (target.extra or {}).get("draft_key")
            finding_id = finding_key_map.get(key) if key else None
        row = Recommendation(
            investigation_id=investigation.id, finding_id=finding_id, passage_id=draft.passage_id,
            kind=draft.kind, rationale=draft.rationale, suggested_revision=draft.suggested_revision,
            status="pending",
        )
        db.add(row)
        db.flush()
        recommendation_rows.append(
            {"id": row.id, "finding_id": finding_id, "passage_id": row.passage_id, "kind": row.kind,
             "rationale": row.rationale, "suggested_revision": row.suggested_revision, "status": "pending"}
        )

    nodes, edges = build_graph(
        title=(db.get(Document, version.document_id).title if version.document_id else "") or version.filename,
        sections=payload["sections"], findings=finding_rows, keywords=keyword_rows,
        recommendations=recommendation_rows, passages_by_id=passages_by_id,
        finding_key_map=finding_key_map, events=events,
    )
    node_id_map: dict[str, str] = {}
    for node in nodes:
        row = GraphNode(
            id=node["id"], investigation_id=investigation.id, node_type=node["node_type"], label=node["label"],
            ref_id=node["ref_id"], passage_id=node["passage_id"], weight=node["weight"], payload=node["payload"],
        )
        db.add(row)
        node_id_map[node["id"]] = node["id"]
    for edge in edges:
        db.add(
            GraphEdge(
                id=edge["id"], investigation_id=investigation.id, source_node_id=edge["source_node_id"],
                target_node_id=edge["target_node_id"], relation=edge["relation"], label=edge["label"],
                strength=edge["strength"],
            )
        )

    # Rewrite crawl events to reference persisted findings (no fabrication risk: only
    # validated findings can be referenced).
    for event in events:
        refs = event.pop("finding_refs", None) or []
        event["finding_ids"] = [finding_key_map[ref] for ref in refs if ref in finding_key_map]
        event["keyword_ids"] = [keyword_rows[i]["id"] for i in range(len(keyword_rows))] if event.get("keyword_count") else []
        event.pop("keyword_count", None)
        if event["stage"] == "discovery":
            event["finding_ids"] = list(finding_key_map.values())
        if event["stage"] == "connection":
            event["node_ids"] = [node["id"] for node in nodes]
            event["edge_ids"] = [edge["id"] for edge in edges]

    investigation.status = "completed"
    investigation.stage = "completed"
    investigation.detail = "Investigation complete"
    investigation.finished_at = datetime.now(timezone.utc)
    metrics = dict(result.metrics)
    metrics.update({
        "event_log": events,
        "graph_counts": {"nodes": len(nodes), "edges": len(edges)},
        "positioning_quality": version.positioning_quality,
        "ocr_needed": version.ocr_needed,
    })
    investigation.metrics = metrics
    db.commit()
    audit(db, investigation.created_by, "investigation.completed", "investigation", investigation.id,
          {k: metrics.get(k) for k in ("validated_findings", "rejected_findings", "keywords", "events", "elapsed_seconds")})
    return investigation


class _SimplePassage:
    """Attribute view of a passage dict, used by the graph builder."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


def cancel_investigation(db: Session, investigation: Investigation) -> Investigation:
    if investigation.status in ("completed", "cancelled"):
        return investigation
    investigation.status = "cancelled"
    investigation.detail = "Cancelled by the user"
    investigation.finished_at = datetime.now(timezone.utc)
    db.commit()
    audit(db, investigation.created_by, "investigation.cancelled", "investigation", investigation.id)
    return investigation


def delete_document(db: Session, user: User, document: Document, purge_files: bool = True) -> None:
    document.deleted_at = datetime.now(timezone.utc)
    if purge_files:
        for version in document.versions:
            path = Path(version.storage_path)
            if path.exists():
                path.unlink(missing_ok=True)
            render_dir = RENDERED_DIR / version.id
            if render_dir.exists():
                shutil.rmtree(render_dir, ignore_errors=True)
    db.commit()
    audit(db, user.id, "document.deleted", "document", document.id, {"purged_files": purge_files})
