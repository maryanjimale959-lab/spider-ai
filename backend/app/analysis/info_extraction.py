"""Important-information extraction.

Pattern-driven, dictionary-free extraction of the things a reader must not miss: dates,
figures, people, definitions, decisions, action items, critical statements, and concrete
facts. Kinds match ``FINDING_KINDS`` in ``app/models.py`` and every value put in
``FindingDraft.extra`` is a slice of the document's own text.
"""
from __future__ import annotations

import re

from app.analysis.evidence import locate
from app.analysis.language import ALL
from app.analysis.segmentation import normalize_tokens
from app.analysis.types import (
    AnalysisContext,
    DocPassage,
    EvidenceDraft,
    FindingDraft,
    Sentence,
)

ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

MONTHS = {
    "en": r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
          r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)",
    "ar": r"(?:يناير|فبراير|مارس|ابريل|أبريل|مايو|يونيو|يوليو|اغسطس|أغسطس|سبتمبر|اكتوبر|أكتوبر|"
          r"نوفمبر|ديسمبر|كانون\s+الاول|كانون\s+الثاني|شباط|اذار|آذار|نيسان|ايار|حزيران|تموز|اب|آب|تشرين\s+الاول|تشرين\s+الثاني)",
    "so": r"(?:Janaayo|Febraayo|Maarso|Abriil|Maajo|Juun|Luuliyo|Agosto|Sebtembar|Sebto|Oktoobar|"
          r"Nofeembar|Diiceembar|Disembar)",
}
WEEKDAYS = {
    "en": r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)",
    "ar": r"(?:السبت|الاحد|الأحد|الاثنين|الثلاثاء|الاربعاء|الأربعاء|الخميس|الجمعة)",
    "so": r"(?:Isniin|Talaado|Arbaco|Khamiis|Jimce|Sabti|Axad)",
}

# Words that legitimately open a sentence capitalised but are not part of a person name.
LEAD_CAPS = {
    "the", "this", "that", "these", "those", "it", "he", "she", "they", "we", "you", "i", "and", "but",
    "or", "so", "then", "there", "their", "in", "on", "at", "for", "with", "after", "before", "during",
    "while", "when", "where", "how", "why", "all", "any", "most", "more", "other", "another", "each",
    "every", "both", "few", "many", "several", "however", "although", "because", "since", "if", "unless",
    "also", "even", "yet", "still", "again", "instead", "meanwhile", "furthermore", "additionally",
    "according", "based", "given", "using", "without", "within", "among", "between", "our", "your", "his",
    "her", "its", "water", "report", "study", "plan", "project", "committee", "government", "district",
    "section", "table", "figure", "chapter", "conclusion", "recommendation", "decision", "date", "note",
}

DIGIT_CLASS = r"[0-9\u0660-\u0669\u06F0-\u06F9]"
UNIT_WORDS = (
    r"(?:%|percent|per\s+cent|million|billion|trillion|thousand|hundred|kg|kilograms?|tons?|"
    r"km|kilomet(?:er|re)s?|meters?|metres?|cm|mm|hectares?|acres?|cubic|square|lit(?:er|re)s?|"
    r"people|persons?|students?|teachers?|households?|families?|patients?|schools?|villages?|"
    r"districts?|regions?|days?|months?|years?|weeks?|hours?|times?|usd|usd\$|dollars?|euros?|shillings?|"
    r"units?|sites?|projects?|cases?|groups?|members?|votes?|hectors?|km2|m2|mw|kw|tonne|tonnes)"
)

STATISTIC = re.compile(
    rf"(?:{DIGIT_CLASS}{{1,3}}(?:,{DIGIT_CLASS}{{3}})*|{DIGIT_CLASS}+)(?:\.{DIGIT_CLASS}+)?\s*"
    rf"(?:{UNIT_WORDS})(?:\s+(?:of|per)\s+[\w'’\-]+)?",
    re.IGNORECASE,
)
PERCENT = re.compile(rf"(?:{DIGIT_CLASS}{{1,3}}(?:,{DIGIT_CLASS}{{3}})*|{DIGIT_CLASS}+)(?:\.{DIGIT_CLASS}+)?\s*(?:%|percent|per\s+cent|\u066a)",
                     re.IGNORECASE)
ISO_DATE = re.compile(rf"{DIGIT_CLASS}{{4}}-{DIGIT_CLASS}{{1,2}}-{DIGIT_CLASS}{{1,2}}")
NUMERIC_DATE = re.compile(rf"(?:{DIGIT_CLASS}{{1,2}}[/-]{DIGIT_CLASS}{{1,2}}[/-]{DIGIT_CLASS}{{2,4}})")

DECISION = {
    "en": r"\b(?:decided|decision|decides|approves?\|approved|approval|agreed|agreement|resolved|resolution|"
          r"adopted|adopts|ratified|signed\s+the|endorsed|authori[sz]ed|was\s+granted|has\s+approved)\b",
    "ar": r"(?:قرّر|قرر|تقرر|قرار|تمت\s+الموافقة|وافق|أقر|اقر|اعتمد|اتفق|اتفاق|مصادقة|توصية\s+اعتمدت)",
    "so": r"(?:go'aan|go'aamiyay|go'aansaday|la\s+go'aamiyay|ogolaaday|ogolaansho|isla\s+afgarad|heshiis|"
          r"saxiixay|ansixiyay|xaqiijiyay)",
}
ACTION = {
    "en": r"(?:\b(?:must|shall|is\s+required\s+to|are\s+required\s+to|needs?\s+to\s+be|has\s+to\s+be|"
          r"is\s+obliged\s+to|will\s+be\s+(?:submitted|delivered|completed|published|conducted)|"
          r"should\s+be|responsible\s+for|is\s+tasked\s+with|deadline)\b)|"
          r"^\s*(?:Ensure|Provide|Submit|Deliver|Report|Include|Prepare|Confirm|Appoint|Allocate|"
          r"Carry\s+out|Review|Complete|Note)\b",
    "ar": r"(?:يجب|ينبغي|يتعين|يُطلب|يطلب|على\s+الجميع|يجب\s+أن|العمل\s+على|موعد\s+نهائي|"
          r"يرجى|عليه\s+أن|لزم)",
    "so": r"(?:waa\s+in|waajib|waa\s+la|loo\s+baahan\s+yahay|lagu\s+amray|waa\s+inay|waajibka|"
          r"muddo\s+kama\s+dambeysa|diyaari|bixi|samee| gudbi)",
}
CRITICAL = {
    "en": r"\b(?:most\s+important|crucial|critical|essential|vital|key\s+(?:issue|point|factor|problem|"
          r"challenge|risk)|at\s+stake|above\s+all|top\s+priority|the\s+main\s+(?:cause|problem|reason|"
          r"risk)|fundamental|indispensable)\b",
    "ar": r"(?:الأهم|اهم\s+شيء|الأساسية|الاساسية|الحيوية|المحورية|أولوية|اولوية|على\s+رأس|"
          r"الأكثر\s+اهمية|جوهرية|خطيرة|حاسمة)",
    "so": r"(?:muhiimad\s+gaar\s+ah|waa\s+muhiim|ahmiyad\s+leahay|udub|horseed|waan\s+lakaab\s+ah|"
          r"ahmiyadda\s+kowaad|waa\s+muhiimad|loobaahay)",
}
DEFINITION = {
    "en": r"(?P<term>[\w'’\- ]{3,50}?)\s+(?:is\s+defined\s+as|are\s+defined\s+as|defined\s+as|means|"
          r"refers\s+to|is\s+understood\s+as|is\s+known\s+as|is\s+called)\s+(?P<rest>[\w'’\- ]{3,80})",
    "ar": r"(?P<term>[\u0600-\u06FF'’\-\u060C ]{3,40}?)\s+(?:هو|هي|عبارة\s+عن|يقصد\s+به|يقصد\s+بـ|يعني|تعني|"
          r"تُعرَّف|تعرف\s+بأنها)\s+(?P<rest>[\u0600-\u06FF'’\-\u060C ]{3,60})",
    "so": r"(?P<term>(?:(?!waa\b)[\w'’\- ]){3,45}?)\s+waa\s+(?P<rest>[\w'’\- ]{2,45}?)\s+"
          r"(?:oo|kaasi\s+oo|taas\s+oo|asi\s+oo|oo\s+la\s+macaan)\b",
}
HONORIFIC = {
    "en": r"(?:Mr|Mrs|Ms|Dr|Prof|Professor|Doctor|Hon|President|Minister|Director|Chair(?:wo)?man|"
          r"Secretary|CEO|Deputy|Engineer|Ambassador|Commissioner|Head\s+of)\.?\s+",
    "so": r"(?:Madaxweyne|Wasiir|Mudane|Xildhibaan|Guddoomiye|Gudoomiye|Agaasime|Professor|"
          r"Dr|Ambassador|Wakiil)\.?\s+",
    "ar": r"(?:السيد|الأستاذ|الاستاذ|الدكتور|البروفيسور|معالي|سعادة|الأستاذة|الاستاذة|"
          r"المهندس|وزیر|وزير|رئيس|مدير|نائب)\s+",
}
NAME_LATIN = re.compile(
    r"(?P<name>(?:[A-Z][A-Za-z'’\-]+\s+){1,3}[A-Z][A-Za-z'’\-]+)"
)
NAME_AR = re.compile(
    rf"(?:(?:{HONORIFIC['ar']})\s*(?P<name>[\u0600-\u06FF'’\-\u060C]{{2,40}}(?:\s+[\u0600-\u06FF'’\-]{{2,30}}){{0,3}}))|"
    rf"(?:(?:قال|قالت|أوضح|اوضح|أوضحت|أكد|اكد|أشار|اشار|أضاف|اضاف|صرح|صرّح|اجتمع|وقع)\s+)"
    rf"(?P<speech>[\u0600-\u06FF'\-]{{2,30}}(?:\s+[\u0600-\u06FF'\-]{{2,30}}){{1,3}})"
)

RELATIVE_DATE = {
    "en": r"\b(?:yesterday|today|tomorrow|next\s+(?:week|month|year|quarter)|last\s+(?:week|month|year|"
          r"quarter|election)|(?:one|two|three|four|five|six|ten|twenty|thirty)\s+(?:days?|weeks?|months?|"
          r"years?)\s+ago|by\s+(?:the\s+end\s+of|next)\s+(?:\w+))\b",
    "ar": r"(?:أمس|اليوم|غدا|غدًا|الأسبوع\s+الماضي|العام\s+الماضي|العام\s+القادم|الشهر\s+الماضي|"
          r"السنة\s+الماضية|المقبل|الماضي)",
    "so": r"(?:shalay|maanta|berri|berri\s+dambe|todobaadkan|todobaadkii\s+hore|bishan|bilkii\s+hore|"
          r"isanadkan|sannadkan|sanadkii\s+hore|sannadka\s+soo\s+socda|dishii\s+hore)",
}

FACT_HINTS = re.compile(
    r"\b(?:there\s+(?:is|are|was|were)|located|situated|consists?\s+of|covers|extends|reached|existed|"
    r"serves|produces|employs|holds|borders|lies|was\s+founded|established|named\s+after)\b",
    re.IGNORECASE,
)

CAPS = 8


# --------------------------------------------------------------------------- helpers
def _stopwords(language: str) -> set[str]:
    return ALL.get(language) or set().union(*ALL.values())


def _clamp(text: str, limit: int = 70) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[:limit]
    if " " in cut[limit - 15:]:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:") + "..."


def _title(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= 90 else _clamp(collapsed, 85)


def _ascii_value(value: str) -> str:
    return " ".join(value.translate(ARABIC_INDIC).split())


def _pattern(patterns: dict[str, str], language: str) -> re.Pattern | None:
    text = patterns.get(language)
    if text is None:
        return None
    return re.compile(text, re.IGNORECASE if language != "ar" else 0)


def _any_pattern(patterns: dict[str, str]) -> re.Pattern:
    joined = "|".join(f"(?:{p})" for p in patterns.values())
    return re.compile(joined, re.IGNORECASE)


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


def _section_label(ctx: AnalysisContext, sentence: Sentence) -> str:
    """Nearest preceding title/heading passage, used only as a location label."""
    passage = ctx.passage(sentence.passage_id)
    if passage is None:
        return "the document"
    if passage.section_title:
        return _clamp(passage.section_title, 40)
    if passage.is_heading:
        return _clamp(passage.text, 40)
    heading: DocPassage | None = None
    for candidate in ctx.passages:
        if candidate.id == passage.id:
            break
        if candidate.is_heading:
            heading = candidate
    return _clamp(heading.text, 40) if heading else "the opening section"


# --------------------------------------------------------------------------- extractors
def _dates(ctx: AnalysisContext) -> list[tuple[Sentence, str, str]]:
    out: list[tuple[Sentence, str, str]] = []
    month_patterns = {k: re.compile(v, re.IGNORECASE) for k, v in MONTHS.items()}
    language = ctx.language
    month_regex = month_patterns.get(language) or re.compile(
        "|".join(f"(?:{v})" for v in MONTHS.values()), re.IGNORECASE)
    calendar = re.compile(
        rf"(?:{month_regex.pattern}\s+{DIGIT_CLASS}{{1,2}}(?:st|nd|rd|th)?,?\s+{DIGIT_CLASS}{{2,4}}"
        rf"|{DIGIT_CLASS}{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{month_regex.pattern},?\s+{DIGIT_CLASS}{{2,4}}"
        rf"|{DIGIT_CLASS}{{1,2}}(?:st|nd|rd|th)?\s+{month_regex.pattern})",
        re.IGNORECASE,
    )
    relative = _any_pattern(RELATIVE_DATE) if language not in RELATIVE_DATE else _pattern(RELATIVE_DATE, language)
    year = re.compile(rf"\b({DIGIT_CLASS}{{4}})\b")
    for sentence in ctx.sentences:
        found: list[tuple[str, str]] = []
        spans: list[tuple[int, int]] = []
        for regex, kind_name in ((calendar, "calendar"), (ISO_DATE, "iso"), (NUMERIC_DATE, "numeric")):
            for match in regex.finditer(sentence.text):
                found.append((_ascii_value(match.group(0)), kind_name))
                spans.append(match.span())
        for match in relative.finditer(sentence.text):
            if any(match.start() >= a and match.end() <= b for a, b in spans):
                continue
            found.append((_ascii_value(match.group(0)), "relative"))
            spans.append(match.span())
        if not found:
            for match in year.finditer(sentence.text):
                inner = match.group(0).translate(ARABIC_INDIC)
                if re.fullmatch(r"(?:1[0-9]{3}|20[0-9]{2}|21[01][0-9])", inner):
                    found.append((inner, "year"))
                    break
        for value, kind_name in found:
            out.append((sentence, value, kind_name))
    return out


def _statistics(ctx: AnalysisContext) -> list[tuple[Sentence, str, str]]:
    out: list[tuple[Sentence, str, str]] = []
    for sentence in ctx.sentences:
        best: tuple[int, str, str] | None = None
        for match in PERCENT.finditer(sentence.text):
            value = _ascii_value(match.group(0))
            if best is None or len(value) > len(best[1]):
                best = (match.start(), value, "percentage")
        for match in STATISTIC.finditer(sentence.text):
            value = _ascii_value(match.group(0))
            if re.fullmatch(rf"{DIGIT_CLASS}{{4}}", value.strip()):
                continue
            if best is None or len(value) > len(best[1]):
                best = (match.start(), value, "figure_with_unit")
        if best:
            out.append((sentence, best[1], best[2]))
    return out


def _names(ctx: AnalysisContext) -> list[tuple[Sentence, str]]:
    stop = _stopwords(ctx.language)
    weekday = re.compile(
        "|".join(f"(?:{v})" for v in WEEKDAYS.values()), re.IGNORECASE)
    months = re.compile("|".join(f"(?:{v})" for v in MONTHS.values()), re.IGNORECASE)
    honorific = re.compile(
        "|".join(f"(?:{p})" for p in HONORIFIC.values()),
        re.IGNORECASE if ctx.language != "ar" else 0,
    )
    out: list[tuple[Sentence, str]] = []
    for sentence in ctx.sentences:
        if ctx.language == "ar":
            for match in NAME_AR.finditer(sentence.text):
                name = (match.group("name") or match.group("speech") or "").strip(" ،,")
                if len(name) >= 4 and not weekday.search(name) and not months.search(name):
                    out.append((sentence, _clamp(name, 40)))
            continue
        for match in NAME_LATIN.finditer(sentence.text):
            name = match.group("name")
            if not name:
                continue
            tokens = name.split()
            if any(months.search(t) or weekday.search(t) for t in tokens):
                continue
            if all(t.casefold() in stop or t.casefold() in LEAD_CAPS for t in tokens):
                continue
            starts_sentence = match.start("name") == 0 or sentence.text[:match.start()].strip() in ("", ":")
            preceded_by_honor = bool(honorific.search(sentence.text[:match.start()][-40:]))
            comma_apposition = sentence.text[:match.start()].rstrip().endswith(",")
            if starts_sentence and not preceded_by_honor and not comma_apposition:
                continue
            if len(tokens) < 2:
                continue
            out.append((sentence, _clamp(name, 40)))
    return out


def _definitions(ctx: AnalysisContext) -> list[tuple[Sentence, str, str]]:
    out: list[tuple[Sentence, str, str]] = []
    codes = [ctx.language] if ctx.language in DEFINITION else list(DEFINITION)
    for sentence in ctx.sentences:
        for code in codes:
            regex = re.compile(DEFINITION[code], re.IGNORECASE if code != "ar" else 0)
            match = regex.search(sentence.text)
            if not match:
                continue
            term = _clamp(_clean_term(match.group("term")), 45)
            rest = _clamp(_clean_term(match.group("rest")), 60)
            if len(term) < 3 or len(rest) < 2:
                continue
            if term.casefold() in _stop_terms(ctx):
                continue
            if code == "en" and len(term.split()) > 4:
                continue
            out.append((sentence, term, rest))
            break
    return out


LEADING_DETERMINERS = ("the ", "a ", "an ", "this ", "that ", "these ", "those ", "in ", "of ", "by ")


def _clean_term(value: str) -> str:
    """Trim punctuation and a leading determiner so ``extra`` holds the term itself."""
    text = " ".join(value.split()).strip(" \u060c,;:-")
    lowered = text.casefold()
    for prefix in LEADING_DETERMINERS:
        if lowered.startswith(prefix):
            text = text[len(prefix):]
            break
    return text.strip(" \u060c,;:-")


def _stop_terms(ctx: AnalysisContext) -> set[str]:
    return _stopwords(ctx.language)


def _marker_hits(ctx: AnalysisContext, patterns: dict[str, str]) -> list[tuple[Sentence, str]]:
    out: list[tuple[Sentence, str]] = []
    codes = [ctx.language] if ctx.language in patterns else list(patterns)
    compiled = [(code, re.compile(patterns[code], re.IGNORECASE if code != "ar" else 0)) for code in codes]
    for sentence in ctx.sentences:
        passage = ctx.passage(sentence.passage_id)
        if passage is None or passage.is_heading:
            continue
        for code, regex in compiled:
            match = regex.search(sentence.text)
            if match:
                out.append((sentence, _clamp(match.group(0), 35)))
                break
    return out


# --------------------------------------------------------------------------- findings
def _build(
    ctx: AnalysisContext,
    kind: str,
    sentence: Sentence,
    title: str,
    body: str,
    span: str | None,
    *,
    extra: dict,
    suggestion: str | None = None,
    severity: str = "info",
    confidence: float = 0.85,
) -> FindingDraft | None:
    evidence = _evidence(ctx, sentence, span)
    if evidence is None:
        return None
    return FindingDraft(
        kind=kind,
        title=_title(title),
        body=" ".join(body.split()),
        evidence=[evidence],
        primary_passage_id=evidence.passage_id,
        suggestion=suggestion,
        severity=severity,
        confidence=confidence,
        extra=extra,
    )


def _date_findings(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    seen: set[tuple[str, str]] = set()
    for sentence, value, kind_name in _dates(ctx):
        key = (sentence.passage_id, value.casefold())
        if key in seen:
            continue
        seen.add(key)
        finding = _build(
            ctx, "date", sentence,
            f"Date: {value}",
            f"A time reference is stated in {_section_label(ctx, sentence)} as \"{value}\" ({kind_name} form). "
            "The surrounding sentence is quoted so the event it dates can be checked.",
            None,
            extra={"value": value, "type": "date", "date_form": kind_name},
        )
        if finding:
            out.append(finding)
        if len(out) >= CAPS:
            break
    return out


def _statistic_findings(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    seen: set[tuple[str, str]] = set()
    for sentence, value, kind_name in _statistics(ctx):
        key = (sentence.passage_id, value.casefold())
        if key in seen:
            continue
        seen.add(key)
        finding = _build(
            ctx, "statistic", sentence,
            f"Statistic: {value}",
            f"A quantity is stated with a unit or percentage: \"{value}\" ({kind_name}). "
            "Quantified statements are the ones a reader can verify against a source.",
            None,
            extra={"value": value, "type": "statistic", "form": kind_name},
        )
        if finding:
            out.append(finding)
        if len(out) >= CAPS:
            break
    return out


def _person_findings(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    seen: set[str] = set()
    for sentence, name in _names(ctx):
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        finding = _build(
            ctx, "person", sentence,
            f"Named entity: {name}",
            f"The name \"{name}\" appears in {_section_label(ctx, sentence)}. The sentence naming it is quoted, "
            "which shows the role the text gives this person.",
            None,
            extra={"value": name, "type": "person"},
            confidence=0.75,
        )
        if finding:
            out.append(finding)
        if len(out) >= CAPS - 2:
            break
    return out


def _definition_findings(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    seen: set[str] = set()
    for sentence, term, rest in _definitions(ctx):
        if term.casefold() in seen:
            continue
        seen.add(term.casefold())
        finding = _build(
            ctx, "definition", sentence,
            f"Definition: {term}",
            f"The document defines \"{term}\" in its own wording. Only the defining sentence is quoted here; "
            "the definition has not been rephrased or extended.",
            None,
            extra={"value": term, "type": "definition", "defined_as": rest},
            confidence=0.8,
        )
        if finding:
            out.append(finding)
        if len(out) >= CAPS - 2:
            break
    return out


def _decision_findings(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    seen: set[str] = set()
    for sentence, marker in _marker_hits(ctx, DECISION):
        if sentence.text in seen:
            continue
        seen.add(sentence.text)
        finding = _build(
            ctx, "decision", sentence,
            f"Decision - {_clamp(sentence.text, 58)}",
            f"This sentence records a decision or an agreement, signalled by the wording \"{marker}\". "
            "Decisions are the statements that change what the parties owe each other, so they need to be kept.",
            None,
            extra={"value": marker, "type": "decision"},
            suggestion="Confirm each decision names who decided, when, and what follows from it.",
            severity="minor",
            confidence=0.78,
        )
        if finding:
            out.append(finding)
        if len(out) >= 5:
            break
    return out


def _action_findings(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    seen: set[str] = set()
    for sentence, marker in _marker_hits(ctx, ACTION):
        if sentence.text in seen:
            continue
        seen.add(sentence.text)
        finding = _build(
            ctx, "action_item", sentence,
            f"Action item - {_clamp(sentence.text, 58)}",
            f"This sentence instructs someone to do something (marker: \"{marker}\"). "
            "An action item is only useful if the actor, the task, and the date are all present.",
            None,
            extra={"value": marker, "type": "action_item"},
            suggestion="State the responsible person or office and the deadline in the same sentence.",
            severity="minor",
            confidence=0.75,
        )
        if finding:
            out.append(finding)
        if len(out) >= 6:
            break
    return out


def _critical_findings(ctx: AnalysisContext) -> list[FindingDraft]:
    out: list[FindingDraft] = []
    seen: set[str] = set()
    for sentence, marker in _marker_hits(ctx, CRITICAL):
        if sentence.text in seen:
            continue
        seen.add(sentence.text)
        finding = _build(
            ctx, "critical_statement", sentence,
            f"Critical statement - {_clamp(sentence.text, 58)}",
            f"The author marks this point as important with \"{marker}\", so the sentence carries weight for the "
            "whole document and is the one to read carefully.",
            None,
            extra={"value": marker, "type": "critical_statement"},
            severity="minor",
            confidence=0.7,
        )
        if finding:
            out.append(finding)
        if len(out) >= 4:
            break
    return out


def _fact_findings(ctx: AnalysisContext, already: list[FindingDraft]) -> list[FindingDraft]:
    quoted = {e.quote for f in already for e in f.evidence}
    numeric = re.compile(rf"{DIGIT_CLASS}")
    out: list[FindingDraft] = []
    seen: set[str] = set()
    for sentence in ctx.sentences:
        if len(out) >= 6:
            break
        if sentence.text in quoted or sentence.text in seen:
            continue
        passage = ctx.passage(sentence.passage_id)
        if passage is None or passage.is_heading:
            continue
        tokens = [t for t in normalize_tokens(sentence.text) if len(t) >= 3 and t not in _stop_terms(ctx)]
        if len(tokens) < 4:
            continue
        has_number = bool(numeric.search(sentence.text))
        has_hint = bool(FACT_HINTS.search(sentence.text))
        if not (has_number or has_hint):
            continue
        reason = ("it states a figure" if has_number else "it asserts a verifiable condition") \
            + (" and uses a factual construction" if has_hint and has_number else "")
        seen.add(sentence.text)
        finding = _build(
            ctx, "fact", sentence,
            f"Fact stated in {_section_label(ctx, sentence)}",
            f"This sentence is presented as a checkable fact rather than an opinion: {reason}. "
            f"It carries {len(tokens)} content word(s) that name what the fact is about.",
            None,
            extra={"type": "fact", "content_terms": len(tokens)},
            confidence=0.6,
        )
        if finding:
            out.append(finding)
    return out


def extract_important_information(ctx: AnalysisContext) -> list[FindingDraft]:
    """Facts, dates, people, definitions, statistics, decisions, action items, critical statements."""
    findings: list[FindingDraft] = []
    findings += _date_findings(ctx)
    findings += _statistic_findings(ctx)
    findings += _person_findings(ctx)
    findings += _definition_findings(ctx)
    findings += _decision_findings(ctx)
    findings += _action_findings(ctx)
    findings += _critical_findings(ctx)
    findings += _fact_findings(ctx, findings)
    deduped: dict[tuple[str, str], FindingDraft] = {}
    for finding in findings:
        if not finding.evidence:
            continue
        key = (finding.kind, finding.evidence[0].quote[:120])
        deduped.setdefault(key, finding)
    return list(deduped.values())
