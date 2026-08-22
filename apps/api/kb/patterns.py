"""Distilled call patterns — the aggregate that CANNOT carry call content.

THE HAZARD, IN ONE SENTENCE
---------------------------
Caller A's words reaching caller B on a live call. Everything in this module exists to
make that unexpressible rather than unlikely. A "collective knowledge base" built the
obvious way — summarise the transcripts, index the summaries, retrieve them mid-call —
is a machine for exactly that, and it passes every test anyone would think to write for
it, because a leak looks like a working feature.

So the aggregate is defined by what it is made of rather than by what it must not
contain. A `CallPattern` is a COUNT over a TOKEN, and every token has one of two
provenances, neither of which is the caller:

1. **OUR closed enums** — `calls.outcome_tag`, `calls.sentiment` (`crm/models.py`). Four
   and three members respectively, fixed by a CHECK constraint in the database.
2. **The TENANT's own extraction schema** — a field `key` they defined, or a member of
   the `enum_values` they declared for it (`calevate_shared.extraction.ExtractionField`).
   The client typed these into the admin console before any call was placed; they are
   the client's vocabulary describing their own business, not anything a caller said.

There is NO free-text field on any type here, so there is nowhere for a transcript to
land. `Vocabulary` then makes that a checkable property rather than a design intention:
every token on every pattern must be a member, and `assert_no_call_content` refuses the
whole batch if one is not.

WHY BOTH AN ADMISSION CHOKEPOINT AND AN EGRESS GUARD
-----------------------------------------------------
`CallOutcome.admit` is the door: it drops any extraction answer that is not a declared
enum member, which is the only place a model's free-text output could otherwise enter.
`assert_no_call_content` is the wall: it re-checks the finished patterns against the
vocabulary on the way out.

Two checks for one property looks redundant and is not. The door protects TODAY's
pipeline; the wall protects the pipeline somebody writes next year against a
`CallPattern` type that by then has one more field. The wall is the test the brief asks
for — it fails loudly the day the aggregator is widened, and it fails at the point of
widening rather than on a call six weeks later.

THE K-ANONYMITY FLOOR
---------------------
A pattern observed on ONE call is that call, relabelled. Aggregate-disclosure practice
has one standard control for this and we use it rather than inventing a second: k-anonymity
(Sweeney, *k-anonymity: a model for protecting privacy*, IJUFKS 2002) — publish nothing
that describes fewer than k records. `MIN_CALLS_PER_PATTERN` is that k, and it is applied
where it can actually bind: on the count of DISTINCT CALLS a pattern was observed on, not
on the number of rows the query returned.

The number is 5 rather than 3 because these aggregates are per AGENT — a single-agent
clinic's calls are a small, self-selecting population, and at k=3 an owner who knows two
of the three callers learns the third's answer by subtraction.

WHAT THIS DELIBERATELY CANNOT PRODUCE, AND WHY THAT IS NOT A GAP
-----------------------------------------------------------------
"Top questions" and "common objections" in a caller's OWN WORDS are not derivable here
and must not be: producing them means reading transcripts and emitting a phrase, which is
the hazard above with a friendlier name. What IS derivable is the same signal expressed
in the tenant's vocabulary — an enum-valued extraction field such as `reason_for_call`
answers "what do callers ask about" without quoting anyone.

"What phrasing converts" is refused here for a second, different reason: this repository
already answers it, with `prompt_experiments` / `prompt_experiment_variants` /
`call_variant_assignments` (`agents/models.py`). A phrasing signal mined from transcripts
would be a second way to answer one question, and the worse of the two — an A/B assignment
proves causation, a correlation over transcripts does not.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from calevate_shared.extraction import ExtractionSchemaSpec

from apps.api.crm.models import OUTCOME_TAGS, SENTIMENTS

#: k, in the k-anonymity sense. See the module docstring for why 5 and not 3.
MIN_CALLS_PER_PATTERN: Final = 5

#: A window with fewer calls than this produces NOTHING, whatever the per-pattern counts
#: say. Without it a week with six calls could publish a pattern covering five of them —
#: technically k=5, and a description of ~83% of one week's callers. The floor on the
#: DENOMINATOR is what makes the floor on the numerator mean anything.
MIN_CALLS_PER_WINDOW: Final = 20

#: What a pattern is ABOUT. Closed, and closed for the same reason every other label in
#: this repo is: it selects the wording of the digest and the arithmetic behind the
#: count. It is not a free-form category somebody can extend at a call site.
#:
#: - `asked_about`  — an enum answer the client's own schema declares (their vocabulary
#:   for "what this call was about"), counted over calls.
#: - `outcome`      — `calls.outcome_tag`, ours.
#: - `sentiment`    — `calls.sentiment`, ours.
#: - `not_captured` — a REQUIRED extraction field the agent failed to capture. The
#:   knowledge-gap signal TRD §6 promises, derived from what the schema asked for rather
#:   than from what the agent said.
PatternKind = Literal["asked_about", "outcome", "sentiment", "not_captured"]

PATTERN_KINDS: tuple[PatternKind, ...] = ("asked_about", "outcome", "sentiment", "not_captured")

#: The kinds whose counts are read OUT OF `call_extractions.data`, and therefore the only
#: ones a scrubbed extraction can no longer speak to. `outcome` and `sentiment` are columns
#: on `calls` that no retention sweep touches, so they keep their full denominator; these
#: two get a smaller one. Two denominators is more machinery than one and it is the
#: honest amount: a single shrunken denominator would understate every outcome rate on a
#: tenant with short lead retention, and a single full one restates the bug this split
#: exists to fix. `CallPattern` carries the one it was counted over, so a reader never has
#: to know which family it is holding.
EXTRACTION_KINDS: frozenset[PatternKind] = frozenset({"asked_about", "not_captured"})


class CallContentLeakError(AssertionError):
    """A token reached an aggregate that no closed enum and no client schema declares.

    `AssertionError` rather than `ProblemError`, and the choice is deliberate: this is
    never a client-facing refusal and never something an operator can remediate by
    changing configuration. It means the code that built the batch is wrong. It should
    stop the batch, page nobody, and fail a test.

    The offending token is NOT put in the message. Whatever it is, it came from somewhere
    it should not have, and the single most likely somewhere is a transcript — so a
    message quoting it would write caller speech into a log line and an exception
    trace, which is the exact thing being defended against (hard rule 6). The KIND and
    the COUNT locate the defect; the debugger reads the input, under the access rules
    that already govern it.
    """


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """Every token an aggregate for ONE agent is allowed to name.

    Built from the agent's published extraction schema plus our own two enums, so it is
    a fact about configuration rather than about calls: this object can be constructed
    for an agent that has never taken a call, and it does not change when one lands.

    `labels` maps a token to what a human should read. It is the CLIENT's own wording
    (`ExtractionField.label`, or the enum member they typed) and it is what a digest
    renders — never an id, never a key, and never anything a caller said.
    """

    tokens: frozenset[str]
    labels: Mapping[str, str]
    #: Field keys the schema marks `required`. The `not_captured` kind is meaningless
    #: for an optional field: not capturing it is the schema working as asked.
    required_field_keys: frozenset[str]
    #: field key -> the enum members it declares. The admission door reads this.
    enum_members: Mapping[str, frozenset[str]]

    @classmethod
    def for_schema(cls, spec: ExtractionSchemaSpec) -> Vocabulary:
        """The vocabulary of one published extraction schema, plus our closed enums.

        Enum ANSWERS are namespaced `answer:{field_key}:{member}` and field keys are
        namespaced `field:{key}`. Namespacing is not decoration: a client whose schema
        declares an enum member `resolved` would otherwise mint a token that collides
        with our `outcome_tag` of the same name, and a pattern's count would silently
        merge two different facts about two different populations.
        """
        tokens: set[str] = set()
        labels: dict[str, str] = {}
        required: set[str] = set()
        enum_members: dict[str, frozenset[str]] = {}

        for tag in OUTCOME_TAGS:
            token = outcome_token(tag)
            tokens.add(token)
            labels[token] = tag.replace("_", " ")
        for sentiment in SENTIMENTS:
            token = sentiment_token(sentiment)
            tokens.add(token)
            labels[token] = sentiment

        for field in spec.fields:
            field_key = field_token(field.key)
            tokens.add(field_key)
            labels[field_key] = field.label
            if field.required:
                required.add(field_key)
            if field.type == "enum" and field.enum_values:
                members = frozenset(field.enum_values)
                enum_members[field.key] = members
                for member in members:
                    token = answer_token(field.key, member)
                    tokens.add(token)
                    # The client typed both halves; the digest reads "Reason: Appointment".
                    labels[token] = f"{field.label}: {member}"

        return cls(
            tokens=frozenset(tokens),
            labels=labels,
            required_field_keys=frozenset(required),
            enum_members=enum_members,
        )

    def label_for(self, token: str) -> str:
        """The client-facing wording for a token, or the token itself.

        The fallback can only be reached by a token this vocabulary does not hold, and
        `assert_no_call_content` refuses those before anything renders — so in a correct
        pipeline it is unreachable. It is here so that a DEBUG render of a rejected batch
        does not raise a second, less informative exception on top of the first.
        """
        return self.labels.get(token, token)


def outcome_token(tag: str) -> str:
    return f"outcome:{tag}"


def sentiment_token(value: str) -> str:
    return f"sentiment:{value}"


def field_token(key: str) -> str:
    return f"field:{key}"


def answer_token(field_key: str, member: str) -> str:
    return f"answer:{field_key}:{member}"


@dataclass(frozen=True, slots=True)
class CallOutcome:
    """ONE call, reduced to tokens, with everything else left behind.

    This is the only type that touches per-call data, and it holds no phone number, no
    name, no summary, no transcript and no extraction VALUE that the client did not
    declare in advance. `call_id` is here for one purpose — counting DISTINCT calls, which
    is what the k-anonymity floor is a floor on — and never reaches a pattern.
    """

    call_id: UUID
    tokens: frozenset[str]
    #: Do we still hold this call's extraction as the agent left it?
    #:
    #: FALSE means a SWEEP DESTROYED IT — the lead-clock TTL or an erasure — and it is a
    #: different fact from "the agent captured nothing", which is TRUE with an empty
    #: `data`. The two are byte-identical in the row and opposite in meaning, which is
    #: why `call_extractions.scrubbed_at` exists (migration f2a6d81b39c4) rather than
    #: being inferred. It defaults True because a `CallOutcome` built by hand — every
    #: test in this lane, and any future assembler — is asserting about data it holds.
    extraction_readable: bool = True

    @classmethod
    def admit(
        cls,
        *,
        call_id: UUID,
        vocabulary: Vocabulary,
        outcome_tag: str | None,
        sentiment: str | None,
        extraction: Mapping[str, object] | None,
        extraction_scrubbed: bool = False,
    ) -> CallOutcome:
        """THE DOOR. Turn one call's row into tokens, dropping everything undeclared.

        Every arm is a membership test against something written down BEFORE the call:
        our two enums, or this agent's published schema. An extraction answer that is not
        a declared member of its field's `enum_values` is DROPPED — silently, and that is
        the right verb here rather than "refused".

        The rejected alternative was raising. An extraction is produced by a language
        model, and a model returning `"appointment "` with a trailing space, or a
        translated member, or a sentence, is a routine occurrence rather than a defect in
        this module — and a batch that raised on it would stop the weekly aggregate for
        the whole tenant on the strength of one call's model output. Dropping loses a
        count; raising loses the feature. What must never happen is the third option —
        letting it through — and that is what this door and the wall behind it prevent.

        A non-enum field contributes NOTHING but its presence, and only when the schema
        marked it required: a `text` field's value is caller-derived by definition (it is
        what the model heard), and a `number` or `date` value is caller-derived too — a
        phone number, an amount, an appointment time. None of them may be counted; that
        the field came back EMPTY is the only fact about it that is ours to publish.

        `extraction_scrubbed` TAKES BOTH EXTRACTION ARMS OFF THE CALL, and only those. A
        retention sweep empties `data` on the lead clock, and the emptied row then says
        the agent captured nothing — so a required field the agent DID capture is counted
        as a miss, and a digest tells the owner their working agent is failing. Skipping
        the arms is what stops that; `distil` then takes the call out of the DENOMINATOR
        those two families are counted over, because a call we cannot read is not evidence
        either way. What it deliberately does NOT do is drop the call from `outcome` and
        `sentiment`: those live on `calls`, no sweep touches them, and they are still
        true. Dropping them too would quietly shrink a real statistic to fix a different
        one.
        """
        tokens: set[str] = set()

        if outcome_tag in OUTCOME_TAGS:
            tokens.add(outcome_token(outcome_tag))
        if sentiment in SENTIMENTS:
            tokens.add(sentiment_token(sentiment))

        if extraction_scrubbed:
            return cls(call_id=call_id, tokens=frozenset(tokens), extraction_readable=False)

        data = extraction or {}
        for field_key, members in vocabulary.enum_members.items():
            value = data.get(field_key)
            if isinstance(value, str) and value in members:
                tokens.add(answer_token(field_key, value))

        for token in vocabulary.required_field_keys:
            key = token.removeprefix("field:")
            if _is_blank(data.get(key)):
                tokens.add(token)

        return cls(call_id=call_id, tokens=frozenset(tokens))


def _is_blank(value: object) -> bool:
    """Did the agent fail to capture this field?

    `None`, absent, empty string and whitespace all mean the same thing to a client
    reading "the agent did not get this", and the extractor produces all four: a field
    the model omitted, a field it returned as null, and a field it returned as "" are the
    same event. `False` and `0` are NOT blank — a captured "no" is a captured answer, and
    counting it as a miss would report a working agent as a broken one.
    """
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


@dataclass(frozen=True, slots=True)
class CallPattern:
    """One distilled pattern: a token, how many calls carried it, out of how many.

    Both counts ride together on purpose. A caller that received `calls` alone would have
    to fetch the denominator from somewhere else to render a rate, and two reads of two
    numbers that must agree is how a screen comes to say "41 of 30" — the same argument
    `RetrievalCapability` makes for carrying its retriever rather than being asked for one.
    """

    kind: PatternKind
    token: str
    calls: int
    of_calls: int

    @property
    def share(self) -> float:
        """The rate, for rendering only. Never persisted, never compared for equality:
        a float that round-trips through a store is a number that stops matching itself.
        """
        return self.calls / self.of_calls if self.of_calls else 0.0


def _kind_of(token: str) -> PatternKind:
    if token.startswith("outcome:"):
        return "outcome"
    if token.startswith("sentiment:"):
        return "sentiment"
    if token.startswith("answer:"):
        return "asked_about"
    return "not_captured"


def distil(
    outcomes: Sequence[CallOutcome],
    *,
    vocabulary: Vocabulary,
    min_calls: int = MIN_CALLS_PER_PATTERN,
    min_window: int = MIN_CALLS_PER_WINDOW,
) -> list[CallPattern]:
    """Count tokens across calls, publish only what clears both floors.

    Ordered by count descending then token ascending — a total order, so two runs over
    the same window produce byte-identical output and a digest that has not changed does
    not LOOK changed. Ordering by count alone leaves ties to dict iteration order, which
    is insertion order, which is row order, which is not stable.

    TWO DENOMINATORS, AND BOTH FLOORS BIND ON WHICHEVER ONE APPLIES. A retention scrub
    destroys an extraction and nothing else, so a scrubbed call is still real evidence
    about `outcome` and `sentiment` and is no evidence at all about `asked_about` and
    `not_captured` (`EXTRACTION_KINDS`). The extraction families are therefore counted
    over the calls we can still read, and — this is the part that is easy to get wrong in
    the unsafe direction — that smaller denominator has to clear `min_window` on its own.
    A family whose population has fallen below the floor publishes NOTHING rather than
    publishing a statistic about a smaller, self-selected group; the outcome and sentiment
    families are unaffected and still publish. Same safe direction as the erasure
    predicate in `kb/insights.py`.

    BOTH FLOORS COUNT DISTINCT CALLS. `min_window` used to be tested against
    `len(outcomes)` — the number of ROWS handed in — and that is the same defect on the
    denominator that the k floor already refuses on the numerator, with none of the
    numerator's protection: six real calls arriving as four rows each clear a window floor
    of twenty, and a token on all six then clears k=5 and publishes "6 of 6". That is
    precisely the disclosure `MIN_CALLS_PER_WINDOW`'s own comment says it exists to
    prevent. Today's reader cannot fan out (`call_extractions` is UNIQUE on
    `(tenant_id, call_id)`), but `distil` is a pure function this module exports, and a
    privacy floor that holds only because of a unique constraint in a table it never
    names is a floor that a second caller removes without touching this file.
    """
    seen: dict[str, set[UUID]] = {}
    for outcome in outcomes:
        for token in outcome.tokens:
            seen.setdefault(token, set()).add(outcome.call_id)

    total = len({outcome.call_id for outcome in outcomes})
    if total < min_window:
        return []
    readable = len({outcome.call_id for outcome in outcomes if outcome.extraction_readable})

    patterns = []
    for token, call_ids in seen.items():
        kind = _kind_of(token)
        of_calls = readable if kind in EXTRACTION_KINDS else total
        if of_calls < min_window or len(call_ids) < min_calls:
            continue
        patterns.append(CallPattern(kind=kind, token=token, calls=len(call_ids), of_calls=of_calls))
    patterns.sort(key=lambda p: (-p.calls, p.token))
    assert_no_call_content(patterns, vocabulary=vocabulary)
    return patterns


#: Five or more consecutive digits. THE SECOND NET, and it is second on purpose — the
#: vocabulary check above is the real guard, because a leak that carries no digits at all
#: (a name, a sentence, an address) is the likelier one and this pattern cannot see it.
#:
#: FIVE, not four: a rendered digest legitimately carries counts, and a busy agent's
#: weekly denominator reaches four figures. An Indian mobile number is ten digits, an
#: E.164 string is up to fifteen, an OTP is six, an order id is longer — every shape this
#: is aimed at clears five comfortably, and a count would have to reach 10,000 calls in a
#: week to collide.
_DIGIT_RUN = re.compile(r"\d{5,}")


def assert_no_call_content(patterns: Iterable[CallPattern], *, vocabulary: Vocabulary) -> None:
    """THE WALL. Refuse a batch carrying anything the vocabulary does not declare.

    This is the check the whole module is for, so it is worth being precise about what it
    proves and what it does not. It proves that every token in the batch was written down
    — by us, in a closed enum, or by the client, in their own schema — before any of these
    calls happened. It does not and cannot prove that the client's own schema contains no
    personal data: a client is free to name an extraction field "Aadhaar number", and that
    label is theirs to publish. What it forecloses is CALLER-derived text, which is the
    thing that can travel from one call to another.

    Called by `distil` on the way out, and again by anything that persists or renders a
    batch it did not itself distil. Cheap enough to call twice (a set membership per
    token), and the whole point is that a future writer who assembles patterns by some
    other route still hits it.
    """
    batch = list(patterns)
    strangers = [p for p in batch if p.token not in vocabulary.tokens]
    if strangers:
        raise CallContentLeakError(
            f"{len(strangers)} of {len(batch)} pattern(s) name a token this agent's "
            "vocabulary does not declare. A pattern may only name a member of our closed "
            "enums or of the client's own extraction schema — see apps/api/kb/patterns.py. "
            "The tokens are deliberately not quoted here: the most likely source of an "
            "undeclared token is a transcript (hard rule 6)."
        )
    mismatched = [p for p in batch if p.kind != _kind_of(p.token)]
    if mismatched:
        raise CallContentLeakError(
            f"{len(mismatched)} pattern(s) carry a kind that does not match their token's "
            "namespace, so the count is arithmetic over two different populations."
        )
    impossible = [p for p in batch if p.calls < 1 or p.calls > p.of_calls]
    if impossible:
        raise CallContentLeakError(
            f"{len(impossible)} pattern(s) count more calls than the window holds, or "
            "none at all — the denominator is not the one these counts were taken over."
        )


def assert_text_carries_no_call_content(body: str, *, declared: Iterable[str] = ()) -> None:
    """The same wall for RENDERED text, which is what actually leaves the building.

    A digest is assembled from a template, our own counts and the client's own labels, so
    by construction it holds no caller speech. This asserts it anyway, because "assembled
    from a template" is a property of the code that renders it today, and the render is
    the last place a leak is still cheap to catch.

    `declared` IS THE CLIENT'S OWN WORDING and is elided before the check, which is the
    fix for a false positive this guard shipped with. A client is entitled to call an
    extraction field "PIN code 500081" or "GSTIN", and the digit run in their own label
    would have raised `CallContentLeakError` — which pages an operator and STOPS THE WHOLE
    SWEEP (`kb_digest_content_refused`). A privacy alarm that fires on ordinary
    configuration is one that gets muted, so the guard is narrowed to the text whose
    provenance is genuinely ours: everything the client did not write.

    Only the digit run is checkable here — see `_DIGIT_RUN`. A guard that tried to detect
    a leaked SENTENCE would be a classifier, i.e. a thing that is sometimes wrong in both
    directions, and a privacy control that is sometimes wrong is worse than one whose
    limits are written down.
    """
    residue = body
    # Longest first: a label that contains another label ("Reason for call: fees" holds
    # "Reason for call") must be removed whole, or the shorter one leaves a fragment.
    for label in sorted(set(declared), key=len, reverse=True):
        if label:
            residue = residue.replace(label, " ")
    if _DIGIT_RUN.search(residue):
        raise CallContentLeakError(
            "the rendered digest carries a run of 5+ digits outside the client's own "
            "wording, which no count in it can produce — a phone number, an id or an "
            "amount has reached it (hard rule 6)"
        )


__all__ = [
    "EXTRACTION_KINDS",
    "MIN_CALLS_PER_PATTERN",
    "MIN_CALLS_PER_WINDOW",
    "PATTERN_KINDS",
    "CallContentLeakError",
    "CallOutcome",
    "CallPattern",
    "PatternKind",
    "Vocabulary",
    "answer_token",
    "assert_no_call_content",
    "assert_text_carries_no_call_content",
    "distil",
    "field_token",
    "outcome_token",
    "sentiment_token",
]
