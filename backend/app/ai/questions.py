"""Document-grounded questions.

Answers are built from the document's own sentences, with citations that were sliced
verbatim out of the passage text (never rewritten). If nothing in the document answers
the question, the answer says so plainly instead of guessing.
"""
from __future__ import annotations

import math
import re
from typing import Any

from app.ai import provider
from app.analysis.segmentation import normalize_tokens, split_sentences
from app.analysis.types import AnalysisContext
from app.core.config import settings

STOP = {"what", "which", "who", "when", "where", "why", "how", "does", "did", "is", "are", "was", "were", "the",
        "a", "an", "of", "to", "in", "for", "on", "and", "or", "about", "with", "please", "tell", "me", "can",
        "you", "list", "mentioned", "mention", "document", "that", "this", "it", "be", "have", "has", "had",
        "its", "their", "there", "here", "them", "they", "than", "then", "very", "much", "many", "some", "any",
        "no", "not", "do", "being", "been", "all", "both", "each", "few", "more", "most", "other", "over",
        "under", "again", "once", "into", "during", "before", "after", "above", "below", "between", "out", "off",
        "up", "down", "our", "your", "my", "he", "she", "we", "am", "will", "would", "shall", "should", "could",
        "might", "must", "need", "dare", "ought", "said", "say", "says", "included", "including", "given",
        "long", "short", "biggest", "best", "way", "ways", "thing", "things", "kind", "kinds", "part", "parts",
        "point", "question", "questions", "answer", "answers", "mean", "means", "explain", "describe"}


def _query_tokens(question: str) -> list[str]:
    return [t for t in normalize_tokens(question) if t not in STOP and len(t) > 2]



class _Retriever:
    """Small BM25-ish scorer over the document's own passages."""

    def __init__(self, ctx: AnalysisContext) -> None:
        self.ctx = ctx
        self.docs = [normalize_tokens(p.text) for p in ctx.passages]
        self.lengths = [max(1, len(d)) for d in self.docs]
        self.avg = sum(self.lengths) / max(1, len(self.lengths))
        self.df: dict[str, int] = {}
        for doc in self.docs:
            for term in set(doc):
                self.df[term] = self.df.get(term, 0) + 1
        self.n = max(1, len(self.docs))

    def score(self, query: list[str]) -> list[float]:
        scores = [0.0] * self.n
        k1, b = 1.5, 0.75
        for term in query:
            df = self.df.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
            for index, doc in enumerate(self.docs):
                tf = doc.count(term)
                if not tf:
                    continue
                norm = tf * (k1 + 1) / (tf + k1 * (1 - b + b * self.lengths[index] / self.avg))
                scores[index] += idf * norm
        return scores

    def top_passages(self, question: str, limit: int = 6) -> tuple[list[str], list[float], list[str]]:
        query = _query_tokens(question)
        if not query:
            return [], [], query
        scores = self.score(query)
        ranked = sorted(range(self.n), key=lambda i: -scores[i])
        chosen = [i for i in ranked if scores[i] > 0.0][:limit]
        return ([self.ctx.passages[i].id for i in chosen], [scores[i] for i in chosen], query)


def _verbatim_sentence_hits(text: str, query: list[str]) -> list[tuple[int, int, str, float]]:
    hits: list[tuple[int, int, str, float]] = []
    tokens = normalize_tokens(text)
    for start, end, sentence in split_sentences(text):
        norm = set(normalize_tokens(sentence))
        overlap = len([t for t in query if t in norm])
        if overlap == 0:
            continue
        coverage = overlap / max(1, len(query))
        positional = 1.0 if re.search(r"\b(is|are|was|were|means?|defined|waa|yahay|عبارة)\b", sentence, re.I) else 0.85
        hits.append((start, end, sentence, coverage * positional))
    hits.sort(key=lambda h: -h[3])
    return hits


def answer(ctx: AnalysisContext, question: str) -> dict[str, Any]:
    retriever = _Retriever(ctx)
    passage_ids, scores, query = retriever.top_passages(question)
    matched_terms = [term for term in query if term in retriever.df]
    if len(matched_terms) < 2:
        return {
            "answer": "This document does not contain the terms your question asks about, so it cannot answer it. "
                      "Try a question using wording that appears in the document, or investigate a different document.",
            "grounded": False,
            "limitation": (
                "Only " + str(len(matched_terms)) + " content word(s) of your question appear anywhere in this "
                "document, so any answer would have to come from outside it."
            ),
            "citations": [],
            "citations_detail": [],
            "engine": "local",
        }
    if not passage_ids:
        return {
            "answer": "This document does not contain the terms your question asks about, so it cannot answer it. "
                      "Try a question using wording that appears in the document, or investigate a different document.",
            "grounded": False,
            "limitation": "No passage of this document shares any content term with the question.",
            "citations": [],
            "citations_detail": [],
            "engine": "local",
        }

    citations: list[dict[str, Any]] = []
    sentences: list[str] = []
    for pid, score in list(zip(passage_ids, scores))[:5]:
        passage = ctx.passage(pid)
        if passage is None:
            continue
        for start, end, sentence, weight in _verbatim_sentence_hits(passage.text, query)[:3]:
            if weight < 0.12:
                continue
            citations.append(
                {"passage_id": pid, "quote": sentence, "start": start, "end": end,
                 "page_number": passage.page_number, "relevance": round(min(1.0, score / max(1e-6, scores[0])), 3)}
            )
            sentences.append(sentence)
            if len(citations) >= 6:
                break
        if len(citations) >= 6:
            break

    if not citations:
        return {
            "answer": "The question matches this document's vocabulary, but no sentence in it states what you asked. "
                      "Here is the closest context so you can judge for yourself.",
            "grounded": False,
            "limitation": "Topical overlap found, but no sentence answers the question directly.",
            "citations": [],
            "citations_detail": [
                {
                    "passage_id": pid,
                    "quote": (ctx.text_of(pid) or "")[:280],
                    "page_number": ctx.passage(pid).page_number if ctx.passage(pid) else None,
                }
                for pid in passage_ids[:3]
            ],
            "engine": "local",
        }

    answer_text = " ".join(_dedupe(sentences)[:4])
    result = {
        "answer": f"From the document: {answer_text}"[:4000],
        "grounded": True,
        "limitation": None,
        "citations": [c["passage_id"] for c in citations],
        "citations_detail": citations,
        "engine": "local",
    }

    if settings.ai_enabled:
        excerpt = provider.excerpt_for_passages(ctx, passage_ids)
        reply = provider.answer_question(question, excerpt, passage_ids)
        if reply.ok and isinstance(reply.data, dict):
            verified = []
            for item in reply.data.get("citations", []) or []:
                pid = str(item.get("passage_id", ""))
                quote = str(item.get("quote", ""))
                passage = ctx.passage(pid)
                if passage is None or not quote or quote not in passage.text:
                    continue  # fabricated quotation - dropped, never shown
                offset = passage.text.find(quote)
                verified.append(
                    {"passage_id": pid, "quote": quote, "start": offset, "end": offset + len(quote),
                     "page_number": passage.page_number, "relevance": 1.0}
                )
            text = str(reply.data.get("answer", "")).strip()
            if text and verified:
                result.update(
                    {"answer": text[:4000], "citations_detail": verified[:6],
                     "citations": [v["passage_id"] for v in verified[:6]],
                     "engine": f"ai:{reply.model}", "grounded": bool(reply.data.get("grounded", True))}
                )
    return result


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().casefold()
        if key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out
