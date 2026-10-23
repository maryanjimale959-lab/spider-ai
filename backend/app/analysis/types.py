"""Shared types for the analysis engine.

Analyzers return *drafts*. Nothing reaches the database until the evidence validator
has confirmed that every quoted passage really exists in the document.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# Investigation goals selectable by the user.
GOALS = (
    "understanding",     # A. document understanding
    "important_info",    # B. important information extraction
    "keywords",          # C. keyword extraction
    "writing",           # D. writing investigation
    "logic_evidence",    # E. logic and evidence investigation
    "recommendations",   # F. recommendations
)

DEFAULT_GOALS = ("understanding", "important_info", "keywords", "writing", "logic_evidence", "recommendations")

SEVERITIES = ("info", "minor", "major")


@dataclass
class DocPassage:
    """Analyzer-facing view of a stored passage."""

    id: str
    text: str
    kind: str = "paragraph"
    page_number: int | None = None
    char_start: int = 0
    char_end: int = 0
    section_id: str | None = None
    section_title: str | None = None
    coordinate_source: str = "dom_element"
    words: int = 0

    @property
    def is_heading(self) -> bool:
        return self.kind in ("title", "heading")


@dataclass
class Sentence:
    text: str
    passage_id: str
    start: int          # offset within the passage text
    end: int
    index: int


@dataclass
class EvidenceDraft:
    passage_id: str
    quote: str
    char_start: int | None = None
    char_end: int | None = None
    note: str | None = None


@dataclass
class FindingDraft:
    kind: str
    title: str
    body: str = ""
    evidence: list[EvidenceDraft] = field(default_factory=list)
    primary_passage_id: str | None = None
    category: str | None = None
    suggestion: str | None = None
    severity: str = "info"
    confidence: float = 0.8
    extra: dict[str, Any] = field(default_factory=dict)

    def passages(self) -> list[str]:
        ids = [e.passage_id for e in self.evidence]
        if self.primary_passage_id:
            ids.insert(0, self.primary_passage_id)
        seen: list[str] = []
        for pid in ids:
            if pid and pid not in seen:
                seen.append(pid)
        return seen


@dataclass
class KeywordDraft:
    term: str
    normalized: str
    category: str = "supporting"          # primary|supporting|technical|concept|acronym|related
    explanation: str = ""
    occurrences: int = 0
    in_document: bool = True              # False = suggested related concept, not found in source
    related_terms: list[str] = field(default_factory=list)
    passage_ids: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass
class RecommendationDraft:
    rationale: str
    kind: str = "revision"
    passage_id: str | None = None
    suggested_revision: str | None = None
    finding: FindingDraft | None = None
    severity: str = "minor"


@dataclass
class AnalysisContext:
    passages: list[DocPassage]
    full_text: str
    language: str = "unknown"
    language_confidence: float = 0.0
    title: str = ""
    file_format: str = ""
    goals: tuple[str, ...] = DEFAULT_GOALS
    sentences: list[Sentence] = field(default_factory=list)

    _by_id: dict[str, DocPassage] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {p.id: p for p in self.passages}
        if not self.sentences:
            self.sentences = build_sentences(self.passages)

    def passage(self, passage_id: str | None) -> DocPassage | None:
        return self._by_id.get(passage_id) if passage_id else None

    def has_goal(self, goal: str) -> bool:
        return goal in self.goals

    def body_passages(self) -> list[DocPassage]:
        return [p for p in self.passages if not p.is_heading]

    def text_of(self, passage_id: str | None) -> str:
        passage = self.passage(passage_id)
        return passage.text if passage else ""


def build_sentences(passages: Iterable[DocPassage]) -> list[Sentence]:
    from app.analysis.segmentation import split_sentences

    out: list[Sentence] = []
    index = 0
    for passage in passages:
        for start, end, text in split_sentences(passage.text):
            out.append(Sentence(text=text, passage_id=passage.id, start=start, end=end, index=index))
            index += 1
    return out
