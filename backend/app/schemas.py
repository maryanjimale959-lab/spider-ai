"""Pydantic request/response models. Every inbound payload is validated here."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

ROLES = Literal["user", "student", "teacher", "admin"]
GOAL_NAMES = ("understanding", "important_info", "keywords", "writing", "logic_evidence", "recommendations")

# Pattern-based email validation (no extra dependency).
EmailString = Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", min_length=3, max_length=320)]


class RegisterRequest(BaseModel):
    email: EmailString
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    role: ROLES = "user"
    institution: str | None = Field(default=None, max_length=200)

    @field_validator("role")
    @classmethod
    def _no_self_admin(cls, value: str) -> str:
        if value == "admin":
            raise ValueError("Administrator accounts are created by an existing administrator")
        return value


class LoginRequest(BaseModel):
    email: EmailString
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    institution: str | None = None
    is_active: bool = True
    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class GrantRequest(BaseModel):
    teacher_email: str = Field(max_length=320)
    scope: Literal["review", "feedback"] = "review"
    note: str | None = Field(default=None, max_length=500)


class InvestigationCreate(BaseModel):
    goals: list[str] | None = None

    @field_validator("goals")
    @classmethod
    def _known_goals(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = [g for g in value if g not in GOAL_NAMES]
        if unknown:
            raise ValueError(f"Unknown investigation goals: {', '.join(unknown)}")
        return value


class QuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=800)


class RecommendationDecision(BaseModel):
    status: Literal["accepted", "dismissed", "edited"]
    user_text: str | None = Field(default=None, max_length=8000)


class CommentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    passage_id: str | None = None
    finding_id: str | None = None
    recommendation_id: str | None = None
    include_with_student: bool = True


class CommentUpdate(BaseModel):
    text: str | None = Field(default=None, max_length=8000)
    include_with_student: bool | None = None


class ReviewCreate(BaseModel):
    document_id: str
    investigation_id: str | None = None
    rubric_id: str | None = None


class ReviewUpdate(BaseModel):
    overall_note: str | None = Field(default=None, max_length=20000)
    rubric_responses: dict[str, Any] | None = None
    rubric_id: str | None = None


class RubricCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    criteria: list[dict[str, Any]] = Field(default_factory=list, max_length=24)

    @field_validator("criteria")
    @classmethod
    def _shape(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for item in value:
            label = str(item.get("label", "")).strip()
            if not label:
                raise ValueError("Every rubric criterion needs a label")
            out.append({"id": str(item.get("id") or label[:40].casefold().replace(" ", "_")),
                        "label": label[:200], "descriptor": str(item.get("descriptor", ""))[:600]})
        return out


class PassageOut(BaseModel):
    id: str
    sort_index: int
    kind: str
    text: str
    page_number: int | None = None
    bbox: dict[str, float] | None = None
    coordinate_source: str
    section_id: str | None = None
    section_title: str | None = None
    char_start: int
    char_end: int
    words: int
    source_lines: list[dict[str, Any]] | None = None
    model_config = {"from_attributes": True}


class SectionOut(BaseModel):
    id: str
    index: int
    level: int
    title: str
    kind: str


class PageOut(BaseModel):
    number: int
    width: float
    height: float
    image_url: str
    image_scale: float
    has_text: bool


class DocumentOut(BaseModel):
    id: str
    title: str
    owner_id: str
    owner_name: str | None = None
    created_at: datetime
    current_version_id: str | None = None
    file_format: str | None = None
    filename: str | None = None
    extraction_status: str | None = None
    language: str | None = None
    word_count: int | None = None
    page_count: int | None = None
    passage_count: int | None = None


class VersionContentOut(BaseModel):
    version_id: str
    document_id: str
    title: str
    file_format: str
    language: str
    language_confidence: float
    positioning_quality: str
    extraction_status: str
    extraction_error: str | None = None
    ocr_needed: bool
    word_count: int
    page_count: int
    page_geometry: list[dict[str, Any]] | None = None
    notes: list[str] = Field(default_factory=list)
    sections: list[SectionOut]
    passages: list[PassageOut]
    pages: list[PageOut]


class FindingOut(BaseModel):
    id: str
    kind: str
    category: str | None = None
    title: str
    body: str
    suggestion: str | None = None
    severity: str
    confidence: float
    primary_passage_id: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    extra: dict[str, Any] | None = None


class KeywordOut(BaseModel):
    id: str
    term: str
    category: str
    explanation: str | None = None
    occurrences: int
    in_document: bool
    related_terms: list[str] | None = None
    passage_ids: list[str] | None = None
    score: float


class RecommendationOut(BaseModel):
    id: str
    finding_id: str | None = None
    passage_id: str | None = None
    kind: str
    rationale: str
    suggested_revision: str | None = None
    status: str
    user_text: str | None = None


class NodeOut(BaseModel):
    id: str
    node_type: str
    label: str
    ref_id: str | None = None
    passage_id: str | None = None
    weight: float
    payload: dict[str, Any] | None = None


class EdgeOut(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    relation: str
    label: str | None = None
    strength: float


class InvestigationStatusOut(BaseModel):
    id: str
    version_id: str
    status: str
    stage: str
    detail: str
    goals: list[str] | None = None
    current_passage_id: str | None = None
    current_task: str | None = None
    error: str | None = None
    engine: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metrics: dict[str, Any] | None = None


class InvestigationResultsOut(BaseModel):
    investigation: InvestigationStatusOut
    findings: list[FindingOut]
    keywords: list[KeywordOut]
    recommendations: list[RecommendationOut]
    nodes: list[NodeOut]
    edges: list[EdgeOut]
    events: list[dict[str, Any]]
    rejected_evidence: list[dict[str, Any]] = Field(default_factory=list)
    ai: dict[str, Any]


class QuestionOut(BaseModel):
    id: str
    question: str
    answer: str
    grounded: bool
    limitation: str | None = None
    citation_passage_ids: list[str] | None = None
    citations_detail: list[dict[str, Any]] = Field(default_factory=list)
    engine: str
    created_at: datetime


class ReviewOut(BaseModel):
    id: str
    document_id: str
    version_id: str
    investigation_id: str | None = None
    teacher_id: str
    teacher_name: str | None = None
    student_id: str
    student_name: str | None = None
    document_title: str
    status: str
    overall_note: str
    rubric_id: str | None = None
    rubric_responses: dict[str, Any] | None = None
    finalized_at: datetime | None = None
    shared_at: datetime | None = None
    share_url: str | None = None
    report_url: str | None = None
    comments: list[dict[str, Any]] = Field(default_factory=list)


class RubricOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    criteria: list[dict[str, Any]] | None = None


class HealthOut(BaseModel):
    app: str
    status: str
    engine: str
    ai: dict[str, Any]
    formats: list[str]
