"""The evidence validator is the product's honesty guarantee. These tests attack it."""
from __future__ import annotations

import pytest

from app.analysis.evidence import locate, validate_findings
from app.analysis.types import DocPassage, EvidenceDraft, FindingDraft
from app.core.ids import new_id


@pytest.fixture()
def passages():
    first = new_id()
    second = new_id()
    return [
        DocPassage(id=first, text="The library opened in March and served 214 visitors.", char_start=0, char_end=56),
        DocPassage(id=second, text="Sleep itself was never measured.", char_start=58, char_end=90),
    ]


def test_verbatim_quote_is_located_with_offsets(passages):
    located = locate("served 214 visitors", passages[0])
    assert located is not None
    start, end, mode = located
    assert mode == "verbatim"
    assert passages[0].text[start - passages[0].char_start:end - passages[0].char_start] == "served 214 visitors"


def test_whitespace_only_difference_still_counts_as_verbatim(passages):
    assert locate("library  opened in March", passages[0]) is not None


def test_invented_quote_is_rejected_and_the_finding_dropped(passages):
    draft = FindingDraft(
        kind="statistic",
        title="Attendance doubled",
        body="Attendance doubled after the campaign.",
        primary_passage_id=passages[0].id,
        evidence=[EvidenceDraft(passage_id=passages[0].id, quote="attendance doubled by 100 per cent")],
    )
    kept, audit = validate_findings([draft], passages)
    assert kept == []
    assert any("not found verbatim" in item["reason"] for item in audit)


def test_quote_attributed_to_the_wrong_passage_is_rejected(passages):
    draft = FindingDraft(
        kind="fact",
        title="Wrong source",
        evidence=[EvidenceDraft(passage_id=passages[1].id, quote="served 214 visitors")],
        primary_passage_id=passages[1].id,
    )
    kept, _ = validate_findings([draft], passages)
    assert kept == []


def test_missing_passage_id_is_rejected(passages):
    draft = FindingDraft(
        kind="fact", title="Ghost", evidence=[EvidenceDraft(passage_id="does-not-exist", quote="anything")],
    )
    kept, audit = validate_findings([draft], passages)
    assert kept == []
    assert any("does not exist" in item["reason"] for item in audit)


def test_finding_keeps_only_the_evidence_that_survives(passages):
    draft = FindingDraft(
        kind="fact",
        title="Partly supported",
        evidence=[
            EvidenceDraft(passage_id=passages[0].id, quote="The library opened in March"),
            EvidenceDraft(passage_id=passages[0].id, quote="the library closed in December"),
        ],
        primary_passage_id=passages[0].id,
    )
    kept, audit = validate_findings([draft], passages)
    assert len(kept) == 1
    assert [evidence.quote for evidence in kept[0].evidence] == ["The library opened in March"]
    assert kept[0].extra["evidence_checked"] == 1


def test_case_and_diacritic_differences_are_labelled_normalised(passages):
    draft = FindingDraft(
        kind="fact",
        title="Normalised",
        evidence=[EvidenceDraft(passage_id=passages[0].id, quote="THE LIBRARY OPENED IN MARCH")],
        primary_passage_id=passages[0].id,
    )
    kept, _ = validate_findings([draft], passages)
    assert len(kept) == 1
    # A normalized match is honest about what it cannot know: no exact character offsets.
    assert kept[0].evidence[0].char_start is None
    assert "not exact" in kept[0].evidence[0].note
    assert kept[0].extra["validated"] is True


def test_primary_passage_is_forced_to_a_cited_one(passages):
    draft = FindingDraft(
        kind="fact",
        title="Mismatched primary",
        evidence=[EvidenceDraft(passage_id=passages[1].id, quote="never measured")],
        primary_passage_id=passages[0].id,
    )
    kept, _ = validate_findings([draft], passages)
    assert kept[0].primary_passage_id == passages[1].id
