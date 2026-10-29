"""Is this call script promotional, and what kind of call is the client placing? (D-943)

TWO DETERMINISTIC CHECKS, NO MODEL CALL. Both are word lists and tables a reviewer can read
and a client can be shown line by line, which is the point: a verdict that blocks a launch
has to say exactly which words caused it.

THE RULE BEHIND THE LINT (official text, TCCCPR Second Amendment 2025, 1 of 2025, cl.2(av),
as read from the TRAI PDF in `docs/research/research_notes/Calevate market and technology
edge/india_regulation.md` §1, 30 Oct 2026): a promotional voice call is any commercial
call with promotional content, and promotional content mixed into a commercial call makes
the WHOLE call promotional. Calevate places service and relationship calls only (the
no-cold-calls pledge, D-692; no 140-series), so one "festive offer" sentence in a service
script turns every call it places into the kind of call we do not make.

THE WORD LISTS ARE CONSERVATIVE ON PURPOSE. A false "promotional" on a launch is a client
who cannot call their own customers, so:

* A STRONG finding is wording that is promotional on its face in any business — a discount,
  a cashback, "limited period", "buy now". Only strong findings make a script
  `promotional`, and only `promotional` blocks a campaign launch.
* A SOFT finding is wording that is promotional in some sentences and not in others —
  "free", "new scheme", "limited slots". It makes the script `check` and never blocks.
* Bare words with an everyday meaning are not matched at all: "offer" as a verb ("we offer
  X-rays"), "sale" in "after-sales" or "flats for sale", "free" in "free parking", "feel
  free", "toll-free", "are you free tomorrow", Hindi "छूट गई" (was missed).
* A negated mention is dropped: "we do not give discounts", "డిస్కౌంట్ లేదు", "कोई छूट नहीं".
* Wording in a FAQ answer or an objection reply is downgraded to soft: the agent says it
  only when a caller asks, which is the caller's question, not our pitch.

What this does NOT judge: whether the PERSON may be called (the dial gate's question,
`compliance.service.check_dispatch`) or whether a list's consent is current
(`campaigns.service._consent_blockers`). It reads words.

Telugu and Hindi are matched as substrings, not on word boundaries: both scripts attach
suffixes to the noun (ఆఫర్లు, ఆఫర్‌తో) and Python's `\\b` splits inside Indic words at the
vowel signs. Latin-script words (English and romanised Telugu/Hindi) use `\\b`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from calevate_shared.call_script import CallScript

Severity = Literal["strong", "soft"]
Verdict = Literal["clear", "check", "promotional"]
Category = Literal["discount", "urgency", "free_offer", "cross_sell", "buy_now"]
Language = Literal["en", "hi", "te"]

#: The most findings one report carries. A script that trips this many is promotional
#: several times over; the client needs the first screenful, not every repeat.
MAX_FINDINGS: Final = 20
#: How much of the surrounding text a finding quotes, each side of the match.
_QUOTE_CONTEXT: Final = 30
#: Where a negation must sit to cancel a match: this many characters before or after.
_NEGATION_BEFORE: Final = 24
_NEGATION_AFTER: Final = 22

#: Where in a script a sentence came from. `answer` parts are said only when asked.
PartKind = Literal["opening", "instruction", "answer", "template"]


@dataclass(frozen=True, slots=True)
class ScriptPart:
    """One piece of text the agent may say, and where it lives in the script."""

    where: str
    text: str
    kind: PartKind = "instruction"


@dataclass(frozen=True, slots=True)
class Finding:
    phrase: str
    category: Category
    language: Language
    severity: Severity
    where: str
    #: The matched words with a little context either side, for the client to find them.
    quote: str


@dataclass(frozen=True, slots=True)
class PromoReport:
    verdict: Verdict
    findings: tuple[Finding, ...]
    #: True when more findings matched than `MAX_FINDINGS`.
    truncated: bool

    @property
    def blocks_launch(self) -> bool:
        return self.verdict == "promotional"


@dataclass(frozen=True, slots=True)
class _Rule:
    pattern: re.Pattern[str]
    category: Category
    language: Language
    severity: Severity


def _latin(words: str, category: Category, language: Language, severity: Severity) -> _Rule:
    return _Rule(re.compile(rf"\b(?:{words})\b", re.IGNORECASE), category, language, severity)


def _indic(
    words: Iterable[str], category: Category, language: Language, severity: Severity
) -> _Rule:
    alternatives = "|".join(re.escape(unicodedata.normalize("NFC", word)) for word in words)
    return _Rule(re.compile(f"(?:{alternatives})"), category, language, severity)


_OFFER_QUALIFIERS = (
    "special|festive|festival|limited[- ]time|limited|launch|introductory|exclusive|exciting|"
    "bumper|mega|combo|diwali|dussehra|sankranti|ugadi|holi|new year|pre[- ]launch|"
    "early[- ]bird|amazing|great|best|current|latest|seasonal"
)

_RULES: Final[tuple[_Rule, ...]] = (
    # --- English ---------------------------------------------------------------------
    _latin(r"discounts?|discounted", "discount", "en", "strong"),
    # Not `_latin`: a `\b` cannot sit beside "%" or "₹", which are not word characters.
    _Rule(
        re.compile(
            r"\b\d{1,2}\s?%\s?off\b|\bflat\s+\d{1,2}\s?%|(?:\brs\.?|₹|\binr)\s?\d[\d,]*\s?off\b",
            re.IGNORECASE,
        ),
        "discount",
        "en",
        "strong",
    ),
    _latin(r"cash\s?back|coupons?|promo\s?codes?|vouchers?", "discount", "en", "strong"),
    _latin(rf"(?:{_OFFER_QUALIFIERS})\s+offers?", "discount", "en", "strong"),
    _latin(r"offers?\s+(?:valid|ends|ending|price|period|available)", "discount", "en", "strong"),
    _latin(r"(?:an|this)\s+offer\s+for\s+you", "discount", "en", "strong"),
    _latin(r"special\s+(?:price|prices|pricing|rate|rates|deal|deals)", "discount", "en", "strong"),
    _latin(
        r"(?:best|great|special|exclusive|amazing|festive|hot)\s+deals?|deals?\s+of\s+the",
        "discount",
        "en",
        "strong",
    ),
    _latin(
        r"(?:mega|big|festive|festival|clearance|flash|diwali|sankranti|year[- ]end|"
        r"end\s+of\s+season|summer|special)\s+sale|on\s+sale",
        "discount",
        "en",
        "strong",
    ),
    _latin(
        r"limited\s+(?:period|time|stock|stocks|units)|hurry(?:\s+up)?|last\s+chance|"
        r"today\s+only|only\s+today|offer\s+ends|while\s+stocks?\s+last|don'?t\s+miss|"
        r"book\s+now\s+and\s+(?:get|save)|before\s+it'?s\s+gone",
        "urgency",
        "en",
        "strong",
    ),
    _latin(r"limited\s+(?:slots|seats)", "urgency", "en", "soft"),
    _latin(r"free\s+(?:gifts?|vouchers?)", "free_offer", "en", "strong"),
    _latin(r"buy\s+now|order\s+now|shop\s+now|grab\s+(?:it|yours|this)", "buy_now", "en", "strong"),
    _latin(
        r"also\s+(?:check\s+out|try|buy|consider|introduce\s+you\s+to)|introducing\s+our|"
        r"upgrade\s+(?:to|your)|(?:new|latest)\s+(?:product|products|scheme|schemes|plan|plans|"
        r"package|packages|collection|launch|project|projects|course|courses|model|models)",
        "cross_sell",
        "en",
        "soft",
    ),
    _latin(
        r"best\s+price|lowest\s+price|attractive\s+price|zero\s+down\s+payment",
        "discount",
        "en",
        "soft",
    ),
    # --- Romanised Telugu and Hindi ----------------------------------------------------
    _latin(
        r"taggimpu|rayithi|rayiti|offer\s+(?:undi|unnadi|undhi|hai|chal\s+raha)",
        "discount",
        "te",
        "strong",
    ),
    _latin(r"sirf\s+aaj|kewal\s+aaj|aakhri\s+mauka|jaldi\s+karein", "urgency", "hi", "strong"),
    _latin(r"ippude\s+konandi|abhi\s+khareedein|abhi\s+kharidein", "buy_now", "hi", "strong"),
    # --- Telugu ------------------------------------------------------------------------
    _indic(
        ("డిస్కౌంట్", "తగ్గింపు", "రాయితీ", "క్యాష్‌బ్యాక్", "క్యాష్ బ్యాక్", "కూపన్", "ఆఫర్", "ప్రత్యేక ధర"),
        "discount",
        "te",
        "strong",
    ),
    _indic(
        ("పరిమిత కాలం", "పరిమిత సమయం", "ఈ రోజు మాత్రమే", "ఈరోజు మాత్రమే", "త్వరపడండి", "చివరి అవకాశం", "ఆలస్యం చేయకండి"),
        "urgency",
        "te",
        "strong",
    ),
    _indic(("ఇప్పుడే కొనండి", "ఇప్పుడే ఆర్డర్ చేయండి"), "buy_now", "te", "strong"),
    _indic(("ఉచిత బహుమతి",), "free_offer", "te", "strong"),
    _indic(("కొత్త స్కీమ్", "కొత్త ప్లాన్", "కొత్త ప్రాజెక్ట్", "కొత్త ఉత్పత్తి"), "cross_sell", "te", "soft"),
    # --- Hindi -------------------------------------------------------------------------
    _indic(
        ("डिस्काउंट", "कैशबैक", "कूपन", "ऑफर", "ऑफ़र", "विशेष कीमत", "खास कीमत", "स्पेशल प्राइस"),
        "discount",
        "hi",
        "strong",
    ),
    # छूट alone: see `_chhoot_is_missed` for the "was missed" sense it must not catch.
    _indic(("छूट",), "discount", "hi", "strong"),
    _indic(
        ("सीमित समय", "सीमित अवधि", "सिर्फ आज", "केवल आज", "जल्दी करें", "आखिरी मौका", "मौका न चूकें"),
        "urgency",
        "hi",
        "strong",
    ),
    _indic(("अभी खरीदें", "अभी ऑर्डर करें"), "buy_now", "hi", "strong"),
    _indic(("मुफ्त उपहार", "मुफ़्त उपहार", "फ्री गिफ्ट"), "free_offer", "hi", "strong"),
    _indic(("नई स्कीम", "नया प्लान", "नई योजना", "नया प्रोजेक्ट"), "cross_sell", "hi", "soft"),
)

# "free" on its own is soft, and only when none of the everyday senses fits.
_FREE_EN: Final = re.compile(r"\bfree\b", re.IGNORECASE)
_FREE_BENIGN_BEFORE: Final = re.compile(
    r"\b(?:feel|toll|hands|sugar|gluten|fat|stress|hassle|are\s+you|you'?re|you\s+are|if\s+you|"
    r"when\s+you|whenever\s+you|be|is\s+he|is\s+she|are\s+they)[\s-]*$",
    re.IGNORECASE,
)
_FREE_BENIGN_AFTER: Final = re.compile(
    r"^[\s-]*(?:parking|wi-?fi|to\s|slot|slots|time|now\b|today\b|tomorrow\b|of\s+charge\s+parking|"
    r"gift|gifts|voucher)",
    re.IGNORECASE,
)
_FREE_INDIC: Final = re.compile("ఉచిత|ఫ్రీ|मुफ्त|मुफ़्त|फ्री")
#: After ఉచిత/मुफ्त: parking, wifi, "are you free" (ఫ్రీగా ఉన్నారా, फ्री हैं), and the gift
#: words the strong rules already caught.
_FREE_INDIC_BENIGN_AFTER: Final = re.compile(
    "^\\s*(?:పార్కింగ్|వైఫై|గా|టైం|బహుమతి|पार्किंग|वाईफाई|हैं|हो|है क्या|उपहार|गिफ्ट)"
)

# "don't miss" is the urgency rule's own phrase, never a negation of what follows it.
_NEGATION_EN_BEFORE: Final = re.compile(
    r"\b(?:no|not|never|without|don'?t(?!\s+miss)|doesn'?t|do\s+not|does\s+not|cannot|can'?t|"
    r"nahi|nahin)\b",
    re.IGNORECASE,
)
_NEGATION_AFTER_RE: Final = re.compile(
    r"\b(?:not\s+available|are\s+not|is\s+not|isn'?t|aren'?t|ledu|levu|undadu|nahi|nahin)\b"
    "|లేదు|లేవు|ఉండదు|ఉండవు|ఇవ్వము|ఇవ్వం|नहीं",
    re.IGNORECASE,
)
_NEGATION_HI_BEFORE: Final = re.compile("नहीं|कोई भी")
_CHHOOT_MISSED: Final = re.compile("^\\s*(?:ग|जा|गय|गई|गए)")


def _norm(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _negated(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - _NEGATION_BEFORE) : start]
    after = text[end : end + _NEGATION_AFTER]
    return bool(
        _NEGATION_EN_BEFORE.search(before)
        or _NEGATION_HI_BEFORE.search(before)
        or _NEGATION_AFTER_RE.search(after)
    )


def _quote(text: str, start: int, end: int) -> str:
    left = max(0, start - _QUOTE_CONTEXT)
    right = min(len(text), end + _QUOTE_CONTEXT)
    snippet = " ".join(text[left:right].split())
    return ("…" if left else "") + snippet + ("…" if right < len(text) else "")


def _free_findings(text: str) -> list[tuple[int, int, Language]]:
    found: list[tuple[int, int, Language]] = []
    for match in _FREE_EN.finditer(text):
        before, after = text[: match.start()], text[match.end() :]
        if _FREE_BENIGN_BEFORE.search(before) or _FREE_BENIGN_AFTER.search(after):
            continue
        found.append((match.start(), match.end(), "en"))
    for match in _FREE_INDIC.finditer(text):
        if _FREE_INDIC_BENIGN_AFTER.search(text[match.end() :]):
            continue
        language: Language = "te" if "ఀ" <= match.group(0)[0] <= "౿" else "hi"
        found.append((match.start(), match.end(), language))
    return found


def _part_findings(part: ScriptPart) -> list[Finding]:
    text = _norm(part.text)
    findings: list[Finding] = []
    taken: list[tuple[int, int]] = []

    def add(
        start: int, end: int, category: Category, language: Language, severity: Severity
    ) -> None:
        if any(start < t_end and end > t_start for t_start, t_end in taken):
            return
        if _negated(text, start, end):
            return
        taken.append((start, end))
        if part.kind == "answer":
            severity = "soft"
        findings.append(
            Finding(
                phrase=text[start:end],
                category=category,
                language=language,
                severity=severity,
                where=part.where,
                quote=_quote(text, start, end),
            )
        )

    for rule in _RULES:
        for match in rule.pattern.finditer(text):
            if match.group(0) == "छूट" and _CHHOOT_MISSED.search(text[match.end() :]):
                continue
            add(match.start(), match.end(), rule.category, rule.language, rule.severity)
    for start, end, language in _free_findings(text):
        add(start, end, "free_offer", language, "soft")
    findings.sort(key=lambda finding: text.find(finding.phrase))
    return findings


def lint(parts: Sequence[ScriptPart]) -> PromoReport:
    """Every finding in every part, and the verdict they add up to."""
    findings = [finding for part in parts if part.text.strip() for finding in _part_findings(part)]
    if any(finding.severity == "strong" for finding in findings):
        verdict: Verdict = "promotional"
    elif findings:
        verdict = "check"
    else:
        verdict = "clear"
    # Strong first, so the screenful the client sees is the part that decides.
    findings.sort(key=lambda finding: finding.severity != "strong")
    return PromoReport(
        verdict=verdict,
        findings=tuple(findings[:MAX_FINDINGS]),
        truncated=len(findings) > MAX_FINDINGS,
    )


def script_parts(script: CallScript, *, outbound: bool = True) -> list[ScriptPart]:
    """What the agent may SAY, from a structured or raw script, labelled for the client.

    The inbound greeting is skipped for an outbound reading only when the script has its
    own outbound opening: otherwise the greeting is what a placed call opens with too.
    """
    if script.raw_override is not None:
        return [ScriptPart("Instructions", script.raw_override)]
    parts: list[ScriptPart] = []
    if outbound and script.outbound_opening_line.strip():
        parts.append(
            ScriptPart("Opening line for calls it places", script.outbound_opening_line, "opening")
        )
    else:
        parts.append(ScriptPart("Opening line", script.opening_line, "opening"))
    parts.append(ScriptPart("Why it is calling", script.outbound_purpose, "opening"))
    parts.append(ScriptPart("Goal", script.goal))
    parts.append(ScriptPart("Who it is", script.identity))
    parts.append(ScriptPart("About the business", script.business_line))
    parts.extend(
        ScriptPart(f"Step {i}", step.instruction) for i, step in enumerate(script.steps, 1)
    )
    for stage in script.stages:
        parts.append(ScriptPart(f"Section “{stage.name}”", stage.instruction))
        parts.extend(ScriptPart(f"Section “{stage.name}”", step.action) for step in stage.procedure)
    parts.append(ScriptPart("Ending", script.ending))
    parts.extend(ScriptPart("Rule for ending calls", rule) for rule in script.end_call_extra_rules)
    parts.extend(
        ScriptPart("Example call", line.text)
        for line in script.example_exchange
        if line.speaker == "agent"
    )
    parts.extend(
        ScriptPart(f"Answer to “{faq.question[:60]}”", faq.answer, "answer") for faq in script.faqs
    )
    parts.extend(
        ScriptPart(f"Reply to “{item.objection[:60]}”", item.response, "answer")
        for item in script.objections
    )
    return parts


# --- why, in plain words -----------------------------------------------------------------

#: One sentence per category, for the client. No provider names, no regulation numbers.
WHY: Final[dict[Category, str]] = {
    "discount": (
        "Talks about a discount, cashback or special price. A call that mentions one counts "
        "as a promotional call, all of it."
    ),
    "urgency": (
        "Pushes the person to act fast. That is sales pressure, so the call counts as promotional."
    ),
    "free_offer": (
        "Offers something free. Fine for things like free parking; a free gift reads as a "
        "promotion."
    ),
    "cross_sell": (
        "Brings up a different product or plan from what the person asked about. Selling "
        "something else makes the call promotional."
    ),
    "buy_now": "Asks the person to buy or order. A service call helps with what they asked about.",
}

#: What the client is asked to do instead, the same for every finding.
FIX: Final = (
    "Keep the call about what this person asked for or already has: their enquiry, booking, "
    "order or account. Leave offers and other products out of calls you place."
)


# --- call purpose ------------------------------------------------------------------------

Purpose = Literal[
    "transactional",
    "service_own_customer",
    "relationship_enquiry",
    "relationship_application",
    "promotional",
    "unclear",
]


@dataclass(frozen=True, slots=True)
class PurposeVerdict:
    purpose: Purpose
    label: str
    #: The clause of the regulation it falls under, for the D-943 row and an auditor.
    basis: str
    #: How long the permission lasts, in plain words, or None where nothing time-boxes it.
    window: str | None
    explanation: str


_PURPOSES: Final[dict[Purpose, PurposeVerdict]] = {
    "transactional": PurposeVerdict(
        "transactional",
        "Reply to something the customer just did",
        "TCCCPR 2025 cl.2(bt): within thirty minutes of a transaction the customer started",
        "30 minutes",
        "A call placed straight after the customer's own action, like the instant call to a "
        "new form lead. A campaign can never be this.",
    ),
    "service_own_customer": PurposeVerdict(
        "service_own_customer",
        "Service call to your own customer",
        "TCCCPR 2025 cl.2(bh)(i): the sender's own customer, about their product or service",
        None,
        "A reminder, confirmation or follow-up to someone who already buys from you. It must "
        "stay about what they already have.",
    ),
    "relationship_enquiry": PurposeVerdict(
        "relationship_enquiry",
        "Follow-up to an enquiry",
        "TCCCPR 2026 cl.2(bb)(ii): an inquiry by the person within the preceding seven days",
        "7 days from their enquiry",
        "Calling back someone who asked you about something. The permission lasts seven days "
        "from when they asked.",
    ),
    "relationship_application": PurposeVerdict(
        "relationship_application",
        "Follow-up to an application",
        "TCCCPR 2026 cl.2(bb)(iii): an application by the person within the preceding three months",
        "3 months from their application",
        "Calling someone about an application they made to you. The permission lasts three "
        "months from when they applied.",
    ),
    "promotional": PurposeVerdict(
        "promotional",
        "Promotional call",
        "TCCCPR 2025 cl.2(av): commercial communication with promotional content",
        None,
        "Selling or marketing. Calevate does not place promotional calls.",
    ),
    "unclear": PurposeVerdict(
        "unclear",
        "Not said yet",
        "none",
        None,
        "Say where this list's permission came from, so we can tell what kind of call it is.",
    ),
}

#: A campaign list's consent source → the purpose it makes a SERVICE campaign. An offline
#: form is read as an enquiry (the shorter window) because we cannot tell a paper sign-up
#: from an application; a purchased list is refused at launch and has no purpose.
_SERVICE_PURPOSE_BY_SOURCE: Final[dict[str, Purpose]] = {
    "existing_customer": "service_own_customer",
    "inbound_enquiry": "relationship_enquiry",
    "web_form_optin": "relationship_enquiry",
    "offline_form_optin": "relationship_enquiry",
}


def campaign_purpose(classification: str, consent_source: str | None) -> PurposeVerdict:
    """The purpose a campaign's own choices declare: its classification and its list."""
    if classification == "promotional":
        return _PURPOSES["promotional"]
    if classification != "service" or consent_source is None:
        return _PURPOSES["unclear"]
    return _PURPOSES[_SERVICE_PURPOSE_BY_SOURCE.get(consent_source, "unclear")]


def lead_source_purpose(consent_basis: str) -> PurposeVerdict:
    """The purpose a form lead's call has once the instant-call window has passed."""
    return _PURPOSES[
        "relationship_application" if consent_basis == "application" else "relationship_enquiry"
    ]


__all__ = [
    "FIX",
    "MAX_FINDINGS",
    "WHY",
    "Finding",
    "PromoReport",
    "Purpose",
    "PurposeVerdict",
    "ScriptPart",
    "campaign_purpose",
    "lead_source_purpose",
    "lint",
    "script_parts",
]
