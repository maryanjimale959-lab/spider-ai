"""Recommendations: turn validated findings into targeted, prioritised advice.

Where the fix is local, the suggested revision is built from the document's own sentence by a
mechanical transformation (replace the misspelling, delete the duplicated word, split the
run-on at its own conjunction, add the missing full stop, standardise one spelling). Nothing
here rewrites content, adds a claim, or supplies a fact the document does not contain; when a
safe local rewrite is not possible, ``suggested_revision`` stays None and the rationale says
what the author should do instead.
"""
from __future__ import annotations

import re
from collections import Counter

from app.analysis.types import AnalysisContext, FindingDraft, KeywordDraft, RecommendationDraft, Sentence

MAX_RECOMMENDATIONS = 18
SEVERITY_RANK = {"major": 0, "minor": 1, "info": 2}

# Bracketed prompts: clearly marked as instructions to the author, never as content.
CITATION_PROMPT = " [state the source, figure, or date this rests on]"
QUANTIFIER_PROMPT = " [insert the number or share]"


# --------------------------------------------------------------------------- helpers
def _collapse(value: str) -> str:
    return " ".join(value.split()).strip()


def _find_sentence(ctx: AnalysisContext, finding: FindingDraft) -> Sentence | None:
    """The original sentence the finding quotes, so revisions start from real text."""
    if not finding.evidence:
        return None
    quote = _collapse(finding.evidence[0].quote)
    passage_id = finding.evidence[0].passage_id
    for sentence in ctx.sentences:
        if sentence.passage_id != passage_id:
            continue
        text = _collapse(sentence.text)
        if text == quote or quote.startswith(text[:20]) or quote in text or text.startswith(quote[:20]):
            return sentence
    return None


def _sentence_with(ctx: AnalysisContext, finding: FindingDraft) -> tuple[Sentence | None, str]:
    sentence = _find_sentence(ctx, finding)
    if sentence is None:
        return None, ""
    return sentence, sentence.text


def _usable_revision(ctx: AnalysisContext, sentence: Sentence, revision: str) -> str | None:
    """A revision is offered only when it really derives from the original sentence."""
    revision = _collapse(revision)
    original = _collapse(sentence.text)
    if not revision or revision == original or len(revision) < max(4, int(len(original) * 0.5)):
        return None
    if len(revision) > 4000:
        return None
    return revision


SUBJECTISH = (r"(?:I|we|you|he|she|they|it|this|these|that|those|the|a|an|our|their|his|her|"
              r"nobody|somebody|everyone|no|every|each|both|neither)")


def _split_run_on(text: str) -> str | None:
    """Break a long coordinated sentence at its own conjunctions; words are only re-cased.

    A split is allowed only where the conjunction is preceded by a comma or is followed by
    something that can act as a subject, so phrases such as "water harvesting and irrigation
    planning" are never cut in half.
    """
    pattern = re.compile(
        rf"\s*(?:,\s*|\s+)(?=(?:and|but|so|then)\s+(?:{SUBJECTISH})\b)|\s*,\s+(?=(?:and|but|so)\s)",
        re.IGNORECASE,
    )
    parts = pattern.split(text)
    parts = [_collapse(part) for part in parts if part and _collapse(part)]
    if len(parts) < 3:
        return None
    rebuilt = parts[0].rstrip(" ,;") + ". "
    for piece in parts[1:]:
        piece = piece.strip(" ,;")
        if not piece:
            continue
        rebuilt = rebuilt + piece[:1].upper() + piece[1:].rstrip(" ,;") + ". "
    rebuilt = _collapse(rebuilt.replace("..", ".")).rstrip(".") + "."
    return rebuilt if len(rebuilt) > len(parts[0]) else None


def _replace_word(text: str, word: str, replacement: str) -> str:
    regex = re.compile(rf"(?<![\w'-]){re.escape(word)}(?![\w'-])", re.IGNORECASE)
    return regex.sub(replacement, text, count=1)


# --------------------------------------------------------------------------- builders
def _writing_revision(ctx: AnalysisContext, finding: FindingDraft) -> tuple[str | None, str]:
    """Return (suggested_revision, instruction) for one writing finding."""
    sentence, original = _sentence_with(ctx, finding)
    extra = finding.extra or {}
    category = finding.category

    if category == "spelling":
        wrong, right = extra.get("occurrence"), extra.get("correction")
        if wrong and right and sentence is not None:
            revised = _replace_word(original, wrong, right)
            text = (f"Replace \"{wrong}\" with \"{right}\". The corrected sentence is shown; no other word is "
                    "changed.")
            return _usable_revision(ctx, sentence, revised), text
        return None, "Correct the misspelled word shown in the evidence."

    if category == "repetition" and extra.get("fix"):
        word = extra["fix"]
        if sentence is not None:
            revised = re.sub(rf"\b({re.escape(word)})\s+\1\b", r"\1", original, count=1, flags=re.IGNORECASE)
            return (_usable_revision(ctx, sentence, revised),
                    f"Delete the second \"{word}\"; the sentence otherwise stays as written.")
        return None, "Delete the duplicated word."

    if category == "punctuation":
        occurrence = extra.get("occurrence")
        if sentence is not None and occurrence and re.search(r"\s+[,.;:!?]", occurrence):
            revised = re.sub(r"(\S)\s+([,.;:!?])", r"\1\2", original)
            return (_usable_revision(ctx, sentence, revised),
                    "Remove the space before the punctuation mark.")
        if "last_characters" in extra:
            passage = ctx.passage(finding.primary_passage_id)
            if passage is not None:
                return _collapse(passage.text) + ".", "End the paragraph with a full stop."
        return None, "Fix the punctuation spacing shown in the evidence."

    if category == "grammar" and extra.get("expected"):
        expected = str(extra["expected"])
        occurrence = extra.get("occurrence")
        if "/" in expected or sentence is None or not occurrence:
            return None, (f"Rewrite \"{_collapse(str(occurrence))}\" as \"{expected}\". Two alternative forms are "
                          "possible, so the wording has to be the author's choice.")
        revised = _replace_word(original, occurrence, expected)
        return (_usable_revision(ctx, sentence, revised),
                f"Use \"{expected}\" in place of \"{occurrence}\"; the rest of the sentence is untouched.")

    if category == "grammar" and extra.get("occurrence") == "i":
        if sentence is not None:
            revised = re.sub(r"(?<![A-Za-z'])i(?![A-Za-z'])", "I", original)
            return _usable_revision(ctx, sentence, revised), "Capitalise the pronoun \"I\"."
        return None, "Capitalise the pronoun \"I\"."

    if category == "clarity" and extra.get("clauses"):
        if sentence is not None:
            revised = _split_run_on(original)
            if revised:
                return (_usable_revision(ctx, sentence, revised),
                        "Split the sentence at its own conjunctions. The revision reuses the author's words; only "
                        "full stops and capital letters are added.")
        return None, "Break this sentence into one statement per sentence."

    if category == "terminology_consistency":
        preferred = extra.get("preferred")
        variants = extra.get("variants") or {}
        if preferred and variants and sentence is not None:
            other = next((v for v in variants if v != preferred), None)
            if other:
                revised = _replace_word(original, other, preferred)
                return (_usable_revision(ctx, sentence, revised),
                        f"Standardise on \"{preferred}\" (the more frequent form here) throughout the document; "
                        f"this instance changes \"{other}\" only.")
        pair = extra.get("pair")
        if pair and sentence is not None:
            return None, (f"Check whether \"{pair[0]}\" and \"{pair[1]}\" name the same thing. If they do, use the "
                          "more frequent spelling everywhere; if not, leave both.")
        return None, "Use one spelling of this term throughout."

    if category in ("readability", "vocabulary", "tone", "audience_suitability", "logical_flow",
                    "paragraph_structure"):
        return None, (finding.suggestion or "Apply the change described in the finding.")
    return None, (finding.suggestion or "Review the quoted wording.")


def _logic_revision(ctx: AnalysisContext, finding: FindingDraft) -> tuple[str | None, str]:
    sentence, original = _sentence_with(ctx, finding)
    kind = finding.kind

    if kind == "unsupported_claim":
        if sentence is not None:
            return (_collapse(original) + CITATION_PROMPT,
                    "The wording of the claim is kept exactly as written; the bracketed prompt marks the place to "
                    "add the support. Nothing is asserted on the document's behalf until the author fills it in.")
        return None, "Add the evidence this claim rests on, or soften the claim."

    if kind == "ambiguous_statement":
        quantifier = finding.extra.get("quantifier")
        if quantifier and sentence is not None:
            revised = _replace_word(original, quantifier, f"{quantifier}{QUANTIFIER_PROMPT}")
            return (_usable_revision(ctx, sentence, revised),
                    f"Keep \"{quantifier}\" and add the measured value next to it, so the claim becomes checkable.")
        reference = finding.extra.get("reference")
        if reference and sentence is not None:
            return None, (f"Replace \"{reference}\" with the name of the thing you mean; the revision is left to "
                          "you because only you know which referent is intended.")
        acronym = finding.extra.get("acronym")
        if acronym:
            return None, (f"Spell out \"{acronym}\" at its first use. The full term is not in the document, so it "
                          "cannot be inserted automatically.")
        return None, "Make the referent or the quantity explicit."

    if kind == "contradiction":
        return None, ("Two sentences quoted in the finding cannot both stand as written. Decide which case each "
                      "describes and qualify or correct one of them; choosing between them is a judgement about "
                      "the facts, which the document itself does not settle.")

    if kind == "overreaching_conclusion":
        return None, ("Bring the closing statement down to what the body actually showed, or add the evidence that "
                      "would justify the stronger wording. The alternative is the author's decision, not a "
                      "mechanical edit, so no rewrite is proposed.")

    if kind == "logic_gap":
        return None, (f"Add the premise before \"{finding.extra.get('connective', 'therefore')}\" in the same "
                      "paragraph, using the same terms as the conclusion.")
    return None, (finding.suggestion or "Address the issue described in the finding.")


def _understanding_advice(finding: FindingDraft) -> tuple[str, str | None] | None:
    if finding.kind == "purpose" and (finding.extra or {}).get("inferred"):
        return ("The document never states its own purpose, so the reader has to infer it from the opening "
                "sentence. Add one sentence at the start that says what the document is for.", None)
    if finding.kind == "structure":
        extra = finding.extra or {}
        if not extra.get("headings"):
            return ("The document has no headings at all, so a reader cannot jump to a point or see how it is "
                    "organised. Split the longest stretches and label each part.", None)
        if extra.get("headings") and not extra.get("numbered_sections") and extra.get("body_passages", 0) >= 4:
            return ("The sections have headings but no ordering, which makes it hard to refer to \"the part about "
                    "pumps\" in feedback or in a meeting. Number the headings.", None)
    if finding.kind == "conclusion" and len(finding.evidence) < 2:
        return ("The conclusion appears at the end of the last paragraph without being labelled. A short heading "
                "over it tells the reader where the argument lands.", None)
    return None


def build_recommendations(
    ctx: AnalysisContext,
    findings: list[FindingDraft],
    keywords: list[KeywordDraft],
) -> list[RecommendationDraft]:
    """Targeted, prioritised recommendations built from validated findings."""
    drafts: list[tuple[int, int, int, RecommendationDraft]] = []
    seen: set[tuple[str, str]] = set()
    family_seen: Counter = Counter()

    def add(finding: FindingDraft, rationale: str, kind: str, revision: str | None) -> None:
        signature = (kind, _collapse(rationale)[:110].casefold())
        if signature in seen:
            return
        seen.add(signature)
        severity = finding.severity if finding.severity in SEVERITY_RANK else "minor"
        # The family counter keeps one example of each distinct issue type ahead of repeats of
        # the same kind, so a 18-item cap still covers spelling, run-ons, evidence, and style.
        family = f"{finding.kind}:{finding.category or ''}:{extra_family(finding)}"
        family_seen[family] += 1
        drafts.append((
            SEVERITY_RANK.get(severity, 1),
            family_seen[family] - 1,
            _position(ctx, finding),
            RecommendationDraft(
                rationale=_collapse(rationale),
                kind=kind,
                passage_id=finding.primary_passage_id,
                suggested_revision=_collapse(revision) if revision else None,
                finding=finding,
                severity=severity,
            ),
        ))

    for finding in findings:
        if not finding.evidence:
            continue
        extra = finding.extra or {}

        if finding.kind == "writing_issue":
            revision, instruction = _writing_revision(ctx, finding)
            if instruction is None:
                continue
            rationale = f"{finding.title}. {instruction}"
            if finding.suggestion and finding.suggestion not in rationale:
                rationale = f"{rationale} {finding.suggestion}"
            add(finding, rationale, _kind_for(finding.category), revision)
            continue

        if finding.kind in ("unsupported_claim", "contradiction", "ambiguous_statement",
                            "overreaching_conclusion", "logic_gap"):
            revision, instruction = _logic_revision(ctx, finding)
            rationale = f"{finding.title}. {instruction}"
            add(finding, rationale, _kind_for(finding.kind), revision)
            continue

        if finding.kind == "clarifying_question":
            continue

        if finding.kind in ("subject", "purpose", "structure", "conclusion", "central_idea"):
            advice = _understanding_advice(finding)
            if advice:
                rationale, revision = advice
                add(finding, rationale, "structure", revision)
            continue

        if finding.kind == "action_item":
            add(finding, f"{finding.title}. Name the person or office responsible and the date in the same "
                         "sentence, so the instruction can be tracked.", "revision", None)
            continue

        if finding.kind == "decision":
            add(finding, f"{finding.title}. Record who decided and when next to the decision; a decision without "
                         "an owner and a date is not actionable.", "revision", None)
            continue

        if finding.kind == "date" and extra.get("type") == "date" and extra.get("date_form") == "year":
            add(finding, f"{finding.title}. Only the year is given. Add the month or the deadline if the date "
                         "matters for the action it dates.", "revision", None)
            continue

    # Keyword coverage advice: the leading term should be present where it matters.
    primary = [k for k in keywords if k.category == "primary" and k.in_document]
    for keyword in primary[:2]:
        if keyword.occurrences >= 2 and len(keyword.passage_ids) == 1:
            finding = next((f for f in findings if f.kind == "keyword_concept"
                            and f.extra.get("term") == keyword.term), None)
            if finding is None:
                continue
            rationale = (f"\"{keyword.term}\" is a leading term of the document but occurs in a single passage. "
                         "Mention it in the opening and in the conclusion so the reader can see the thread.")
            add(finding, rationale, "structure", None)

    drafts.sort(key=lambda item: (item[0], item[1], item[2], item[3].rationale))
    return [draft for _sev, _family, _pos, draft in drafts][:MAX_RECOMMENDATIONS]


def extra_family(finding: FindingDraft) -> str:
    """Stable sub-label so two spelling recommendations still count as one family."""
    extra = finding.extra or {}
    return str(extra.get("correction") or extra.get("expected") or extra.get("quantifier")
               or extra.get("connective") or "")


def _position(ctx: AnalysisContext, finding: FindingDraft) -> int:
    passage = ctx.passage(finding.primary_passage_id)
    if passage is None:
        return 10 ** 6
    for position, candidate in enumerate(ctx.passages):
        if candidate.id == passage.id:
            return position
    return 10 ** 6


def _kind_for(label: str | None) -> str:
    if not label:
        return "revision"
    if label in ("spelling", "grammar", "punctuation", "terminology_consistency"):
        return "revision"
    if label in ("clarity", "readability", "vocabulary", "repetition"):
        return "style"
    if label in ("tone", "audience_suitability"):
        return "tone"
    if label in ("logical_flow", "paragraph_structure"):
        return "structure"
    if label == "unsupported_claim":
        return "evidence"
    if label in ("contradiction", "ambiguous_statement", "overreaching_conclusion", "logic_gap"):
        return "clarity"
    return "revision"
