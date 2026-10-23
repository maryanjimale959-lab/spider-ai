"""Teacher review workflow: authorized inbox, drafts, comments, rubrics, finalization, sharing.

The AI findings shown here are advisory. Teachers write the academic judgement, and the
product never labels a submission as plagiarism or AI-written from writing style alone.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    AccessGrant, Document, DocumentVersion, Finding, Investigation, Passage, Recommendation, ReviewComment,
    Rubric, TeacherReview, User,
)
from app.schemas import (
    CommentCreate, CommentUpdate, ReviewCreate, ReviewOut, RubricCreate, RubricOut, ReviewUpdate,
)
from app.security import CurrentUser

router = APIRouter(prefix="/api", tags=["teacher-review"])

ADVISORY_NOTICE = (
    "SPIDER AI findings are machine-generated observations about the text. They are advisory: the teacher decides "
    "what they mean for this submission. This tool does not detect plagiarism or AI-authored writing, and a writing "
    "pattern or an unsupported claim is not evidence of misconduct."
)


def _review_or_404(db: Session, review_id: str, user: User) -> TeacherReview:
    review = db.get(TeacherReview, review_id)
    if review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    _require_reviewer(db, review, user)
    return review


def _require_reviewer(db: Session, review: TeacherReview, user: User) -> None:
    if user.role == "admin" or review.teacher_id == user.id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the assigned reviewer can edit this review")


def _grant_or_403(db: Session, document_id: str, user: User) -> AccessGrant:
    if user.role == "admin":
        return AccessGrant(document_id=document_id, teacher_id=user.id, granted_by=user.id, scope="review")
    grant = db.scalar(
        select(AccessGrant).where(AccessGrant.document_id == document_id, AccessGrant.teacher_id == user.id)
    )
    if grant is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "No authorisation on file for this submission. The student (or an administrator) must grant review access.",
        )
    return grant


@router.get("/reviews/inbox")
def review_inbox(user: CurrentUser, db: Session = Depends(get_db)):
    """Submissions this teacher is authorised to review, with what the engine found."""
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This workspace is for teacher and administrator accounts")
    query = select(AccessGrant).where(AccessGrant.teacher_id == user.id)
    grants = db.scalars(query).all()
    inbox = []
    for grant in grants:
        document = db.get(Document, grant.document_id)
        if document is None or document.deleted_at is not None:
            continue
        version = db.get(DocumentVersion, document.current_version_id) if document.current_version_id else None
        investigation = None
        if version is not None:
            investigation = db.scalar(
                select(Investigation).where(Investigation.version_id == version.id)
                .order_by(Investigation.created_at.desc())
            )
        review = db.scalar(
            select(TeacherReview).where(TeacherReview.document_id == document.id, TeacherReview.teacher_id == user.id)
            .order_by(TeacherReview.created_at.desc())
        )
        student = db.get(User, document.owner_id)
        metrics = investigation.metrics if investigation else {}
        inbox.append(
            {
                "document_id": document.id,
                "title": document.title,
                "student_name": student.full_name if student else "Unknown",
                "student_email": student.email if student else "",
                "scope": grant.scope,
                "granted_note": grant.note,
                "version_id": version.id if version else None,
                "extraction_status": version.extraction_status if version else None,
                "language": version.language if version else "unknown",
                "word_count": version.word_count if version else 0,
                "page_count": version.page_count if version else 0,
                "investigation_id": investigation.id if investigation else None,
                "investigation_status": investigation.status if investigation else "not_started",
                "summary": {
                    "findings": (metrics or {}).get("validated_findings"),
                    "keywords": (metrics or {}).get("keywords"),
                    "writing_issues": None,
                    "language_engine": (metrics or {}).get("engine"),
                },
                "review_id": review.id if review else None,
                "review_status": review.status if review else None,
            }
        )
    return {"reviews": inbox, "advisory_notice": ADVISORY_NOTICE}


@router.post("/reviews", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def create_review(payload: ReviewCreate, user: CurrentUser, db: Session = Depends(get_db)):
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Teacher account required")
    document = db.get(Document, payload.document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _grant_or_403(db, document.id, user)
    existing = db.scalar(
        select(TeacherReview).where(TeacherReview.document_id == document.id, TeacherReview.teacher_id == user.id,
                                    TeacherReview.status != "shared")
    )
    if existing is not None:
        return _review_out(db, existing)
    review = TeacherReview(
        document_id=document.id, version_id=document.current_version_id or "", teacher_id=user.id,
        student_id=document.owner_id, investigation_id=payload.investigation_id, rubric_id=payload.rubric_id,
        status="draft",
    )
    db.add(review)
    db.commit()
    services.audit(db, user.id, "review.created", "teacher_review", review.id, {"document": document.id})
    return _review_out(db, review)


@router.get("/reviews/{review_id}", response_model=ReviewOut)
def get_review(review_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    return _review_out(db, _review_or_404(db, review_id, user))


@router.patch("/reviews/{review_id}", response_model=ReviewOut)
def update_review(review_id: str, payload: ReviewUpdate, user: CurrentUser, db: Session = Depends(get_db)):
    review = _review_or_404(db, review_id, user)
    if review.status == "shared":
        raise HTTPException(status.HTTP_409_CONFLICT, "This feedback has already been shared with the student")
    if payload.overall_note is not None:
        review.overall_note = payload.overall_note
    if payload.rubric_responses is not None:
        _validate_rubric_responses(db, review, payload.rubric_responses)
        review.rubric_responses = payload.rubric_responses
    if payload.rubric_id is not None:
        review.rubric_id = payload.rubric_id
    db.commit()
    return _review_out(db, review)


@router.post("/reviews/{review_id}/comments", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def add_comment(review_id: str, payload: CommentCreate, user: CurrentUser, db: Session = Depends(get_db)):
    review = _review_or_404(db, review_id, user)
    if review.status == "shared":
        raise HTTPException(status.HTTP_409_CONFLICT, "Feedback already shared")
    comment = ReviewComment(
        review_id=review.id, author_id=user.id, text=payload.text.strip(), passage_id=payload.passage_id,
        finding_id=payload.finding_id, recommendation_id=payload.recommendation_id,
        include_with_student=payload.include_with_student,
    )
    db.add(comment)
    db.commit()
    services.audit(db, user.id, "review.comment_added", "teacher_review", review.id)
    return _review_out(db, review)


@router.patch("/comments/{comment_id}", response_model=ReviewOut)
def edit_comment(comment_id: str, payload: CommentUpdate, user: CurrentUser, db: Session = Depends(get_db)):
    comment = db.get(ReviewComment, comment_id)
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    review = _review_or_404(db, comment.review_id, user)
    if payload.text is not None:
        comment.text = payload.text.strip()
    if payload.include_with_student is not None:
        comment.include_with_student = payload.include_with_student
    db.commit()
    return _review_out(db, review)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    comment = db.get(ReviewComment, comment_id)
    if comment is None:
        return None
    review = _review_or_404(db, comment.review_id, user)
    if review.status == "shared":
        raise HTTPException(status.HTTP_409_CONFLICT, "Feedback already shared")
    db.delete(comment)
    db.commit()
    return None


@router.post("/reviews/{review_id}/finalize", response_model=ReviewOut)
def finalize_review(review_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    review = _review_or_404(db, review_id, user)
    if not review.overall_note.strip() and not review.comments:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Add your own note or comments before finalizing. AI observations alone are not feedback to a student.",
        )
    review.status = "finalized"
    review.finalized_at = datetime.now(timezone.utc)
    db.commit()
    services.audit(db, user.id, "review.finalized", "teacher_review", review.id)
    return _review_out(db, review)


@router.post("/reviews/{review_id}/share", response_model=ReviewOut)
def share_review(review_id: str, user: CurrentUser, db: Session = Depends(get_db)):
    review = _review_or_404(db, review_id, user)
    if review.status != "finalized":
        raise HTTPException(status.HTTP_409_CONFLICT, "Finalize the review before sharing it")
    if not review.share_token:
        import secrets

        review.share_token = secrets.token_urlsafe(18)
    review.status = "shared"
    review.shared_at = datetime.now(timezone.utc)
    db.commit()
    services.audit(db, user.id, "review.shared", "teacher_review", review.id)
    return _review_out(db, review)


@router.get("/reports/{share_token}")
def student_report(share_token: str, db: Session = Depends(get_db)):
    """Read-only feedback a teacher chose to share. Only included comments appear."""
    review = db.scalar(select(TeacherReview).where(TeacherReview.share_token == share_token))
    if review is None or review.status != "shared":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This feedback link is not available")
    document = db.get(Document, review.document_id)
    teacher = db.get(User, review.teacher_id)
    payload = build_report(db, review)
    return {
        "document_title": document.title if document else "",
        "teacher_name": teacher.full_name if teacher else "Reviewer",
        "shared_at": review.shared_at,
        **payload,
        "advisory_notice": ADVISORY_NOTICE,
    }


@router.get("/rubrics", response_model=list[RubricOut])
def list_rubrics(user: CurrentUser, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Rubric).where((Rubric.owner_id == user.id) | (Rubric.owner_id == "shared")).order_by(Rubric.name)
    ).all()
    return [RubricOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/rubrics", response_model=RubricOut, status_code=status.HTTP_201_CREATED)
def create_rubric(payload: RubricCreate, user: CurrentUser, db: Session = Depends(get_db)):
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Teacher account required")
    rubric = Rubric(owner_id=user.id, name=payload.name.strip(), description=payload.description,
                    criteria=payload.criteria)
    db.add(rubric)
    db.commit()
    return RubricOut.model_validate(rubric, from_attributes=True)


def build_report(db: Session, review: TeacherReview) -> dict:
    """Assemble the shareable feedback: teacher words + only the AI items the teacher kept."""
    included_comments = [c for c in review.comments]
    findings = []
    if review.investigation_id:
        for comment in included_comments:
            if comment.finding_id:
                finding = db.get(Finding, comment.finding_id)
                if finding is not None:
                    findings.append(
                        {"id": finding.id, "kind": finding.kind, "title": finding.title, "severity": finding.severity,
                         "teacher_comment": comment.text, "passage_id": finding.primary_passage_id}
                    )
    recommendations = []
    for comment in included_comments:
        if comment.recommendation_id:
            recommendation = db.get(Recommendation, comment.recommendation_id)
            if recommendation is not None:
                recommendations.append(
                    {"id": recommendation.id, "rationale": recommendation.rationale, "status": recommendation.status,
                     "teacher_comment": comment.text}
                )
    return {
        "overall_note": review.overall_note,
        "comments": [
            {
                "id": c.id, "text": c.text, "passage_id": c.passage_id, "finding_id": c.finding_id,
                "passage_excerpt": (db.get(Passage, c.passage_id).text[:400] if c.passage_id and db.get(Passage, c.passage_id) else None),
                "created_at": c.created_at,
            } for c in included_comments if c.include_with_student
        ],
        "private_comment_count": len([c for c in included_comments if not c.include_with_student]),
        "highlighted_findings": findings,
        "recommendations": recommendations,
        "rubric": _rubric_block(db, review),
    }


def _rubric_block(db: Session, review: TeacherReview) -> dict | None:
    if not review.rubric_id or not review.rubric_responses:
        return None
    rubric = db.get(Rubric, review.rubric_id)
    if rubric is None:
        return None
    criteria = {c.get("id"): c for c in (rubric.criteria or [])}
    rows = []
    for criterion_id, response in (review.rubric_responses or {}).items():
        criterion = criteria.get(criterion_id, {"label": criterion_id})
        rows.append({"id": criterion_id, "label": criterion.get("label", criterion_id),
                     "descriptor": criterion.get("descriptor", ""), "response": response})
    return {"name": rubric.name, "criteria": rows}


def _validate_rubric_responses(db: Session, review: TeacherReview, responses: dict) -> None:
    """Teacher-entered scores/levels only. Nothing is inferred, and no grade is computed."""
    if not review.rubric_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Attach a rubric before recording responses")
    rubric = db.get(Rubric, review.rubric_id)
    if rubric is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rubric not found")
    allowed = {c.get("id") for c in (rubric.criteria or [])}
    unknown = [key for key in responses if key not in allowed]
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown rubric criteria: {', '.join(unknown)}")
    for value in responses.values():
        text = str(value)
        if len(text) > 400:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Rubric responses must be short labels or notes")


def _review_out(db: Session, review: TeacherReview) -> ReviewOut:
    document = db.get(Document, review.document_id)
    teacher = db.get(User, review.teacher_id)
    student = db.get(User, review.student_id)
    comments = db.scalars(select(ReviewComment).where(ReviewComment.review_id == review.id)
                          .order_by(ReviewComment.created_at)).all()
    share_url = f"/report/{review.share_token}" if review.share_token else None
    return ReviewOut(
        id=review.id, document_id=review.document_id, version_id=review.version_id,
        investigation_id=review.investigation_id, teacher_id=review.teacher_id,
        teacher_name=teacher.full_name if teacher else None, student_id=review.student_id,
        student_name=student.full_name if student else None,
        document_title=document.title if document else "", status=review.status, overall_note=review.overall_note,
        rubric_id=review.rubric_id, rubric_responses=review.rubric_responses, finalized_at=review.finalized_at,
        shared_at=review.shared_at, share_url=share_url,
        report_url=f"/api/reports/{review.share_token}" if review.share_token else None,
        comments=[
            {"id": c.id, "text": c.text, "passage_id": c.passage_id, "finding_id": c.finding_id,
             "recommendation_id": c.recommendation_id, "include_with_student": c.include_with_student,
             "created_at": c.created_at.isoformat()} for c in comments
        ],
    )
