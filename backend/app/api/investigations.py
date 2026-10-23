"""Investigation lifecycle: create, poll real status, fetch results, crawl events, questions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services, worker
from app.ai import provider as ai_provider
from app.ai import questions as question_engine
from app.analysis.types import AnalysisContext
from app.core.database import get_db
from app.models import (
    Document, DocumentQuestion, EvidenceReference, Finding, GraphEdge, GraphNode, Investigation, Keyword,
    Passage, Recommendation, Section, User,
)
from app.schemas import (
    EdgeOut, FindingOut, InvestigationCreate, InvestigationResultsOut, InvestigationStatusOut, KeywordOut,
    NodeOut, QuestionOut, QuestionRequest, RecommendationDecision, RecommendationOut,
)
from app.security import CurrentUser

router = APIRouter(prefix="/api", tags=["investigations"])


def _load_investigation(db: Session, user: User, investigation_id: str) -> Investigation:
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation not found")
    try:
        services.accessible_version(db, user, investigation.version_id)
    except services.AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return investigation


def _status_out(investigation: Investigation) -> InvestigationStatusOut:
    metrics = dict(investigation.metrics or {})
    metrics.pop("event_log", None)
    return InvestigationStatusOut(
        id=investigation.id, version_id=investigation.version_id, status=investigation.status,
        stage=investigation.stage, detail=investigation.detail, goals=investigation.goals,
        current_passage_id=investigation.current_passage_id, current_task=investigation.current_task,
        error=investigation.error, engine=investigation.engine, started_at=investigation.started_at,
        finished_at=investigation.finished_at, metrics=metrics,
    )


@router.post("/versions/{version_id}/investigations", response_model=InvestigationStatusOut,
             status_code=status.HTTP_202_ACCEPTED)
def start_investigation(
    version_id: str,
    payload: InvestigationCreate,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    try:
        version = services.accessible_version(db, user, version_id)
    except services.AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    if version.extraction_status == "failed":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            version.extraction_error or "This document could not be extracted")
    if version.extraction_status == "pending":
        worker.submit("extraction", version.id)
    investigation = services.create_investigation(db, version, user, payload.goals)
    worker.submit("investigation", investigation.id)
    return _status_out(investigation)


@router.get("/investigations/{investigation_id}", response_model=InvestigationStatusOut)
def investigation_status(investigation_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    return _status_out(_load_investigation(db, user, investigation_id))


@router.get("/investigations/{investigation_id}/results", response_model=InvestigationResultsOut)
def investigation_results(investigation_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    investigation = _load_investigation(db, user, investigation_id)
    findings = db.scalars(select(Finding).where(Finding.investigation_id == investigation.id)).all()
    evidence_rows = db.scalars(
        select(EvidenceReference).where(EvidenceReference.finding_id.in_([f.id for f in findings] or ["-"]))
    ).all()
    evidence_by_finding: dict[str, list[dict]] = {}
    for row in evidence_rows:
        evidence_by_finding.setdefault(row.finding_id, []).append(
            {"id": row.id, "passage_id": row.passage_id, "quote": row.quote, "char_start": row.char_start,
             "char_end": row.char_end, "validation": row.validation, "note": row.note}
        )

    keywords = db.scalars(select(Keyword).where(Keyword.investigation_id == investigation.id)
                          .order_by(Keyword.score.desc())).all()
    recommendations = db.scalars(select(Recommendation).where(Recommendation.investigation_id == investigation.id)).all()
    nodes = db.scalars(select(GraphNode).where(GraphNode.investigation_id == investigation.id)).all()
    edges = db.scalars(select(GraphEdge).where(GraphEdge.investigation_id == investigation.id)).all()
    events = list((investigation.metrics or {}).get("event_log", []))

    return InvestigationResultsOut(
        investigation=_status_out(investigation),
        findings=[
            FindingOut(
                id=f.id, kind=f.kind, category=f.category, title=f.title, body=f.body, suggestion=f.suggestion,
                severity=f.severity, confidence=f.confidence, primary_passage_id=f.primary_passage_id,
                evidence=evidence_by_finding.get(f.id, []), extra=f.extra,
            ) for f in findings
        ],
        keywords=[
            KeywordOut(
                id=k.id, term=k.term, category=k.category, explanation=k.explanation, occurrences=k.occurrences,
                in_document=k.in_document, related_terms=k.related_terms, passage_ids=k.passage_ids or [], score=k.score,
            ) for k in keywords
        ],
        recommendations=[
            RecommendationOut(
                id=r.id, finding_id=r.finding_id, passage_id=r.passage_id, kind=r.kind, rationale=r.rationale,
                suggested_revision=r.suggested_revision, status=r.status, user_text=r.user_text,
            ) for r in recommendations
        ],
        nodes=[NodeOut(id=n.id, node_type=n.node_type, label=n.label, ref_id=n.ref_id, passage_id=n.passage_id,
                       weight=n.weight, payload=n.payload or {}) for n in nodes],
        edges=[EdgeOut(id=e.id, source_node_id=e.source_node_id, target_node_id=e.target_node_id,
                       relation=e.relation, label=e.label, strength=e.strength) for e in edges],
        events=events,
        rejected_evidence=list((investigation.metrics or {}).get("rejected_evidence", [])),
        ai=ai_provider.status(),
    )


@router.post("/investigations/{investigation_id}/cancel", response_model=InvestigationStatusOut)
def cancel_investigation(investigation_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    investigation = _load_investigation(db, user, investigation_id)
    return _status_out(services.cancel_investigation(db, investigation))


@router.get("/versions/{version_id}/investigations/latest", response_model=InvestigationStatusOut | None)
def latest_investigation(version_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    try:
        version = services.accessible_version(db, user, version_id)
    except services.AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    investigation = db.scalar(
        select(Investigation).where(Investigation.version_id == version.id)
        .order_by(Investigation.created_at.desc())
    )
    return _status_out(investigation) if investigation else None


@router.post("/recommendations/{recommendation_id}/decision", response_model=RecommendationOut)
def decide_recommendation(
    recommendation_id: str,
    payload: RecommendationDecision,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    recommendation = db.get(Recommendation, recommendation_id)
    if recommendation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recommendation not found")
    investigation = db.get(Investigation, recommendation.investigation_id)
    services.accessible_version(db, user, investigation.version_id)
    recommendation.status = payload.status
    recommendation.user_text = payload.user_text
    from datetime import datetime, timezone

    recommendation.decided_at = datetime.now(timezone.utc)
    db.commit()
    services.audit(db, user.id, "recommendation.decided", "recommendation", recommendation.id, {"status": payload.status})
    return RecommendationOut(
        id=recommendation.id, finding_id=recommendation.finding_id, passage_id=recommendation.passage_id,
        kind=recommendation.kind, rationale=recommendation.rationale,
        suggested_revision=recommendation.suggested_revision, status=recommendation.status,
        user_text=recommendation.user_text,
    )


@router.post("/investigations/{investigation_id}/questions", response_model=QuestionOut)
def ask_question(
    investigation_id: str,
    payload: QuestionRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    """Answers come only from this document. Anything the document does not say is reported as such."""
    investigation = _load_investigation(db, user, investigation_id)
    passages = db.scalars(select(Passage).where(Passage.version_id == investigation.version_id)
                          .order_by(Passage.sort_index)).all()
    sections = {s.id: s.title for s in db.scalars(select(Section).where(Section.version_id == investigation.version_id)).all()}
    context = AnalysisContext(
        passages=[_doc_passage(p, sections.get(p.section_id)) for p in passages],
        full_text="\n\n".join(p.text for p in passages),
        language=(investigation.metrics or {}).get("language", "unknown"),
        goals=tuple(investigation.goals or []),
    )
    result = question_engine.answer(context, payload.question)
    record = DocumentQuestion(
        investigation_id=investigation.id, asked_by=user.id, question=payload.question,
        answer=result["answer"], grounded=result["grounded"], limitation=result.get("limitation"),
        citation_passage_ids=result["citations"], engine=result["engine"],
    )
    db.add(record)
    db.commit()
    services.audit(db, user.id, "question.asked", "investigation", investigation.id,
                   {"grounded": result["grounded"], "engine": result["engine"]})
    return QuestionOut(
        id=record.id, question=record.question, answer=record.answer, grounded=record.grounded,
        limitation=record.limitation, citation_passage_ids=record.citation_passage_ids,
        citations_detail=result.get("citations_detail", []), engine=record.engine, created_at=record.created_at,
    )


@router.get("/investigations/{investigation_id}/questions", response_model=list[QuestionOut])
def list_questions(investigation_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    investigation = _load_investigation(db, user, investigation_id)
    rows = db.scalars(
        select(DocumentQuestion).where(DocumentQuestion.investigation_id == investigation.id)
        .order_by(DocumentQuestion.created_at.desc())
    ).all()
    return [
        QuestionOut(
            id=r.id, question=r.question, answer=r.answer, grounded=r.grounded, limitation=r.limitation,
            citation_passage_ids=r.citation_passage_ids, citations_detail=[], engine=r.engine, created_at=r.created_at,
        ) for r in rows
    ]


@router.get("/keywords/{keyword_id}/occurrences")
def keyword_occurrences(keyword_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    """Where a term actually appears - used by the teacher keyword explorer."""
    keyword = db.get(Keyword, keyword_id)
    if keyword is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Keyword not found")
    investigation = db.get(Investigation, keyword.investigation_id)
    services.accessible_version(db, user, investigation.version_id)
    rows = db.scalars(select(Passage).where(Passage.id.in_(keyword.passage_ids or []))).all()
    term = keyword.term.casefold()
    out = []
    for passage in rows:
        lowered = passage.text.casefold()
        cursor = lowered.find(term)
        while cursor >= 0:
            out.append({"passage_id": passage.id, "page_number": passage.page_number, "start": cursor,
                        "end": cursor + len(term), "excerpt": passage.text[max(0, cursor - 80):cursor + len(term) + 80]})
            cursor = lowered.find(term, cursor + 1)
    return {"term": keyword.term, "occurrences": len(out), "hits": out}


def _doc_passage(passage: Passage, section_title: str | None):
    from app.analysis.types import DocPassage

    return DocPassage(
        id=passage.id, text=passage.text, kind=passage.kind, page_number=passage.page_number,
        char_start=passage.char_start, char_end=passage.char_end, section_id=passage.section_id,
        section_title=section_title, coordinate_source=passage.coordinate_source, words=passage.words,
    )
