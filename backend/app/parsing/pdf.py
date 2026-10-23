"""PDF parsing with PyMuPDF: real text blocks, real bounding boxes, rendered pages.

This is the format where the spider can stand on exact source coordinates: every
passage keeps the union bounding box of its text lines in PDF points, plus the page
geometry needed to convert points to screen pixels at any zoom level.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

try:  # PyMuPDF >= 1.24 exposes both names; 2.x prefers `pymupdf`
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

from app.parsing.base import ParsedDocument, ParsedPage, ParsedPassage, ParsedSection, clean_text
from app.core.ids import new_id

MIN_BLOCK_CHARS = 2


def _line_text(line: dict) -> str:
    return "".join(span.get("text", "") for span in line.get("spans", []))


def _block_size(block: dict) -> float:
    sizes = [
        span.get("size", 0.0)
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span.get("text", "").strip()
    ]
    if not sizes:
        return 0.0
    return max(sizes, key=lambda s: sizes.count(s))


def parse_pdf(path: Path, render_dir: Path, zoom: float = 2.0) -> ParsedDocument:
    doc = ParsedDocument(format="pdf", parser="pymupdf", positioning_quality="pdf_bbox")
    with fitz.open(str(path)) as pdf:
        # Body size = most common span size across the document; anything clearly larger is a heading.
        size_counter: Counter[float] = Counter()
        for page in pdf:
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                size = round(_block_size(block), 1)
                if size:
                    size_counter[size] += max(1, len(_line_text(block["lines"][0])) // 10)
        body_size = size_counter.most_common(1)[0][0] if size_counter else 11.0

        sort_index = 0
        section: ParsedSection | None = None
        page_has_text: list[bool] = []

        for page_no, page in enumerate(pdf, start=1):
            rect = page.rect
            image_name = f"page-{page_no}.png"
            image_path = render_dir / image_name
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            pix.save(str(image_path))
            doc.pages.append(
                ParsedPage(number=page_no, width=float(rect.width), height=float(rect.height),
                           image_path=str(image_path), image_scale=zoom, has_text=True)
            )

            blocks = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0 and b.get("lines")]
            blocks.sort(key=lambda b: (round(b["bbox"][1] / 4.0), b["bbox"][0]))
            found_text = False

            for block in blocks:
                lines = block["lines"]
                # Join wrapped lines with spaces: the block is one paragraph of prose, and
                # the per-line rectangles below preserve where each visual line actually sits.
                text = clean_text(" ".join(_line_text(line) for line in lines))
                if len(text) < MIN_BLOCK_CHARS:
                    continue
                found_text = True
                size = round(_block_size(block), 1)
                x0, y0, x1, y1 = block["bbox"]
                bbox = {"x": float(x0), "y": float(y0), "w": float(x1 - x0), "h": float(y1 - y0)}

                is_heading = size > body_size * 1.12 and len(text) <= 160
                first_page_big = page_no == 1 and sort_index == 0 and size >= body_size * 1.25
                kind = "title" if first_page_big else ("heading" if is_heading else "paragraph")

                if kind in ("title", "heading"):
                    section = ParsedSection(id=new_id(), index=len(doc.sections), level=0 if kind == "title" else 1,
                                            title=text[:300], kind=kind)
                    doc.sections.append(section)
                    if kind == "title" and not doc.title:
                        doc.title = text[:200]

                lines = [
                    {"x": float(l["bbox"][0]), "y": float(l["bbox"][1]),
                     "w": float(l["bbox"][2] - l["bbox"][0]), "h": float(l["bbox"][3] - l["bbox"][1]),
                     "text": _line_text(l)}
                    for l in block["lines"] if _line_text(l).strip()
                ]
                doc.passages.append(
                    ParsedPassage(id=new_id(), sort_index=sort_index, kind=kind, text=text,
                                  page_number=page_no, bbox=bbox, lines=lines,
                                  section_id=section.id if section else None,
                                  coordinate_source="pdf_bbox")
                )
                sort_index += 1

            page_has_text.append(found_text)
            if not found_text:
                doc.pages[-1].has_text = False

        if page_has_text and not any(page_has_text):
            doc.needs_ocr = True
            doc.positioning_quality = "none"
            doc.notes.append(
                "No embedded text layer was found in this PDF. It appears to be a scan: "
                "OCR must be enabled before the spider can walk on its text."
            )
        elif not all(page_has_text):
            doc.needs_ocr = True
            doc.notes.append(
                f"{page_has_text.count(False)} of {len(page_has_text)} pages have no text layer and were skipped "
                "by the analyzer. Enable OCR to investigate them."
            )

        if not doc.title and doc.passages:
            doc.title = path.stem

    return doc.finalize()
