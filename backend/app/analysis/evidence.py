"""Evidence validation.

The single most important guarantee in SPIDER AI: a finding only survives if a real
span of the document backs it up. Every quote is checked against the stored passage
text; anything that does not appear is rejected and the finding is dropped (or
stripped down to the evidence that did check out). This is applied to local analysis
and to any LLM output, so neither can invent citations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.analysis.segmentation import normalize_word
from app.analysis.types import DocPassage, EvidenceDraft, FindingDraft

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\W\d_]+", re.UNICODE)


def _collapse(value: str) -> str:
    return _WS.sub(" ", value).strip()


def _loose(value: str) -> str:
    """Case/diacritic/punctuation-insensitive comparison form, token boundary preserved."""
    tokens = [_collapse(normalize_word(token)) for token in _PUNCT.findall(value)]
    return " ".join(t for t in tokens if t)


@dataclass
class ValidatedEvidence:
    passage_id: str
    quote: str
    char_start: int | None
    char_end: int | None
    validation: str          # verbatim | normalized
    note: str | None = None


@dataclass
class ValidationResult:
    finding: FindingDraft | None
    evidence: list[ValidatedEvidence] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    @property
    def kept(self) -> bool:
        return self.finding is not None


def locate(quote: str, passage: DocPassage) -> tuple[int, int, str] | None:
    """Find the quote in the passage. Returns (char_start, char_end, validation) or None."""
    text = passage.text
    candidate = _collapse(quote)
    if not candidate:
        return None
    index = text.find(candidate)
    if index >= 0:
        return passage.char_start + index, passage.char_start + index + len(candidate), "verbatim"

    # Whitespace-flexible verbatim scan (line breaks inside a PDF block).
    pattern = re.escape(candidate).replace(r"\ ", r"\s+")
    match = re.search(pattern, text)
    if match:
        return passage.char_start + match.start(), passage.char_start + match.end(), "verbatim"

    loose_quote = _loose(candidate)
    loose_text = _loose(text)
    if loose_quote and loose_quote in loose_text:
        # Offsets cannot be mapped exactly through normalization; report passage-level
        # anchoring and be honest in the note instead of guessing a character range.
        return None, None, "normalized"
    return None


def validate_finding(finding: FindingDraft, passages_by_id: dict[str, DocPassage]) -> ValidationResult:
    kept: list[ValidatedEvidence] = []
    rejected: list[dict[str, Any]] = []

    for draft in finding.evidence:
        passage = passages_by_id.get(draft.passage_id)
        if passage is None:
            rejected.append({"passage_id": draft.passage_id, "reason": "passage does not exist in this document"})
            continue
        if len(_collapse(draft.quote)) > len(passage.text):
            rejected.append({"passage_id": draft.passage_id, "reason": "quote is longer than the passage it cites"})
            continue
        located = locate(draft.quote, passage)
        if located is None:
            rejected.append({"passage_id": draft.passage_id, "reason": "quote not found verbatim in the passage"})
            continue
        start, end, mode = located
        kept.append(
            ValidatedEvidence(
                passage_id=passage.id,
                quote=_collapse(draft.quote),
                char_start=start,
                char_end=end,
                validation=mode,
                note=None if mode == "verbatim" else "Matched ignoring case, diacritics and punctuation; "
                                                    "character offsets are not exact.",
            )
        )

    if not kept:
        reason = rejected[0]["reason"] if rejected else "no source passage cited"
        rejected.append({"passage_id": finding.primary_passage_id, "reason": f"finding dropped: {reason}"})
        return ValidationResult(finding=None, evidence=[], rejected=rejected)

    # The spider needs exactly one landing passage; prefer cited primary if it survived.
    if finding.primary_passage_id not in {e.passage_id for e in kept}:
        finding.primary_passage_id = kept[0].passage_id
    finding.evidence = [
        EvidenceDraft(passage_id=e.passage_id, quote=e.quote, char_start=e.char_start, char_end=e.char_end, note=e.note)
        for e in kept
    ]
    finding.extra = {**(finding.extra or {}), "validated": True, "evidence_checked": len(kept), "rejected": len(rejected)}
    return ValidationResult(finding=finding, evidence=kept, rejected=rejected)


def validate_findings(
    findings: list[FindingDraft], passages: list[DocPassage]
) -> tuple[list[FindingDraft], list[dict[str, Any]]]:
    by_id = {p.id: p for p in passages}
    accepted: list[FindingDraft] = []
    audit: list[dict[str, Any]] = []
    for finding in findings:
        result = validate_finding(finding, by_id)
        if result.kept and result.finding is not None:
            accepted.append(result.finding)
        if result.rejected:
            audit.extend({"finding": finding.kind, "title": finding.title, **item} for item in result.rejected)
    return accepted, audit
