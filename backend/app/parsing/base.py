"""Normalized document representation shared by every parser.

Parsers never return raw library structures. They return sections and passages with
stable identifiers, page numbers, character offsets, and source coordinates when the
format actually provides them. Positioning is never fabricated: when exact text
coordinates are unavailable the passage is anchored to its container and
``coordinate_source`` says so.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b\u200c\u200d\ufeff]")
WS = re.compile(r"[ \t\u00a0\u2007\u202f]+")
MULTINL = re.compile(r"\n{3,}")

KIND_RANK = {"title": 0, "heading": 1, "paragraph": 2, "list_item": 3, "table_row": 4, "caption": 5}


def clean_text(value: str) -> str:
    value = CONTROL_CHARS.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    value = WS.sub(" ", value)
    value = MULTINL.sub("\n\n", value)
    return value.strip()


def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text) if w])


@dataclass
class ParsedPassage:
    id: str
    sort_index: int
    kind: str
    text: str
    char_start: int = 0
    char_end: int = 0
    page_number: int | None = None
    bbox: dict[str, float] | None = None          # source-space coordinates (PDF points)
    # Per-line rectangles, in source units, for precise scan-beam positioning.
    lines: list[dict[str, Any]] | None = None
    section_id: str | None = None
    coordinate_source: str = "dom_element"        # pdf_bbox | dom_element | container
    words: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedSection:
    id: str
    index: int
    level: int
    title: str
    kind: str = "heading"
    parent_id: str | None = None


@dataclass
class ParsedPage:
    number: int
    width: float
    height: float
    image_path: str = ""
    image_scale: float = 2.0
    has_text: bool = True


@dataclass
class ParsedDocument:
    format: str = ""
    parser: str = ""
    language: str = "unknown"
    language_confidence: float = 0.0
    positioning_quality: str = "dom_element"      # pdf_bbox | dom_element | container | none
    needs_ocr: bool = False
    title: str = ""
    sections: list[ParsedSection] = field(default_factory=list)
    passages: list[ParsedPassage] = field(default_factory=list)
    pages: list[ParsedPage] = field(default_factory=list)
    full_text: str = ""
    word_count: int = 0
    char_count: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def finalize(self) -> "ParsedDocument":
        """Compute character offsets into the full extracted text and totals."""
        cursor = 0
        chunks: list[str] = []
        for passage in self.passages:
            text = clean_text(passage.text)
            passage.text = text
            passage.words = word_count(text)
            passage.char_start = cursor
            passage.char_end = cursor + len(text)
            chunks.append(text)
            cursor += len(text) + 2          # paragraph separator "\n\n"
            if passage.page_number is not None:
                passage.coordinate_source = passage.coordinate_source
        self.full_text = "\n\n".join(chunks)
        self.word_count = sum(p.words for p in self.passages)
        self.char_count = len(self.full_text)
        self.passages.sort(key=lambda p: (p.sort_index,))
        return self


def blank_passage(text: str, sort_index: int, kind: str = "paragraph", passage_id: str = "", **kw: Any) -> ParsedPassage:
    return ParsedPassage(id=passage_id, sort_index=sort_index, kind=kind, text=text, **kw)
