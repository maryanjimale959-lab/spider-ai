"""SQLAlchemy entities for SPIDER AI.

Stable passage IDs are the spine of the product: they connect the analysis results,
the crawling spider, the document viewer, and the network graph.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# --------------------------------------------------------------------------- enums
ROLES = ("user", "student", "teacher", "admin")

# Investigation / extraction job states. Real states only - never fake progress.
EXTRACTION_STATUSES = ("pending", "extracting", "ready", "failed", "needs_ocr")
INVESTIGATION_STATUSES = (
    "queued", "extracting", "analyzing", "validating", "building_graph", "completed", "failed", "cancelled",
)

FINDING_KINDS = (
    "subject", "purpose", "central_idea", "structure", "argument", "conclusion",
    "fact", "date", "person", "definition", "statistic", "decision", "action_item", "critical_statement",
    "keyword_concept", "writing_issue", "logic_gap", "unsupported_claim", "contradiction",
    "ambiguous_statement", "overreaching_conclusion", "strength", "recommendation", "clarifying_question",
)

WRITING_CATEGORY = (
    "grammar", "spelling", "clarity", "paragraph_structure", "logical_flow", "repetition",
    "tone", "vocabulary", "terminology_consistency", "readability", "audience_suitability", "punctuation",
)

NODE_TYPES = (
    "spider", "document", "section", "topic", "keyword", "fact", "claim", "evidence",
    "writing_issue", "contradiction", "recommendation", "question",
)

EDGE_RELATIONS = (
    "contains", "mentions", "supports", "contradicts", "explains", "derived_from", "occurs_in", "suggests",
)


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------------------- users
class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="user")
    institution: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    documents: Mapped[list["Document"]] = relationship(back_populates="owner")


class AccessGrant(TimestampMixin, Base):
    """Explicit authorization for a teacher to review someone else's document."""

    __tablename__ = "access_grants"
    __table_args__ = (UniqueConstraint("document_id", "teacher_id", name="uq_grant_doc_teacher"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    granted_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(String(40), default="review")  # review | feedback
    note: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- documents
class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(400))
    # Plain reference (no FK cycle between documents and versions; SQLite cannot ALTER
    # to add a deferred constraint). Resolved by the service layer.
    current_version_id: Mapped[str | None] = mapped_column(String(32), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped["User"] = relationship(back_populates="documents")
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentVersion.version_no"
    )


class DocumentVersion(TimestampMixin, Base):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)

    filename: Mapped[str] = mapped_column(String(500))
    storage_path: Mapped[str] = mapped_column(String(700))
    media_type: Mapped[str] = mapped_column(String(120))
    file_format: Mapped[str] = mapped_column(String(30))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)

    parser: Mapped[str] = mapped_column(String(40), default="")
    language: Mapped[str] = mapped_column(String(10), default="unknown")
    language_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)

    extraction_status: Mapped[str] = mapped_column(String(20), default="pending")
    extraction_error: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Coordinate spaces are stored separately:
    #   source  -> PDF points / page pixel size (authoritative, stable)
    #   screen  -> computed in the browser at render time from scroll/zoom/resize
    page_geometry: Mapped[list | None] = mapped_column(JSON)
    positioning_quality: Mapped[str] = mapped_column(String(24), default="dom_element")
    ocr_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Honest statements from the parser about what it could and could not locate.
    parsing_notes: Mapped[list | None] = mapped_column(JSON)

    document: Mapped["Document"] = relationship(back_populates="versions")
    sections: Mapped[list["Section"]] = relationship(back_populates="version", cascade="all, delete-orphan")
    passages: Mapped[list["Passage"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="Passage.sort_index"
    )


class Section(TimestampMixin, Base):
    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    index: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(30), default="heading")

    version: Mapped["DocumentVersion"] = relationship(back_populates="sections")
    passages: Mapped[list["Passage"]] = relationship(back_populates="section")


class Passage(TimestampMixin, Base):
    """A stable unit of source text the spider can stand on."""

    __tablename__ = "passages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str | None] = mapped_column(ForeignKey("sections.id", ondelete="SET NULL"), index=True)

    sort_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
    kind: Mapped[str] = mapped_column(String(30), default="paragraph")  # title|heading|paragraph|list_item|table_row|caption
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)

    page_number: Mapped[int | None] = mapped_column(Integer)
    # Source-space bounding box (PDF points, or rendered canvas units).
    bbox_x: Mapped[float | None] = mapped_column(Float)
    bbox_y: Mapped[float | None] = mapped_column(Float)
    bbox_w: Mapped[float | None] = mapped_column(Float)
    bbox_h: Mapped[float | None] = mapped_column(Float)
    # pdf_bbox  -> exact text coordinates from the file
    # dom_element -> located by the rendered paragraph element in the browser
    # container -> located by the containing section only (documented limitation)
    coordinate_source: Mapped[str] = mapped_column(String(20), default="dom_element")
    words: Mapped[int] = mapped_column(Integer, default=0)
    # Source-space line rectangles (PDF only): [{x,y,w,h,text}] in PDF points.
    source_lines: Mapped[list | None] = mapped_column(JSON)

    version: Mapped["DocumentVersion"] = relationship(back_populates="passages")
    section: Mapped["Section | None"] = relationship(back_populates="passages")


class DocumentPage(TimestampMixin, Base):
    """Rendered raster page for PDFs so the spider can walk on the real page image."""

    __tablename__ = "document_pages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    width: Mapped[float] = mapped_column(Float, default=0)   # PDF points
    height: Mapped[float] = mapped_column(Float, default=0)
    image_path: Mapped[str] = mapped_column(String(700), default="")
    image_scale: Mapped[float] = mapped_column(Float, default=2.0)
    has_text: Mapped[bool] = mapped_column(Boolean, default=True)


# --------------------------------------------------------------------------- investigations
class Investigation(TimestampMixin, Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    goals: Mapped[list | None] = mapped_column(JSON)          # selected investigation tasks
    status: Mapped[str] = mapped_column(String(20), default="queued")
    stage: Mapped[str] = mapped_column(String(60), default="queued")
    detail: Mapped[str] = mapped_column(String(300), default="")
    current_passage_id: Mapped[str | None] = mapped_column(ForeignKey("passages.id", ondelete="SET NULL"))
    current_task: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    engine: Mapped[str] = mapped_column(String(40), default="local")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    findings: Mapped[list["Finding"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    keywords: Mapped[list["Keyword"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan"
    )
    nodes: Mapped[list["GraphNode"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    edges: Mapped[list["GraphEdge"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")


class Finding(TimestampMixin, Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    category: Mapped[str | None] = mapped_column(String(40))  # writing issue category, etc.
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(12), default="info")  # info|minor|major
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    primary_passage_id: Mapped[str | None] = mapped_column(ForeignKey("passages.id", ondelete="SET NULL"), index=True)
    extra: Mapped[dict | None] = mapped_column(JSON)

    investigation: Mapped["Investigation"] = relationship(back_populates="findings")
    evidence: Mapped[list["EvidenceReference"]] = relationship(back_populates="finding", cascade="all, delete-orphan")


class EvidenceReference(TimestampMixin, Base):
    """A quotation the validator checked against the real passage text."""

    __tablename__ = "evidence_references"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    passage_id: Mapped[str] = mapped_column(ForeignKey("passages.id", ondelete="CASCADE"), index=True)
    quote: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    validation: Mapped[str] = mapped_column(String(16), default="verbatim")  # verbatim|normalized|rejected
    note: Mapped[str | None] = mapped_column(String(300))

    finding: Mapped["Finding"] = relationship(back_populates="evidence")


class Keyword(TimestampMixin, Base):
    __tablename__ = "keywords"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    term: Mapped[str] = mapped_column(String(200))
    normalized: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(30), default="supporting")  # primary|supporting|technical|concept|acronym|related
    explanation: Mapped[str | None] = mapped_column(Text)
    occurrences: Mapped[int] = mapped_column(Integer, default=0)
    in_document: Mapped[bool] = mapped_column(Boolean, default=True)  # False = AI-suggested related concept
    related_terms: Mapped[list | None] = mapped_column(JSON)
    passage_ids: Mapped[list | None] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float, default=0.0)

    investigation: Mapped["Investigation"] = relationship(back_populates="keywords")


class Recommendation(TimestampMixin, Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[str | None] = mapped_column(ForeignKey("findings.id", ondelete="SET NULL"))
    passage_id: Mapped[str | None] = mapped_column(ForeignKey("passages.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="revision")
    rationale: Mapped[str] = mapped_column(Text, default="")
    suggested_revision: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|accepted|dismissed|edited
    user_text: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    investigation: Mapped["Investigation"] = relationship(back_populates="recommendations")


class DocumentQuestion(TimestampMixin, Base):
    __tablename__ = "document_questions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    asked_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    grounded: Mapped[bool] = mapped_column(Boolean, default=False)
    limitation: Mapped[str | None] = mapped_column(String(400))
    citation_passage_ids: Mapped[list | None] = mapped_column(JSON)
    engine: Mapped[str] = mapped_column(String(24), default="local")


# --------------------------------------------------------------------------- graph
class GraphNode(TimestampMixin, Base):
    __tablename__ = "graph_nodes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    node_type: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(300))
    ref_id: Mapped[str | None] = mapped_column(String(32))
    passage_id: Mapped[str | None] = mapped_column(ForeignKey("passages.id", ondelete="SET NULL"))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    payload: Mapped[dict | None] = mapped_column(JSON)

    investigation: Mapped["Investigation"] = relationship(back_populates="nodes")


class GraphEdge(TimestampMixin, Base):
    __tablename__ = "graph_edges"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    source_node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"))
    target_node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"))
    relation: Mapped[str] = mapped_column(String(30))
    label: Mapped[str | None] = mapped_column(String(120))
    strength: Mapped[float] = mapped_column(Float, default=1.0)

    investigation: Mapped["Investigation"] = relationship(back_populates="edges")


# --------------------------------------------------------------------------- teacher review
class TeacherReview(TimestampMixin, Base):
    __tablename__ = "teacher_reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    investigation_id: Mapped[str | None] = mapped_column(ForeignKey("investigations.id", ondelete="SET NULL"))
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|finalized|shared
    overall_note: Mapped[str] = mapped_column(Text, default="")
    rubric_id: Mapped[str | None] = mapped_column(ForeignKey("rubrics.id", ondelete="SET NULL"))
    rubric_responses: Mapped[dict | None] = mapped_column(JSON)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    share_token: Mapped[str | None] = mapped_column(String(40), unique=True)

    comments: Mapped[list["ReviewComment"]] = relationship(back_populates="review", cascade="all, delete-orphan")


class ReviewComment(TimestampMixin, Base):
    __tablename__ = "review_comments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    review_id: Mapped[str] = mapped_column(ForeignKey("teacher_reviews.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    passage_id: Mapped[str | None] = mapped_column(ForeignKey("passages.id", ondelete="SET NULL"))
    finding_id: Mapped[str | None] = mapped_column(ForeignKey("findings.id", ondelete="SET NULL"))
    recommendation_id: Mapped[str | None] = mapped_column(ForeignKey("recommendations.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    include_with_student: Mapped[bool] = mapped_column(Boolean, default=True)

    review: Mapped["TeacherReview"] = relationship(back_populates="comments")


class Rubric(TimestampMixin, Base):
    """Optional criteria. Scores are entered by the teacher; the AI never assigns grades."""

    __tablename__ = "rubrics"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    criteria: Mapped[list | None] = mapped_column(JSON)


class AuditEvent(TimestampMixin, Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[dict | None] = mapped_column(JSON)
