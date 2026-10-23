"""Logic and evidence investigation.

Looks for claims the document does not support, statements that conflict, conclusions that
reach further than the body, gaps between a premise and its "therefore", and wording too
vague to test. The wording of every finding is deliberately careful: a missing citation does
not make a claim false, it makes it uncheckable inside this document. Questions for the
reader are derived only from observations already made here.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from app.analysis.evidence import locate
from app.analysis.language import ALL
from app.analysis.segmentation import normalize_tokens, normalize_word, tokenize
from app.analysis.types import AnalysisContext, DocPassage, EvidenceDraft, FindingDraft, Sentence

ASSERTION = {
    "en": r"\b(?:proves?|proved|guarante(?:e|ed|d)|clearly|obviously|evidently|necessarily|always|never|"
          r"all\s+\w+|every\s+\w+|no\s+\w+\s+(?:can|could|will|would)|studies\s+show|research\s+shows|"
          r"it\s+is\s+known|everyone\s+knows|undoubtedly|certainly|definitely|without\s+doubt|"
          r"in\s+every\s+case|completely|entirely)\b",
    "ar": r"(?:يُثبت|يثبت|بوضوح|بالتأكيد|لا\s+شك|دائمًا|دائما|أبدًا|ابدا|جميع|كل\s+\w+|"
          r"الدراسات\s+توضح|من\s+المعروف|بلا\s+شك|حتمًا|حتما|كامل)",
    "so": r"(?:caddeynayaa|caddeynaysaa|hubaal|madan\s+shaki\s+lahayn|had\s+iyo\s+hadba|waligii|"
          r"dhamaan|kulan\s+caddeyn|la\s+og\s+yahay|run\s+ahayd|hubsho)",
}
SUPPORT = {
    "en": r"(?:\b(?:1[0-9]{3}|20[0-9]{2}|21[01][0-9])\b|\[[^\]]{1,60}\]|\([^)]{1,60}\d[^)]{0,40}\)|"
          r"\baccording\s+to\b|\bet\s+al\b|\bcited\s+by\b|\bas\s+reported\b|\breferences?\b|"
          r"\bsurvey\b|\bstudy\b|\breport(?:ed)?\s+(?:by|in)\b|\bhttps?://|\bpage\s+\d+|\bp\.\s*\d+|"
          r"\bnote\s+\d+\b)",
    "ar": r"(?:[0-9\u0660-\u0669]{4}|وفقًا\s+ل|حسب\s+ما|كما\s+ورد|دراسة|مسح|"
          r"تقرير\s+من|\[[^\]]{1,40}\]|\([^)]{1,40}[0-9\u0660-\u0669]{1,4}[^)]{0,20}\))",
    "so": r"(?:[0-9]{4}|sida\s+loo\s+sheegay|warbixintii|sahan|darasad|\[[^\]]{1,40}\]|"
          r"\([^)]{1,40}[0-9]{1,4}[^)]{0,20}\))",
}
NEGATION = {
    "en": r"\b(?:not|no|never|cannot|can\s+not|neither|nor|without|fails?\s+to|lacks?\s+"
          r"(?:any)?|did\s+not|does\s+not|is\s+not|are\s+not|was\s+not|were\s+not|has\s+not|"
          r"have\s+not|had\s+not|will\s+not|would\s+not|should\s+not|do\s+not)\b",
    "ar": r"(?:ليس|ليست|لن|لم|ولا|غير|بلا|\bلا\b|\bما\b\s+(?:يستطيع|يمكن|يقدر|يوجد))",
    "so": r"(?:\bma\b|\baan\b|\bmayan\b|\bmay\b|\bwaxba\b|\baysan\b|\bisan\b|\ble'a\b|\bnot\b)",
}
AFFIRMATION = {
    "en": r"\b(?:is|are|was|were|can|could|will|would|does|do|has|have|had|should|must|may)\b",
    "ar": r"(?:هو|هي|يوجد|يمكن|يستطيع|كان|كانت|قد\s+تم|تم|يكون|تكون)",
    "so": r"(?:\bwaa\b|\bayaa\b|\bbaa\b|\bwuxuu\b|\bwaxay\b|\buu\b|\bshaqaynayaa\b)",
}
HEDGES = {
    "en": r"\b(?:may|might|could|perhaps|possibly|probably|appears|seems|suggests|indicates?|"
          r"some\s+evidence|in\s+some\s+cases|partially|not\s+always|unclear)\b",
    "ar": r"(?:قد|ربما|يبدو|يشير|من الممكن|أحيانًا|بعض\s+الأدلة)",
    "so": r"(?: laga yaabaa|yeelan|suuragal|mark\w*\s+qaar|lahaan|inkastoo|malaha|sa\w*qaar)",
}
CONSEQUENCE = {
    "en": r"\b(?:therefore|thus|hence|so\b|as\s+a\s+result|consequently|accordingly|it\s+follows)\b",
    "ar": r"(?:لذلك|إذن|اذاً|وبالتالي|نتيجة\s+لذلك|من\s+أجل\s+ذلك|لهذا)",
    "so": r"(?:sidaas\s+darteed|sidaa\s+dawadeed|taas\s+oo\s+darteed|markaas|sida\s+ku\s+habsan)",
}
PRONOUN_START = {
    "en": r"^(?:this|that|these|those|it|they|which|he|she|there)\b",
    "ar": r"^(?:هذا|هذه|ذلك|ذَلِكَ|تلك|هو|هي|هم|هن)",
    "so": r"^(?:kan|taas|kuwa|waa|isag|iyad|sidaas| taas)\b",
}
VAGUE = {
    "en": r"\b(?:some|several|many|a\s+lot\s+of|a\s+number\s+of|various|few|most|numerous|"
          r"a\s+great\s+deal|plenty|lots|a\s+while|often|rarely|sometimes)\b",
    "ar": r"(?:بعض|عدة|كثير|عدد\s+من|العديد|غالب|أحيانًا|قليل)",
    "so": r"(?:qaar|badan|koob|tir\w+|ayaar|imar|dhawr|marar\s+qaar|weyn)",
}
CONCLUSION_HEAD = {
    "en": r"\b(?:conclusion|conclusions|summary|recommendations|findings|closing)\b",
    "ar": r"(?:خاتمة|خلاصة|الاستنتاجات|النتائج|التوصيات)",
    "so": r"(?:gunaanad|soo\s*koobid|soo-koobid|talooyin|natiijooyin|gabay\s+soo)",
}
VERBISH = re.compile(r"^\w{0,12}(?:ing|ed|es|s)$", re.IGNORECASE)
PRONOUNS = {
    "i", "you", "he", "she", "it", "we", "they", "this", "that", "these", "those", "who", "which",
    "there", "their", "they", "him", "her", "his", "hers", "its", "us", "them",
}
STOP_CONNECTORS = {"the", "of", "and", "to", "in", "a", "an", "for", "on", "with", "at", "by", "from"}


# --------------------------------------------------------------------------- helpers
def _stopwords(language: str) -> set[str]:
    if language in ALL:
        return ALL[language]
    union: set[str] = set()
    for stop in ALL.values():
        union |= stop
    return union


def _content(text: str, language: str) -> list[str]:
    stop = _stopwords(language)
    minimum = 2 if language == "ar" else 3
    return [t for t in normalize_tokens(text) if len(t) >= minimum and t not in stop and not t.isdigit()]


def _pattern(table: dict[str, str], language: str, extra_flags: int = 0) -> re.Pattern:
    codes = [language] if language in table else list(table)
    joined = "|".join(f"(?:{table[c]})" for c in codes)
    flags = re.IGNORECASE if language != "ar" else 0
    return re.compile(joined, flags | extra_flags)


def _clamp(value: str, limit: int = 70) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[:limit]
    if " " in cut[limit - 15:]:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:.") + "..."


def _title(value: str) -> str:
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= 90 else _clamp(collapsed, 85)


def _evidence(ctx: AnalysisContext, sentence: Sentence, span: str | None = None,
              note: str | None = None) -> EvidenceDraft | None:
    passage = ctx.passage(sentence.passage_id)
    if passage is None:
        return None
    candidates = []
    if span:
        candidates.append(" ".join(span.split()).strip())
    candidates.append(" ".join(sentence.text.split()).strip())
    for candidate in candidates:
        if candidate and len(candidate) <= len(passage.text) and locate(candidate, passage) is not None:
            return EvidenceDraft(passage_id=passage.id, quote=candidate, note=note)
    return None


def _finding(ctx: AnalysisContext, kind: str, title: str, body: str, evidence: list[EvidenceDraft | None],
             *, suggestion: str | None = None, severity: str = "major", confidence: float = 0.7,
             extra: dict | None = None) -> FindingDraft | None:
    kept = [e for e in evidence if e is not None]
    if not kept or not kept[0].passage_id:
        return None
    return FindingDraft(
        kind=kind,
        title=_title(title),
        body=" ".join(body.split()),
        evidence=kept,
        primary_passage_id=kept[0].passage_id,
        suggestion=suggestion,
        severity=severity,
        confidence=confidence,
        extra=extra or {},
    )


def _negation_scope_overlap(negative: Sentence, affirmative: Sentence, negation: re.Pattern,
                            language: str) -> str | None:
    """The word the negation acts on, when the other sentence uses that same word positively.

    Requiring the negated term to reappear keeps this rule from pairing every sentence that
    happens to contain "not" with an unrelated one.
    """
    target = set(_content(affirmative.text, language))
    match = negation.search(negative.text)
    if not match:
        return None
    after = [t for t in normalize_tokens(negative.text[match.end():]) if len(t) >= 3][:3]
    for token in after:
        if token in target:
            return token
        # Inflected forms differ (Somali "shaqaynayaa" / "shaqaynayo"), so a shared stem counts.
        stem = token[:5]
        if len(token) >= 5 and any(other.startswith(stem) or token.startswith(other[:5]) for other in target
                                   if len(other) >= 5):
            return token
    return None


def _body_sentences(ctx: AnalysisContext) -> list[Sentence]:
    headings = {p.id for p in ctx.passages if p.is_heading}
    return [s for s in ctx.sentences if s.passage_id not in headings]


def _sentences_of_passage(ctx: AnalysisContext, passage_id: str) -> list[Sentence]:
    return [s for s in ctx.sentences if s.passage_id == passage_id]


# --------------------------------------------------------------------------- findings
def _unsupported_claims(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    assertion = _pattern(ASSERTION, ctx.language)
    support = _pattern(SUPPORT, ctx.language)
    sentences = ctx.sentences
    for position, sentence in enumerate(sentences):
        if len(out) >= 8:
            break
        passage = ctx.passage(sentence.passage_id)
        if passage is None or passage.is_heading:
            continue
        match = assertion.search(sentence.text)
        if not match:
            continue
        window = [sentences[i] for i in (position - 1, position, position + 1) if 0 <= i < len(sentences)]
        if any(support.search(s.text) for s in window):
            continue
        collector_note = ("No citation, figure, date, or named source appears in this sentence or in the "
                          "sentences on either side of it.")
        out.append(_finding(
            ctx, "unsupported_claim",
            f"Claim without in-document support: {_clamp(sentence.text, 55)}",
            f"The sentence states something categorically (\"{_clamp(match.group(0), 30)}\"). "
            f"{collector_note} A missing citation does not show the claim is wrong - it shows that a reader "
            "cannot check it inside this document, and nothing here settles whether the author has the evidence "
            "or not.",
            [_evidence(ctx, sentence)],
            suggestion="Add the support the claim rests on: the figure, the date, the source name, or the "
                       "reasoning that leads to it.",
            severity="major",
            confidence=0.7,
            extra={"marker": match.group(0), "support_found": False, "window_sentences": len(window)},
        ))
    return out


def _contradictions(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    negation = _pattern(NEGATION, ctx.language)
    body = _body_sentences(ctx)
    index: dict[str, list[int]] = defaultdict(list)
    contents = [_content(s.text, ctx.language) for s in body]
    for position, tokens in enumerate(contents):
        for token in set(tokens):
            index[token].append(position)
    pairs: list[tuple[int, int, int]] = []
    for _token, positions in index.items():
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                pairs.append((positions[i], positions[j], abs(positions[i] - positions[j])))
    shared_counter: Counter = Counter()
    for a, b, distance in pairs:
        shared_counter[(a, b)] = len(set(contents[a]) & set(contents[b]))
    for (a, b), shared in sorted(shared_counter.items(), key=lambda item: (item[0][0], item[0][1])):
        if len(out) >= 5:
            break
        if shared < 2:
            continue
        first, second = body[a], body[b]
        if first.passage_id == second.passage_id and first.index == second.index:
            continue
        if b - a > 12:
            continue
        first_neg, second_neg = bool(negation.search(first.text)), bool(negation.search(second.text))
        if first_neg == second_neg:
            continue
        affirmative_side = second if first_neg else first
        negative_side = first if first_neg else second
        negated_term = _negation_scope_overlap(negative_side, affirmative_side, negation, ctx.language)
        if not negated_term:
            continue
        overlap = sorted(set(contents[a]) & set(contents[b]))[:4]
        out.append(_finding(
            ctx, "contradiction",
            f"Two statements about {', '.join(overlap)} point opposite ways",
            "Both sentences speak about the same terms quoted here, and the word the negation acts on "
            f"({negated_term}) appears in both. One states something and the other denies it, so they cannot "
            "both be true as written. If both are meant to hold, one of them needs a condition, a date, or a "
            "different subject; if the later sentence corrects the earlier one, the correction has to be visible.",
            [_evidence(ctx, negative_side, note="The statement that denies."),
             _evidence(ctx, affirmative_side, note="The statement that affirms.")],
            suggestion="Keep the sentence the document supports and change the other into the qualified version "
                       "it really describes (which season, which site, which year).",
            severity="major",
            confidence=0.6,
            extra={"shared_terms": overlap, "negated_term": negated_term, "sentence_gap": abs(b - a)},
        ))
    return out


def _ambiguous_statements(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    pronoun = _pattern(PRONOUN_START, ctx.language)
    vague = _pattern(VAGUE, ctx.language)
    modal = _pattern(AFFIRMATION, ctx.language)
    sentences = ctx.sentences
    for position, sentence in enumerate(sentences):
        if len(out) >= 8:
            break
        passage = ctx.passage(sentence.passage_id)
        if passage is None or passage.is_heading:
            continue
        previous = sentences[position - 1] if position else None

        if pronoun.match(sentence.text.strip()):
            candidates = [t for t in _content(previous.text, ctx.language)
                          if not VERBISH.match(t) and t not in PRONOUNS] if previous else []
            leading = " ".join(sentence.text.split()[0:1])
            if previous is None or not candidates:
                out.append(_finding(
                    ctx, "ambiguous_statement",
                    f"\"{leading}\" at the start has nothing in the previous sentence to point at",
                    f"The sentence opens with \"{leading}\", and the sentence before it (quoted) contains no "
                    "content noun the word could refer to. The reader has to guess which of the document's "
                    "topics is meant.",
                    [_evidence(ctx, sentence),
                     _evidence(ctx, previous) if previous is not None else None],
                    suggestion=f"Replace \"{leading}\" with the name of the thing you mean.",
                    severity="minor",
                    confidence=0.6,
                    extra={"reference": leading, "candidates": 0},
                ))
            elif len(candidates) > 2:
                out.append(_finding(
                    ctx, "ambiguous_statement",
                    f"\"{leading}\" could refer to {len(candidates)} different things",
                    f"The sentence opens with \"{leading}\". The sentence before it offers {len(candidates)} "
                    f"content nouns ({', '.join(candidates[:5])}), so the reference is not fixed by the wording.",
                    [_evidence(ctx, sentence), _evidence(ctx, previous)],
                    suggestion=f"Name the intended referent instead of \"{leading}\".",
                    severity="minor",
                    confidence=0.5,
                    extra={"reference": leading, "candidates": len(candidates),
                           "candidate_terms": candidates[:6]},
                ))
            continue

        match = vague.search(sentence.text)
        if match and (modal.search(sentence.text) or len(_content(sentence.text, ctx.language)) >= 5):
            out.append(_finding(
                ctx, "ambiguous_statement",
                f"Unmeasured quantity: \"{_clamp(match.group(0), 30)}\"",
                f"This sentence makes a statement whose size is left open by \"{_clamp(match.group(0), 30)}\". "
                "Because the sentence carries the claim rather than illustrating it, the reader cannot tell how "
                "wide the statement is, and neither can a check.",
                [_evidence(ctx, sentence, match.group(0))],
                suggestion="Put the number, the share, or the list of cases in place of the vague word.",
                severity="minor",
                confidence=0.6,
                extra={"quantifier": match.group(0)},
            ))
            continue

    acronyms: dict[str, int] = {}
    where: dict[str, Sentence] = {}
    for sentence in sentences:
        for raw in tokenize(sentence.text):
            if re.fullmatch(r"[A-Z]{2,6}", raw):
                acronyms[raw] = acronyms.get(raw, 0) + 1
                where.setdefault(raw, sentence)
    for acronym, hits in sorted(acronyms.items(), key=lambda item: -item[1])[:3]:
        if len(_acronym_expansions(ctx, acronym)) > 0:
            continue
        sentence = where[acronym]
        out.append(_finding(
            ctx, "ambiguous_statement",
            f"Abbreviation \"{acronym}\" is never spelled out",
            f"\"{acronym}\" is used {hits} time(s). Nowhere in the document does a phrase appear whose words "
            "start with those letters, so its meaning has to be assumed by the reader.",
            [_evidence(ctx, sentence, acronym)],
            suggestion="Write the full term the first time it appears and put the abbreviation after it in brackets.",
            severity="minor",
            confidence=0.7,
            extra={"acronym": acronym, "occurrences": hits},
        ))
    return out


def _acronym_expansions(ctx: AnalysisContext, acronym: str) -> list[str]:
    letters = [ch.lower() for ch in acronym]
    found: list[str] = []
    for passage in ctx.passages:
        words = tokenize(passage.text)
        for start in range(len(words)):
            if not normalize_word(words[start]).lower().startswith(letters[0]):
                continue
            cursor = start
            picked: list[str] = []
            for needed in letters:
                while cursor < len(words) and normalize_word(words[cursor]).casefold() in STOP_CONNECTORS and picked:
                    cursor += 1
                if cursor >= len(words):
                    break
                candidate = normalize_word(words[cursor]).lower()
                if not candidate.startswith(needed):
                    break
                picked.append(words[cursor])
                cursor += 1
            if len(picked) == len(letters) and " ".join(picked).casefold() != acronym.casefold():
                found.append(" ".join(picked))
    return found


def _logic_gaps(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    consequence = _pattern(CONSEQUENCE, ctx.language)
    for sentence in ctx.sentences:
        if len(out) >= 6:
            break
        passage = ctx.passage(sentence.passage_id)
        if passage is None or passage.is_heading:
            continue
        match = consequence.search(sentence.text)
        if not match:
            continue
        conclusion_terms = set(_content(sentence.text, ctx.language))
        premises = [
            other for other in _sentences_of_passage(ctx, passage.id)
            if other.index != sentence.index
            and len(set(_content(other.text, ctx.language)) & conclusion_terms) >= 2
        ]
        if premises:
            continue
        neighbouring = [
            other for other in ctx.sentences
            if other.passage_id != passage.id and abs(other.index - sentence.index) <= 3
            and len(set(_content(other.text, ctx.language)) & conclusion_terms) >= 2
        ]
        if neighbouring:
            continue
        out.append(_finding(
            ctx, "logic_gap",
            f"Conclusion word \"{_clamp(match.group(0), 25)}\" with no premise sharing its terms",
            f"The sentence draws a consequence (\"{_clamp(match.group(0), 25)}\"), but no sentence in the same "
            "passage - and none in the three sentences around it - talks about the same things as the "
            "conclusion. The step that should justify it is missing from where the reader is looking.",
            [_evidence(ctx, sentence)],
            suggestion="Add the sentence that states what leads to this, in the same paragraph and using the same "
                       "terms, or move the conclusion under the section that contains its premise.",
            severity="minor",
            confidence=0.6,
            extra={"connective": match.group(0), "conclusion_terms": sorted(conclusion_terms)[:6]},
        ))
    return out


def _overreaching(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    absolute = _pattern(ASSERTION, ctx.language)
    hedge = _pattern(HEDGES, ctx.language)
    body = _body_sentences(ctx)
    hedged = [s for s in body if hedge.search(s.text)]
    if len(hedged) < 2:
        return out

    conclusion_passages: list[DocPassage] = []
    heading = _pattern(CONCLUSION_HEAD, ctx.language, re.MULTILINE)
    collecting = False
    for passage in ctx.passages:
        if passage.is_heading:
            collecting = bool(heading.search(passage.text))
            continue
        if collecting:
            conclusion_passages.append(passage)
    if not conclusion_passages:
        tail = body[-2:] if len(body) >= 2 else body
        conclusion_passages = [ctx.passage(s.passage_id) for s in tail if ctx.passage(s.passage_id)]
    ids = {p.id for p in conclusion_passages if p}
    for sentence in body:
        if len(out) >= 3:
            break
        if sentence.passage_id not in ids:
            continue
        match = absolute.search(sentence.text)
        if not match:
            continue
        out.append(_finding(
            ctx, "overreaching_conclusion",
            f"Conclusion states more than the body supports: {_clamp(sentence.text, 50)}",
            f"The closing part of the document uses unqualified wording (\"{_clamp(match.group(0), 25)}\") while "
            f"the body hedged in {len(hedged)} sentence(s) (\"{ _clamp(hedged[0].text, 40)}\" is one of them). "
            "The conclusion therefore carries a certainty the argument above it never claims.",
            [_evidence(ctx, sentence, note="The conclusion as written."),
             _evidence(ctx, hedged[0], note="A hedged statement from the body.")],
            suggestion="Bring the conclusion down to what the body actually showed, or add the evidence that "
                       "would justify the stronger wording.",
            severity="major",
            confidence=0.6,
            extra={"absolute_marker": match.group(0), "hedged_sentences": len(hedged)},
        ))
    return out


# --------------------------------------------------------------------------- questions
def _clarifying_questions(ctx: AnalysisContext, findings: list[FindingDraft]) -> list[FindingDraft]:
    """Questions worth asking about the document, each derived from one observation made above."""
    out: list[FindingDraft] = []
    wanted = ("unsupported_claim", "contradiction", "overreaching_conclusion", "ambiguous_statement", "logic_gap")
    for kind in wanted:
        picked = [f for f in findings if f.kind == kind]
        for finding in picked[:2]:
            if len(out) >= 8:
                break
            quote = finding.evidence[0].quote if finding.evidence else ""
            if finding.kind == "unsupported_claim":
                question = ("What would you point to if a reader asked you to support this sentence using only "
                            f"what is written in the document? It reads: \"{_clamp(quote, 70)}\"")
            elif finding.kind == "contradiction":
                question = ("Two sentences here describe the same terms in opposite ways. Which one is true for "
                            "which case, and what would you add to the other so the two no longer clash?")
            elif finding.kind == "overreaching_conclusion":
                question = (f"The closing sentence says \"{_clamp(quote, 70)}\". Which of the body's findings "
                            "lets you say that, and what would you say instead if the body only suggests it?")
            elif finding.kind == "logic_gap":
                question = ("You wrote this as a consequence. What is the step before it, and where in the "
                            "document should the reader find that step?")
            else:
                question = (f"In \"{_clamp(quote, 70)}\" what exactly do you mean - which thing, and how many? "
                            "Answer in one sentence you could put in the text.")
            finding_draft = _finding(
                ctx, "clarifying_question",
                f"Question for the author ({kind})",
                question,
                list(finding.evidence),
                severity="info",
                confidence=0.6,
                extra={"derived_from": kind, "source_title": finding.title},
            )
            if finding_draft is not None:
                out.append(finding_draft)
    return out


def investigate_logic(ctx: AnalysisContext) -> list[FindingDraft]:
    """Claims without support, contradictions, ambiguity, gaps, overreach, and derived questions."""
    findings: list[FindingDraft] = []
    findings += _unsupported_claims(ctx)
    findings += _contradictions(ctx)
    findings += _ambiguous_statements(ctx)
    findings += _logic_gaps(ctx)
    findings += _overreaching(ctx)
    findings += _clarifying_questions(ctx, findings)
    return [f for f in findings if f and f.evidence]
