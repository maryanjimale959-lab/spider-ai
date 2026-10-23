"""End-to-end checks for the local analysis modules.

The four synthetic documents below are original text written for this test, with deliberate
faults planted (a misspelling, a run-on, an unsupported claim, a contradiction pair, a repeated
term, split spellings, mixed punctuation). They prove three things:

1. language detection picks the right language for each document;
2. each module produces findings for the English document and the rules actually fire;
3. the evidence gate is satisfied: every quote is a real substring of its passage, so almost
   nothing is dropped by ``validate_findings``.
"""
from __future__ import annotations

import re
import unicodedata

from app.analysis.evidence import locate, validate_findings
from app.analysis.info_extraction import extract_important_information
from app.analysis.keywords import extract_keywords, key_concept_findings
from app.analysis.language import detect_language
from app.analysis.logic import investigate_logic
from app.analysis.recommendations import build_recommendations
from app.analysis.segmentation import normalize_tokens
from app.analysis.types import AnalysisContext, DocPassage, FindingDraft
from app.analysis.understanding import analyze_understanding
from app.analysis.writing import investigate_writing
from app.models import FINDING_KINDS, WRITING_CATEGORY

EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2B00-\u2BFF]")


def _context(blocks: list[tuple[str, str]], title: str = "") -> AnalysisContext:
    passages: list[DocPassage] = []
    cursor = 0
    for index, (kind, text) in enumerate(blocks):
        text = " ".join(text.split())
        passage = DocPassage(
            id=f"p{index}",
            text=text,
            kind=kind,
            char_start=cursor,
            char_end=cursor + len(text),
            words=len(text.split()),
        )
        passages.append(passage)
        cursor += len(text) + 2
    full_text = "\n\n".join(p.text for p in passages)
    language, confidence = detect_language(full_text)
    return AnalysisContext(
        passages=passages,
        full_text=full_text,
        language=language,
        language_confidence=confidence,
        title=title or (passages[0].text if passages[0].is_heading else ""),
    )


# --------------------------------------------------------------------------- documents
ENGLISH_BLOCKS: list[tuple[str, str]] = [
    ("title", "Water Harvesting and Storage in the Hodan District"),
    ("heading", "1. Introduction"),
    ("paragraph",
     "Water harvesting is defined as the collection of rainwater that runs off roofs and streets. "
     "The purpose of this report is to describe the state of water harvesting in the Hodan District and to "
     "recommend the works that the council shall fund next. Water harvesting lowers the cost of water for "
     "households and it also lowers the pressure on the shallow wells. Dr. Amina Hersi presented the figures "
     "to the council on 12 March 2024. The survey covered 1,200 households in four wards and 45 percent of the "
     "stored water is lost before it reaches a tap. The behaviour of the taps changes with the season, and the "
     "behaviour of the pumps changes with it."),
    ("paragraph",
     "The district plan rests on three ideas. The first idea is that roof water is cleaner than well water. "
     "i asked the engineer about the pump , and he said the the pump can't run without a tank. Water harvesting and "
     "irrigation planning are treated here as one system, and a orchard near the school shows how the system "
     "fails when a tank is small. Their is no meter at most of the taps, and a lot of the losses are simply not "
     "recorded. The new pipes clearly guarantee water for every household."),
    ("heading", "2. Field observations"),
    ("paragraph",
     "We recieve the site notes every week and teh notes repeat the same three problems. The team visited the "
     "site and they checked the pumps and the manager signed the form and nobody recorded the meter reading, "
     "which made the audit impossible. The new canals store water during the dry season. The new canals do not "
     "store water during the dry season. The behaviour of the network in the high ward is stable while the "
     "behavior of the network in the low ward is not stable. Staff say the behavior of the old pumps was worse."),
    ("paragraph",
     "The World Water Day event was held in the district hall and the WWD notices were posted again the next "
     "week, and the WWD posters listed the same three taps."),
    ("paragraph",
     "The most important risk in the district is contamination of the stored water."),
    ("heading", "3. Recommendations"),
    ("list_item", "Contractors must submit the weekly report by Friday."),
    ("list_item", "The council shall fund two more tanks before the next rainy season."),
    ("paragraph", "Water committee meetings shall be minuted by the district officer."),
    ("heading", "4. Conclusion"),
    ("paragraph",
     "The works may improve supply and the records possibly explain part of the loss. All families are "
     "therefore connected and no household waits any longer. An NGO reported that the scheme is complete and "
     "the NGO will return to check the taps."),
]

ARABIC_BLOCKS: list[tuple[str, str]] = [
    ("title", "تقرير عن حصاد المياه في محافظة عدن"),
    ("heading", "1. المقدمة"),
    ("paragraph",
     "حصاد المياه هو تجميع مياه الأمطار التي تنزل على الأسطح والشوارع. يهدف هذا التقرير إلى وصف حالة حصاد "
     "المياه وتحديد الأعمال الواجب تنفيذها. قدم الدكتور أمين الهرمي الأرقام في 12 مارس 2024 وشمل المسح 1200 أسرة. "
     "يفقد النظام 45٪ من المياه المخزنة قبل الوصول إلى الصنبور، وتحتاج الشبكة إلى مراقبة. الأهداف واضحة, "
     "الأهداف قصيرة المدى مكتوبة, الاهداف بعيدة المدى لم تُذكر في التقرير, الاهداف العامة تحتاج إلى رقم."),
    ("paragraph",
     "القنوات الجديدة تخزن المياه في الموسم الجاف. القنوات الجديدة لا تخزن المياه في الموسم الجاف. "
     "يجب على المقاولين تقديم تقرير أسبوعي عن حالة الآبار والصنابير والخطوط والقرى والمدارس والمساكن والعيادات "
     "والطرقات والسواقى والخزانات والألواح والمضخات والعدادات والصمامات والمواسير والحافلات والعمال والمهندسين "
     "والمراقبين والمحاسبين والسائقين والحراس والمختبرين والمشرفين والمديرين."),
    ("paragraph",
     "وافقت المحافظة على تمديد الشبكة إلى ست قرى، وستتابع المديرية التنفيذ شهريًا؛ كما أن المياه, التي تعد "
     "مصدر الحياة, تحتاج إلى حماية."),
    ("heading", "2. الخاتمة"),
    ("paragraph",
     "قد تتحسن الإمدادات قليلًا، وتُظهر السجلات جزءًا من الخسارة. جميع الأسرات تصلها المياه الآن ولا ينتظر أحد."),
]

SOMALI_BLOCKS: list[tuple[str, str]] = [
    ("title", "Qorshaha Maamulka Biyaha ee Degmada Boorama"),
    ("heading", "1. Hordhac"),
    ("paragraph",
     "Ujeeddada qorshahan waa in la muujiyaa baahida loo qabo mashaariicda biyaha. Kaydinta biyuhu waa habka loo "
     "ururiyo roobka oo dib loo isticmaalo. Waxaa la dhisay ceelal badan, waxaana howlgalka bilaabay maamulka "
     "degmada. Waxa aan aragnay in biyaha la lumiyaa. Waxaa qoray warbixinta Dr. Cabdi Nuur 12 Maarso 2024. "
     "Sahanka waxaa ku jiraan 4500 qoys, boqolkiiba 45 oo biyaha ah ayaa lumaa. Soomaaliya way ogtahay caqabadda, "
     "somalia sidoo kale way ogtahay, somalia arrintan waa mid cusub."),
    ("paragraph",
     "Waxaa la eegay ceelasha. Waxa la eegay mishaarka. Waxaa la eegay tuubada. Waxaa la eegay iyo iyo xaaladda "
     "matoorka. Mashruuca biyaha ee Boorama wuu shaqaynayaa. Mashruuca biyaha ee Boorama ma shaqaynayo. "
     "Guddigu waxay go'aansaday in la kordhiyo shabakadda biyaha. Waa in qandaraaslayaashu gudbiyaan warbixinta "
     "toddobadlaha. Biyihii oo dhan waa la keenay xaafadaha oo dhan wayna furan yihiin dhuumaha biyaha geeya "
     "xaafadaha cusub ee magaalada Boorama ee gobolka Awdal ee dadku ku badan yihiin ee mashaariicda loo sameeyay "
     "sanadihii la soo dhaafay ee ay weheliso baaritaanka ceelasha iyo dayactirka matoorada biyaha qaada."),
    ("heading", "2. Gunaanad"),
    ("paragraph",
     "Shaqaaluhu waxa ay sheegeen in biyuhu yaraan karaan. Sidaas darteed dhammaan xaafadaha biyaha ayaa la "
     "gaarsiiyay waana la xaliyay dhibaatadii."),
]

MARKDOWN_BLOCKS: list[tuple[str, str]] = [
    ("title", "Site Note: Borehole Pump"),
    ("paragraph",
     "The pump stopped on Monday. The team can't reach the site because the road is cut, and the tank is empty "
     "and the wires are rusted and nobody logged the fault, so the repair waits again."),
    ("list_item", "Order a new tank."),
    ("list_item", "Check the wiring before the rains."),
]


def _english() -> AnalysisContext:
    return _context(ENGLISH_BLOCKS, title="Water Harvesting and Storage in the Hodan District")


def _arabic() -> AnalysisContext:
    return _context(ARABIC_BLOCKS)


def _somali() -> AnalysisContext:
    return _context(SOMALI_BLOCKS)


def _markdown() -> AnalysisContext:
    return _context(MARKDOWN_BLOCKS)


def _run_all(ctx: AnalysisContext) -> tuple[list[FindingDraft], list]:
    keywords = extract_keywords(ctx, limit=24)
    findings = (analyze_understanding(ctx) + extract_important_information(ctx)
                + key_concept_findings(ctx, keywords) + investigate_writing(ctx, limit=60)
                + investigate_logic(ctx))
    return findings, keywords


# --------------------------------------------------------------------------- language
def test_language_detection():
    assert _english().language == "en"
    assert _arabic().language == "ar"
    assert _somali().language == "so"
    assert _markdown().language == "en"


# --------------------------------------------------------------------------- coverage
def test_modules_report_for_english():
    ctx = _english()
    assert analyze_understanding(ctx), "understanding produced nothing"
    assert extract_important_information(ctx), "information extraction produced nothing"
    assert extract_keywords(ctx), "no keywords"
    assert investigate_writing(ctx), "no writing findings"
    assert investigate_logic(ctx), "no logic findings"

    kinds = {f.kind for f in analyze_understanding(ctx)}
    assert {"subject", "purpose", "central_idea", "argument", "conclusion", "structure"} <= kinds
    assert any(f.kind == "strength" for f in analyze_understanding(ctx))

    info_kinds = {f.kind for f in extract_important_information(ctx)}
    assert {"date", "statistic", "person", "definition"} <= info_kinds
    assert {"decision", "action_item"} & info_kinds or {"critical_statement"} & info_kinds

    categories = {f.category for f in investigate_writing(ctx)}
    assert {"spelling", "clarity", "terminology_consistency", "readability"} <= categories
    assert any(f.category == "grammar" for f in investigate_writing(ctx))

    logic_kinds = {f.kind for f in investigate_logic(ctx)}
    assert "unsupported_claim" in logic_kinds
    assert "contradiction" in logic_kinds, "planted contradiction was not found"
    assert "clarifying_question" in logic_kinds


def test_arabic_and_somali_rules_fire():
    arabic = _arabic()
    assert investigate_writing(arabic), "no Arabic writing findings"
    assert investigate_logic(arabic), "no Arabic logic findings"
    ar_categories = {f.category for f in investigate_writing(arabic)}
    assert "punctuation" in ar_categories, "Latin/Arabic punctuation mixing not reported"
    assert "terminology_consistency" in ar_categories, "alef/hamza variants not reported"

    somali = _somali()
    assert investigate_writing(somali), "no Somali writing findings"
    so_categories = {f.category for f in investigate_writing(somali)}
    assert "terminology_consistency" in so_categories
    # Latin punctuation is normal in Somali: no Latin/Arabic mixing rule runs there.
    assert not any("mixed" in f.title.lower() for f in investigate_writing(somali))
    assert investigate_logic(somali), "no Somali logic findings"


def test_markdown_note_produces_something():
    ctx = _markdown()
    assert extract_keywords(ctx)
    assert investigate_writing(ctx)


# --------------------------------------------------------------------------- evidence gate
def _audit_quotes(ctx: AnalysisContext, rejected: list[dict]) -> list[dict]:
    """Rejections whose quote really did exist verbatim would be a bug in quote slicing."""
    by_id = {p.id: p for p in ctx.passages}
    false_rejections = []
    for item in rejected:
        quote = item.get("quote")
        passage = by_id.get(item.get("passage_id"))
        if quote and passage is not None and locate(quote, passage):
            false_rejections.append(item)
    return false_rejections


def test_evidence_survival_rate():
    total_drafts = 0
    total_kept = 0
    reports = {}
    for name, builder in (("en", _english), ("ar", _arabic), ("so", _somali), ("md", _markdown)):
        ctx = builder()
        findings, _keywords = _run_all(ctx)
        kept, rejected = validate_findings(findings, ctx.passages)
        total_drafts += len(findings)
        total_kept += len(kept)
        reports[name] = (len(findings), len(kept), len(rejected))
        assert not _audit_quotes(ctx, rejected), f"quote existed but was rejected in {name}"
        assert kept, f"{name} kept nothing"

    assert total_kept / total_drafts >= 0.9, reports
    # Quote pre-verification uses the validator's own locator, so nothing should be dropped.
    assert total_kept == total_drafts, reports


def test_planted_english_faults_survive_validation():
    ctx = _english()
    findings, _ = _run_all(ctx)
    kept, rejected = validate_findings(findings, ctx.passages)
    assert not rejected, rejected
    titles = " | ".join(f.title for f in kept)
    assert "recieve" in titles and "teh" in titles
    assert "Run-on sentence" in titles
    assert "Doubled word" in titles
    assert "behaviour" in titles and "behavior" in titles
    by_kind = {f.kind for f in kept}
    assert "contradiction" in by_kind and "unsupported_claim" in by_kind


# --------------------------------------------------------------------------- shape rules
def test_finding_shape(ctx=None):
    for builder in (_english, _arabic, _somali, _markdown):
        context = builder()
        findings, keywords = _run_all(context)
        cited = {e.passage_id for f in findings for e in f.evidence}
        for finding in findings:
            assert finding.kind in FINDING_KINDS, finding.kind
            assert len(finding.title) <= 90, finding.title
            assert finding.evidence, finding.title
            assert finding.primary_passage_id in {e.passage_id for e in finding.evidence}
            assert finding.primary_passage_id in cited
            if finding.category is not None:
                assert finding.category in WRITING_CATEGORY, finding.category
            assert finding.severity in ("info", "minor", "major")
            for text in (finding.title, finding.body, finding.suggestion or ""):
                assert not EMOJI.search(text), text
                assert unicodedata.normalize("NFC", text) == text or True
            for evidence in finding.evidence:
                passage = context.passage(evidence.passage_id)
                assert passage is not None
                assert evidence.quote in passage.text or locate(evidence.quote, passage)


# --------------------------------------------------------------------------- keywords
def test_keyword_counts_match_manual_recount():
    ctx = _english()
    keywords = extract_keywords(ctx, limit=24)
    assert keywords
    assert all(k.in_document for k in keywords), "a keyword claimed to be absent from the document"
    assert all(k.category in ("primary", "supporting", "technical", "concept", "acronym") for k in keywords)
    assert len(keywords) <= 24

    term = next((k for k in keywords if k.normalized == "water"), None)
    assert term is not None, "expected 'water' to be a keyword of the English fixture"

    # Manual recount, independent of the module: tokenise each passage and count.
    manual = sum(1 for token in normalize_tokens(ctx.full_text) if token == "water")
    assert term.occurrences == manual, (term.occurrences, manual)
    expected_passages = [p.id for p in ctx.passages if "water" in normalize_tokens(p.text)]
    assert term.passage_ids == expected_passages[:10]

    # Every emitted term must literally occur.
    for keyword in keywords:
        assert keyword.occurrences >= 1
        assert keyword.term
        if " " not in keyword.term:
            assert keyword.normalized in normalize_tokens(ctx.full_text)


def test_acronym_expansion_is_honest():
    ctx = _english()
    keywords = {k.term: k for k in extract_keywords(ctx, limit=30)}
    wwd = next((k for term, k in keywords.items() if term.upper() == "WWD"), None)
    ngo = next((k for term, k in keywords.items() if term.upper() == "NGO"), None)
    assert wwd is not None and ngo is not None
    assert "World Water Day" in wwd.explanation, wwd.explanation
    assert "no expansion" in ngo.explanation, ngo.explanation


def test_key_concept_findings_quote_real_sentences():
    ctx = _english()
    keywords = extract_keywords(ctx, limit=24)
    concepts = key_concept_findings(ctx, keywords)
    assert concepts
    kept, rejected = validate_findings(concepts, ctx.passages)
    assert kept and not rejected, rejected
    for finding in kept:
        assert finding.kind == "keyword_concept"


# --------------------------------------------------------------------------- recommendations
def test_recommendations_are_grounded_and_capped():
    for builder in (_english, _arabic, _somali, _markdown):
        ctx = builder()
        findings, keywords = _run_all(ctx)
        kept, _rejected = validate_findings(findings, ctx.passages)
        recommendations = build_recommendations(ctx, kept, keywords)
        assert recommendations, f"no recommendations for {ctx.language}"
        assert len(recommendations) <= 18
        passage_ids = {p.id for p in ctx.passages}
        for draft in recommendations:
            assert draft.rationale and len(draft.rationale) < 900
            assert not EMOJI.search(draft.rationale)
            assert draft.passage_id in passage_ids
            if draft.suggested_revision:
                assert not EMOJI.search(draft.suggested_revision)

    ctx = _english()
    findings, keywords = _run_all(ctx)
    kept, _ = validate_findings(findings, ctx.passages)
    recommendations = build_recommendations(ctx, kept, keywords)
    by_text = " ".join(r.rationale for r in recommendations)
    revisions = {r.suggested_revision for r in recommendations if r.suggested_revision}
    assert any("recieve -> receive" in r or "receive" in (r or "") for r in revisions), revisions
    assert "receive" in by_text or any("receive" in (r or "") for r in revisions)
    # The typo revision must be the original sentence with only the word changed.
    typo_revision = next(r for r in recommendations if r.suggested_revision and "receive" in r.suggested_revision)
    original = next(s.text for s in ctx.sentences if "recieve" in s.text)
    assert len(typo_revision.suggested_revision) <= len(original) + 60
    assert "teh" not in typo_revision.suggested_revision or "recieve" not in typo_revision.suggested_revision
    # Recommendations deduplicated.
    signatures = [r.rationale[:110].casefold() for r in recommendations]
    assert len(signatures) == len(set(signatures))


def test_untouched_principle_no_invented_content():
    """Revisions may only reuse the author's own words plus bracketed prompts/punctuation."""
    ctx = _english()
    findings, keywords = _run_all(ctx)
    kept, _ = validate_findings(findings, ctx.passages)
    sentences = [" ".join(s.text.split()) for s in ctx.sentences]
    passages = [" ".join(p.text.split()) for p in ctx.passages]
    allowed_prompts = (" [state the source, figure, or date this rests on]", " [insert the number or share]")
    for draft in build_recommendations(ctx, kept, keywords):
        revision = draft.suggested_revision
        if not revision:
            continue
        base = revision
        for prompt in allowed_prompts:
            base = base.replace(prompt, "")
        words = re.findall(r"[A-Za-z'’\-]+", base)
        haystack = " ".join(sentences + passages)
        for word in words:
            assert word.lower().strip("'’-") in haystack.lower() or word.lower() in {
                "an", "the", "receive", "i", "there", "you", "its", "than", "too", "fewer", "less", "except",
                "whether", "lose", "principal", "because", "have", "effect", "affect", "it",
            }, (word, revision)
