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
from typing import Final, Literal, cast, get_args

from calevate_shared.call_script import CallScript
from calevate_shared.call_words import Live as _Live
from calevate_shared.call_words import LivePattern as _LivePattern
from calevate_shared.call_words import extend as _extend
from calevate_shared.call_words import say as _say
from calevate_shared.call_words import table

Severity = Literal["strong", "soft"]
Verdict = Literal["clear", "check", "promotional"]
Category = Literal["discount", "urgency", "free_offer", "cross_sell", "buy_now", "claim"]
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
    #: The languages of wording this checker cannot read (`unread_languages`), by English
    #: name. Never "clear" while any is listed (G5-3).
    not_checked_in: tuple[str, ...] = ()

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


def _indic_rules() -> tuple[_Rule, ...]:
    """The Telugu and Hindi rules, from the founder's detector file (`call_words.json`,
    `call_purpose.rules`), keyed "<language> <category> <severity>". A key naming a
    language, category or severity this checker does not know fails at import rather than
    being skipped, so a typo cannot quietly switch a launch-gate rule off; an emptied list
    is that rule switched off."""
    rules: list[_Rule] = []
    for key, words in table("call_purpose.rules").items():
        language, category, severity = key.split()
        if (
            language not in get_args(Language)
            or category not in get_args(Category)
            or severity not in get_args(Severity)
        ):
            raise ValueError(f"call_words call_purpose.rules has an unknown key {key!r}")
        if words:
            rules.append(
                _indic(
                    words,
                    cast(Category, category),
                    cast(Language, language),
                    cast(Severity, severity),
                )
            )
    return tuple(rules)


_OFFER_QUALIFIERS = (
    "special|festive|festival|limited[- ]time|limited|launch|introductory|exclusive|exciting|"
    "bumper|mega|combo|diwali|dussehra|sankranti|ugadi|holi|new year|pre[- ]launch|"
    "early[- ]bird|amazing|great|best|current|latest|seasonal"
)

_BOOKED_THINGS = (
    "appointment|appointments|visit|site\\s+visit|slot|session|class|classes|call|payment|emi|"
    "dose|follow-?up|check-?up|test|exam|booking|interview|demo|consultation|scan|delivery"
)

_EN_RULES: Final[tuple[_Rule, ...]] = (
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
        r"today\s+only|only\s+today|offer\s+ends|while\s+stocks?\s+last|"
        # Not "don't miss your appointment": a reminder of something already booked.
        rf"don'?t\s+miss(?!\s+(?:your|the)\s+(?:{_BOOKED_THINGS})\b)|"
        r"book\s+now\s+and\s+(?:get|save)|before\s+it'?s\s+gone|"
        r"last\s+few\s+(?:units|flats|plots|homes|villas)",
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
    _latin(r"guaranteed\s+returns?", "claim", "en", "soft"),
    # --- Romanised Telugu and Hindi ----------------------------------------------------
    _latin(
        r"taggimpu|rayithi|rayiti|offer\s+(?:undi|unnadi|undhi|hai|chal\s+raha)",
        "discount",
        "te",
        "strong",
    ),
    _latin(r"sirf\s+aaj|kewal\s+aaj|aakhri\s+mauka|jaldi\s+karein", "urgency", "hi", "strong"),
    _latin(r"ippude\s+konandi|abhi\s+khareedein|abhi\s+kharidein", "buy_now", "hi", "strong"),
)
#: The English and romanised rules above, then the Telugu and Hindi ones from the founder's
#: lists (`call_words.json`, `call_purpose.rules`), rebuilt when an edit is installed.
_RULES: Final[_Live[tuple[_Rule, ...]]] = _Live(lambda: (*_EN_RULES, *_indic_rules()))

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
#: "Free" in Telugu and Hindi letters, and the words after it that make it everyday (free
#: parking, "are you free"): the founder's lists in `call_words.json`.
_FREE_INDIC: Final = _LivePattern(lambda: _say("call_purpose._FREE_INDIC"))
_FREE_INDIC_BENIGN_AFTER: Final = _LivePattern(
    lambda: _say("call_purpose._FREE_INDIC_BENIGN_AFTER")
)

# "don't miss" is the urgency rule's own phrase, never a negation of what follows it.
_NEGATION_EN_BEFORE: Final = re.compile(
    r"\b(?:no|not|never|without|don'?t(?!\s+miss)|doesn'?t|do\s+not|does\s+not|cannot|can'?t|"
    r"nahi|nahin)\b",
    re.IGNORECASE,
)
_NEGATION_AFTER_RE: Final = _LivePattern(
    lambda: _extend(
        r"\b(?:not\s+available|are\s+not|is\s+not|isn'?t|aren'?t|ledu|levu|undadu|nahi|nahin)\b",
        "call_purpose._NEGATION_AFTER_RE",
    ),
    re.IGNORECASE,
)
_NEGATION_HI_BEFORE: Final = _LivePattern(lambda: _say("call_purpose._NEGATION_HI_BEFORE"))
#: A negation reaches only as far as its own clause: "Don't wait, flat 20% off" and "Rs 500
#: off, not available anywhere else" negate nothing about the offer.
#: Em dash, en dash and the Devanagari danda (by code point: RUF001 refuses the dashes) end
#: a clause too.
_CLAUSE_BREAK: Final = re.compile("[,.;:!?\n" + "".join(map(chr, (0x2014, 0x2013, 0x0964))) + "]")
#: Sales idioms built on a negative word that negate no offer: "No cost EMI with 10% off".
_NEGATIVE_IDIOMS: Final = re.compile(
    r"\b(?:no[\s-]+cost|no\s+hidden|no\s+extra|no\s+waiting|don'?t\s+wait|do\s+not\s+wait|"
    r"not\s+just|not\s+only)\b",
    re.IGNORECASE,
)


#: Indic words of the strong lists that also have an everyday sense, told apart by the
#: letters around them: छूट is "was missed" before a vowel sign or गया/जाना (छूटी हुई कॉल,
#: छूट गई) and an exemption after "tax" (टैक्स छूट); ఆఫర్/ऑफर is the verb "to offer" before
#: "do" (సైట్ విజిట్ ఆఫర్ చేయండి, ऑफर करें) and a job offer before "letter". The words and
#: patterns are the founder's (`call_words.json`), keyed by the word as written.
def _patterns_by_word(key: str) -> dict[str, re.Pattern[str]]:
    return {
        unicodedata.normalize("NFC", word): re.compile(pattern)
        for word, pattern in table(key).items()
    }


_INDIC_EVERYDAY_AFTER: Final[_Live[dict[str, re.Pattern[str]]]] = _Live(
    lambda: _patterns_by_word("call_purpose._INDIC_EVERYDAY_AFTER")
)
_INDIC_EVERYDAY_BEFORE: Final[_Live[dict[str, re.Pattern[str]]]] = _Live(
    lambda: _patterns_by_word("call_purpose._INDIC_EVERYDAY_BEFORE")
)


def _norm(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _everyday_sense(text: str, start: int, end: int) -> bool:
    word = text[start:end]
    after = _INDIC_EVERYDAY_AFTER().get(word)
    before = _INDIC_EVERYDAY_BEFORE().get(word)
    return bool(
        (after is not None and after.search(text[end:]))
        or (before is not None and before.search(text[:start]))
    )


def _negated(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - _NEGATION_BEFORE) : start]
    breaks = list(_CLAUSE_BREAK.finditer(before))
    if breaks:
        before = before[breaks[-1].end() :]
    before = _NEGATIVE_IDIOMS.sub(" ", before)
    after = text[end : end + _NEGATION_AFTER]
    cut = _CLAUSE_BREAK.search(after)
    if cut is not None:
        after = after[: cut.start()]
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
        telugu = unicodedata.name(match.group(0)[0], "").startswith("TELUGU")
        language: Language = "te" if telugu else "hi"
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

    for rule in _RULES():
        for match in rule.pattern.finditer(text):
            if _everyday_sense(text, match.start(), match.end()):
                continue
            add(match.start(), match.end(), rule.category, rule.language, rule.severity)
    for start, end, language in _free_findings(text):
        add(start, end, "free_offer", language, "soft")
    findings.sort(key=lambda finding: text.find(finding.phrase))
    return findings


def first_finding(text: str) -> Finding | None:
    """The first promotional or urgency wording in one line, in reading order, or None.

    The script lint (`agents/script_lint`, D-945) reports per line through this, so the
    writer's repair round, the readiness card and the launch block read one word list
    with one negation and everyday-sense logic."""
    found = _part_findings(ScriptPart("", text))
    return found[0] if found else None


#: Letters whose words this checker has no list for, by the Unicode name of the script's
#: letters, with the language a script means to an owner. Latin, Telugu and Devanagari are
#: read (`Language`). A script full of "தள்ளுபடி" would otherwise read "clear" on a launch
#: gate (audit of 5 Nov 2026, G5-3).
_UNREAD_SCRIPTS: Final[dict[str, str]] = {
    "TAMIL": "Tamil",
    "KANNADA": "Kannada",
    "MALAYALAM": "Malayalam",
    "BENGALI": "Bengali",
    "GUJARATI": "Gujarati",
    "GURMUKHI": "Punjabi",
    "ORIYA": "Odia",
    "ARABIC": "Urdu",
}


def unread_languages(text: str) -> tuple[str, ...]:
    """The languages of `text`'s letters this checker cannot read, in first-seen order."""
    seen: dict[str, None] = {}
    for ch in text:
        if ch.isascii() or not ch.isalpha():
            continue
        script = unicodedata.name(ch, "").split(" ")[0]
        if script in _UNREAD_SCRIPTS:
            seen.setdefault(_UNREAD_SCRIPTS[script], None)
    return tuple(seen)


def lint(parts: Sequence[ScriptPart]) -> PromoReport:
    """Every finding in every part, and the verdict they add up to. Wording in a language the
    checker cannot read makes the verdict at least `check`, never `clear`."""
    findings = [finding for part in parts if part.text.strip() for finding in _part_findings(part)]
    unread = unread_languages(" ".join(part.text for part in parts))
    if any(finding.severity == "strong" for finding in findings):
        verdict: Verdict = "promotional"
    elif findings or unread:
        verdict = "check"
    else:
        verdict = "clear"
    # Strong first, so the screenful the client sees is the part that decides.
    findings.sort(key=lambda finding: finding.severity != "strong")
    return PromoReport(
        verdict=verdict,
        findings=tuple(findings[:MAX_FINDINGS]),
        truncated=len(findings) > MAX_FINDINGS,
        not_checked_in=unread,
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
    "claim": (
        "Promises a result, like guaranteed returns. That reads as a sales pitch; say only what "
        "the business can show."
    ),
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
    "first_finding",
    "lead_source_purpose",
    "lint",
    "script_parts",
]
