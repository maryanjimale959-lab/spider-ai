"""Document understanding pass: subject, purpose, central ideas, arguments, conclusions,
structure, and observable strengths.

Every statement is built from the passages themselves: the title and heading passages, the
first sentence of each section, and counted structural facts. Nothing here summarises the
document's *meaning* beyond what the text states, and every finding carries a quote that the
evidence validator can find verbatim in the cited passage.
"""
from __future__ import annotations

import re
from collections import defaultdict

from app.analysis.evidence import locate
from app.analysis.language import ALL
from app.analysis.segmentation import normalize_tokens
from app.analysis.types import (
    AnalysisContext,
    DocPassage,
    EvidenceDraft,
    FindingDraft,
    Sentence,
)

# --------------------------------------------------------------------------- markers
PURPOSE = {
    "en": r"\b(?:the\s+purpose\s+of|this\s+(?:report|study|paper|document|essay|proposal|plan|"
          r"review|analysis|note|chapter)\s+(?:aims|is\s+to|seeks|examines|analyses|analyzes|"
          r"discusses|describes|explores|reviews|presents|outlines|assesses|evaluates)|"
          r"we\s+aim\s+to|the\s+(?:objective|goal|aim)\s+(?:of|is)|in\s+order\s+to|"
          r"the\s+report\s+focuses|this\s+work\s+focuses)\b",
    "ar": r"(?:الغرض\s+من|هدف\s+هذا|يهدف|تهدف|تتناول\s+هذه|تستعرض\s+هذه|تبحث\s+هذه|"
          r"تقدم\s+هذه|بهدف|هذه\s+الدراسة|هذه\s+التقرير|الغاية\s+من)",
    "so": r"(?:ujeeddada|hadafka|qorshahan\s+wuxuu|waxay\s+ujeeddaa|si\s+loo|iyadoo\s+la\s+doonayo|"
          r"barashada|warbixintan\s+waxay|drasadan\s+waxay|qorshaha\s+loogu|ulajeeddada)",
}

ARGUMENT = {
    "en": r"\b(?:because|since|therefore|thus|hence|as\s+a\s+result|which\s+means|leads\s+to|"
          r"results?\s+in|shows?\s+that|indicates?\s+that|demonstrates?\s+that|however|although|"
          r"even\s+though|for\s+this\s+reason|on\s+the\s+other\s+hand|should|must|ought\s+to)\b",
    "ar": r"(?:لأن|لأنه|إذن|اذاً|إذاً|لذلك|وبالتالي|نتيجة\s+لذلك|على\s+الرغم|ومع\s+ذلك|"
          r"مما\s+يؤدي|يدل\s+على|يشير\s+إلى|ينبغي|يجب)",
    "so": r"(?:maxaa\s+yeelay|maadaama|sidaas\s+darteed|hase\s+yeeshee|inkastoo|waxay\s+muujisaa|"
          r"waxay\s+keentay|sidaa\s+dawadeed|taas\s+oo\s+darteed|waa\s+in|waajib\s+inay)",
}

CONCLUSION_HEADINGS = {
    "en": r"\b(?:conclusion|conclusions|summary|summing\s+up|closing|findings|recommendations|"
          r"final\s+remarks|outlook)\b",
    "ar": r"(?:خاتمة|خلاصة|الاستنتاجات|النتائج|التوصيات|في\s+النهاية)",
    "so": r"(?:gunaanad|soo\s*koobid|soo-koobid|talooyin|natiijooyin|gebo\s*gebo|gabagabo)",
}

DEFINITION = {
    "en": r"[\w'’\- ]{3,60}?\s+(?:is\s+defined\s+as|are\s+defined\s+as|defined\s+as|means|refers\s+to|"
          r"is\s+understood\s+as|is\s+known\s+as|is\s+referred\s+to\s+as)\s+[\w'’\- ]{3,}",
    "ar": r"[\u0600-\u06FF'’\- ]{3,60}?\s+(?:هو|هي|عبارة\s+عن|يقصد\s+به|يقصد\s+بـ|يعني|تُعرَّف\s+بأنها|"
          r"تعني)\s+[\u0600-\u06FF'’\- ]{3,}",
    "so": r"(?:(?!waa\b)[\w'’\- ]{3,60}?)\s+waa\s+[\w'’\- ]{2,40}?\s+(?:oo|kaasi\s+oo|taas\s+oo|asi\s+oo|"
          r"oo\s+la\s+macaan)",
}

DATA_UNITS = (
    r"(?:%|percent|per\s+cent|million|billion|trillion|thousand|kg|ton|tons|km|hectare|hectares|"
    r"meter|meters|metre|metres|people|person|students|households|families|patients|schools|"
    r"days|months|years|weeks|times|usd|dollars|euros|units|villages|districts|cubes|cm3|km2)"
)
NUM_WITH_UNIT = re.compile(
    rf"\b\d[\d,.]*\s*{DATA_UNITS}\b|\b\d+(?:[.,]\d+)?\s*%|\b\d[\d,.]*\s+(?:cubic|square)\b",
    re.IGNORECASE,
)
DATEISH = re.compile(
    r"\b(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[A-Za-z\u0600-\u06FF]{3,12}?\s+\d{2,4}|"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{2,4}|(?:1[89]|2[01])\d{2})\b",
    re.IGNORECASE,
)
OBLIGATION = {
    "en": r"\b(?:must|shall|is\s+required\s+to|are\s+required\s+to|needs?\s+to\s+be|will\s+be\s+submitted|"
          r"should\s+submit|deadline|by\s+the\s+end\s+of)\b",
    "ar": r"(?:يجب|ينبغي|يتعين|موعد\s+نهائي|عليه\s+أن|يجب\s+أن)",
    "so": r"(?:waa\s+in|waajib|waa\s+la\s+amaar|muddo\s+kama\s+dambeysa|markii\s+la\s+gaadho)",
}

# --------------------------------------------------------------------------- helpers
def _stopwords(language: str) -> set[str]:
    if language in ALL:
        return ALL[language]
    union: set[str] = set()
    for stop in ALL.values():
        union |= stop
    return union


def _content_tokens(text: str, language: str) -> list[str]:
    stop = _stopwords(language)
    minimum = 2 if language == "ar" else 3
    return [t for t in normalize_tokens(text) if len(t) >= minimum and t not in stop]


def _sentences_by_passage(ctx: AnalysisContext) -> dict[str, list[Sentence]]:
    grouped: dict[str, list[Sentence]] = defaultdict(list)
    for sentence in ctx.sentences:
        grouped[sentence.passage_id].append(sentence)
    return grouped


def _sections(ctx: AnalysisContext) -> list[dict]:
    """Group passages under the heading that opens them (unclosed intro group first)."""
    out: list[dict] = []
    current: dict | None = None
    for passage in ctx.passages:
        if passage.is_heading:
            current = {"heading": passage, "body": []}
            out.append(current)
        else:
            if current is None:
                current = {"heading": None, "body": []}
                out.append(current)
            current["body"].append(passage)
    return out


def _section_label(section: dict, language: str) -> str:
    heading = section.get("heading")
    if heading is not None:
        return _clamp(heading.text, 60)
    body = section.get("body") or []
    if body and body[0].section_title:
        return _clamp(body[0].section_title, 60)
    return "the opening section"


def _clamp(text: str, limit: int = 88) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[:limit]
    space = cut.rfind(" ")
    if space > limit - 20:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "..."


def _title(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= 90 else _clamp(collapsed, 85)


def _passage_evidence(ctx: AnalysisContext, passage: DocPassage, note: str | None = None) -> EvidenceDraft | None:
    return _evidence(ctx, passage.id, passage.text.strip(), passage.text.strip(), note)


def _sentence_evidence(ctx: AnalysisContext, sentence: Sentence, note: str | None = None) -> EvidenceDraft | None:
    return _evidence(ctx, sentence.passage_id, sentence.text.strip(), sentence.text.strip(), note)


def _evidence(ctx: AnalysisContext, passage_id: str, wanted: str, fallback: str,
              note: str | None = None) -> EvidenceDraft | None:
    """Quote only if the validator can locate it; otherwise fall back to the whole sentence."""
    passage = ctx.passage(passage_id)
    if passage is None:
        return None
    for candidate in (wanted.strip(), fallback.strip()):
        if candidate and len(candidate) <= len(passage.text) and locate(candidate, passage) is not None:
            return EvidenceDraft(passage_id=passage.id, quote=candidate, note=note)
    return None


def _finding(
    ctx: AnalysisContext,
    kind: str,
    title: str,
    body: str,
    evidence: list[EvidenceDraft | None],
    *,
    suggestion: str | None = None,
    severity: str = "info",
    confidence: float = 0.8,
    extra: dict | None = None,
) -> FindingDraft | None:
    kept = [e for e in evidence if e is not None]
    if not kept:
        return None
    primary = ctx.passage(kept[0].passage_id)
    if primary is None:
        return None
    return FindingDraft(
        kind=kind,
        title=_title(title),
        body=" ".join(body.split()),
        evidence=kept,
        primary_passage_id=primary.id,
        suggestion=suggestion,
        severity=severity,
        confidence=confidence,
        extra=extra or {},
    )


def _marker_find(ctx: AnalysisContext, sentences: list[Sentence], patterns: dict[str, str],
                 language: str) -> tuple[Sentence, str] | None:
    """First sentence matching the language pattern (falls back to other languages when unknown)."""
    order = [language] if language in patterns else list(patterns)
    if language not in patterns:
        order = list(patterns)
    for code in order:
        pattern = re.compile(patterns[code], re.IGNORECASE)
        for sentence in sentences:
            match = pattern.search(sentence.text)
            if match and ctx.passage(sentence.passage_id) is not None:
                return sentence, _clamp(match.group(0), 40)
    return None


# --------------------------------------------------------------------------- findings
def _subject_finding(ctx: AnalysisContext, sections: list[dict]) -> list[FindingDraft]:
    headings = [p for p in ctx.passages if p.is_heading]
    title_passage = next((p for p in ctx.passages if p.kind == "title"), None)
    if title_passage is None:
        title_passage = headings[0] if headings else None

    if title_passage is not None:
        title_terms = set(_content_tokens(title_passage.text, ctx.language))
        echoing = sum(
            1 for p in ctx.passages
            if p.id != title_passage.id and title_terms & set(_content_tokens(p.text, ctx.language))
        )
        evidence = _passage_evidence(ctx, title_passage, note="Title or heading quoted as written.")
        finding = _finding(
            ctx, "subject",
            f"Subject: {_clamp(title_passage.text, 60)}",
            f"The document states its subject in a title/heading passage ({title_passage.kind}). "
            f"{echoing} further passage(s) reuse at least one content term from that heading, "
            f"so the subject named there is the one the body keeps returning to.",
            [evidence],
            extra={"source": "title" if title_passage.kind == "title" else "heading",
                   "echoing_passages": echoing},
            confidence=0.88,
        )
        if finding:
            return [finding]

    first_body = ctx.body_passages()[0] if ctx.body_passages() else None
    if first_body is not None:
        opening = _sentences_by_passage(ctx).get(first_body.id, [])
        sentence = opening[0] if opening else None
        if sentence is not None:
            finding = _finding(
                ctx, "subject",
                f"Subject: {_clamp(sentence.text, 60)}",
                "The document has no title or heading passage, so the subject is taken from the opening "
                "sentence of the first paragraph, which is what the reader meets first.",
                [_sentence_evidence(ctx, sentence)],
                confidence=0.7,
                extra={"source": "opening_sentence"},
            )
            return [finding] if finding else []
    return []


def _purpose_finding(ctx: AnalysisContext, sections: list[dict]) -> list[FindingDraft]:
    sentences = ctx.sentences[:80]
    hit = _marker_find(ctx, sentences, PURPOSE, ctx.language)
    if hit:
        sentence, marker = hit
        evidence = _sentence_evidence(ctx, sentence)
        finding = _finding(
            ctx, "purpose",
            f"Purpose stated in the text ({_label_of(ctx, sentence)})",
            f"The document declares its own purpose with the phrase \"{marker}\". "
            f"The sentence that does this is quoted here, so the purpose is the author's wording, not an inference.",
            [evidence],
            extra={"marker": marker, "sentence_index": sentence.index},
            confidence=0.85,
        )
        return [finding] if finding else []

    first_body = ctx.body_passages()[0] if ctx.body_passages() else None
    if first_body is None:
        return []
    opening = _sentences_by_passage(ctx).get(first_body.id, [])
    sentence = opening[0] if opening else None
    if sentence is None:
        return []
    numbers = len(NUM_WITH_UNIT.findall(first_body.text))
    obligations = _count_markers(ctx.sentences, OBLIGATION, ctx.language)
    data_note = (
        f"The opening paragraph also contains {numbers} figure(s) expressed with a unit, "
        "which points to a reporting purpose."
        if numbers else
        f"No figure with a unit appears in the opening paragraph; {obligations} obligation "
        "statement(s) exist in the document, which points to a directive purpose."
        if obligations else
        "The opening is descriptive rather than directive or numerical."
    )
    finding = _finding(
        ctx, "purpose",
        f"Purpose inferred from the opening ({_label_of(ctx, sentence)})",
        f"No explicit purpose statement was found in the text, so purpose is inferred. "
        f"The document opens with: quoted below. {data_note}",
        [_sentence_evidence(ctx, sentence)],
        suggestion="State the purpose in one sentence at the start so the reader does not have to infer it.",
        confidence=0.6,
        extra={"inferred": True},
    )
    return [finding] if finding else []


def _label_of(ctx: AnalysisContext, sentence: Sentence) -> str:
    passage = ctx.passage(sentence.passage_id)
    if passage is None:
        return "body"
    if passage.section_title:
        return _clamp(passage.section_title, 40)
    for section in _sections(ctx):
        if sentence.passage_id in {p.id for p in section["body"]}:
            return _section_label(section, ctx.language)
    return passage.kind


def _count_markers(sentences: list[Sentence], patterns: dict[str, str], language: str) -> int:
    codes = [language] if language in patterns else list(patterns)
    compiled = [re.compile(patterns[c], re.IGNORECASE) for c in codes if c in patterns]
    if not compiled:
        compiled = [re.compile(patterns[c], re.IGNORECASE) for c in patterns]
    hits = 0
    for sentence in sentences:
        if any(p.search(sentence.text) for p in compiled):
            hits += 1
    return hits


def _central_idea_findings(ctx: AnalysisContext, sections: list[dict]) -> list[FindingDraft]:
    grouped = _sentences_by_passage(ctx)
    out: list[FindingDraft] = []
    candidates: list[tuple[str, DocPassage, str]] = []
    for section in sections:
        for passage in section["body"]:
            candidates.append((_section_label(section, ctx.language), passage, "section"))
    if not candidates:
        candidates = [("the opening section", p, "paragraph") for p in ctx.body_passages()]

    seen: set[str] = set()
    for label, passage, _kind in candidates:
        if len(out) >= 4:
            break
        sentences = grouped.get(passage.id, [])
        if not sentences:
            continue
        sentence = sentences[0]
        if sentence.text in seen:
            continue
        seen.add(sentence.text)
        rest = len(sentences) - 1
        evidence = _sentence_evidence(ctx, sentence)
        finding = _finding(
            ctx, "central_idea",
            f"Central idea in {_clamp(label, 45)}",
            f"The leading sentence of this part carries its main idea; {rest} further sentence(s) develop it "
            f"inside the same passage ({passage.words or len(passage.text.split())} words).",
            [evidence],
            extra={"section": label, "developing_sentences": rest},
            confidence=0.75,
        )
        if finding:
            out.append(finding)
    return out


def _argument_findings(ctx: AnalysisContext) -> list[FindingDraft]:
    hit_count = 0
    out: list[FindingDraft] = []
    for sentence in ctx.sentences:
        if hit_count >= 4:
            break
        passage = ctx.passage(sentence.passage_id)
        if passage is None or passage.is_heading:
            continue
        pair = _marker_find_in(ctx, sentence)
        if not pair:
            continue
        marker, connective = pair
        evidence = _sentence_evidence(ctx, sentence)
        finding = _finding(
            ctx, "argument",
            f"Argument step: claim linked by \"{_clamp(connective, 30)}\"",
            "This sentence joins a position to a reason or consequence using the connective quoted below. "
            "It is the kind of sentence that carries the document's argument forward.",
            [evidence],
            severity="info",
            extra={"connective": connective, "marker": marker},
            confidence=0.7,
        )
        if finding:
            out.append(finding)
            hit_count += 1
    return out


def _marker_find_in(ctx: AnalysisContext, sentence: Sentence) -> tuple[str, str] | None:
    codes = [ctx.language] if ctx.language in ARGUMENT else list(ARGUMENT)
    for code in codes:
        pattern = re.compile(ARGUMENT[code], re.IGNORECASE)
        match = pattern.search(sentence.text)
        if match:
            return code, match.group(0).strip().lower() if code == "en" else match.group(0)
    return None


def _conclusion_finding(ctx: AnalysisContext, sections: list[dict]) -> list[FindingDraft]:
    grouped = _sentences_by_passage(ctx)
    heading_pattern = (CONCLUSION_HEADINGS.get(ctx.language)
                       or "|".join(CONCLUSION_HEADINGS.values()))
    regex = re.compile(heading_pattern, re.IGNORECASE)

    target: DocPassage | None = None
    label = ""
    for section in sections:
        heading = section["heading"]
        if heading is not None and regex.search(heading.text) and section["body"]:
            target = section["body"][-1]
            label = _clamp(heading.text, 45)
            break
    if target is None:
        body = ctx.body_passages()
        if not body:
            return []
        target = body[-1]
        label = "the final paragraph"

    sentences = grouped.get(target.id, [])
    sentence = sentences[-1] if sentences else None
    if sentence is None:
        return []
    closing = sentences[0] if len(sentences) > 1 else sentence
    evidence = [_sentence_evidence(ctx, sentence)]
    if closing is not sentence:
        evidence.append(_sentence_evidence(ctx, closing))
    finding = _finding(
        ctx, "conclusion",
        f"Conclusion at {_clamp(label, 45)}",
        f"{label.title()} ends the document's reasoning. The closing sentence is quoted; the opening sentence of "
        "the same passage is quoted with it so the reader can see what the conclusion wraps up.",
        evidence,
        extra={"location": label},
        confidence=0.75,
    )
    return [finding] if finding else []


def _structure_finding(ctx: AnalysisContext, sections: list[dict]) -> list[FindingDraft]:
    headings = [p for p in ctx.passages if p.is_heading]
    body = ctx.body_passages()
    list_items = [p for p in ctx.passages if p.kind == "list_item"]
    table_rows = [p for p in ctx.passages if p.kind == "table_row"]
    numbered = [p for p in headings if re.match(r"^\s*(?:\d+[.)]?|[-*•]|[IVXLC]+[.)])\b", p.text)]
    sentences = len(ctx.sentences)
    words = sum((p.words or len(p.text.split())) for p in ctx.passages)
    avg = round(words / len(body), 1) if body else 0.0
    longest = max(body, key=lambda p: len(p.text), default=None)

    list_note = f"{len(list_items)} list item(s)" if list_items else "no list items"
    row_note = f"{len(table_rows)} table row(s)" if table_rows else "no table rows"
    parts = [
        f"{len(headings)} title/heading passage(s)",
        f"{len(body)} body passage(s)",
        list_note,
        row_note,
        f"{sentences} sentence(s)",
        f"about {words} word(s) total, averaging {avg} words per body passage",
    ]
    evidence: list[EvidenceDraft | None] = []
    if headings:
        evidence.append(_passage_evidence(ctx, headings[0], note="First heading, quoted as written."))
    if not evidence and body:
        evidence.append(_passage_evidence(ctx, body[0]))
    title = "Structure: " + _clamp(", ".join(parts[:2]), 70)
    body_text = "The document is organised as " + ", ".join(parts) + "."
    if numbered:
        body_text += f" {len(numbered)} heading(s) carry an explicit number or bullet marker."
    if longest is not None:
        body_text += (f" The longest body passage holds {len(longest.text.split())} words; "
                      f"the shortest holds {min((p.words or len(p.text.split())) for p in body)} words.")
    extra = {
        "headings": len(headings), "body_passages": len(body), "list_items": len(list_items),
        "table_rows": len(table_rows), "sentences": sentences, "numbered_headings": len(numbered),
        "numbered_sections": bool(numbered),
    }
    finding = _finding(ctx, "structure", title, body_text, evidence, extra=extra, confidence=0.9)
    return [finding] if finding else []


def _strength_findings(ctx: AnalysisContext, sections: list[dict]) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    grouped = _sentences_by_passage(ctx)

    # Consistent sectioning: headings that are each followed by body text.
    filled = [s for s in sections if s["heading"] is not None and s["body"]]
    if len(filled) >= 2:
        evidence = _passage_evidence(ctx, filled[0]["heading"])
        finding = _finding(
            ctx, "strength",
            "Strength: consistent sectioning",
            f"{len(filled)} headings are each followed by at least one body passage, so no heading is left empty. "
            "A reader can navigate the document by its headings alone.",
            [evidence],
            severity="info",
            extra={"property": "sectioning", "filled_headings": len(filled)},
            confidence=0.85,
        )
        if finding:
            out.append(finding)

    # Defined terms.
    definition_hit = _marker_find(ctx, ctx.sentences, DEFINITION, ctx.language)
    if definition_hit:
        sentence, marker = definition_hit
        finding = _finding(
            ctx, "strength",
            "Strength: key terms are defined",
            f"The document defines a term in its own words (pattern: \"{_clamp(marker, 40)}\"). "
            "Defining terms in-text reduces ambiguity for the reader.",
            [_sentence_evidence(ctx, sentence)],
            extra={"property": "defined_terms"},
            confidence=0.8,
        )
        if finding:
            out.append(finding)

    # Data present.
    data_sentences = [s for s in ctx.sentences if NUM_WITH_UNIT.search(s.text)]
    if data_sentences:
        longest = max(data_sentences, key=lambda s: len(NUM_WITH_UNIT.findall(s.text)))
        finding = _finding(
            ctx, "strength",
            "Strength: quantitative data is present",
            f"{len(data_sentences)} sentence(s) state figures together with a unit or percentage sign, "
            "which makes claims checkable instead of purely verbal.",
            [_sentence_evidence(ctx, longest)],
            extra={"property": "data_present", "sentences_with_figures": len(data_sentences)},
            confidence=0.8,
        )
        if finding:
            out.append(finding)

    # Dated statements.
    dated = [s for s in ctx.sentences if DATEISH.search(s.text)]
    if dated:
        finding = _finding(
            ctx, "strength",
            "Strength: statements are anchored in time",
            f"{len(dated)} sentence(s) carry an explicit date or year, so the reader can order events "
            "instead of guessing when something happened.",
            [_sentence_evidence(ctx, dated[0])],
            extra={"property": "dated_statements", "sentences_with_dates": len(dated)},
            confidence=0.78,
        )
        if finding:
            out.append(finding)

    # Action items.
    obligation_hit = _marker_find(ctx, ctx.sentences, OBLIGATION, ctx.language)
    if obligation_hit:
        sentence, marker = obligation_hit
        finding = _finding(
            ctx, "strength",
            "Strength: duties and deadlines are stated",
            f"The document assigns obligations explicitly (marker: \"{_clamp(marker, 30)}\"), which tells the "
            "reader who has to act, instead of leaving it implied.",
            [_sentence_evidence(ctx, sentence)],
            extra={"property": "action_items"},
            confidence=0.75,
        )
        if finding:
            out.append(finding)

    # Lists used for enumeration.
    list_items = [p for p in ctx.passages if p.kind == "list_item"]
    if len(list_items) >= 2:
        finding = _finding(
            ctx, "strength",
            "Strength: enumeration broken into list items",
            f"{len(list_items)} list-item passages separate individual points from the prose, which makes them "
            "easier to check one by one.",
            [_passage_evidence(ctx, list_items[0])],
            extra={"property": "lists", "list_items": len(list_items)},
            confidence=0.75,
        )
        if finding:
            out.append(finding)

    # Multi-paragraph sections with more than one sentence each.
    developed = [s for s in filled if sum(len(grouped.get(p.id, [])) for p in s["body"]) >= 3]
    if developed and not any(f.extra.get("property") == "sectioning" for f in out):
        finding = _finding(
            ctx, "strength",
            "Strength: sections are developed, not named only",
            f"{len(developed)} heading(s) open parts that contain three or more sentences, so the structure is "
            "supported by actual content rather than headings alone.",
            [_passage_evidence(ctx, developed[0]["heading"])],
            extra={"property": "developed_sections", "sections": len(developed)},
            confidence=0.7,
        )
        if finding:
            out.append(finding)

    return out[:4]


def analyze_understanding(ctx: AnalysisContext) -> list[FindingDraft]:
    """Subject, purpose, central ideas, arguments, conclusion, structure, strengths."""
    sections = _sections(ctx)
    findings: list[FindingDraft] = []
    findings += _subject_finding(ctx, sections)
    findings += _purpose_finding(ctx, sections)
    findings += _central_idea_findings(ctx, sections)
    findings += _argument_findings(ctx)
    findings += _conclusion_finding(ctx, sections)
    findings += _structure_finding(ctx, sections)
    findings += _strength_findings(ctx, sections)
    return [f for f in findings if f and f.evidence]
