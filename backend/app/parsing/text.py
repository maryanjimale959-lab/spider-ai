"""Plain text, Markdown, HTML, and CSV parsing using only safe standard parsing."""
from __future__ import annotations

import csv
import io
import re
from html.parser import HTMLParser
from pathlib import Path

from app.core.ids import new_id
from app.parsing.base import ParsedDocument, ParsedPassage, ParsedSection, clean_text

BLOCK_TAGS = {"p", "div", "section", "article", "li", "tr", "br", "figure", "figcaption", "blockquote", "pre"}
HEAD_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "object", "head"}
VOID_TAGS = {"meta", "link", "br", "img", "input", "hr", "source", "area", "col", "base", "wbr"}


def _push_paragraph(doc: ParsedDocument, text: str, kind: str, section: ParsedSection | None, index: int) -> int:
    text = clean_text(text)
    if not text:
        return index
    doc.passages.append(
        ParsedPassage(id=new_id(), sort_index=index, kind=kind, text=text[:4000],
                      section_id=section.id if section else None, coordinate_source="dom_element")
    )
    return index + 1


# --------------------------------------------------------------------------- txt
def parse_txt(path: Path) -> ParsedDocument:
    doc = ParsedDocument(format="txt", parser="plain-text", positioning_quality="dom_element")
    raw = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    blocks = [b for b in re.split(r"\n\s*\n", raw) if b.strip()]
    index = 0
    section: ParsedSection | None = None
    for position, block in enumerate(blocks):
        text = clean_text(block.replace("\n", " "))
        if position == 0 and len(text.split()) <= 18 and len(text) < 140:
            kind = "title"
        elif re.fullmatch(r"[A-Z0-9 \-–:&/]{4,60}", text) and len(text.split()) <= 10:
            kind = "heading"
        else:
            kind = "paragraph"
        if kind in ("title", "heading"):
            section = ParsedSection(id=new_id(), index=len(doc.sections), level=0 if kind == "title" else 1,
                                    title=text[:300], kind=kind)
            doc.sections.append(section)
            if kind == "title":
                doc.title = text[:200]
        index = _push_paragraph(doc, text, kind, section, index)
    doc.title = doc.title or path.stem
    doc.notes.append("Plain text has no coordinates; the spider stands on the rendered paragraph element.")
    return doc.finalize()


# --------------------------------------------------------------------------- markdown
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_LIST = re.compile(r"^\s*([-*+]|\d+\.)\s+(.*)$")


def parse_markdown(path: Path) -> ParsedDocument:
    doc = ParsedDocument(format="markdown", parser="markdown", positioning_quality="dom_element")
    raw = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    lines = raw.split("\n")
    index = 0
    section: ParsedSection | None = None
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal index
        if buffer:
            index = _push_paragraph(doc, " ".join(buffer), "paragraph", section, index)
            buffer.clear()

    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _MD_HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            title = clean_text(re.sub(r"[*_`]", "", heading.group(2)))
            if not title:
                continue
            kind = "title" if (level == 1 and not doc.sections) else "heading"
            section = ParsedSection(id=new_id(), index=len(doc.sections), level=level, title=title[:300], kind=kind)
            doc.sections.append(section)
            if kind == "title" and not doc.title:
                doc.title = title[:200]
            index = _push_paragraph(doc, title, kind, section, index)
            continue
        list_item = _MD_LIST.match(line)
        if list_item:
            flush()
            index = _push_paragraph(doc, re.sub(r"[*_`]", "", list_item.group(2)), "list_item", section, index)
            continue
        if line.startswith("|") and "|" in line[1:]:
            flush()
            cells = [clean_text(c) for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
                index = _push_paragraph(doc, " | ".join(c for c in cells if c), "table_row", section, index)
            continue
        if not line.strip():
            flush()
            continue
        buffer.append(line.strip())
    flush()
    doc.title = doc.title or path.stem
    doc.notes.append("Markdown passages are anchored to their rendered element; no page coordinates exist in the source.")
    return doc.finalize()


# --------------------------------------------------------------------------- html
class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str, int]] = []   # (kind, text, level)
        self._current: list[str] = []
        self._kind = "paragraph"
        self._level = 9
        self._skip_stack: list[str] = []
        self.title_text = ""

    def _start_block(self, kind: str, level: int = 9) -> None:
        self._flush()
        self._kind, self._level = kind, level

    def _flush(self) -> None:
        text = clean_text(" ".join(self._current))
        self._current = []
        if text:
            self.blocks.append((self._kind, text, self._level))

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in VOID_TAGS:
            if tag == "br":
                self._current.append("\n")
            return
        if tag in SKIP_TAGS:
            self._skip_stack.append(tag)
            return
        if self._skip_stack:
            return
        if tag in HEAD_TAGS:
            self._start_block("title" if (tag == "h1" and not self.blocks) else "heading", HEAD_TAGS[tag])
        elif tag == "li":
            self._start_block("list_item")
        elif tag == "p" or tag in BLOCK_TAGS:
            self._start_block("caption" if tag == "figcaption" else "paragraph")

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if tag in SKIP_TAGS:
            if tag in self._skip_stack:
                self._skip_stack.remove(tag)
            return
        if self._skip_stack:
            return
        if tag in BLOCK_TAGS or tag in HEAD_TAGS or tag in ("td", "th", "span"):
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_stack:
            return
        self._current.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def parse_html(path: Path) -> ParsedDocument:
    doc = ParsedDocument(format="html", parser="html-parser", positioning_quality="dom_element")
    raw = path.read_text(encoding="utf-8", errors="replace")
    extractor = _HtmlTextExtractor()
    extractor.feed(raw)
    extractor.close()

    index = 0
    section: ParsedSection | None = None
    for kind, text, level in extractor.blocks:
        if len(text) > 4000:
            text = text[:4000]
        if kind in ("title", "heading"):
            section = ParsedSection(id=new_id(), index=len(doc.sections), level=level, title=text[:300], kind=kind)
            doc.sections.append(section)
            if kind == "title" and not doc.title:
                doc.title = text[:200]
        index = _push_paragraph(doc, text, kind, section, index)
    doc.title = doc.title or path.stem
    doc.notes.append(
        "HTML was parsed with a safe standard-library tokenizer; scripts, styles, and markup were dropped and "
        "only visible text became passages. Passages anchor to their rendered element."
    )
    return doc.finalize()


# --------------------------------------------------------------------------- csv / tsv
def parse_csv(path: Path) -> ParsedDocument:
    doc = ParsedDocument(format="csv", parser="csv", positioning_quality="dom_element")
    sample = path.read_text(encoding="utf-8", errors="replace")[:4096]
    delimiter = "\t" if path.suffix.lower() in (".tsv",) or sample.count("\t") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(path.read_text(encoding="utf-8", errors="replace")), delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        doc.notes.append("The spreadsheet contained no readable rows.")
        return doc.finalize()

    header = [clean_text(h) for h in rows[0]]
    index = 0
    section = ParsedSection(id=new_id(), index=0, level=0, title=path.stem, kind="title")
    doc.sections.append(section)
    doc.title = path.stem
    index = _push_paragraph(doc, " | ".join(h for h in header if h), "heading", section, index)

    for row in rows[1:]:
        pairs = [f"{header[i]}: {clean_text(cell)}" for i, cell in enumerate(row) if i < len(header) and header[i] and cell.strip()]
        text = "; ".join(pairs) or " | ".join(clean_text(c) for c in row if c.strip())
        if text:
            index = _push_paragraph(doc, text[:2000], "table_row", section, index)
    doc.notes.append(
        "Spreadsheet rows are read as records. Structure-based analysis is limited: there is no prose layout for "
        "the spider to walk between paragraphs, so it moves row by row."
    )
    return doc.finalize()
