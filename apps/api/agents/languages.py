"""WHICH LANGUAGES THIS PRODUCT SELLS — the API-side half of the one declaration.

`calevate_shared.languages` says what the SPEECH STACK can do: 23 languages Sarvam's STT
can transcribe, 11 its TTS can speak, and the 11-language intersection an agent can
actually hold a call in. This module says what we OFFER, and it is the only place in
`apps/api` that DECLARES that set. Two other modules spell the same tags and neither is a
second declaration: `compliance/disclosure.py` and `agents/handoff.py` key their
per-language SENTENCES by them, which is content for a language rather than a list of
languages, and `tests/product_languages_test.py` holds both to the built set.

TWO SETS, AND THE DIFFERENCE IS WHO MAY SEE THEM (D-855, founder 23 Oct 2026).
* BUILT (`BUILT_LANGUAGES`): every language an agent can be stored in — the three always
  offered plus the staged ones (`calevate_shared.languages.STAGED_LANGUAGE_IDS`: Tamil,
  Kannada, Malayalam, Marathi). The wire enum, the CHECK constraints and the voice
  catalogue's language tags use this set, so turning a staged language on needs no
  deploy and no migration.
* OFFERED TO CLIENTS (`client_language_tags()`): the three, plus each staged language the
  console switch `staged_agent_languages_enabled` names AND whose readiness record
  (`STAGED_LANGUAGE_READINESS`) is complete. Read on every request from the in-memory
  settings (no IO), so every client input path (`OfferedLanguage`), the publish gate
  (`refuse_unoffered_language`) and the pickers (`GET /v1/agents/languages`) agree.
  The readiness record is checked at read time as well as at write time, so a row written
  into `platform_settings` around the console still offers nothing unreviewed.
* TEST ACCOUNTS (`staged_language_test_tenant_ids`): the switch refuses a language until
  one test call in it has been checked, and that call needs a published agent. So the
  operator's own test accounts are offered every staged language whose sentences are
  reviewed, through the same create, publish and call path a client uses.

WHY THE READINESS RECORD IS CODE AND NOT A CONSOLE ROW. What it vouches for is text in
this repository — the disclosure, recording, memory and handover sentences and the starter
openings — so the sign-off travels in the same review as the sentences it covers. A
console row could mark a sentence reviewed that a later commit changed.

WHY A `Literal` AT ALL, WHEN THE TAGS COULD BE DERIVED. Pydantic needs a STATIC type to
turn into an OpenAPI `enum`, and that enum is what gives the generated TypeScript client
its union (`apps/web/src/lib/api/schema.d.ts`) — so a computed tuple here would cost every
screen its exhaustiveness check. The Literal is therefore the ONE remaining hand-typed
copy of the tags, and it is held equal to `built_language_tags()` by
`tests/product_languages_test.py`, which fails if either side moves alone.

WHAT A WRONG LANGUAGE COSTS, AND WHY THE REFUSAL IS WRITTEN RATHER THAN GENERATED.
`Literal` alone refuses `xx-IN` with pydantic's own "Input should be 'te-IN', ..." — a
sentence `core/errors._LIBRARY_PHRASINGS` drops on purpose, because it is written for
whoever implemented the model. The three refusals below are written for whoever is holding
the request, and they differ because the MISTAKES differ: an unknown code is a typo, an
unoffered conversational language is a product boundary, and a comprehension-only language
is the dead-air failure `calevate_shared.languages` exists to prevent — the caller would be
heard perfectly and answered with silence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Final, Literal, get_args
from uuid import UUID

from calevate_shared import call_words
from calevate_shared.languages import (
    built_languages,
    find_language,
    offered_language_tags,
    staged_language_tags,
)
from pydantic import BeforeValidator

from apps.api.core.context import principal_var
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

__all__ = [
    "BUILT_LANGUAGES",
    "FALLBACK_REPLY_LANGUAGE",
    "LANGUAGE_LABELS",
    "MAX_REPLY_LANGUAGES",
    "STAGED_LANGUAGE_READINESS",
    "Language",
    "LanguageRefusedError",
    "OfferedLanguage",
    "StagedLanguageReadiness",
    "assert_default_language_offered",
    "assert_staged_languages_may_switch_on",
    "client_language_tags",
    "default_extra_languages",
    "default_primary_language",
    "default_reply_languages",
    "enabled_staged_tags",
    "every_client_language_tags",
    "language_refusal",
    "platform_default_language",
    "published_extra_languages",
    "readiness_note",
    "refuse_unoffered_language",
    "reply_languages_refusal",
    "staged_language_test_tenants",
]

#: EVERY LANGUAGE AN AGENT CAN BE STORED IN, as the wire and `agents.language_primary` spell
#: them: the three always offered (Telugu first, BRD §1 and the column's server default),
#: then the four staged ones (D-855). Never what a client is offered — that is
#: `client_language_tags()`.
#:
#: **THE ONLY HAND-TYPED COPY OF THESE TAGS IN `apps/`.** See
#: `calevate_shared.languages.OFFERED_LANGUAGE_IDS` for what else a new language needs in
#: the same change; `tests/product_languages_test.py` is red until all of it is there.
Language = Literal["te-IN", "hi-IN", "en-IN", "ta-IN", "kn-IN", "ml-IN", "mr-IN"]

#: The same tags as a tuple, for the callers that FILTER rather than type: the CHECK
#: constraints and the voice catalogue, which must hold a staged language's agents and
#: voices before any client can choose one.
BUILT_LANGUAGES: Final[tuple[Language, ...]] = get_args(Language)

#: How a language reads in a sentence a person approves — a copilot card, a picker, an
#: operator's table. From the shared declaration's `english_name`, so the label a client
#: reads and the label an operator reads are one string. Keyed by `str`: the keys ARE
#: `BUILT_LANGUAGES`, which `tests/product_languages_test.py` asserts.
LANGUAGE_LABELS: Final[Mapping[str, str]] = {
    row.bcp47: row.english_name for row in built_languages()
}


# --- the staged languages ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StagedLanguageReadiness:
    """What a person must put on record before a staged language can reach a caller
    (OPERATIONS §2 L-series, D-855). Every field starts empty; a reviewer fills it in the
    same commit that changes nothing else about the language."""

    #: The native speaker who reviewed every fixed sentence an agent speaks in this
    #: language: the AI disclosure, recording notice and caller-memory notice
    #: (`compliance/disclosure.py`), the handover line (`agents/handoff.py`) and the
    #: starter openings (`calevate_shared/spoken_style.json`). Until then each is
    #: NEEDS NATIVE-SPEAKER REVIEW.
    sentences_reviewed_by: str | None = None
    sentences_reviewed_on: date | None = None
    #: The day one test call in this language was listened to end to end.
    test_call_checked_on: date | None = None
    #: Where ThinnestAI confirmed the language works on a phone call (a reply's reference).
    #: Its docs list the language by name (mirror snapshots/2026-10-19/pages/api-reference/
    #: agents/create-agent.md:827-837); that is not the same as a call in it working.
    engine_confirmation: str | None = None
    #: The language's BCP-47 tag, for the checks read from data rather than recorded here.
    tag: str = ""

    def missing(self) -> tuple[str, ...]:
        """What is still to be put on record, in the words an operator reads."""
        gaps: list[str] = []
        if not opt_out_phrases_recorded(self.tag):
            gaps.append("its do-not-call phrases recorded")
        if not privacy_notice_recorded(self.tag):
            gaps.append("its caller privacy notice lines recorded")
        if not (self.sentences_reviewed_by and self.sentences_reviewed_on):
            gaps.append("a native speaker's review of its spoken sentences")
        if self.test_call_checked_on is None:
            gaps.append("one test call checked")
        if not self.engine_confirmation:
            gaps.append("ThinnestAI's confirmation that it works on a call")
        return tuple(gaps)

    @property
    def ready(self) -> bool:
        return not self.missing()

    @property
    def testable(self) -> bool:
        """Sentences reviewed: enough to offer the language in a test account
        (`staged_language_test_tenant_ids`) so the test call can be made."""
        return bool(self.sentences_reviewed_by and self.sentences_reviewed_on)


#: One record per staged language, none complete (23 Oct 2026).
STAGED_LANGUAGE_READINESS: Final[Mapping[str, StagedLanguageReadiness]] = {
    tag: StagedLanguageReadiness(tag=tag) for tag in staged_language_tags()
}


def opt_out_phrases_recorded(tag: str) -> bool:
    """Whether the do-not-call detector can hear "don't call me" in this language: the
    founder's phrases for it (`call_words.json`, `optout.patterns`, read by
    `compliance/optout`). A language without them may not reach a caller, or a caller's
    opt-out in it would never reach the do-not-call ledger (G5-2, TRAI)."""
    base = tag.split("-")[0].lower()
    return base == "en" or bool(call_words.table("optout.patterns").get(base))


def privacy_notice_recorded(tag: str) -> bool:
    """Whether the short caller privacy notice (`compliance/privacy_notice`) has lines in
    this language. A language without them would leave its clients' callers no notice they
    can read in it (DPDP §5(3)), so it may not be switched on until they are written."""
    # Imported here: the notice module reaches the agent models, which import this one.
    from apps.api.compliance.privacy_notice import has_notice_lines

    return has_notice_lines(tag)


def _chosen(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def enabled_staged_tags(raw: str | None = None) -> tuple[str, ...]:
    """The staged languages every client may choose now: named by the console switch AND
    ready. In declaration order, whatever order the switch lists them in."""
    value = get_settings().staged_agent_languages_enabled if raw is None else raw
    chosen = set(_chosen(value))
    return tuple(
        tag
        for tag in staged_language_tags()
        if tag in chosen and STAGED_LANGUAGE_READINESS[tag].ready
    )


def staged_language_test_tenants() -> frozenset[UUID]:
    """The accounts where a staged language with reviewed sentences is offered before it is
    switched on for everyone, so its test call can be made through the ordinary create,
    publish and call path. Empty, the default, means none. A malformed entry is dropped and
    logged (`retrieval/shadow.py`'s reason: a console typo must not fail a request)."""
    raw = (get_settings().staged_language_test_tenant_ids or "").strip()
    found: set[UUID] = set()
    dropped = 0
    for entry in _chosen(raw):
        try:
            found.add(UUID(entry))
        except ValueError:
            dropped += 1
    if dropped:
        log.error("staged_language_test_tenant_unparseable", extra={"dropped": dropped})
    return frozenset(found)


def _acting_tenant() -> UUID | None:
    principal = principal_var.get()
    return principal.tenant_id if principal is not None else None


def client_language_tags(tenant_id: UUID | None = None) -> tuple[str, ...]:
    """THE languages a client may choose, publish and be shown, right now.

    `tenant_id` is the account asking; omitted, it is the request's principal's. A test
    account (`staged_language_test_tenants`) also gets each staged language whose
    sentences are reviewed."""
    enabled = enabled_staged_tags()
    tenant = tenant_id if tenant_id is not None else _acting_tenant()
    if tenant is not None and tenant in staged_language_test_tenants():
        enabled = tuple(
            tag
            for tag in staged_language_tags()
            if tag in enabled or STAGED_LANGUAGE_READINESS[tag].testable
        )
    return _default_first(offered_language_tags() + enabled)


def every_client_language_tags() -> tuple[str, ...]:
    """The languages every client may choose, whoever is asking: the test accounts' extra
    staged languages left out. In declaration order."""
    return offered_language_tags() + enabled_staged_tags()


def _default_first(tags: tuple[str, ...]) -> tuple[str, ...]:
    """`tags` with the console's starting language moved to the front, so the first
    language a picker shows is the one a new agent starts in. With the default setting
    (Telugu) the order is the declaration's, unchanged."""
    chosen = get_settings().default_agent_language
    if chosen not in tags:
        return tags
    return (chosen, *(tag for tag in tags if tag != chosen))


def platform_default_language(tenant_id: UUID | None = None) -> str:
    """The language a new agent starts in when nothing about its business names one: the
    console's `default_agent_language`, or, when this account may not choose it (a staged
    language switched off after it was set), the first language the account may."""
    return client_language_tags(tenant_id)[0]


def assert_default_language_offered(raw: str | None) -> None:
    """Refuse a console write of a starting language some client may not choose: it would
    be skipped for them rather than honoured, which reads as the setting not working."""
    allowed = every_client_language_tags()
    if raw in allowed:
        return
    raise ProblemError.business_rule(
        "default_agent_language_not_offered",
        f"{raw} is not a language every client is offered.",
        remediation="Choose from "
        + ", ".join(f"{tag} ({LANGUAGE_LABELS[tag]})" for tag in allowed)
        + ".",
    )


def readiness_note(tag: str) -> str:
    """One line for the console: what this staged language still needs, or that it is ready."""
    gaps = STAGED_LANGUAGE_READINESS[tag].missing()
    if not gaps:
        return "Ready to offer."
    return "Cannot be switched on yet. Still needed: " + "; ".join(gaps) + "."


def assert_staged_languages_may_switch_on(raw: str) -> None:
    """Refuse a console write that names an unknown or unready staged language.

    Runs before the write (`ops/config_service.set_value`), so the switch can never hold a
    language whose sentences nobody has reviewed. Turning languages OFF is never refused.
    """
    unknown = [tag for tag in _chosen(raw) if tag not in STAGED_LANGUAGE_READINESS]
    if unknown:
        raise ProblemError.business_rule(
            "staged_language_unknown",
            f"{', '.join(unknown)} is not a staged agent language.",
            remediation="Choose from "
            + ", ".join(f"{tag} ({LANGUAGE_LABELS[tag]})" for tag in staged_language_tags())
            + ".",
        )
    unready = [tag for tag in _chosen(raw) if not STAGED_LANGUAGE_READINESS[tag].ready]
    if unready:
        raise ProblemError.business_rule(
            "staged_language_not_ready",
            " ".join(
                f"{LANGUAGE_LABELS[tag]} still needs "
                + "; ".join(STAGED_LANGUAGE_READINESS[tag].missing())
                + "."
                for tag in unready
            ),
            remediation=(
                "Finish its native-speaker review, its test call and the voice platform's "
                "confirmation, then switch it on."
            ),
        )


# --- refusals --------------------------------------------------------------------------


def _permitted(tenant_id: UUID | None = None) -> str:
    return ", ".join(f"{tag} ({LANGUAGE_LABELS[tag]})" for tag in client_language_tags(tenant_id))


def language_refusal(value: str) -> str:
    """Why this language is refused, in a sentence the caller can act on.

    THREE GROUNDS, because three different mistakes arrive here and only one of them is a
    typo. The comprehension-only arm is the one worth reading twice: Sarvam's STT can
    transcribe twelve languages its TTS cannot speak, so an agent configured in one of
    them would understand every caller and answer none. A staged language that is not
    switched on reads exactly like any other language we do not sell yet: a client is
    never told it exists.
    """
    row = find_language(value)
    if row is None:
        head = f"“{value}” is not a language code we recognise."
    elif row.comprehension_only:
        head = (
            f"An agent cannot be set to {row.english_name}: callers speaking it are "
            "transcribed accurately, but no voice on this platform can speak it back, so "
            "the agent would hear the caller and answer with silence."
        )
    else:
        head = f"Calevate does not offer {row.english_name} yet."
    return f"{head} Choose one of: {_permitted()}."


def _offered(value: object) -> object:
    """Refuse a language a client may not choose BEFORE the `Literal` does, so the sentence
    is ours. A `BeforeValidator`: after the Literal has rejected the value no field
    validator runs. Non-strings pass through to the Literal, which refuses them."""
    if isinstance(value, str) and value not in client_language_tags():
        raise LanguageRefusedError(language_refusal(value))
    return value


class LanguageRefusedError(ValueError):
    """`OfferedLanguage`'s refusal: a sentence written for the person, so a reader that
    otherwise hides validation messages (the copilot's `parse_args`) may pass it on."""


#: THE TYPE EVERY CLIENT WIRE FIELD THAT TAKES A LANGUAGE USES. Same OpenAPI enum as
#: `Language` (a `BeforeValidator` adds no JSON-schema of its own), narrowed at run time to
#: `client_language_tags()`.
#:
#: RESPONSE models use bare `Language`: what comes back is a column the CHECK constraint
#: already bounds, and an agent created while a staged language was on keeps reading back
#: after it is switched off.
OfferedLanguage = Annotated[Language, BeforeValidator(_offered)]


def refuse_unoffered_language(language_primary: str, *, tenant_id: UUID) -> None:
    """The publish gate: an agent whose main language clients may not choose right now is
    not put on the phone. Its extra languages are narrowed instead
    (`published_extra_languages`), since the main one is what its notices are spoken in."""
    if language_primary in client_language_tags(tenant_id):
        return
    row = find_language(language_primary)
    name = row.english_name if row is not None else language_primary
    raise ProblemError.business_rule(
        "agent_language_not_offered",
        f"{name} is not offered yet, so an agent speaking it cannot be published.",
        remediation=f"Change the agent's main language to one of: {_permitted(tenant_id)}.",
    )


# --- reply languages -----------------------------------------------------------------

#: The most languages an agent replies in, its main one included: the voice platform's own
#: ceiling ("one, or up to four", thinnest-findings/mirror/snapshots/2026-10-18/pages/
#: agent/behaviour.md:66-80; `languages` `maxItems: 4`, api-reference/agents/
#: update-agent.md:754-768).
MAX_REPLY_LANGUAGES: Final = 4

#: The language every new agent can also reply in when its creator names nothing else,
#: after the platform's starting language (founder decision, 18 Oct 2026: Telugu, then
#: English, with Telugu as that starting language).
FALLBACK_REPLY_LANGUAGE: Final[Language] = "en-IN"


def default_reply_languages(tenant_id: UUID | None = None) -> tuple[str, ...]:
    """What a new agent replies in when neither its creator nor its business names any:
    the platform's starting language, then English. The main language always comes first
    at publish, because it is the one the agent falls back to and its notices are in."""
    return tuple(dict.fromkeys((platform_default_language(tenant_id), FALLBACK_REPLY_LANGUAGE)))


def default_primary_language(
    business: Sequence[str] | None, *, tenant_id: UUID | None = None
) -> str:
    """The main language of a new agent whose creator named none.

    The first of the business profile's languages this account may choose right now, so a
    Hindi-speaking business is not handed a Telugu agent; else the platform's starting
    language. A profile language that is staged and switched off is skipped rather than
    refused, because nobody chose it for this agent."""
    allowed = client_language_tags(tenant_id)
    for tag in business or ():
        if tag in allowed:
            return tag
    return platform_default_language(tenant_id)


def default_extra_languages(
    primary: str, business: Sequence[str] | None = None, *, tenant_id: UUID | None = None
) -> list[str]:
    """The extra languages a new agent is created with (founder, 18 Oct 2026).

    The business profile's languages when it lists any (`business_profiles.languages`, the
    starting list for agents created from now on), else the default pair; either way after
    the main language, each once, at most `MAX_REPLY_LANGUAGES` in all. Without a business
    list, and with Telugu as the starting language, a Telugu agent replies in Telugu then
    English, an English one in English then Telugu, a Hindi one in Hindi, Telugu and
    English."""
    source = business if business else default_reply_languages(tenant_id)
    return published_extra_languages(primary, source, tenant_id=tenant_id)[
        : MAX_REPLY_LANGUAGES - 1
    ]


def reply_languages_refusal(languages: Sequence[str]) -> str | None:
    """Why this ordered list of reply languages is refused, or None when it is usable.
    The tags themselves are checked by `OfferedLanguage`; this is the list's own shape."""
    if not languages:
        return "Choose at least one language for the agent to reply in."
    if len(languages) > MAX_REPLY_LANGUAGES:
        return f"An agent replies in at most {MAX_REPLY_LANGUAGES} languages."
    if len(set(languages)) != len(languages):
        return "Each language can be chosen only once."
    return None


def published_extra_languages(
    primary: str, stored: Sequence[str] | None, *, tenant_id: UUID | None = None
) -> list[str]:
    """The extra languages an agent is published with, from `agents.languages_extra`.

    Languages clients may choose right now only, never the primary, each once, in the
    order stored. A staged language switched off after an agent took it is dropped here
    at the next publish, rather than refusing the agent: its main language still carries
    every notice.
    """
    allowed = client_language_tags(tenant_id)
    extra: list[str] = []
    for tag in stored or ():
        if tag in allowed and tag != primary and tag not in extra:
            extra.append(tag)
    return extra
