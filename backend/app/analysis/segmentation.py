"""Sentence and word segmentation that works for Latin (English/Somali) and Arabic script."""
from __future__ import annotations

import re
import unicodedata

ARABIC_RE = re.compile(r"[^\W\d_]{0,}", re.UNICODE)
LATIN_TOKEN = re.compile(r"[A-Za-zÀ-ÿāēīōūşïöüàáâãèéêëìíîòóôõùúûçñ]+(?:[-'’][A-Za-zÀ-ÿāēīōūşïöüàáâèéêìíòóùúçñ]+)*")
ARABIC_TOKEN = re.compile(r"[ء-ي\u0640\u064B-\u0652\u0670][^\s\u060C\u061F\u061B\u06D4]+")
MIXED_TOKEN = re.compile(r"[^\W\d_]+(?:[-'’_][^\W\d_]+)*", re.UNICODE)
NUMBER_TOKEN = re.compile(r"[-+]?[0-9][0-9,\.\s]*%?|\b\d+(?:[.,]\d+)?\s?(?:%|percent)\b", re.IGNORECASE)

# Sentence-final punctuation per script/language. Arabic uses ، ; ؟ ۄ-style separators.
_TERMINATORS = ".!?؛،؟\u061F\u066B\u066D"
_SENT_SPLIT = re.compile(rf"(?<=[{_TERMINATORS}])\s+|(?<=[{_TERMINATORS}])(?=[^\s{_TERMINATORS}][A-Z\u0600-\u06FF])")

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "no", "vs", "etc", "e.g", "i.e", "fig", "al",
    "approx", "dept", "inc", "ltd", "ref", "art", "vol", "p", "pp", "sgt", "capt", "gen",
}
# Arabic abbreviations rarely appear; keep the guard symmetrical for numbers like "1.2"
_NUM_DOT = re.compile(r"(?<=\d)\.(?=\d)")


def is_arabic_char(ch: str) -> bool:
    code = ord(ch)
    return 0x0600 <= code <= 0x06FF or 0xFB50 <= code <= 0xFDFF or 0xEE00 <= code <= 0xFEFF


def normalize_word(word: str) -> str:
    """Casefold, strip diacritics/tatweel for Arabic, unify apostrophes."""
    word = word.replace("\u2019", "'").replace("\u0640", "")
    word = "".join(ch for ch in word if not (0x064B <= ord(ch) <= 0x0652 or ord(ch) == 0x0670))
    return word.casefold()


def tokenize(text: str) -> list[str]:
    return MIXED_TOKEN.findall(text)


def normalize_tokens(text: str) -> list[str]:
    return [normalize_word(t) for t in tokenize(text)]


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, sentence) offsets inside ``text``. Never returns empty pieces."""
    if not text or not text.strip():
        return []
    guarded = _NUM_DOT.sub("\u2024", text)
    raw: list[tuple[int, str]] = []
    pos = 0
    for piece in _SENT_SPLIT.split(guarded):
        if piece is None:
            continue
        # Re-locate the piece in the original text (we only substituted a character, length preserved).
        idx = guarded.find(piece, pos) if piece else pos
        if idx < 0:
            idx = pos
        raw.append((idx, piece))
        pos = idx + max(len(piece), 1)

    sentences: list[tuple[int, int, str]] = []
    buffer_start: int | None = None
    buffer: list[str] = []

    def flush(end: int) -> None:
        nonlocal buffer_start, buffer
        joined = " ".join(buffer).strip()
        if joined and buffer_start is not None:
            sentences.append((buffer_start, min(end, len(text)), joined))
        buffer_start, buffer = None, []

    for idx, piece in raw:
        stripped = piece.strip()
        if not stripped:
            continue
        if buffer_start is None:
            buffer_start = idx
        buffer.append(stripped)
        last = stripped[-1]
        ends = last in ".!?؛?\u061F"
        # Split on Arabic comma only when the fragment is already long enough to be a clause.
        if not ends and last in "،,\u066B" and len(" ".join(buffer)) > 140:
            ends = True
        if ends:
            tail = stripped.rstrip(_TERMINATORS)
            low = normalize_word(tail.split()[-1]) if tail.split() else ""
            if low.rstrip(".") in _ABBREVIATIONS and last == ".":
                continue
            if len(stripped) < 3 and last in ".":
                continue
            flush(idx + len(piece))
    if buffer:
        flush(len(guarded))

    # Drop sentence fragments shorter than 2 characters; keep offset honesty.
    return [(s, e, t) for s, e, t in sentences if len(t) >= 2]


def syllable_count(word: str) -> int:
    """Vowel-group heuristic for Latin script (used by readability scoring)."""
    word = word.lower()
    if not word.isascii():
        return max(1, len(re.findall(r"[aeiouāēīōū]+", word)) or 1)
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and count > 1 and not word.endswith(("le", "ee", "ye")):
        count -= 1
    return max(1, count)


def word_length_units(word: str, language: str) -> float:
    """Readable length proxy that also works for Arabic and Somali."""
    if language == "ar":
        # Arabic is morphologically dense: a short word often carries a full clause.
        return max(1.0, len(word) / 4.0)
    return float(syllable_count(word))


def strip_punctuation(word: str) -> str:
    return "".join(ch for ch in word if unicodedata.category(ch)[0] not in ("P", "S"))
