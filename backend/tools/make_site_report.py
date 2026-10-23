"""Build the multi-page verification fixture used by the headless UI checks.

The text is synthetic and marked as such on every page. It exists so the crawl
has to cross a page break, and so the rule engine has real claims, figures and
repeated phrasing to work with - it is never presented as a real document.

    .venv/Scripts/python tools/make_site_report.py
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import fitz

SECTIONS: list[tuple[str, list[str]]] = [
    (
        "Field notes - water point survey",
        [
            "This report records the survey of water points carried out across four villages between March and June.",
            "The team inspected 86 hand pumps and recorded the condition of each one, the distance to the nearest homestead, and the name of the committee responsible for maintenance.",
            "Overall the results show that most water points are functioning, but that the quality of the surrounding drainage has declined since the previous survey.",
        ],
    ),
    (
        "1 Method",
        [
            "Each village was visited twice. The first visit was used to walk the perimeter and list the water points; the second visit was used to test the pump and interview the committee.",
            "Interviews were conducted with two households living within 300 metres of each water point. Notes were taken in English and translated afterwards.",
            "The survey covered 86 hand pumps in total. Of these, 71 were reported as working on the day of the visit.",
            "A further nine pumps were reported as broken, and six could not be assessed because the lock was missing.",
        ],
    ),
    (
        "2 Findings",
        [
            "The drainage around 34 water points was described as poor. Standing water was observed within five metres of the pump apron in 21 cases.",
            "Committees were active at 52 of the 86 sites. Where a committee was absent, the time since the last inspection was reported as more than eighteen months.",
            "The distance to the nearest homestead averaged 240 metres, with a maximum of 780 metres at the northern site.",
            "Households reported that the water table had dropped over the dry season. This claim was not measured and should be checked against the records of the district office.",
            "The report concludes that the scheme is a success overall. No figures are given for the cost of the repairs already carried out.",
        ],
    ),
    (
        "3 Discussion",
        [
            "The pattern of failures is consistent with deferred maintenance rather than with equipment faults. Spare parts were available in the district town but were not budgeted for by the committees.",
            "Where committees met regularly, the apron and drainage were kept clear, and the pump was reported as working.",
            "It would be wrong to read the higher functioning rate in the southern villages as evidence of better management; soil conditions differ and the sample is small.",
        ],
    ),
    (
        "4 Recommendations",
        [
            "A spare-part fund should be established for each cluster of sites, with the committee collecting contributions quarterly.",
            "The nine broken pumps should be prioritised for repair before the next dry season.",
            "Drainage works should be scheduled at the 21 sites where standing water was observed.",
            "The claim about the falling water table should be verified against district records before it is repeated in any summary.",
            "A short paragraph on cost recovery should be added, since the present report states a conclusion about success without giving the figures behind it.",
        ],
    ),
]

FOOTER = "SPIDER AI verification fixture - synthetic text, not a real document."


def build(target: Path) -> int:
    doc = fitz.open()
    width, height, margin = 595.28, 841.89, 62
    for title, body in SECTIONS:
        page = doc.new_page(width=width, height=height)
        y = margin + 24
        page.insert_text((margin, y), title, fontsize=15, fontname="hebo")
        y += 32
        for paragraph in body:
            for line in textwrap.wrap(paragraph, 88):
                page.insert_text((margin, y), line, fontsize=11, fontname="helv")
                y += 15
            y += 13
        page.insert_text((margin, height - 44), FOOTER, fontsize=8.5, fontname="helv", color=(0.45, 0.45, 0.45))
    doc.save(target)
    pages = doc.page_count
    doc.close()
    return pages


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "samples" / "site_report.pdf"
    count = build(out)
    check = fitz.open(out)
    characters = sum(len(page.get_text()) for page in check)
    check.close()
    print(f"wrote {out} - {count} pages, {characters} characters")
