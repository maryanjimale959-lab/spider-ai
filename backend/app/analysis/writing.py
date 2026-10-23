"""Writing investigation: language-aware, rule-based, dictionary-free.

Every rule inspects the document's own strings and quotes the offending span verbatim, so a
reader can see exactly what was noticed. Findings are written to be useful to a human author:
plain description of the issue, a practical fix, no mocking, no invented grammar "rules", and
no judgement of features that are normal for the language (Arabic is treated as unvowelled by
default; Latin punctuation in Somali text is correct and is never flagged).

Categories come from ``WRITING_CATEGORY`` in ``app/models.py``:
grammar, spelling, clarity, paragraph_structure, logical_flow, repetition, tone, vocabulary,
terminology_consistency, readability, audience_suitability, punctuation.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from app.analysis.evidence import locate
from app.analysis.language import ALL
from app.analysis.segmentation import (
    is_arabic_char,
    normalize_tokens,
    normalize_word,
    tokenize,
    word_length_units,
)
from app.analysis.types import AnalysisContext, DocPassage, EvidenceDraft, FindingDraft, Sentence

WRITING_KIND = "writing_issue"

# --------------------------------------------------------------------------- vocabularies
TYPOS: dict[str, str] = {
    "teh": "the", "adn": "and", "taht": "that", "thier": "their", "hte": "the", "wich": "which",
    "recieve": "receive", "recieved": "received", "recieving": "receiving", "reciept": "receipt",
    "seperate": "separate", "seperated": "separated", "seperateley": "separately",
    "definately": "definitely", "definate": "definite", "occured": "occurred",
    "occurence": "occurrence", "occurences": "occurrences", "accomodate": "accommodate",
    "accomodation": "accommodation", "acheive": "achieve", "acheived": "achieved",
    "knowlege": "knowledge", "goverment": "government", "governer": "governor",
    "enviroment": "environment", "enviromental": "environmental", "managment": "management",
    "bussiness": "business", "buisness": "business", "comittee": "committee",
    "arguement": "argument", "developement": "development", "embarass": "embarrass",
    "experiance": "experience", "exprience": "experience", "freind": "friend", "foriegn": "foreign",
    "happend": "happened", "imediately": "immediately", "emmediately": "immediately",
    "neccessary": "necessary", "necessery": "necessary", "sucessful": "successful",
    "succesful": "successful", "succsess": "success", "tounge": "tongue", "whant": "want",
    "becuase": "because", "becaue": "because", "becaus": "because", "alot": "a lot",
    "assingment": "assignment", "basicly": "basically", "beautifull": "beautiful",
    "betwen": "between", "beetwen": "between", "belive": "believe", "belived": "believed",
    "calender": "calendar", "changable": "changeable", "colledge": "college",
    "comander": "commander", "commited": "committed", "competation": "competition",
    "complecated": "complicated", "concious": "conscious", "controler": "controller",
    "correnspond": "correspond", "critism": "criticism", "decison": "decision",
    "descrition": "description", "difrence": "difference", "diffrent": "different",
    "dirctly": "directly", "discusion": "discussion", "efect": "effect", "eliment": "element",
    "equel": "equal", "excatly": "exactly", "exersize": "exercise", "extrem": "extreme",
    "familer": "familiar", "finacial": "financial", "forcast": "forecast", "fourty": "forty",
    "funtional": "functional", "furthur": "further", "gardenerne": "gardener",
    "gaurantee": "guarantee", "grammer": "grammar", "harrass": "harass", "heared": "heard",
    "helpfull": "helpful", "identicle": "identical", "inconvencient": "inconvenient",
    "independance": "independence", "infomation": "information", "innocentt": "innocent",
    "interresting": "interesting", "judment": "judgment", "labratory": "laboratory",
    "liason": "liaison", "libary": "library", "maintanance": "maintenance",
    "medeival": "medieval", "milennium": "millennium", "minature": "miniature",
    "mischevious": "mischievous", "mountian": "mountain", "musuim": "museum",
    "negociation": "negotiation", "occassion": "occasion", "offical": "official",
    "oportunity": "opportunity", "oppasite": "opposite", "paralel": "parallel",
    "particuliar": "particular", "pasttime": "pastime", "perscription": "prescription",
    "positon": "position", "possesion": "possession", "prefered": "preferred",
    "preffered": "preferred", "problably": "probably", "prominant": "prominent",
    "pronounciation": "pronunciation", "recomended": "recommended", "refered": "referred",
    "refering": "referring", "registation": "registration", "relevent": "relevant",
    "religous": "religious", "remeber": "remember", "remebered": "remembered",
    "repitition": "repetition", "reserch": "research", "shcedule": "schedule",
    "schedual": "schedule", "secretery": "secretary", "sieze": "seize", "similer": "similar",
    "sincerly": "sincerely", "sincierely": "sincerely", "soical": "social", "speach": "speech",
    "speciffic": "specific", "stament": "statement", "strenght": "strength",
    "substatial": "substantial", "sugget": "suggest", "superintendant": "superintendent",
    "surprize": "surprise", "tendicy": "tendency", "themselfs": "themselves",
    "tomatos": "tomatoes", "truely": "truly", "untill": "until", "vaccum": "vacuum",
    "vegatables": "vegetables", "vengence": "vengeance", "weild": "wield", "whlie": "while",
    "writting": "writing", "yeild": "yield", "wether": "whether", "anothe": "another",
    "becase": "because", "throug": "through", "throught": "thought", "alwways": "always",
    "realy": "really", "realyl": "really", "wiil": "will", "woild": "would", "ttest": "test",
}

AUX_EN = {
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "can", "could", "may", "might", "must", "am",
}
PARTICIPLES = {
    "done", "given", "seen", "known", "taken", "made", "kept", "left", "sent", "brought", "found",
    "built", "written", "shown", "understood", "spoken", "eaten", "driven", "gone", "come", "begun",
    "run", "thrown", "drawn", "grown", "flown", "beaten", "risen", "born", "torn", "worn",
}
IRREGULAR_VERBS = AUX_EN | PARTICIPLES | {
    "say", "said", "go", "goes", "went", "come", "came", "make", "made", "take", "took", "get",
    "got", "give", "gave", "know", "knew", "see", "saw", "find", "found", "keep", "kept", "leave",
    "left", "put", "bring", "brought", "think", "thought", "write", "wrote", "read", "run", "ran",
    "hold", "held", "stand", "stood", "win", "won", "show", "showed", "build", "built", "send",
    "sent", "tell", "told", "become", "became", "fall", "fell", "feel", "felt", "mean", "meant",
    "pay", "paid", "sit", "sat", "speak", "spoke", "steal", "stole", "teach", "taught", "wear",
    "wore", "work", "works", "provide", "provides", "require", "requires", "suggest", "suggests",
    "indicate", "indicates", "show", "shows", "state", "states", "remain", "remains", "exist",
    "exists", "include", "includes", "reduce", "reduces", "increase", "increases", "cost", "costs",
}
PASSIVE_MARKERS = r"\b(?:is|are|was|were|be|been|being)\b(?:\s+\w+ly)?\s+(\w+(?:ed|en|wn|den|ken|ght|ought))"
NOMINAL_SUFFIXES = ("tion", "sion", "ment", "ness", "ity", "ance", "ence")
HEDGES = (r"\b(?:may|might|could|perhaps|possibly|probably|appears|seems|suggests|indicates?|"
          r"seems?\s+to|it\s+appears|somewhat|relatively|tends?\s+to|usually|generally)\b")
ABSOLUTES = (r"\b(?:always|never|all|every|clearly|obviously|undeniably|certainly|definitely|"
             r"proves|guaranteed|guarantee|impossible|inevitable|without\s+doubt|complete)\b")
INFORMAL = (r"\b(?:a\s+lot\s+of|kind\s+of|sort\s+of|stuff|things|guys|kids|pretty\s+much|got|gotten|"
            r"big|huge|crazy|awesome|ok|okay|yeah|nope|gonna|wanna|lots\s+of|bit\s+of|nice)\b")
FORMAL = (r"\b(?:therefore|herein|hereby|pursuant|shall|furthermore|moreover|consequently|"
          r"it\s+is\s+recommended|the\s+undersigned|in\s+accordance|notwithstanding|whereas)\b")
CONTRACTIONS = r"\b[a-z]+(?:n't|'re|'ve|'ll|'d)\b"
VAGUE_QUANTIFIERS = (r"\b(?:some|several|many|a\s+lot\s+of|a\s+number\s+of|various|few|most|"
                     r"numerous|a\s+great\s+deal|plenty|lots)\b")

# (pattern, expected form, explanation) - each is chosen for high precision.
CONFUSABLES: list[tuple[str, str, str]] = [
    (r"\b(?:should|could|would|must|might)\s+of\b", "should have / could have / must have",
     "the auxiliary is followed by \"of\" instead of \"have\""),
    (r"\b(?:more|better|greater|less|other|rather|later|sooner|different)\s+then\b", "than",
     "a comparison uses \"then\" where \"than\" is required"),
    (r"\b(?:to|so)\s+(?:much|many|late|soon|bad|heavy|expensive|difficult|far)\b", "too",
     "\"to\" is used where the intensifier \"too\" is meant"),
    (r"\btheir\s+(?:is|are|was|were)\b", "there is / there are",
     "\"their\" is used where the existential \"there\" is required"),
    (r"\byour\s+(?:welcome|going|coming|right|wrong|able)\b", "you are / you're",
     "\"your\" is used where \"you are\" is meant"),
    (r"\bit's\s+(?:name|report|role|size|own|purpose|first|best|cost|use|time|future|history|"
     r"location|number|problem|responsibility|part|decision|price)\b", "its",
     "\"it's\" (it is) is used where the possessive \"its\" is required"),
    (r"\b(?:the|an|a|no|its|this)\s+affect\s+of\b", "effect",
     "\"affect\" is used as a noun where \"effect\" is required"),
    (r"\bwill\s+effect\s+(?:a\s+)?(?:change|changes|improvement|improvements|reduction)\b", "affect",
     "\"effect\" is used as a verb where \"affect\" is required"),
    (r"\bless\s+(?:people|students|children|schools|days|years|months|weeks|times|households|"
     r"families|cases|groups|villages|reports|pumps)\b", "fewer",
     "\"less\" is used before a plural count noun, where \"fewer\" is standard"),
    (r"\bfewer\s+(?:water|money|time|information|food|energy|equipment|space|traffic|effort)\b", "less",
     "\"fewer\" is used before an uncountable noun, where \"less\" is standard"),
    (r"\b(?:all|each|every|without)\s+accept\b", "except",
     "\"accept\" is used where the exclusion \"except\" is meant"),
    (r"\bweather\s+or\s+not\b|\bdepends?\s+on\s+weather\b", "whether",
     "\"weather\" is used where the alternative \"whether\" is meant"),
    (r"\bloose\s+(?:control|weight|money|time|the\s+ability)\b", "lose",
     "\"loose\" is used where the verb \"lose\" is meant"),
    (r"\bprinciple\s+(?:reason|role|cause|factor|advantage|characteristic|problem)\b", "principal",
     "\"principle\" (a rule) is used where \"principal\" (main) is meant"),
    (r"\b(?:on|in|the)\s+principal\s+(?:of|that|which)\b", "principle",
     "\"principal\" is used where \"principle\" is meant"),
    (r"\b(?:due\s+to\s+the\s+fact\s+that)\b", "because",
     "a wordy phrase stands where one conjunction would do"),
    (r"\b(?:currently\s+at\s+this\s+time|each\s+and\s+every|past\s+history|advance\s+planning)\b",
     "a single word", "two words say the same thing, so one is redundant"),
]

FRAGMENT_EXCLUDE = re.compile(r"^\s*(?:e\.g|i\.e|fig|table|note|see|ref|NB)\b", re.IGNORECASE)

ARABIC_HAMZA = {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ئ": "ي", "ؤ": "و"}
ARABIC_LATIN_PUNCT = re.compile(r"[,;:?!()]")
ARABIC_OWN_PUNCT = re.compile(r"[،؛؟]")
SOMALI_VARIANTS: list[tuple[str, str, str]] = [
    ("waxaa", "waxa", "the subject marker"),
    ("ayaa", "aya", "the focus marker"),
    ("iyo", "iyou", "the conjunction \"and\""),
    ("laakiin", "lakiin", "the conjunction \"but\""),
    ("soomaaliya", "somalia", "the country name"),
    ("maamulka", "mamulka", "the word for administration"),
    ("shaqaale", "shaqale", "the word for workers"),
    ("qorshaha", "qorshihii", "the word for the plan"),
]

SEVERITY_RANK = {"major": 0, "minor": 1, "info": 2}


# --------------------------------------------------------------------------- text helpers
def _stopwords(language: str) -> set[str]:
    return ALL.get(language) or set()


def _union_stopwords() -> set[str]:
    out: set[str] = set()
    for stop in ALL.values():
        out |= stop
    return out


def _content(text: str, language: str) -> list[str]:
    stop = _stopwords(language) or _union_stopwords()
    minimum = 2 if language == "ar" else 3
    return [t for t in normalize_tokens(text) if len(t) >= minimum and t not in stop and not t.isdigit()]


def _clamp(value: str, limit: int = 70) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[:limit]
    if " " in cut[limit - 15:]:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:.") + "..."


def _title(value: str) -> str:
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= 90 else _clamp(collapsed, 85)


def _has_finite_verb(tokens: list[str]) -> bool:
    for token in tokens:
        if token in IRREGULAR_VERBS:
            return True
        if len(token) >= 4 and token.endswith("ed"):
            return True
        if len(token) >= 5 and token.endswith("ing"):
            return True
        # Present-tense forms are indistinguishable from plurals without a dictionary, so any
        # s-final word counts as a possible verb. This makes the rule miss some real fragments
        # rather than accuse a correct sentence.
        if len(token) >= 4 and token.endswith("s"):
            return True
    return False


def _levenshtein(a: str, b: str, maximum: int = 2) -> int:
    if abs(len(a) - len(b)) > maximum:
        return maximum + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


# --------------------------------------------------------------------------- collector
class _Collector:
    def __init__(self, ctx: AnalysisContext) -> None:
        self.ctx = ctx
        self.items: list[tuple[int, int, FindingDraft]] = []
        self.keys: set[tuple[str, str]] = set()

    def add(
        self,
        category: str,
        title: str,
        body: str,
        quotes: list[tuple[str, str] | None],
        *,
        suggestion: str | None = None,
        severity: str = "minor",
        confidence: float = 0.75,
        extra: dict | None = None,
        order: int = 10 ** 6,
    ) -> None:
        evidence: list[EvidenceDraft] = []
        for item in quotes:
            if not item:
                continue
            passage_id, quote = item
            checked = self._verified(passage_id, quote)
            if checked is not None:
                evidence.append(checked)
        if not evidence:
            return
        key = (category, evidence[0].quote[:120].casefold(), title[:40])
        if key in self.keys:
            return
        self.keys.add(key)
        finding = FindingDraft(
            kind=WRITING_KIND,
            title=_title(title),
            body=" ".join(body.split()),
            evidence=evidence,
            primary_passage_id=evidence[0].passage_id,
            category=category,
            suggestion=suggestion,
            severity=severity,
            confidence=confidence,
            extra=extra or {},
        )
        self.items.append((SEVERITY_RANK.get(severity, 3), order, finding))

    def findings(self) -> list[FindingDraft]:
        return [finding for _rank, _order, finding in self.items]

    def _verified(self, passage_id: str, quote: str) -> EvidenceDraft | None:
        passage = self.ctx.passage(passage_id)
        if passage is None:
            return None
        for candidate in (" ".join(quote.split()).strip(), passage.text.strip()):
            if candidate and len(candidate) <= len(passage.text) and locate(candidate, passage) is not None:
                return EvidenceDraft(passage_id=passage.id, quote=candidate)
        return None


def _sentence_quotes(ctx: AnalysisContext, sentence: Sentence, span: str | None = None) -> tuple[str, str]:
    """Return (passage_id, quote). The span is used when it really occurs; else the sentence."""
    passage = ctx.passage(sentence.passage_id)
    if passage is not None and span:
        candidate = " ".join(span.split()).strip()
        if candidate and locate(candidate, passage) is not None:
            return passage.id, candidate
    return sentence.passage_id, " ".join(sentence.text.split()).strip()


# --------------------------------------------------------------------------- English rules
def _rule_doubled_words(collector: _Collector) -> None:
    ctx = collector.ctx
    pattern = re.compile(r"\b(\w{2,})\s+\1\b", re.IGNORECASE)
    allowed = {"had", "that", "what"}
    for sentence in ctx.sentences:
        passage = ctx.passage(sentence.passage_id)
        if passage is None:
            continue
        for match in pattern.finditer(sentence.text):
            word = match.group(1)
            if word.casefold() in allowed:
                continue
            if any(is_arabic_char(ch) for ch in word) and ctx.language == "ar":
                continue
            collector.add(
                "repetition",
                f"Doubled word: \"{word} {word}\"",
                f"The word \"{word}\" is written twice in a row with nothing between the two copies. "
                "This is almost always a typing slip rather than a deliberate repetition.",
                [_sentence_quotes(ctx, sentence, match.group(0))],
                suggestion=f"Delete one copy of \"{word}\".",
                severity="minor" if word.casefold() not in TYPOS else "major",
                confidence=0.9,
                extra={"occurrence": match.group(0), "fix": word},
                order=sentence.index,
            )


def _rule_typos(collector: _Collector) -> None:
    ctx = collector.ctx
    counts = Counter(t for t in normalize_tokens(ctx.full_text) if t in TYPOS)
    for sentence in ctx.sentences:
        for raw in tokenize(sentence.text):
            correct = TYPOS.get(normalize_word(raw))
            if not correct:
                continue
            times = counts[normalize_word(raw)]
            collector.add(
                "spelling",
                f"Spelling: \"{raw}\" should be \"{correct}\"",
                f"\"{raw}\" is a misspelling of \"{correct}\"; it occurs {times} time(s) in the document. "
                "Misspelled words are the fastest way for a reader to lose confidence in a document.",
                [_sentence_quotes(ctx, sentence, raw)],
                suggestion=f"Replace \"{raw}\" with \"{correct}\" everywhere it appears.",
                severity="major" if times >= 2 else "minor",
                confidence=0.9,
                extra={"occurrence": raw, "correction": correct, "times": times},
                order=sentence.index,
            )


def _rule_confusables(collector: _Collector) -> None:
    ctx = collector.ctx
    for pattern, expected, reason in CONFUSABLES:
        regex = re.compile(pattern, re.IGNORECASE)
        for sentence in ctx.sentences:
            for match in regex.finditer(sentence.text):
                collector.add(
                    "grammar",
                    f"Confused words: {_clamp(match.group(0), 40)}",
                    f"In this sentence {reason}. The text reads \"{_clamp(match.group(0), 40)}\" where "
                    f"\"{expected}\" is the standard form.",
                    [_sentence_quotes(ctx, sentence, match.group(0))],
                    suggestion=f"Rewrite \"{_clamp(match.group(0), 40)}\" as \"{expected}\".",
                    severity="minor",
                    confidence=0.85,
                    extra={"occurrence": match.group(0), "expected": expected},
                    order=sentence.index,
                )


def _rule_articles(collector: _Collector) -> None:
    ctx = collector.ctx
    vowel_sound_consonants = ("uni", "use", "used", "user", "uses", "usage", "eu", "one", "once",
                             "every", "united", "ultra", "urban", "urea")
    vowel_aspirate = ("honest", "honor", "honour", "hour", "heir", "honesty")
    regex = re.compile(r"\b(a|an|A|An)\s+([A-Za-z][A-Za-z'’\-]*)")
    for sentence in ctx.sentences:
        for match in regex.finditer(sentence.text):
            article, word = match.group(1), match.group(2)
            lowered = word.casefold()
            starts_vowel = lowered[0] in "aeiou"
            consonant_illusion = lowered.startswith(vowel_sound_consonants)
            if article.lower() == "a" and starts_vowel and not consonant_illusion:
                collector.add(
                    "grammar",
                    f"Article agreement: \"a {word}\"",
                    f"\"a\" stands before \"{word}\", which begins with a vowel sound, so \"an\" is expected.",
                    [_sentence_quotes(ctx, sentence, match.group(0))],
                    suggestion=f"Write \"an {word}\".",
                    confidence=0.8,
                    extra={"occurrence": match.group(0), "expected": f"an {word}"},
                    order=sentence.index,
                )
            elif article.lower() == "an" and not starts_vowel and not lowered.startswith(vowel_aspirate):
                collector.add(
                    "grammar",
                    f"Article agreement: \"an {word}\"",
                    f"\"an\" stands before \"{word}\", which begins with a consonant sound, so \"a\" is expected.",
                    [_sentence_quotes(ctx, sentence, match.group(0))],
                    suggestion=f"Write \"a {word}\".",
                    confidence=0.8,
                    extra={"occurrence": match.group(0), "expected": f"a {word}"},
                    order=sentence.index,
                )


def _rule_fragments(collector: _Collector) -> None:
    ctx = collector.ctx
    for sentence in ctx.sentences:
        passage = ctx.passage(sentence.passage_id)
        if passage is None or passage.is_heading or passage.kind == "list_item":
            continue
        if FRAGMENT_EXCLUDE.search(sentence.text):
            continue
        if re.search(r"[?:]$", sentence.text.strip()):
            continue
        tokens = normalize_tokens(sentence.text)
        if len(tokens) < 6 or _has_finite_verb(tokens):
            continue
        collector.add(
            "grammar",
            f"Sentence without a main verb ({len(tokens)} words)",
            "This sentence has no verbal word in it: nothing states what the subject does or is. A reader has "
            "to attach it to a neighbouring sentence to find the claim.",
            [_sentence_quotes(ctx, sentence)],
            suggestion="Add the verb that says what happens, or join this fragment to the sentence before it.",
            severity="minor",
            confidence=0.6,
            extra={"words": len(tokens)},
            order=sentence.index,
        )


def _rule_run_ons(collector: _Collector) -> None:
    ctx = collector.ctx
    coordinator = re.compile(r"\s*,?\s+(?:and|but|so|then|while|because|which|that)\s+", re.IGNORECASE)
    splice = re.compile(
        r",\s+(?:I|we|you|he|she|they|it|this|these|the\s+\w+|our|their|his|her)\s+"
        r"(?:was|were|had|has|have|did|does|went|came|made|said|got|gave|took|knew|told|saw|found|"
        r"decided|approved|visited|checked|signed|refused|asked|noted|issued)\b",
        re.IGNORECASE,
    )
    for sentence in ctx.sentences:
        passage = ctx.passage(sentence.passage_id)
        if passage is None or passage.is_heading:
            continue
        words = tokenize(sentence.text)
        segments = coordinator.split(sentence.text)
        finite = sum(1 for segment in segments if _has_finite_verb(normalize_tokens(segment)))
        conjunction = coordinator.search(sentence.text)
        conjunction_text = _clamp(conjunction.group(0), 12).strip() if conjunction else "and"
        if finite >= 3 and len(words) >= 22 and len(sentence.text) > 120:
            collector.add(
                "clarity",
                f"Run-on sentence ({len(words)} words, {finite} clauses)",
                f"This single sentence strings together {finite} clauses with \"{conjunction_text}\" "
                "and no full stop between them. Each clause states something separate, so the reader has to hold "
                "all of them at once.",
                [_sentence_quotes(ctx, sentence)],
                suggestion=(
                    "Break it at the conjunctions: put a full stop after the first completed statement and start "
                    "the next sentence with the new subject. Keep one claim per sentence."
                ),
                severity="major" if len(words) >= 40 else "minor",
                confidence=0.75,
                extra={"words": len(words), "clauses": finite},
                order=sentence.index,
            )
            continue
        match = splice.search(sentence.text)
        if match and len(words) >= 14:
            collector.add(
                "punctuation",
                f"Comma splice near \"{_clamp(match.group(0), 30)}\"",
                "Two complete statements are joined by a comma only. Each side could stand as its own sentence, "
                "so the comma understates the break.",
                [_sentence_quotes(ctx, sentence, match.group(0))],
                suggestion="Replace that comma with a full stop, or add a conjunction such as \"and\" or \"because\".",
                severity="minor",
                confidence=0.7,
                extra={"occurrence": match.group(0)},
                order=sentence.index,
            )


def _rule_punctuation_spacing(collector: _Collector) -> None:
    ctx = collector.ctx
    space_before = re.compile(r"(\S)\s+([,.;:!?])")
    for sentence in ctx.sentences:
        match = space_before.search(sentence.text)
        if match:
            collector.add(
                "punctuation",
                f"Space before \"{match.group(2)}\"",
                f"A space sits before the \"{match.group(2)}\" in \"{_clamp(match.group(0), 30)}\", which makes the "
                "pause read as if it belongs to the next word.",
                [_sentence_quotes(ctx, sentence, match.group(0))],
                suggestion=f"Remove the space so the \"{match.group(2)}\" follows its word directly.",
                severity="minor",
                confidence=0.9,
                extra={"occurrence": match.group(0)},
                order=sentence.index,
            )
    for passage in ctx.body_passages():
        if passage.kind not in ("paragraph",):
            continue
        text = passage.text.rstrip()
        if len(text) < 40 or text.endswith((".", "!", "?", ":", "؛", "؟", "۔", ")", "”")):
            continue
        collector.add(
            "punctuation",
            f"Paragraph does not end with a full stop ({len(text.split())} words)",
            "The last sentence of this paragraph has no ending punctuation, so the reader cannot tell whether "
            "the text was cut short or simply left unmarked.",
            [(_verified_passage(passage) or (passage.id, passage.text.strip()))],
            suggestion="Add a full stop at the end of the sentence.",
            severity="minor",
            confidence=0.85,
            extra={"last_characters": text[-25:]},
            order=passage.char_start,
        )


def _verified_passage(passage: DocPassage) -> tuple[str, str] | None:
    collapsed = " ".join(passage.text.split()).strip()
    if collapsed and locate(collapsed, passage) is not None:
        return passage.id, collapsed
    return None


def _rule_lowercase_i(collector: _Collector) -> None:
    ctx = collector.ctx
    regex = re.compile(r"(?<![A-Za-z'])i(?![A-Za-z'])")
    for sentence in ctx.sentences:
        match = regex.search(sentence.text)
        if match:
            collector.add(
                "grammar",
                "Lowercase \"i\" used as a pronoun",
                "The first-person pronoun is written as \"i\" in lowercase. In English writing this reads as "
                "an unfinished correction rather than a stylistic choice.",
                [_sentence_quotes(ctx, sentence, sentence.text[max(0, match.start() - 20):match.end() + 20])],
                suggestion="Write \"I\" whenever it refers to the writer.",
                severity="minor",
                confidence=0.9,
                extra={"occurrence": "i"},
                order=sentence.index,
            )


def _rule_sentence_start_repetition(collector: _Collector) -> None:
    ctx = collector.ctx
    grouped: dict[str, list[Sentence]] = defaultdict(list)
    for sentence in ctx.sentences:
        grouped[sentence.passage_id].append(sentence)
    run: list[tuple[str, list[Sentence]]] = []
    for sentence in ctx.sentences:
        first = normalize_word(tokenize(sentence.text)[0]) if tokenize(sentence.text) else ""
        if run and run[-1][0] == first:
            run[-1][1].append(sentence)
        else:
            run.append((first, [sentence]))
        if len(run[-1][1]) >= 3:
            sentences = run[-1][1]
            collector.add(
                "repetition",
                f"Three consecutive sentences start with \"{sentences[0].text.split()[0]}\"",
                "The openings of consecutive sentences repeat the same word, which makes the paragraph read as "
                "a list of separate statements instead of a connected argument.",
                [_sentence_quotes(ctx, sentences[0]), _sentence_quotes(ctx, sentences[-1])],
                suggestion="Start at least one of them with the thing being discussed, or with the reason or "
                           "result that links it to the previous sentence.",
                severity="minor",
                confidence=0.7,
                extra={"start": first, "count": len(sentences)},
                order=sentence.index,
            )
            run = []


def _rule_passive(collector: _Collector) -> None:
    ctx = collector.ctx
    regex = re.compile(PASSIVE_MARKERS, re.IGNORECASE)
    hits: list[Sentence] = []
    for sentence in ctx.sentences:
        passage = ctx.passage(sentence.passage_id)
        if passage is None or passage.is_heading:
            continue
        if regex.search(sentence.text):
            hits.append(sentence)
    headings = {p.id for p in ctx.passages if p.is_heading}
    body = [s for s in ctx.sentences if s.passage_id not in headings]
    if len(hits) >= 4 and body and len(hits) / len(body) >= 0.28:
        ratio = round(100 * len(hits) / len(body))
        collector.add(
            "readability",
            f"Passive constructions in about {ratio}% of sentences",
            f"{len(hits)} of {len(body)} sentences put the action before the actor using a passive form "
            "(\"was approved\", \"were installed\"). The reader then has to look for who acted, and sometimes "
            "the document never says.",
            [_sentence_quotes(ctx, hits[0]), _sentence_quotes(ctx, hits[-1])],
            suggestion="For the key statements, name the actor first: \"the council approved\" instead of "
                       "\"it was approved\".",
            severity="minor",
            confidence=0.7,
            extra={"passive_sentences": len(hits), "sentences": len(body), "percent": ratio},
            order=hits[0].index,
        )


def _rule_nominalisation(collector: _Collector) -> None:
    ctx = collector.ctx
    stop = _stopwords(ctx.language)
    tokens = [t for t in _content(ctx.full_text, ctx.language)]
    nominal = [t for t in tokens if t.endswith(NOMINAL_SUFFIXES) and len(t) >= 7]
    if len(nominal) >= 12 and tokens and len(nominal) / len(tokens) >= 0.11:
        top = Counter(nominal).most_common(4)
        example = None
        for sentence in ctx.sentences:
            if any(word in normalize_tokens(sentence.text) for word, _c in top):
                example = sentence
                break
        if example is not None:
            collector.add(
                "vocabulary",
                f"Abstract nouns carry {round(100 * len(nominal) / len(tokens))}% of the content words",
                f"Nouns built from verbs (\"{top[0][0]}\", \"{top[1][0]}\") dominate the wording. Turning actions "
                "into nouns removes the actor and lengthens every sentence.",
                [_sentence_quotes(ctx, example)],
                suggestion="Replace two or three of these nouns with the verb they came from: "
                           "\"makes an assessment of\" becomes \"assesses\".",
                severity="minor",
                confidence=0.6,
                extra={"nominalisations": len(nominal), "content_words": len(tokens),
                       "examples": [w for w, _c in top]},
                order=example.index,
            )


def _rule_register(collector: _Collector) -> None:
    ctx = collector.ctx
    formal = re.compile(FORMAL, re.IGNORECASE)
    informal = re.compile(INFORMAL, re.IGNORECASE)
    contracted = re.compile(CONTRACTIONS)
    exclaims = 0
    formal_hits, informal_hits = [], []
    for sentence in ctx.sentences:
        if formal.search(sentence.text):
            formal_hits.append(sentence)
        if informal.search(sentence.text) or contracted.search(sentence.text):
            informal_hits.append(sentence)
        exclaims += sentence.text.count("!")
    if len(formal_hits) >= 2 and len(informal_hits) >= 1:
        collector.add(
            "tone",
            "Formal and informal wording mixed",
            "The document uses report language such as \"shall\" or \"therefore\" but also conversational wording "
            "and contractions. Mixed registers make it unclear who the document is written for.",
            [_sentence_quotes(ctx, informal_hits[0]), _sentence_quotes(ctx, formal_hits[0])],
            suggestion="Choose one register. For a report, write contractions out (\"can't\" to \"cannot\") and "
                       "replace casual words with the precise term.",
            severity="minor",
            confidence=0.65,
            extra={"formal_sentences": len(formal_hits), "informal_sentences": len(informal_hits)},
            order=min(s.index for s in informal_hits),
        )
    if len(informal_hits) >= 3 and not formal_hits and ctx.title:
        collector.add(
            "audience_suitability",
            "Conversational wording in a titled document",
            f"{len(informal_hits)} sentences use conversational wording (contractions or vague everyday words) "
            "and no formal connective appears anywhere. The document carries a title, so the reader expects "
            "a consistent register.",
            [_sentence_quotes(ctx, informal_hits[0])],
            suggestion="Name the reader (decision maker, community, funder) and replace everyday words with the "
                       "terms that reader uses.",
            severity="minor",
            confidence=0.55,
            extra={"informal_sentences": len(informal_hits)},
            order=informal_hits[0].index,
        )
    if exclaims >= 2:
        first = next((s for s in ctx.sentences if "!" in s.text), None)
        if first is not None:
            collector.add(
                "tone",
                f"{exclaims} exclamation mark(s) in the text",
                "Exclamation marks express the author's feeling rather than the strength of the statement. In an "
                "investigative document the figure or the evidence does that job.",
                [_sentence_quotes(ctx, first)],
                suggestion="Replace each exclamation mark with a full stop and state what makes the point important.",
                severity="minor",
                confidence=0.6,
                extra={"count": exclaims},
                order=first.index,
            )


def _rule_hedges_absolutes(collector: _Collector) -> None:
    ctx = collector.ctx
    hedge_re = re.compile(HEDGES, re.IGNORECASE)
    absolute_re = re.compile(ABSOLUTES, re.IGNORECASE)
    hedged = [s for s in ctx.sentences if hedge_re.search(s.text)]
    absolute = [s for s in ctx.sentences if absolute_re.search(s.text) and not hedge_re.search(s.text)]
    if absolute and len(hedged) >= 2:
        collector.add(
            "tone",
            f"{len(absolute)} unqualified claim(s) against {len(hedged)} cautious ones",
            "Some sentences state outcomes without any qualification (\"always\", \"all\", \"proves\") while others "
            "carefully hedge (\"may\", \"suggests\"). The document therefore reads as certain in exactly the places "
            "where it has admitted it is not.",
            [_sentence_quotes(ctx, absolute[0]), _sentence_quotes(ctx, hedged[0])],
            suggestion="Match the strength of the wording to the strength of what the document actually shows.",
            severity="minor",
            confidence=0.6,
            extra={"absolute": len(absolute), "hedged": len(hedged)},
            order=absolute[0].index,
        )
    if len(hedged) >= 6 and ctx.sentences:
        share = round(100 * len(hedged) / len(ctx.sentences))
        collector.add(
            "clarity",
            f"{share}% of sentences are hedged",
            f"{len(hedged)} sentences soften their statement (\"may\", \"appears\", \"possibly\"). When almost every "
            "claim is qualified the reader cannot tell what the document actually concludes.",
            [_sentence_quotes(ctx, hedged[0]), _sentence_quotes(ctx, hedged[-1])],
            suggestion="Keep the hedge only where the evidence really is incomplete; state the rest plainly.",
            severity="minor",
            confidence=0.55,
            extra={"hedged": len(hedged), "percent": share},
            order=hedged[0].index,
        )


# Surfaces that must be paired explicitly because suffix rules cannot reach them.
EXPLICIT_VARIANTS: dict[str, str] = {
    "centre": "center", "centres": "centers", "metre": "meter", "metres": "meters",
    "litre": "liter", "litres": "liters", "fibre": "fiber", "fibres": "fibers",
    "colour": "color", "colourful": "colorful", "manoeuvre": "maneuver",
    "programme": "program", "catalogue": "catalog", "dialogue": "dialog",
    "practise": "practice", "licence": "license", "defence": "defense", "offence": "offense",
    "travelling": "traveling", "cancelled": "canceled", "fulfil": "fulfill", "instalment": "installment",
    "skilful": "skillful", "judgement": "judgment", "acknowledgement": "acknowledgment",
}


def _variant_key(word: str) -> str:
    """Canonical spelling key so British/American variants collapse onto one entry."""
    if word in EXPLICIT_VARIANTS:
        return EXPLICIT_VARIANTS[word]
    out = word
    for suffix, replacement in (
        ("isation", "ization"), ("ised", "ized"), ("ises", "izes"), ("ise", "ize"),
        ("yses", "yzes"), ("yse", "yze"), ("our", "or"), ("logue", "log"),
    ):
        if out.endswith(suffix) and len(out) - len(suffix) >= 3:
            out = out[: -len(suffix)] + replacement
            break
    return out


def _tail_variants(first: str, second: str) -> bool:
    """True when the two spellings differ only near the end of the word."""
    longer = max(len(first), len(second))
    common = 0
    for a, b in zip(first, second):
        if a != b:
            break
        common += 1
    return common >= longer - 3


def _rule_terminology_variants(collector: _Collector) -> None:
    ctx = collector.ctx
    counts = Counter(_content(ctx.full_text, ctx.language))
    qualifying = {w: c for w, c in counts.items() if c >= 2 and len(w) >= 5}
    by_key: dict[str, list[str]] = defaultdict(list)
    for word in qualifying:
        by_key[_variant_key(word)].append(word)
    reported = 0
    for _key, words in sorted(by_key.items()):
        if reported >= 5:
            break
        if len(words) < 2:
            continue
        words = sorted(words, key=lambda w: -qualifying[w])
        first, second = words[0], words[1]
        if _levenshtein(first, second, 2) > 2 or not _tail_variants(first, second):
            continue
        quotes: list[tuple[str, str] | None] = []
        order: int | None = None
        for sentence in ctx.sentences:
            tokens = normalize_tokens(sentence.text)
            for word in (first, second):
                if word in tokens and len(quotes) < 2:
                    if not any(q and q[0] == sentence.passage_id and word in q[1] for q in quotes):
                        quotes.append(_sentence_quotes(ctx, sentence, word))
                        if order is None:
                            order = sentence.index
        if len(quotes) < 2:
            continue
        collector.add(
            "terminology_consistency",
            f"Same term spelled two ways: \"{first}\" and \"{second}\"",
            f"The document uses both \"{first}\" ({qualifying[first]} time(s)) and \"{second}\" "
            f"({qualifying[second]} time(s)). Neither spelling is wrong on its own; using both in one document "
            "makes the reader wonder whether two different things are meant.",
            quotes,
            suggestion=f"Pick one form - \"{first}\" is the more frequent here - and use it throughout.",
            severity="minor",
            confidence=0.8,
            extra={"variants": {first: qualifying[first], second: qualifying[second]},
                   "preferred": first},
            order=order if order is not None else 10 ** 6,
        )
        reported += 1


def _rule_near_duplicates(collector: _Collector) -> None:
    """Edit-distance 1-2 word pairs that both occur twice or more: possible split spelling."""
    ctx = collector.ctx
    counts = Counter(_content(ctx.full_text, ctx.language))
    qualifying = sorted(w for w, c in counts.items() if c >= 2 and len(w) >= 5)
    reported = 0
    for i, first in enumerate(qualifying):
        if reported >= 4:
            break
        for second in qualifying[i + 1:]:
            if abs(len(first) - len(second)) > 2:
                continue
            if _levenshtein(first, second, 2) > 2 or not _tail_variants(first, second):
                continue
            if _variant_key(first) != _variant_key(second) and not (
                    first.endswith("ing") or second.endswith("ing")
                    or first.endswith("ed") or second.endswith("ed")):
                continue
            quotes: list[tuple[str, str] | None] = []
            order: int | None = None
            for sentence in ctx.sentences:
                tokens = normalize_tokens(sentence.text)
                for word in (first, second):
                    if word in tokens and len(quotes) < 2 and not any(q and word in q[1] for q in quotes):
                        quotes.append(_sentence_quotes(ctx, sentence, word))
                        if order is None:
                            order = sentence.index
            if len(quotes) < 2:
                continue
            collector.add(
                "terminology_consistency",
                f"Two close spellings: \"{first}\" / \"{second}\"",
                f"\"{first}\" occurs {counts[first]} time(s) and \"{second}\" occurs {counts[second]} time(s); "
                "they differ by one or two letters. If the document means the same term both times, the spelling "
                "should be unified; if the two words mean different things, they are fine as they are.",
                quotes,
                suggestion="Check the two quoted uses: if they name the same thing, keep the form that appears "
                           "more often and change the other occurrences.",
                severity="minor",
                confidence=0.5,
                extra={"pair": [first, second], "counts": {first: counts[first], second: counts[second]}},
                order=order if order is not None else 10 ** 6,
            )
            reported += 1
            break


def _rule_readability(collector: _Collector) -> None:
    ctx = collector.ctx
    language = ctx.language
    words: list[str] = []
    units = 0.0
    for sentence in ctx.sentences:
        tokens = tokenize(sentence.text)
        words.extend(tokens)
        units += sum(word_length_units(t, language) for t in tokens)
    sentence_count = len(ctx.sentences)
    if not words or sentence_count < 2:
        return
    asl = len(words) / sentence_count
    asu = units / len(words)
    score = 206.835 - 1.015 * asl - 84.6 * asu
    longest = max(ctx.sentences, key=lambda s: len(tokenize(s.text)))
    score_label = ("hard to read" if score < 30 else
                   "moderately hard to read" if score < 50 else
                   "fairly easy to read")
    proxy = ("word length is used as a stand-in for syllable count, which is the usual approximation for "
             "non-Latin text" if language != "en" else "syllable count is estimated from the vowel groups")
    quotes = [_sentence_quotes(ctx, longest)]
    collector.add(
        "readability",
        f"Reading-ease estimate {round(score, 1)} on the 0-100 Flesch scale",
        f"Computed from this document's own numbers: {len(words)} word(s) in {sentence_count} sentence(s), "
        f"so {round(asl, 1)} words per sentence and {round(asu, 2)} length units per word ({proxy}). "
        f"The Flesch reading-ease formula gives {round(score, 1)} out of 100, which is {score_label}. "
        "The figure describes the prose, not the writer, and it moves only when sentence length or word "
        "length changes.",
        quotes,
        suggestion="Shorten the longest sentences and replace long derived words with plain verbs; sentence length "
                   "is the lever that moves this figure fastest.",
        severity="info" if score >= 30 else "minor",
        confidence=0.9,
        extra={"flesch_like": round(score, 1), "mean_sentence_words": round(asl, 2),
               "mean_units_per_word": round(asu, 2), "words": len(words), "sentences": sentence_count,
               "longest_sentence_words": len(tokenize(longest.text))},
        order=longest.index,
    )


def _rule_long_sentences(collector: _Collector) -> None:
    ctx = collector.ctx
    threshold = 45 if ctx.language != "ar" else 40
    flagged = 0
    for sentence in ctx.sentences:
        passage = ctx.passage(sentence.passage_id)
        if passage is None or passage.is_heading:
            continue
        words = tokenize(sentence.text)
        if len(words) < threshold or flagged >= 6:
            continue
        flagged += 1
        collector.add(
            "clarity",
            f"Sentence of {len(words)} words",
            f"This sentence runs to {len(words)} words. Everything after the first clause has to be held in memory "
            "before the reader reaches the point of the sentence.",
            [_sentence_quotes(ctx, sentence)],
            suggestion="Cut it into two or three sentences, one statement each, keeping the author's order.",
            severity="minor" if len(words) < 60 else "major",
            confidence=0.8,
            extra={"words": len(words)},
            order=sentence.index,
        )


def _rule_paragraph_structure(collector: _Collector) -> None:
    ctx = collector.ctx
    body = [p for p in ctx.body_passages() if p.kind in ("paragraph", "list_item")]
    grouped: dict[str, list[Sentence]] = defaultdict(list)
    for sentence in ctx.sentences:
        grouped[sentence.passage_id].append(sentence)
    single = [p for p in body if p.kind == "paragraph" and len(grouped.get(p.id, [])) == 1]
    if len(single) >= 2:
        collector.add(
            "paragraph_structure",
            f"{len(single)} paragraph(s) of one sentence",
            "Several paragraphs contain only a single sentence. Each one announces a point and then stops, so the "
            "reader gets a sequence of headings with no development under them.",
            [(_verified_passage(single[0]) or (single[0].id, single[0].text))],
            suggestion="Group one-sentence paragraphs with the paragraph that explains them, or add the reason, "
                       "example, or figure that the sentence claims.",
            severity="minor",
            confidence=0.7,
            extra={"single_sentence_paragraphs": len(single)},
            order=single[0].char_start,
        )
    walls = [p for p in body if len(p.text.split()) > 250]
    for wall in walls[:2]:
        collector.add(
            "paragraph_structure",
            f"Block of {len(wall.text.split())} words without a break",
            "This passage runs past 250 words with no paragraph or heading break inside it, so the reader has no "
            "place to stop and no way to find a point again later.",
            [(_verified_passage(wall) or (wall.id, wall.text))],
            suggestion="Split it where the topic changes and give the new part a short heading.",
            severity="major",
            confidence=0.8,
            extra={"words": len(wall.text.split())},
            order=wall.char_start,
        )


def _rule_logical_flow(collector: _Collector) -> None:
    ctx = collector.ctx
    body = [p for p in ctx.body_passages() if p.kind == "paragraph" and len(_content(p.text, ctx.language)) >= 5]
    pairs: list[tuple[DocPassage, DocPassage, int, int]] = []
    for previous, current in zip(body, body[1:]):
        before = set(_content(previous.text, ctx.language))
        after = set(_content(current.text, ctx.language))
        if not (before & after):
            shared_previous = len(before)
            pairs.append((previous, current, shared_previous, len(after)))
    if not pairs:
        return
    previous, current, shared_previous, _after = pairs[0]
    collector.add(
        "logical_flow",
        f"{len(pairs)} paragraph change(s) with no shared term",
        f"This paragraph and the one before it share no content word at all ({shared_previous} content word(s) in "
        "the first, in the second none of them reappear). Nothing in the wording tells the reader why the "
        "discussion moved here.",
        [_verified_passage(previous), _verified_passage(current)],
        suggestion="Open the second paragraph by naming what links it to the first, or move it under the heading "
                   "it belongs to.",
        severity="minor",
        confidence=0.6,
        extra={"disconnected_pairs": len(pairs)},
        order=current.char_start,
    )


def _rule_repetition(collector: _Collector) -> None:
    ctx = collector.ctx
    tokens = _content(ctx.full_text, ctx.language)
    if not tokens:
        return
    counts = Counter(tokens)
    total = len(tokens)
    top_word, top_count = counts.most_common(1)[0]
    if top_count >= 8 and top_count / total >= 0.02:
        sentences = [s for s in ctx.sentences if top_word in normalize_tokens(s.text)]
        collector.add(
            "repetition",
            f"\"{top_word}\" used {top_count} times",
            f"\"{top_word}\" is by far the most frequent content word: {top_count} of {total} content words, "
            f"spread over {len(sentences)} sentence(s). When one word carries that much of the text, sentences "
            "start to repeat themselves in wording even when they differ in content.",
            [_sentence_quotes(ctx, sentences[0]), _sentence_quotes(ctx, sentences[-1])] if len(sentences) > 1
            else [_sentence_quotes(ctx, sentences[0])],
            suggestion="Check the sentences where it appears twice within one paragraph: some can name the same "
                       "thing more specifically, others can be merged.",
            severity="minor",
            confidence=0.65,
            extra={"term": top_word, "occurrences": top_count, "content_words": total},
            order=sentences[0].index,
        )
    grams: Counter = Counter()
    for sentence in ctx.sentences:
        norm = _content(sentence.text, ctx.language)
        for size in (3, 4):
            for start in range(max(len(norm) - size + 1, 0)):
                grams[" ".join(norm[start: start + size])] += 1
    repeated = [(g, c) for g, c in grams.most_common(8) if c >= 3]
    if repeated:
        phrase, hits = repeated[0]
        example = next((s for s in ctx.sentences if phrase in " ".join(_content(s.text, ctx.language))), None)
        if example is not None:
            collector.add(
                "repetition",
                f"Phrase repeated {hits} times: {_clamp(phrase, 45)}",
                f"The same {len(phrase.split())}-word sequence recurs {hits} times. A fixed phrase used that often "
                "usually means several sentences are making one point.",
                [_sentence_quotes(ctx, example)],
                suggestion="Keep the phrase for the key statements; reword the others or drop them.",
                severity="minor",
                confidence=0.6,
                extra={"phrase": phrase, "occurrences": hits},
                order=example.index,
            )


def _rule_within_sentence_repetition(collector: _Collector) -> None:
    ctx = collector.ctx
    for sentence in ctx.sentences:
        words = _content(sentence.text, ctx.language)
        counts = Counter(words)
        if len(words) < 6:
            continue
        word, hits = counts.most_common(1)[0]
        if hits >= 3 and word not in TYPOS:
            collector.add(
                "vocabulary",
                f"\"{word}\" three or more times in one sentence",
                f"This sentence uses \"{word}\" {hits} times. The reader loses track of which instance is meant, "
                "and the sentence reads as circular.",
                [_sentence_quotes(ctx, sentence)],
                suggestion="Keep the first use, then refer to it with a shorter label (\"it\", \"this\", the "
                           "specific sub-type being discussed).",
                severity="minor",
                confidence=0.65,
                extra={"term": word, "times": hits},
                order=sentence.index,
            )
            break


def _rule_audience_acronyms(collector: _Collector) -> None:
    ctx = collector.ctx
    acronyms: dict[str, int] = {}
    for raw in tokenize(ctx.full_text):
        if re.fullmatch(r"[A-Z]{2,6}", raw):
            acronyms[raw] = acronyms.get(raw, 0) + 1
    if len(acronyms) >= 3:
        first_acronym = max(acronyms, key=lambda a: acronyms[a])
        example = next((s for s in ctx.sentences if re.search(rf"\b{first_acronym}\b", s.text)), None)
        if example is not None:
            collector.add(
                "audience_suitability",
                f"{len(acronyms)} acronyms used without spelling out",
                f"The document uses {len(acronyms)} different uppercase abbreviations "
                f"({', '.join(list(acronyms)[:6])}). A reader outside the team will not know what they stand for, "
                "and the abbreviations quietly become the argument.",
                [_sentence_quotes(ctx, example, first_acronym)],
                suggestion="Write each abbreviation out in full the first time it appears, then use the short form.",
                severity="minor",
                confidence=0.6,
                extra={"acronyms": acronyms},
                order=example.index,
            )


# --------------------------------------------------------------------------- Arabic rules
def _rule_arabic_punctuation_mix(collector: _Collector) -> None:
    ctx = collector.ctx
    latin = [m.group(0) for s in ctx.sentences for m in ARABIC_LATIN_PUNCT.finditer(s.text)]
    own = [m.group(0) for s in ctx.sentences for m in ARABIC_OWN_PUNCT.finditer(s.text)]
    if len(latin) >= 3 and len(own) >= 1:
        example = next((s for s in ctx.sentences if ARABIC_LATIN_PUNCT.search(s.text)), None)
        if example is not None:
            collector.add(
                "punctuation",
                f"Latin punctuation mixed with Arabic punctuation ({len(latin)} vs {len(own)})",
                "The text switches between Latin marks ( , . ; ? ) and Arabic marks ( ، ؛ ؟ ) in the same document. "
                "Mixed punctuation breaks the flow of right-to-left reading and can make a list separator look like "
                "a sentence end.",
                [_sentence_quotes(ctx, example)],
                suggestion="Choose Arabic punctuation for the Arabic text and use it consistently.",
                severity="minor",
                confidence=0.8,
                extra={"latin_marks": len(latin), "arabic_marks": len(own)},
                order=example.index,
            )


def _hamza_canonical(word: str) -> str:
    return "".join(ARABIC_HAMZA.get(ch, ch) for ch in word)


def _diff_chars(a: str, b: str) -> set[tuple[str, str]]:
    if len(a) != len(b):
        return set()
    return {(x, y) for x, y in zip(a, b) if x != y}


def _rule_arabic_script_variants(collector: _Collector) -> None:
    ctx = collector.ctx
    counts = Counter(_content(ctx.full_text, "ar"))
    by_canonical: dict[str, list[str]] = defaultdict(list)
    for word in counts:
        if len(word) < 4:
            continue
        by_canonical[_hamza_canonical(word)].append(word)
    reported = 0
    for _key, words in sorted(by_canonical.items()):
        if reported >= 4:
            break
        if len(words) < 2:
            continue
        words = sorted(words, key=lambda w: -counts[w])
        first, second = words[0], words[1]
        differences = _diff_chars(first, second)
        if not differences:
            continue
        # Only report pairs that differ exclusively in hamza / ta marbuta / alif maksura spelling.
        if all(_hamza_canonical(x) == _hamza_canonical(y) for x, y in differences):
            quotes: list[tuple[str, str] | None] = []
            order: int | None = None
            for sentence in ctx.sentences:
                tokens = normalize_tokens(sentence.text)
                for word in (first, second):
                    if word in tokens and len(quotes) < 2 and not any(
                            q and word in q[1] for q in quotes):
                        quotes.append(_sentence_quotes(ctx, sentence, word))
                        if order is None:
                            order = sentence.index
            if len(quotes) < 2:
                continue
            collector.add(
                "terminology_consistency",
                f"Same word written two ways: {first} / {second}",
                f"The document writes this word as \"{first}\" ({counts[first]} time(s)) and also as \"{second}\" "
                f"({counts[second]} time(s)). The difference is only in spelling (hamza, ta marbuta or alif "
                "maksura), so consistency is the fix rather than correctness.",
                quotes,
                suggestion=f"Use one form throughout; \"{first}\" is the more frequent one here.",
                severity="minor",
                confidence=0.8,
                extra={"variants": {first: counts[first], second: counts[second]}},
                order=order if order is not None else 10 ** 6,
            )
            reported += 1


def _rule_arabic_long_chain(collector: _Collector) -> None:
    ctx = collector.ctx
    for sentence in ctx.sentences:
        words = tokenize(sentence.text)
        wa_prefixed = sum(1 for w in words if w.startswith("و") and len(w) > 2)
        if wa_prefixed >= 6 and "،" not in sentence.text and "," not in sentence.text:
            collector.add(
                "clarity",
                f"Chain of {wa_prefixed} clauses joined without a separator",
                "Several clauses are linked only by the prefix meaning \"and\", with no separator between them. "
                "The reader has to guess where one point stops and the next begins.",
                [_sentence_quotes(ctx, sentence)],
                suggestion="Break the chain: put a full stop after the first completed point, or separate the "
                           "items with the Arabic comma.",
                severity="minor",
                confidence=0.7,
                extra={"wa_prefixed": wa_prefixed, "words": len(words)},
                order=sentence.index,
            )
            break


def _rule_arabic_repeated_particles(collector: _Collector) -> None:
    ctx = collector.ctx
    particles = {"من", "في", "على", "أن", "ان", "التي", "الذي", "إلى", "الى", "عن", "مع", "هذا"}
    worst: tuple[int, Sentence, str, int] | None = None
    for sentence in ctx.sentences:
        counts = Counter(normalize_tokens(sentence.text))
        for particle in particles:
            hits = counts.get(particle, 0)
            if hits >= 6 and (worst is None or hits > worst[3]):
                worst = (sentence.index, sentence, particle, hits)
    if worst:
        sentence, particle, hits = worst[1], worst[2], worst[3]
        collector.add(
            "repetition",
            f"\"{particle}\" repeated {hits} times in one sentence",
            f"One function word ({particle}) appears {hits} times inside a single sentence, which usually means "
            "the sentence is really two or three statements pressed together.",
            [_sentence_quotes(ctx, sentence)],
            suggestion="Split the sentence, or attach the repeated phrase to the noun it belongs to instead of "
                       "repeating the particle.",
            severity="minor",
            confidence=0.65,
            extra={"particle": particle, "times": hits},
            order=sentence.index,
        )


# --------------------------------------------------------------------------- Somali rules
def _rule_somali_doubled_letters(collector: _Collector) -> None:
    ctx = collector.ctx
    pattern = re.compile(r"\w*([a-zA-Z])\1\1\w*")
    for sentence in ctx.sentences:
        for raw in tokenize(sentence.text):
            match = pattern.fullmatch(raw)
            if not match:
                continue
            collector.add(
                "spelling",
                f"Doubled letters in \"{raw}\"",
                f"\"{raw}\" contains three of the same letter in a row. Somali doubles a vowel or consonant for "
                "meaning, but a tripled letter is normally a keyboard slip.",
                [_sentence_quotes(ctx, sentence, raw)],
                suggestion=f"Remove the extra letter so the word reads with a single (or doubled) letter: \"{re.sub(r'(.)\1+', r'\1\1', raw)}\".",
                severity="minor",
                confidence=0.7,
                extra={"occurrence": raw},
                order=sentence.index,
            )


def _rule_somali_variants(collector: _Collector) -> None:
    ctx = collector.ctx
    counts = Counter(_content(ctx.full_text, "so"))
    for primary, secondary, label in SOMALI_VARIANTS:
        first, second = counts.get(primary, 0), counts.get(secondary, 0)
        if second >= 2 and first >= 1 or (first >= 2 and second >= 2):
            quotes: list[tuple[str, str] | None] = []
            order: int | None = None
            for sentence in ctx.sentences:
                tokens = normalize_tokens(sentence.text)
                for word in (primary, secondary):
                    if word in tokens and len(quotes) < 2 and not any(q and word in q[1] for q in quotes):
                        quotes.append(_sentence_quotes(ctx, sentence, word))
                        if order is None:
                            order = sentence.index
            if len(quotes) < 2:
                continue
            collector.add(
                "terminology_consistency",
                f"Two spellings of {label}: \"{primary}\" / \"{secondary}\"",
                f"The document uses both \"{primary}\" ({first}) and \"{secondary}\" ({second}) for the same "
                "function word. Somali accepts more than one of these forms, so the issue is consistency inside "
                "one document rather than correctness.",
                quotes,
                suggestion=f"Choose one spelling - \"{primary}\" is more common in this text - and keep it.",
                severity="minor" if secondary != "iyou" else "major",
                confidence=0.7,
                extra={"variants": {primary: first, secondary: second}},
                order=order if order is not None else 10 ** 6,
            )


def _rule_somali_particle_repetition(collector: _Collector) -> None:
    ctx = collector.ctx
    particles = ("waxaa", "waxa", "ayaa", "sidaas", "inkastoo", "markii")
    run: list[Sentence] = []
    for sentence in ctx.sentences:
        tokens = normalize_tokens(sentence.text)
        first = tokens[0] if tokens else ""
        if first in particles:
            run.append(sentence)
            if len(run) == 4:
                collector.add(
                    "repetition",
                    "Four sentences open with the same focus marker",
                    f"Four consecutive sentences begin with \"{run[0].text.split()[0]}\" (a Somali focus/inversion "
                    "marker). The construction is grammatical; used in every sentence it flattens the paragraph "
                    "and hides which statement is the important one.",
                    [_sentence_quotes(ctx, run[0]), _sentence_quotes(ctx, run[-1])],
                    suggestion="Vary two of them by starting with the subject or with the place, time, or reason.",
                    severity="minor",
                    confidence=0.6,
                    extra={"marker": first, "count": len(run)},
                    order=sentence.index,
                )
                run = []
        else:
            run = []


# --------------------------------------------------------------------------- generic polarity (used by logic.py too)
def language_rules(language: str) -> tuple[str, ...]:
    return {
        "en": ("doubled", "typos", "confusables", "articles", "fragments", "run_ons", "punctuation",
               "lowercase_i", "start_repetition", "passive", "nominalisation", "register", "hedging",
               "variants", "near_duplicates", "readability", "long", "paragraphs", "flow", "repetition",
               "within", "acronyms"),
        "ar": ("doubled", "punctuation", "readability", "long", "paragraphs", "flow", "repetition",
               "within", "arabic_punct", "arabic_variants", "arabic_chain", "arabic_particles"),
        "so": ("doubled", "punctuation", "near_duplicates", "readability", "long", "paragraphs", "flow",
               "repetition", "within", "somali_doubled", "somali_variants", "somali_particles"),
    }.get(language, ("doubled", "punctuation", "readability", "long", "paragraphs", "flow", "repetition", "within"))


# --------------------------------------------------------------------------- entry point
def investigate_writing(ctx: AnalysisContext, limit: int = 60) -> list[FindingDraft]:
    """Language-aware writing investigation; findings capped and ordered by severity then position."""
    collector = _Collector(ctx)
    rules = {
        "doubled": _rule_doubled_words,
        "typos": _rule_typos,
        "confusables": _rule_confusables,
        "articles": _rule_articles,
        "fragments": _rule_fragments,
        "run_ons": _rule_run_ons,
        "punctuation": _rule_punctuation_spacing,
        "lowercase_i": _rule_lowercase_i,
        "start_repetition": _rule_sentence_start_repetition,
        "passive": _rule_passive,
        "nominalisation": _rule_nominalisation,
        "register": _rule_register,
        "hedging": _rule_hedges_absolutes,
        "variants": _rule_terminology_variants,
        "near_duplicates": _rule_near_duplicates,
        "readability": _rule_readability,
        "long": _rule_long_sentences,
        "paragraphs": _rule_paragraph_structure,
        "flow": _rule_logical_flow,
        "repetition": _rule_repetition,
        "within": _rule_within_sentence_repetition,
        "acronyms": _rule_audience_acronyms,
        "arabic_punct": _rule_arabic_punctuation_mix,
        "arabic_variants": _rule_arabic_script_variants,
        "arabic_chain": _rule_arabic_long_chain,
        "arabic_particles": _rule_arabic_repeated_particles,
        "somali_doubled": _rule_somali_doubled_letters,
        "somali_variants": _rule_somali_variants,
        "somali_particles": _rule_somali_particle_repetition,
    }
    for name in language_rules(ctx.language):
        runner = rules.get(name)
        if runner is not None:
            runner(collector)
    findings = sorted(collector.items, key=lambda item: (item[0], item[1], item[2].title))
    return [finding for _rank, _order, finding in findings][:max(limit, 0)]
