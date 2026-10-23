"""Investigation engine.

Runs the goal-selected analyzers over the real extracted passages, then validates every
finding's evidence. It also records an ordered *event log*: the genuine sequence of
what the engine examined and what it produced. The frontend replays that log to drive
the spider, so every step of the crawl corresponds to a real analysis event.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from app.analysis import evidence as evidence_validator
from app.analysis.types import (
    DEFAULT_GOALS, AnalysisContext, DocPassage, FindingDraft, KeywordDraft, RecommendationDraft,
)
from app.core.ids import new_id

ProgressFn = Callable[[str, str, str | None], None]

STAGES = ("arrival", "exploration", "investigation", "discovery", "connection", "completion")

# Which analyzer produces which finding kinds, in crawl order.
TASK_SEQUENCE = (
    ("understanding", "Mapping the document's structure", ("title", "heading")),
    ("understanding", "Identifying the subject and purpose", ("title", "paragraph")),
    ("important_info", "Extracting key facts and figures", ("paragraph", "list_item", "table_row")),
    ("keywords", "Tracking recurring concepts", ("paragraph", "list_item", "table_row")),
    ("writing", "Investigating sentence quality", ("paragraph", "list_item", "heading")),
    ("writing", "Investigating flow and structure", ("heading", "paragraph")),
    ("logic_evidence", "Checking claims against evidence", ("paragraph", "list_item")),
    ("recommendations", "Preparing recommendations", ("paragraph",)),
)


@dataclass
class EngineResult:
    findings: list[FindingDraft] = field(default_factory=list)
    keywords: list[KeywordDraft] = field(default_factory=list)
    recommendations: list[RecommendationDraft] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    rejected_evidence: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def build_context(
    passages: list[dict[str, Any]], full_text: str, language: str, language_confidence: float,
    title: str, file_format: str, goals: tuple[str, ...] | list[str] | None = None,
) -> AnalysisContext:
    docs = [
        DocPassage(
            id=p["id"], text=p["text"], kind=p.get("kind", "paragraph"),
            page_number=p.get("page_number"), char_start=p.get("char_start", 0), char_end=p.get("char_end", 0),
            section_id=p.get("section_id"), section_title=p.get("section_title"),
            coordinate_source=p.get("coordinate_source", "dom_element"), words=p.get("words", 0),
        )
        for p in passages
    ]
    return AnalysisContext(
        passages=docs, full_text=full_text, language=language, language_confidence=language_confidence,
        title=title, file_format=file_format, goals=tuple(goals or DEFAULT_GOALS),
    )


class InvestigationEngine:
    def __init__(self, ctx: AnalysisContext, progress: ProgressFn | None = None) -> None:
        self.ctx = ctx
        self.progress = progress or (lambda *_: None)
        self.result = EngineResult()
        self._seq = 0
        self.started = time.perf_counter()

    # ------------------------------------------------------------------ events
    def emit(self, stage: str, task: str, passage_id: str | None = None, **payload: Any) -> None:
        self._seq += 1
        self.result.events.append(
            {
                "seq": self._seq,
                "stage": stage,
                "task": task,
                "passage_id": passage_id,
                "finding_ids": payload.pop("finding_ids", []),
                "keyword_ids": payload.pop("keyword_ids", []),
                "edge_ids": payload.pop("edge_ids", []),
                "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                **payload,
            }
        )

    def _order_passages(self, kinds: tuple[str, ...]) -> list[DocPassage]:
        picked = [p for p in self.ctx.passages if p.kind in kinds]
        return picked or list(self.ctx.passages)

    # ------------------------------------------------------------------ stages
    def run(self) -> EngineResult:
        ctx = self.ctx
        if not ctx.passages:
            self.result.metrics["empty_document"] = True
            self.progress("completed", "The document contains no text to investigate", None)
            return self.result

        # Stage 1 - arrival: the spider enters at the title / first passage.
        entry = ctx.passages[0]
        self.progress("analyzing", "The document is open and ready to read", None)
        self.emit("arrival", "Starting at the opening of the document", entry.id, passage_kind=entry.kind)

        # Stage 2 - initial exploration over the structure.
        self.progress("analyzing", "Mapping the document structure", None)
        structure_passages = [p for p in ctx.passages if p.is_heading][:14] or [entry]
        for passage in structure_passages:
            self.emit("exploration", "Reading the outline", passage.id, passage_kind=passage.kind)

        drafts: list[FindingDraft] = []
        keyword_drafts: list[KeywordDraft] = []

        # Stage 3 - investigation, one real analyzer at a time.
        if ctx.has_goal("understanding"):
            from app.analysis.understanding import analyze_understanding

            self.progress("analyzing", "Understanding what the document is about", None)
            produced = analyze_understanding(ctx)
            drafts += produced
            self._emit_analysis_events("investigation", "Understanding the document", produced)

        if ctx.has_goal("important_info"):
            from app.analysis.info_extraction import extract_important_information

            self.progress("analyzing", "Extracting important information", None)
            produced = extract_important_information(ctx)
            drafts += produced
            self._emit_analysis_events("investigation", "Extracting facts, dates, and definitions", produced)

        if ctx.has_goal("keywords"):
            from app.analysis.keywords import extract_keywords, key_concept_findings

            self.progress("analyzing", "Extracting keywords", None)
            keyword_drafts = extract_keywords(ctx)
            self.emit(
                "investigation", "Recording recurring concepts", None,
                keyword_count=len(keyword_drafts),
            )
            drafts += key_concept_findings(ctx, keyword_drafts)

        if ctx.has_goal("writing"):
            from app.analysis.writing import investigate_writing

            self.progress("analyzing", "Investigating writing quality", None)
            produced = investigate_writing(ctx)
            drafts += produced
            self._emit_analysis_events("investigation", "Investigating sentences and structure", produced)

        if ctx.has_goal("logic_evidence"):
            from app.analysis.logic import investigate_logic

            self.progress("analyzing", "Checking claims and evidence", None)
            produced = investigate_logic(ctx)
            drafts += produced
            self._emit_analysis_events("investigation", "Checking claims against in-document evidence", produced)

        # Stage 4 - validation gate. Findings without surviving evidence are dropped here.
        self.progress("validating", "Validating every quotation against the source text", None)
        before = len(drafts)
        validated, rejected = evidence_validator.validate_findings(drafts, ctx.passages)
        self.result.findings = validated
        self.result.rejected_evidence = rejected[:120]
        surviving_refs = [
            (finding.extra or {}).get("draft_key") for finding in validated if (finding.extra or {}).get("draft_key")
        ]
        self.emit(
            "discovery", "Evidence check complete", None,
            finding_refs=surviving_refs,
            checked=before, kept=len(validated), rejected=before - len(validated),
        )

        # Stage 5 - recommendations (they rest on validated findings only).
        if ctx.has_goal("recommendations"):
            from app.analysis.recommendations import build_recommendations

            self.progress("analyzing", "Preparing recommendations", None)
            self.result.recommendations = build_recommendations(ctx, validated, keyword_drafts)

        self.result.keywords = keyword_drafts

        # Stage 6 - completion: the spider withdraws to a resting place.
        rest = self._resting_passage()
        self.emit("connection", "Linking findings to the network", None)
        self.emit("completion", "Investigation complete, moving to rest", rest)
        elapsed = round(time.perf_counter() - self.started, 3)
        self.progress("completed", "Investigation finished", None)
        self.result.metrics = {
            "elapsed_seconds": elapsed,
            "language": ctx.language,
            "language_confidence": ctx.language_confidence,
            "passages": len(ctx.passages),
            "sentences": len(ctx.sentences),
            "words": sum(p.words for p in ctx.passages),
            "draft_findings": before,
            "validated_findings": len(validated),
            "rejected_findings": before - len(validated),
            "keywords": len(keyword_drafts),
            "recommendations": len(self.result.recommendations),
            "events": len(self.result.events),
            "goals": list(ctx.goals),
            "resting_passage_id": rest,
            "engine": "local",
        }
        return self.result

    # ------------------------------------------------------------------ helpers
    def _emit_analysis_events(self, stage: str, task: str, produced: list[FindingDraft]) -> None:
        """One crawl step per produced finding, in document order (spider visits passages)."""
        ordered = sorted(produced, key=lambda f: self._passage_order(f.primary_passage_id))
        for finding in ordered:
            key = new_id()
            finding.extra = {**(finding.extra or {}), "draft_key": key}
            self.emit(stage, task, finding.primary_passage_id, finding_refs=[key],
                      draft_kind=finding.kind, category=finding.category)

    def _passage_order(self, passage_id: str | None) -> int:
        for index, passage in enumerate(self.ctx.passages):
            if passage.id == passage_id:
                return index
        return len(self.ctx.passages)

    def _resting_passage(self) -> str | None:
        """The spider rests on the title/margin: first heading, else first passage."""
        for passage in self.ctx.passages:
            if passage.kind in ("title", "heading"):
                return passage.id
        return self.ctx.passages[0].id if self.ctx.passages else None


def temporary_keyword_id(index: int) -> str:
    return f"kw-{new_id()[:8]}-{index}"
