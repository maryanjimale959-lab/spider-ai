"""Keyword extraction without a dictionary or a network.

Scoring is real: term frequency with a word-length normalisation, plus a TextRank-style
co-occurrence pass over the content tokens of each sentence. Multiword terms come from
adjacent co-occurrence counts, acronyms are matched against expansions that actually occur
in the document, and every explanation states only what the document shows (where the term
appears, which terms it appears next to, whether a definition-style sentence exists).

Only terms that literally occur in the text are emitted, so ``in_document`` is always True.
Suggested *related* concepts are left to the AI layer.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from app.analysis.evidence import locate
from app.analysis.language import ALL
from app.analysis.segmentation import is_arabic_char, normalize_tokens, normalize_word, tokenize
from app.analysis.types import AnalysisContext, DocPassage, EvidenceDraft, FindingDraft, KeywordDraft, Sentence

GRAPH_VOCAB = 220
WINDOW = 5
RANK_ITERATIONS = 20
RANK_DAMPING = 0.85
RANK_FLOOR = 0.15
MAX_PASSAGE_IDS = 10

DEFINITION_HINT = re.compile(
    r"\b(?:is\s+defined\s+as|are\s+defined\s+as|defined\s+as|means|refers\s+to|is\s+known\s+as|"
    r"is\s+called|waa\s+[\w'’\-]+\s+oo|عبارة\s+عن|يقصد|هو\s+[\u0600-\u06FF]+\s+الذي)\b",
    re.IGNORECASE,
)
STOP_CONNECTORS = {
    "the", "of", "and", "to", "in", "a", "an", "for", "on", "with", "at", "by", "from", "as", "that", "which",
}


# --------------------------------------------------------------------------- vocabulary
def _stopwords(language: str) -> set[str]:
    if language in ALL:
        return ALL[language]
    union: set[str] = set()
    for stop in ALL.values():
        union |= stop
    return union


def _is_content(token: str, stop: set[str], language: str) -> bool:
    if not token or token in stop:
        return False
    if token.isdigit():
        return False
    minimum = 2 if language == "ar" else 3
    if len(token) < minimum and not any(is_arabic_char(ch) for ch in token):
        return False
    if language != "ar" and not any(ch.isalpha() for ch in token):
        return False
    return True


def _passage_tokens(ctx: AnalysisContext) -> dict[str, list[str]]:
    """Normalised raw tokens per passage (order preserved) - the base for every count."""
    return {p.id: normalize_tokens(p.text) for p in ctx.passages}


def _surface_forms(ctx: AnalysisContext) -> dict[str, Counter]:
    forms: dict[str, Counter] = defaultdict(Counter)
    for passage in ctx.passages:
        for raw in tokenize(passage.text):
            forms[normalize_word(raw)][raw] += 1
    return forms


def _best_surface(forms: dict[str, Counter], normalized: str, fallback: str) -> str:
    counter = forms.get(normalized)
    if not counter:
        return fallback
    top = counter.most_common(1)[0][0]
    return top if len(top) >= len(normalized) else fallback


# --------------------------------------------------------------------------- scoring
def _cooccurrence(sentences: list[Sentence], stop: set[str], language: str) -> tuple[Counter, dict[str, Counter]]:
    """Weight of adjacent-window co-occurrences, and neighbour weights per term."""
    weight: Counter = Counter()
    neighbours: dict[str, Counter] = defaultdict(Counter)
    for sentence in sentences:
        window_source = [t for t in normalize_tokens(sentence.text) if _is_content(t, stop, language)]
        if len(window_source) < 2:
            continue
        for i, token in enumerate(window_source):
            for other in window_source[i + 1: i + 1 + WINDOW]:
                if other == token:
                    continue
                weight[(token, other)] += 1
                neighbours[token][other] += 1
                neighbours[other][token] += 1
    return weight, neighbours


def _textrank(vocab: list[str], neighbours: dict[str, Counter]) -> dict[str, float]:
    allowed = set(vocab)
    adjacency = {t: {n: w for n, w in neighbours.get(t, {}).items() if n in allowed} for t in vocab}
    out_strength = {t: sum(adjacency[t].values()) or 1.0 for t in vocab}
    ranks = {t: 1.0 for t in vocab}
    for _ in range(RANK_ITERATIONS):
        updated: dict[str, float] = {}
        for term in vocab:
            total = 0.0
            for neighbour, w in adjacency[term].items():
                total += (w / out_strength[neighbour]) * ranks[neighbour]
            updated[term] = RANK_FLOOR + RANK_DAMPING * total
        ranks = updated
    if not ranks:
        return {}
    peak = max(ranks.values()) or 1.0
    return {t: v / peak for t, v in ranks.items()}


def _title_terms(ctx: AnalysisContext, stop: set[str], language: str) -> set[str]:
    terms: set[str] = set()
    for passage in ctx.passages:
        if passage.is_heading:
            terms.update(t for t in normalize_tokens(passage.text) if _is_content(t, stop, language))
    return terms


def _phrase_candidates(sentences: list[Sentence], stop: set[str], language: str,
                      counts: Counter) -> Counter:
    """Adjacent content tokens that repeatedly appear next to each other in the same order."""
    phrase_counts: Counter = Counter()
    for sentence in sentences:
        raw = tokenize(sentence.text)
        norm = [normalize_word(t) for t in raw]
        if not raw:
            continue
        # Keep runs of consecutive content tokens, then take 2- and 3-grams inside each run.
        run: list[str] = []
        runs: list[list[str]] = []
        for index, token in enumerate(norm):
            if _is_content(token, stop, language):
                run.append(token)
            else:
                if run:
                    runs.append(run)
                run = []
        if run:
            runs.append(run)
        for tokens in runs:
            for size in (2, 3):
                for start in range(0, len(tokens) - size + 1):
                    gram = tokens[start: start + size]
                    if all(counts.get(g, 0) >= 2 for g in gram):
                        phrase_counts[" ".join(gram)] += 1
    return phrase_counts


def _expansion(ctx: AnalysisContext, acronym: str) -> str | None:
    """Return the expansion if a matching word-initial sequence really occurs in the document."""
    letters = [ch.lower() for ch in acronym]
    for passage in ctx.passages:
        words = tokenize(passage.text)
        for start in range(len(words)):
            if not normalize_word(words[start]).lower().startswith(letters[0]):
                continue
            cursor = start
            picked: list[str] = []
            for needed in letters:
                while cursor < len(words) and normalize_word(words[cursor]).lower() in STOP_CONNECTORS and picked:
                    cursor += 1
                if cursor >= len(words):
                    break
                candidate = normalize_word(words[cursor]).lower()
                if not candidate.startswith(needed):
                    picked = []
                    break
                picked.append(words[cursor])
                cursor += 1
            if len(picked) == len(letters):
                text = " ".join(picked)
                if text.casefold() == acronym.casefold():
                    continue
                return text
    return None


# --------------------------------------------------------------------------- explanations
def _location_label(ctx: AnalysisContext, passage: DocPassage) -> str:
    if passage.section_title:
        return _truncate(passage.section_title, 40)
    if passage.is_heading:
        return _truncate(passage.text, 40)
    heading = None
    for candidate in ctx.passages:
        if candidate.id == passage.id:
            break
        if candidate.is_heading:
            heading = candidate
    return _truncate(heading.text, 40) if heading else "the opening section"


def _definition_fragment(ctx: AnalysisContext, term: str) -> str | None:
    for sentence in ctx.sentences:
        if term.casefold() not in normalize_word(sentence.text):
            continue
        if DEFINITION_HINT.search(sentence.text):
            return " ".join(sentence.text.split())[:120]
    return None


def _explain(ctx: AnalysisContext, term: str, normalized: str, occurrences: int,
             passage_ids: list[str], neighbours: dict[str, Counter], first: DocPassage | None,
             category: str, expansion: str | None, language: str) -> str:
    parts: list[str] = []
    where = f"occurs {occurrences} time(s) in {len(passage_ids)} passage(s)"
    if first is not None:
        where += f", first in {_location_label(ctx, first)}"
    parts.append(where)
    top = [n for n, _w in neighbours.get(normalized, Counter()).most_common(3) if n != normalized]
    if top:
        parts.append("appears next to " + ", ".join(top))
    definition = _definition_fragment(ctx, normalized)
    if definition:
        parts.append("a definition-style sentence mentions it")
    if category == "acronym":
        parts.append(
            f"its expansion \"{expansion}\" appears in the document"
            if expansion else
            "no expansion of this letter sequence appears anywhere in the document"
        )
    if category == "primary" and first is not None and first.is_heading:
        parts.append("it is used in a title or heading")
    if len(normalized.split()) > 1:
        parts.append("it appears as the same multiword sequence, not as isolated words")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:]


# --------------------------------------------------------------------------- public API
def extract_keywords(ctx: AnalysisContext, limit: int = 24) -> list[KeywordDraft]:
    stop = _stopwords(ctx.language)
    language = ctx.language
    token_lists = _passage_tokens(ctx)
    forms = _surface_forms(ctx)

    counts: Counter = Counter()
    where: dict[str, list[str]] = defaultdict(list)
    per_passage_content: dict[str, set[str]] = {}
    for passage in ctx.passages:
        toks = [t for t in token_lists.get(passage.id, []) if _is_content(t, stop, language)]
        per_passage_content[passage.id] = set(toks)
        for token in set(toks):
            counts[token] += toks.count(token)
            where[token].append(passage.id)
    for term, ids in where.items():
        where[term] = list(dict.fromkeys(ids))

    _pair_weights, neighbours = _cooccurrence(ctx.sentences, stop, language)
    ranked = sorted(counts, key=lambda t: (-counts[t], t))[:GRAPH_VOCAB]
    ranks = _textrank(ranked, neighbours)
    title_terms = _title_terms(ctx, stop, language)

    tf_scores = {t: counts[t] / (1.0 + math.log(max(len(t), 2))) for t in counts}
    tf_peak = max(tf_scores.values()) if tf_scores else 1.0
    rank_peak = max(ranks.values()) if ranks else 1.0

    candidates: list[tuple[str, str, int, list[str], float, str]] = []
    for term in counts:
        score = 0.0
        if tf_peak:
            score += 0.55 * (tf_scores[term] / tf_peak)
        score += 0.35 * (ranks.get(term, 0.0) / (rank_peak or 1.0))
        dispersion = len(where[term])
        score += 0.1 * min(dispersion / max(len(ctx.passages), 1), 1.0)
        if term in title_terms:
            score += 0.18
        candidates.append((term, term, counts[term], where[term], score, "single"))

    phrase_counts = _phrase_candidates(ctx.sentences, stop, language, counts)
    for phrase, hits in phrase_counts.items():
        if hits < 2:
            continue
        parts = phrase.split()
        phrase_where = [p.id for p in ctx.passages if phrase in " ".join(token_lists.get(p.id, []))]
        occurrences = sum(
            1 for p in ctx.passages
            for i in range(len(token_lists.get(p.id, [])) - len(parts) + 1)
            if token_lists[p.id][i: i + len(parts)] == parts
        )
        score = 0.55 * (max(tf_scores.get(t, 0.0) for t in parts) / tf_peak) * min(hits, 4) / 4
        score += 0.3 * (sum(ranks.get(t, 0.0) for t in parts) / (len(parts) * (rank_peak or 1.0)))
        if any(t in title_terms for t in parts):
            score += 0.15
        display = " ".join(_best_surface(forms, t, t) for t in parts)
        candidates.append((phrase, display, occurrences, phrase_where, score, "phrase"))

    acronyms: dict[str, int] = {}
    acronym_where: dict[str, list[str]] = defaultdict(list)
    for passage in ctx.passages:
        for raw in tokenize(passage.text):
            if re.fullmatch(r"[A-Z]{2,6}", raw) and raw.lower() not in stop:
                acronyms[raw] = acronyms.get(raw, 0) + 1
                acronym_where[raw].append(passage.id)
    for letters, hits in acronyms.items():
        where_ids = list(dict.fromkeys(acronym_where[letters]))
        candidates.append((letters.lower(), letters, hits, where_ids, 0.62 if hits >= 2 else 0.5, "acronym"))

    candidates.sort(key=lambda item: (-item[4], item[0]))

    drafts: list[KeywordDraft] = []
    used: set[str] = set()
    max_score = candidates[0][4] if candidates else 1.0
    passage_by_id = {p.id: p for p in ctx.passages}
    for normalized, display, occurrences, passage_ids, score, kind in candidates:
        if len(drafts) >= limit:
            break
        key = normalized
        if key in used or occurrences <= 0:
            continue
        used.add(key)

        category = _categorise(ctx, key, normalized, occurrences, passage_ids, score, max_score,
                              title_terms, kind, forms, stop, language)
        expansion = _expansion(ctx, display.upper()) if category == "acronym" else None
        first = passage_by_id.get(passage_ids[0]) if passage_ids else None
        related = [n for n, _w in neighbours.get(normalized, Counter()).most_common(3)
                   if n != normalized and n not in used][:3]
        drafts.append(KeywordDraft(
            term=_best_surface(forms, normalized, display) if kind == "single" else display,
            normalized=normalized if kind != "acronym" else display.lower(),
            category=category,
            explanation=_explain(ctx, key, normalized, occurrences, passage_ids, neighbours, first,
                                category, expansion, language),
            occurrences=occurrences,
            in_document=True,
            related_terms=related,
            passage_ids=passage_ids[:MAX_PASSAGE_IDS],
            score=round(min(score, 1.0), 3),
        ))
    return drafts


def _categorise(ctx: AnalysisContext, key: str, normalized: str, occurrences: int,
                passage_ids: list[str], score: float, max_score: float, title_terms: set[str],
                kind: str, forms: dict[str, Counter], stop: set[str], language: str) -> str:
    if kind == "acronym":
        return "acronym"
    surfaces = forms.get(normalized) or Counter()
    capitalised = bool(surfaces) and all(word[0].isupper() for word in surfaces if word)
    rare = occurrences <= 2
    if normalized in title_terms and not rare:
        return "primary"
    if score >= 0.55 * max_score:
        return "primary"
    if rare and (capitalised or len(normalized.split()) > 1):
        return "technical"
    if _definition_fragment(ctx, normalized):
        return "concept"
    if kind == "phrase":
        return "supporting" if occurrences >= 3 else "concept"
    if score >= 0.3 * max_score:
        return "supporting"
    return "concept" if occurrences >= 2 else "technical"


def key_concept_findings(ctx: AnalysisContext, keywords: list[KeywordDraft]) -> list[FindingDraft]:
    """Link the leading keywords to the passage where they are used most substantively."""
    stop = _stopwords(ctx.language)
    findings: list[FindingDraft] = []
    sentence_index: dict[str, list[Sentence]] = defaultdict(list)
    for sentence in ctx.sentences:
        sentence_index[sentence.passage_id].append(sentence)

    ordered = [k for k in keywords if k.in_document and k.category in ("primary", "concept", "acronym")]
    for keyword in ordered[:3]:
        needle = keyword.normalized or keyword.term.casefold()
        best: tuple[int, Sentence] | None = None
        for sentence in ctx.sentences:
            tokens = normalize_tokens(sentence.text)
            joined = " ".join(tokens)
            if needle not in tokens and needle not in joined:
                continue
            passage = ctx.passage(sentence.passage_id)
            if passage is None or passage.is_heading:
                continue
            substance = len([t for t in tokens if _is_content(t, stop, ctx.language)])
            if best is None or substance > best[0]:
                best = (substance, sentence)
        if best is None:
            continue
        sentence = best[1]
        passage = ctx.passage(sentence.passage_id)
        if passage is None:
            continue
        collapsed = " ".join(sentence.text.split())
        if locate(collapsed, passage) is None:
            continue
        findings.append(FindingDraft(
            kind="keyword_concept",
            title=f"Key concept: {_truncate(keyword.term, 60)}",
            body=(
                f"\"{_truncate(keyword.term, 60)}\" occurs {keyword.occurrences} time(s) across "
                f"{len(keyword.passage_ids)} passage(s). The sentence quoted here is its most developed use in "
                f"the document ({best[0]} content word(s)), so it is where the concept is actually explained "
                "rather than only named."
            ),
            evidence=[EvidenceDraft(passage_id=passage.id, quote=collapsed)],
            primary_passage_id=passage.id,
            severity="info",
            confidence=0.75,
            extra={"term": keyword.term, "occurrences": keyword.occurrences, "category": keyword.category},
        ))
    return findings


def _truncate(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[:limit].rstrip(" ,;:") + "..."
