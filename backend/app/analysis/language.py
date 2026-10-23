"""Language identification for English, Arabic, and Somali documents.

Detection is script-first (Arabic letters), then stopword-rate comparison between the
Latin-script candidates. The detected language selects which writing rules run.
"""
from __future__ import annotations

from collections import Counter

from app.analysis.segmentation import is_arabic_char, normalize_tokens

EN_STOPWORDS = {
    "the", "of", "and", "to", "in", "a", "is", "that", "for", "it", "with", "as", "was", "on", "be", "by",
    "this", "or", "from", "are", "at", "an", "which", "have", "has", "had", "were", "but", "not", "they",
    "their", "we", "you", "he", "she", "his", "her", "its", "our", "can", "will", "would", "should", "could",
    "there", "than", "then", "who", "all", "any", "most", "more", "also", "such", "into", "about", "after",
    "before", "because", "however", "therefore", "these", "those", "each", "other", "some", "may", "must",
}

AR_STOPWORDS = {
    "في", "من", "على", "أن", "ان", "هذا", "هذه", "التي", "الذي", "مع", "عن", "الى", "إلى", "قال", "كما",
    "بين", "كل", "بعض", "عند", "لكن", "قد", "هل", "ما", "هو", "هي", "نحن", "هم", "انت", "أنت", "كان",
    "غير", "حتى", "لو", "او", "أو", "و", "لا", "اذا", "إذا", "انها", "إنها", "بما", "لذلك", "حيث",
    "خلال", "بعد", "قبل", "اي", "أي", "هناك", "نحو", "ضد", "عبر", "ذلك", "ذَلِكَ", "بل", "أما", "اما",
}

SO_STOPWORDS = {
    "waxaa", "baa", "oo", "ku", "ayaa", "iyo", "ee", "in", "inuu", "inay", "sida", "la", "ah", "yahay",
    "tahay", "karo", "karta", "waa", "kale", "lahayn", "lagu", "waxay", "waxan", "aniga", "iyaga", "aad",
    "loo", "ka", "sidoo", "kale", "ay", "isku", "wadahadalka", "haddii", "hase", "yeeshee", "waayo",
    "sow", "ma", "maya", "markii", "meel", "la'aanta", "inta", "hela", "sameyn", "qaadan", "ahaa",
    "jira", "jiro", "wax", "qof", "wadan", "dadka", "ayaa", "waxaa",
}

ALL = {"en": EN_STOPWORDS, "ar": AR_STOPWORDS, "so": SO_STOPWORDS}


def detect_language(text: str, min_words: int = 12) -> tuple[str, float]:
    """Return (language_code, confidence 0..1). 'unknown' when too little text to judge."""
    if not text or not text.strip():
        return "unknown", 0.0
    tokens = normalize_tokens(text)
    letters = [t for t in tokens if t]
    if not letters:
        return "unknown", 0.0

    arabic_hits = sum(1 for t in letters for ch in t if is_arabic_char(ch))
    total_chars = sum(len(t) for t in letters) or 1
    arabic_ratio = arabic_hits / total_chars
    counter = Counter(letters)
    total_tokens = sum(counter.values())

    if arabic_ratio > 0.25:
        hits = {lang: sum(c for w, c in counter.items() if w in stop) for lang, stop in ALL.items()}
        score = max(hits, key=hits.get) if max(hits.values()) else "ar"
        language = "ar" if score == "ar" else score
        conf = min(0.99, 0.6 + 0.39 * arabic_ratio)
        return language, round(conf, 3)

    if total_tokens < min_words:
        return "unknown", round(0.3 + 0.4 * (total_tokens / min_words), 3)

    rates = {lang: sum(c for w, c in counter.items() if w in stop) / total_tokens for lang, stop in ALL.items()}
    best = max(rates, key=rates.get)
    ordered = sorted(rates.values(), reverse=True)
    margin = ordered[0] - ordered[1]
    confidence = min(0.98, 0.55 + ordered[0] * 2.2 + margin * 1.5)
    if ordered[0] < 0.04:
        return "unknown", round(0.4, 3)
    return best, round(confidence, 3)


def language_label(code: str) -> str:
    return {"en": "English", "ar": "Arabic", "so": "Somali", "unknown": "unidentified"}.get(code, code)


def supported(code: str) -> bool:
    return code in ALL
