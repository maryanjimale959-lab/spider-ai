"""Generate the sample PDF / DOCX / TXT documents used for seeding and manual testing.

Run from the backend directory:
    ./.venv/Scripts/python.exe tools/make_samples.py
"""
from __future__ import annotations

import re
from pathlib import Path

import docx
import pymupdf

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
SOURCE = SAMPLES / "english_report.md"

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
LIST = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$")


def blocks() -> list[tuple[str, str]]:
    text = SOURCE.read_text(encoding="utf-8")
    out: list[tuple[str, str]] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        heading = HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            out.append(("h1" if level == 1 else "h2", heading.group(2).strip()))
        elif LIST.match(line):
            out.append(("list", LIST.match(line).group(1).strip()))
        else:
            out.append(("p", line.strip()))
    return out


def make_pdf(path: Path) -> None:
    page_width, page_height = 595.28, 841.89
    margin = 68.0
    doc = pymupdf.open()
    page = doc.new_page(width=page_width, height=page_height)
    y = margin

    def new_page_if_needed(needed: float) -> None:
        nonlocal page, y
        if y + needed > page_height - margin:
            page = doc.new_page(width=page_width, height=page_height)
            y = margin

    for kind, text in blocks():
        size = {"h1": 19.0, "h2": 14.0, "p": 11.0, "list": 11.0}[kind]
        width = page_width - 2 * margin
        lines = wrap(text, size, width)
        line_height = size * 1.42
        new_page_if_needed(len(lines) * line_height + 14)
        for line in lines:
            page.insert_text((margin, y + size), line, fontsize=size, fontname="helv", color=(0.09, 0.11, 0.16))
            y += line_height
        y += 10.0 if kind == "p" else 14.0
    doc.save(str(path))
    doc.close()


def wrap(text: str, size: float, width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pymupdf.get_text_length(candidate, fontname="helv", fontsize=size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def make_docx(path: Path) -> None:
    document = docx.Document()
    document.core_properties.title = "Focus and Morning Screen Time in Secondary Classrooms"
    for kind, text in blocks():
        if kind == "h1":
            document.add_heading(text, level=0)
        elif kind == "h2":
            document.add_heading(text, level=1)
        elif kind == "list":
            document.add_paragraph(text, style="List Number")
        else:
            document.add_paragraph(text)
    table = document.add_table(rows=3, cols=3)
    table.rows[0].cells[0].text = "Group"
    table.rows[0].cells[1].text = "Reported phone minutes"
    table.rows[0].cells[2].text = "Mornings rated 4 or 5"
    table.rows[1].cells[0].text = "Over 90 minutes"
    table.rows[1].cells[1].text = "108"
    table.rows[1].cells[2].text = "71%"
    table.rows[2].cells[0].text = "Under 30 minutes"
    table.rows[2].cells[1].text = "22"
    table.rows[2].cells[2].text = "34%"
    document.save(str(path))


def make_txt(path: Path) -> None:
    lines: list[str] = []
    for kind, text in blocks():
        if kind in ("h1", "h2"):
            lines.append("")
            lines.append(text.upper() if kind == "h2" else text)
            lines.append("")
        elif kind == "list":
            lines.append(f"- {text}")
        else:
            lines.append(text)
            lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    make_pdf(SAMPLES / "english_report.pdf")
    make_docx(SAMPLES / "english_report.docx")
    make_txt(SAMPLES / "english_report.txt")
    html = ["<html><head><meta charset='utf-8'><title>Library plan</title></head><body>"]
    for kind, text in blocks():
        if kind == "h1":
            html.append(f"<h1>{escape(text)}</h1>")
        elif kind == "h2":
            html.append(f"<h2>{escape(text)}</h2>")
        elif kind == "list":
            html.append(f"<ul><li>{escape(text)}</li></ul>")
        else:
            html.append(f"<p>{escape(text)}</p>")
    html.append("</body></html>")
    (SAMPLES / "english_report.html").write_text("\n".join(html), encoding="utf-8")
    print("samples written:", sorted(p.name for p in SAMPLES.iterdir()))


def escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    main()
