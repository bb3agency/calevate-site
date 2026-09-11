"""May THIS voice be offered here, right now? — the offerability seam for the catalogue.

`agents/voices.py` answers "is this a voice we sell" (a reviewed commit). This module
answers the live question a picker has to answer on every render: "may a client be put on
it TODAY, on this deployment" — and, when not, WHY, in a sentence the person who can fix
it will recognise. It is the voice twin of `agents/llm_models.offerable_models()` /
`_operator_unofferable_reason()`, and it is deliberately the same shape: a pure predicate
per entry, grounds ordered by whose problem they are, `None` meaning offerable.

GROUND ZERO, WHICH APPLIES TO EVERY VOICE: HAS AN OPERATOR OFFERED IT? (D-588)
-------------------------------------------------------------------------------
The founder's requirement is that **only the voices they enable in the admin console are
selectable** — by a client for their own agent, and by an admin for anyone's. That is a
FOURTH ground, it is the one that applies to both providers, and it is checked FIRST
because it outranks the other three by ownership: whether a Cartesia key is installed is
not a question worth answering about a voice nobody has decided to sell.

It has three ways to fail, and they are three different sentences because they send an
operator to three different places:

* **`disabled`** — synced, known, switched off here. One click on the Voices page.
* **`archived`** — retired here. One click, from the archived list.
* **not curated at all** — the voice is in this process's catalogue snapshot but has no
  live row: it has been WITHDRAWN from the voice platform's own list (or the snapshot is
  older than the table). Nothing in this console fixes that; it is the vendor's statement
  about their account.

**IT IS MEASURED, NOT SNAPSHOTTED, AND THAT IS DELIBERATE.** Grounds 1-3 sit in in-process
snapshots refreshed on a 30-second poll. Curation is a row an operator changed ten seconds
ago on the screen they are still looking at, so it is read per request — one SELECT against
a platform-scoped table of tens of rows, on a picker render and a voice write, never on a
call path. An operator who enables a voice and cannot see it for half a minute reports a
bug; the poll bought nothing here.

**THE FOUR GROUNDS COMPOSE, AND NOTHING MASKS ANYTHING.** A voice can be enabled and still
unofferable because its price is unattested, and the reason a client reads is the one that
is actually deciding. `_deciding_ground` below is the single ordering.

THE THREE GROUNDS FOR THE CARTESIA TIER, AND THEIR THREE OWNERS (D-547 §4.C.2)
--------------------------------------------------------------------------------
1. **No Cartesia key installed** — the founder pastes one into the ops console
   (`Settings.cartesia_api_key`, probed live by `ops/secret_probes.py`).
2. **No attested Cartesia TTS price** — hard rule 7, the rule `offerable_models()` applies
   to an LLM (`NO_ATTESTED_PRICE_REASON`): an unpriced minute is unmetered spend, not a free
   one, and the only place the refusal is free is the selection. The predicate is INJECTED,
   and **Phase D wired it to the real attestation** (`ops/model_pricing.TtsPriceAttestation`,
   plan §3.5, D-547): `ops/pricing_snapshot.py` installs a reader over the
   attested-price store (`ops/model_pricing.tts_price_is_billable`) at startup and
   refreshes it on the same 30-second poll the LLM price readers use, so attesting a
   Cartesia price in the ops console makes the tier offerable within one poll — and
   immediately, because the attestation route refreshes the snapshot itself.
   `default_tts_price_is_billable` is what answers before any of that has happened.
3. **The platform-wide cap is reached** — `Settings.cartesia_agent_cap` (Q10): Cartesia's
   TTS is a monthly plan with a concurrency ceiling, so the third clinic on it forces the
   next plan rather than costing a third more, and nothing in a ledger would say so. The
   cap is a count of LIVE agents on the Cartesia tier across EVERY tenant; an operator
   raises it in the console after deciding to.

A Sarvam voice fails none of these: the key is the engine's own leg today, the price is on
the card, and there is no cap. What it does NOT escape is ground zero: a Sarvam voice
nobody has enabled is not offered either, which is the whole point of the founder's
requirement and the reason the curation check sits above the `provider == "sarvam"`
short-circuit rather than inside the Cartesia arm.

THE THREE SENTENCES ARE FOR AN OPERATOR, AND THE ROUTE IS CLIENT-READABLE
-------------------------------------------------------------------------
All three name a vendor and two name one of our own settings, and `GET /v1/agents/voices`
is `agents:read` in EITHER realm — a client is the Principal Entity and may read what their
agent sounds like. So the sentences fork by AUDIENCE, exactly as
`llm_models.unofferable_reason` already forks for a model: the operator keeps the ground
they can fix, and a client is told the one thing they can act on, in the tier's own
client-facing name ("Studio") rather than the vendor's. `None`-ness does not fork —
offerability is one fact — which is what lets `OfferedVoice.offerable` stay derived from
`reason` for both audiences.

WHY THE COUNT IS A PARAMETER AND THE CATALOGUE READ IS ASYNC
------------------------------------------------------------
`offerable_models()` is sync because all three of its facts sit in in-process snapshots.
Ground 3 here does not: it is a row count. So the PREDICATES (`unofferable_reason`,
`offerable_voices`) are sync and pure — they take the count — and `offered_catalogue()` is
the async caller that measures it, and only measures it when a Cartesia voice would
otherwise be offerable (a deployment with no Cartesia key opens no session for this).

THE CROSS-TENANT COUNT, AND WHY IT IS THE SHAPE IT IS (hard rule 1)
-------------------------------------------------------------------
`agents` is a tenant table with FORCEd RLS. `admin_session()` widens `organizations` and
NOTHING else (`apps/api/db/session.py`), so a single `SELECT count(*) FROM agents` under it
returns zero rows, honestly. The platform-scope reads this repository already makes —
`copilot/admin_tools.py` §1 and `admin/service.tenant_overview` — do it the one way RLS
permits: enumerate the directory under `app.admin`, then ENTER each tenant with its own
GUC and count there. `count_live_cartesia_agents` is that loop, in one function, so no
second reader of the cap can widen a policy to avoid it. It is N+1 by construction and
`tenant_overview` carries the measured number (3.3 ms per account); it runs only on the
picker and the voice write, never on a call path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.llm_models import LlmReasonAudience
from apps.api.agents.voice_curation import VoiceCuration, read_curation
from apps.api.agents.voices import CurationState, Voice, VoiceProvider, catalogue
from apps.api.billing.rates import voice_tier_label
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session

#: WHO a refusal sentence is written for. IMPORTED, never re-declared: "operator or client"
#: is one vocabulary and a second `Literal` beside it is where the two would come to spell
#: an audience differently (D-104). `llm_models.LlmReasonAudience` carries the argument for
#: the split; this module applies it to a voice.
VoiceReasonAudience = LlmReasonAudience

# --- ground 2: the price seam Phase D wires --------------------------------------

#: A sync predicate: is a minute on this provider's tier BILLABLE — attested, or read from
#: the vendor? The same contract `billing/rates.llm_price_is_billable` has for a model.
TtsPriceReader = Callable[[VoiceProvider], bool]


def default_tts_price_is_billable(provider: VoiceProvider) -> bool:
    """The answer BEFORE anything has been read from the price store.

    Sarvam's TTS cost is metered off the engine's own reported synthesizer leg, so that
    tier is billable with nothing attested; Cartesia's is attested by nobody until an
    operator reads an invoice. Not a placeholder that says yes — the honest reading of
    what this tree can price with no store behind it, and the SAME statement
    `ops/model_pricing.tts_price_is_billable` makes with an empty table.

    PUBLIC because `ops/pricing_snapshot.py` builds its cold snapshot from it (D-547).
    That module installs the real reader at startup and refreshes it off the request path,
    so between `install_pricing_readers()` and the first successful read there is a window
    in which the snapshot has measured nothing — and a snapshot that answered "no" there
    would refuse EVERY voice, Sarvam included, on a picker whose Sarvam tier needs no
    attestation at all. One definition, used in both places, is what stops that window
    from having its own rule (`tests/voice_tier_test.py` pins the two together).
    """
    return provider == "sarvam"


_price_reader: TtsPriceReader | None = None


def install_tts_price_reader(reader: TtsPriceReader | None) -> None:
    """Register where "is this tier priced" comes from. `None` uninstalls.

    The sibling of `agents/llm_models.install_llm_credential_reader` and
    `billing/rates.install_llm_price_attestations`, same shape for the same reason: the
    picker must not import the ops console, and it must stay exercisable with no database.
    **`ops/pricing_snapshot.install_pricing_readers` installs it** over the attested-price
    store (D-547, plan §4.D.1), beside the three LLM readers and refreshed by the same
    poll; until it is called — in a test, or in a process that never started the
    refresher — the default above answers.
    """
    global _price_reader
    _price_reader = reader


def tts_price_is_billable(provider: VoiceProvider) -> bool:
    """Ground 2, in one place."""
    reader = _price_reader or default_tts_price_is_billable
    return reader(provider)


# --- ground 1: the installed key ---------------------------------------------------


def cartesia_credential_installed() -> bool:
    """Is a Cartesia API key installed on this deployment?

    THE SAME READ THE CARTESIA ENGINE ADAPTER MAKES (`engine/__init__.py`), and the same
    class of read `llm_models.installed_llm_providers()` makes for Azure through
    `azure_credentials()`: `get_settings()`, into which the ops console's encrypted store is
    overlaid (`core/settings.apply_platform_overrides`). Not a second notion of "installed"
    — a key pasted in the console and a key injected from the secrets manager both land
    here, which is where the adapter would read it from. Blank-stripped for
    `azure_credentials`' reason: an operator clearing the field leaves `""`.
    """
    return bool((get_settings().cartesia_api_key or "").strip())


# --- the reasons: one sentence per ground, keyed by the ground --------------------

NO_CARTESIA_CREDENTIAL_REASON: Final = (
    "this platform holds no Cartesia API key, so a call on this voice would synthesise "
    "against nothing — install `cartesia_api_key` in the ops console"
)
NO_ATTESTED_TTS_PRICE_REASON: Final = (
    "nobody has recorded what the Cartesia voice tier costs on this account, and an "
    "unpriced minute is unmetered spend rather than a free one — attest the Cartesia TTS "
    "price in the ops console"
)


DISABLED_REASON: Final = (
    "this voice is switched off for the whole platform — enable it on the admin console's "
    "Voices page if it should be offered"
)
ARCHIVED_REASON: Final = (
    "this voice has been archived for the whole platform — restore it from the archived "
    "list on the admin console's Voices page if it should be offered again"
)
NOT_CURATED_REASON: Final = (
    "the voice platform no longer lists this voice on our account, so a call on it would "
    "be refused — it was removed or renamed there, and nothing in this console restores it"
)

#: What the CLIENT reads when curation is the deciding ground. It deliberately does NOT go
#: through `client_unofferable_reason`: that sentence names the tier ("the Studio voice is
#: not available on your account yet"), which is a claim about their PLAN, and it would be
#: simply false about a single persona an operator switched off. Names no vendor, no
#: setting and no console — the three things a client-readable route may not print.
CLIENT_NOT_OFFERED_REASON: Final = (
    "this voice is not one of the voices offered on your account — pick another from the "
    "list, or ask your account manager"
)


def curation_unofferable_reason(state: CurationState | None) -> str | None:
    """Ground zero, in one place: the OPERATOR's sentence for a voice nobody offers, or
    `None` when an operator has enabled it.

    `None` for `state` is not "unknown" and must not be softened into one — it is a voice
    the catalogue snapshot holds and the live table does not, which is what a withdrawal
    upstream looks like from here (`voice_sync.read_cached_catalogue` drops withdrawn rows,
    so the two disagree for exactly as long as one process's snapshot is stale, and forever
    if a client's agent is on a voice the vendor has removed).

    Failing CLOSED on the unknown is the safe direction and the only defensible one: the
    live `400` proving it — *"Provided voice: Anushka is not available for the provider:
    sarvam"* — is what happens when we offer a voice the platform does not have.
    """
    if state is None:
        return NOT_CURATED_REASON
    if state == "disabled":
        return DISABLED_REASON
    if state == "archived":
        return ARCHIVED_REASON
    return None


#: THE GROUNDS THAT MEAN "NOT ON OFFER HERE", as opposed to "offered, and currently
#: unavailable". A closed vocabulary because a SCREEN branches on it: the picker renders a
#: voice the platform intends to offer and cannot (no attested price, no credential, the
#: Cartesia cap) so its reason is read, and omits one the operator has simply not put on
#: offer — of which there are four hundred and sixteen.
#:
#: Derived from the sentence rather than returned beside it, so there is still ONE place
#: that decides why a voice is refused (`_operator_unofferable_reason`) and no second
#: switch to keep in step with it.
_NOT_ON_OFFER_SENTENCES: Final = frozenset({NOT_CURATED_REASON, DISABLED_REASON, ARCHIVED_REASON})


def is_not_on_offer(reason: str | None) -> bool:
    """Is this refusal "the operator has not put it on offer", rather than "it is offered
    and something is currently wrong with it"? See `_NOT_ON_OFFER_SENTENCES`."""
    return reason in _NOT_ON_OFFER_SENTENCES


def client_unofferable_reason(voice: Voice) -> str:
    """THE ONE SENTENCE A CLIENT SEES for any unofferable voice, whichever ground failed.

    The three grounds are collapsed for `llm_models.CLIENT_UNAVAILABLE_REASON`'s reason: a
    client has no ops console, no vendor account and no key, so which of the three is
    missing is not a distinction they can act on — and printing it would tell them to do
    something impossible while naming a vendor and one of our settings on a route their
    realm can read.

    It names the TIER, by the name a client is told the tier is called
    (`billing/rates.voice_tier_label` — "Clear", "Studio"), never the vendor: which company
    synthesises a tier is our business and must be able to change without a client-visible
    rename (founder, 7 Sep 2026).

    Lower-case and with no leading dash for the three operator grounds' reason: the picker
    completes "Cannot be chosen — {…}" with it.
    """
    return (
        f"the {voice_tier_label(voice.provider)} voice is not available on your account "
        "yet — ask your account manager"
    )


def cartesia_cap_reached_reason(*, cap: int, live: int) -> str:
    """Ground 3's sentence carries both numbers: an operator deciding whether to raise the
    cap needs to know how far past it the next agent would be."""
    return (
        f"the platform-wide Cartesia agent cap is reached ({live} live Cartesia agent(s), "
        f"cap {cap}) — a further agent on this tier forces the next Cartesia plan, so raise "
        "`cartesia_agent_cap` in the ops console only after deciding to"
    )


# --- the verdict -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OfferedVoice:
    """One catalogue voice and why it may not be chosen here — `reason` is `None` exactly
    when it may. Carried together so a picker cannot render the list and lose the verdict."""

    voice: Voice
    reason: str | None

    @property
    def offerable(self) -> bool:
        return self.reason is None


def _operator_unofferable_reason(
    voice: Voice, *, cartesia_live_agents: int, curation: VoiceCuration
) -> str | None:
    """The OPERATOR ground — which of the FOUR conditions failed, named so an operator can
    act on it. `unofferable_reason` is the audience-aware wrapper; this is its truth.

    **THE ONE PLACE THE FOUR GROUNDS ARE ORDERED**, by whose problem it is, exactly as
    `llm_models._operator_unofferable_reason` orders its three: a tier with no key cannot
    be fixed by attesting a price, so the key is reported first and the reader is sent to
    one action at a time. A voice failing two grounds gets the earlier sentence.

    **CURATION IS FIRST AND IS ABOVE THE `sarvam` SHORT-CIRCUIT (D-588).** It is the only
    ground that applies to both providers, and it outranks the rest by ownership: whether a
    Cartesia key is installed is not worth telling anybody about a voice this platform has
    not decided to sell. Putting it below the short-circuit would have exempted every Sarvam
    voice from the founder's one requirement.

    Both facts are PASSED IN rather than read here — `cartesia_live_agents` from
    `count_live_cartesia_agents`, `curation` from `read_curation` — so this stays a pure
    function a test can drive through every arm without a database, which is what lets the
    picker and the write backstop provably ask the same question.
    """
    curated = curation_unofferable_reason(curation.get(voice.id))
    if curated is not None:
        return curated
    if voice.provider == "sarvam":
        return None
    if not cartesia_credential_installed():
        return NO_CARTESIA_CREDENTIAL_REASON
    if not tts_price_is_billable(voice.provider):
        return NO_ATTESTED_TTS_PRICE_REASON
    cap = get_settings().cartesia_agent_cap
    if cartesia_live_agents >= cap:
        return cartesia_cap_reached_reason(cap=cap, live=cartesia_live_agents)
    return None


def unofferable_reason(
    voice: Voice,
    *,
    cartesia_live_agents: int,
    curation: VoiceCuration,
    audience: VoiceReasonAudience = "operator",
) -> str | None:
    """Why `voice` cannot be offered here, or `None` when it can — in the AUDIENCE's language.

    `None` MEANS THE SAME THING FOR BOTH AUDIENCES: offerability is one fact, so this returns
    `None` for exactly the offerable voices whichever audience asks. Only the SENTENCE for an
    unofferable one differs — the operator gets the ground they can fix, the client gets the
    one action they have (`client_unofferable_reason`). Keeping the None-ness
    audience-independent is what lets `OfferedVoice.offerable` be derived from the reason
    without the flag and the sentence ever disagreeing.

    Default `"operator"` so every existing caller — the write backstop, the tests — keeps its
    behaviour unchanged; the client realm opts in, at the route, by realm.

    **THE CLIENT SENTENCE FORKS ON WHICH GROUND DECIDED (D-588).** For the three priced
    grounds it is `client_unofferable_reason`, which names the TIER and sends them to their
    account manager. For curation it is `CLIENT_NOT_OFFERED_REASON`, because the tier
    sentence would be false about a single persona an operator switched off — it would tell
    a client their plan lacks a quality they are already paying for. The None-ness is still
    audience-independent, which is what keeps `OfferedVoice.offerable` derivable from the
    reason for either reader.
    """
    reason = _operator_unofferable_reason(
        voice, cartesia_live_agents=cartesia_live_agents, curation=curation
    )
    if reason is None or audience == "operator":
        return reason
    if curation_unofferable_reason(curation.get(voice.id)) is not None:
        return CLIENT_NOT_OFFERED_REASON
    return client_unofferable_reason(voice)


def offerable_voices(
    *,
    cartesia_live_agents: int,
    curation: VoiceCuration,
    voices: tuple[Voice, ...] | None = None,
    audience: VoiceReasonAudience = "operator",
) -> tuple[OfferedVoice, ...]:
    """EVERY catalogue voice with its verdict — never a shorter list.

    `voices=None` means "whatever is in force NOW" and is resolved in the body, never as a
    default argument: the catalogue is synced from the engine (D-585), so a module-level
    default would freeze whatever was installed at IMPORT and serve it for the life of the
    process — the picker would silently stop seeing a voice the operator cloned an hour ago.

    A picker that received only the offerable voices would render a Cartesia tier that
    silently does not exist on this deployment, and the operator who installed the key an
    hour ago would have no way to see that the price is what is still missing. The reason
    per voice is the product; the filtering is the caller's, if they want it.
    """
    voices = catalogue() if voices is None else voices
    return tuple(
        OfferedVoice(
            voice=voice,
            reason=unofferable_reason(
                voice,
                cartesia_live_agents=cartesia_live_agents,
                curation=curation,
                audience=audience,
            ),
        )
        for voice in voices
    )


async def offerability_of(voice: Voice, *, state: CurationState) -> str | None:
    """The OPERATOR's verdict for ONE voice whose curation state the caller already knows —
    `None` when it may be offered.

    **IT EXISTS FOR THE WRITE THAT HAS NOT COMMITTED YET** (D-590). `offered_catalogue`
    measures curation with `read_curation()`, which opens its own session and therefore
    cannot see the row `voice_admission.admit_voice` just wrote inside the request's
    transaction — so an operator adding their first Cartesia voice would be told it was
    unofferable because "the platform no longer lists it", which is both wrong and alarming.
    The state is passed in instead, and everything else goes through the SAME four-ground
    ordering the picker uses, so the sentence on the add response and the sentence in the
    picker cannot come to disagree.

    **THIS IS WHERE THE CARTESIA CAP GETS ITS NAME SAID OUT LOUD.** If every agent ends up on
    a cloned — therefore Cartesia — voice, every agent is on the dearer tier and the third
    live one meets `Settings.cartesia_agent_cap`. `cartesia_cap_reached_reason` prints the
    cap, the live count and what raising it commits the platform to, so the refusal reads as
    a decision somebody made rather than as a bug.
    """
    needs_count = voice.provider == "cartesia" and cartesia_tier_could_be_offered()
    live = await count_live_cartesia_agents() if needs_count else 0
    return unofferable_reason(
        voice, cartesia_live_agents=live, curation={voice.id: state}, audience="operator"
    )


def cartesia_tier_could_be_offered() -> bool:
    """Would ground 3 be the deciding ground for a Cartesia voice? True when the two cheap
    grounds pass — which is when, and only when, the count is worth measuring."""
    return cartesia_credential_installed() and tts_price_is_billable("cartesia")


# LIVE tenants only, by `deleted_at IS NULL` — the same predicate `admin/health.client_health`
# and `ops/engine_latency._DIRECTORY` resolve the directory with, spelled the same way so the
# three cannot come to mean different populations.
_DIRECTORY: Final = "SELECT id FROM organizations WHERE deleted_at IS NULL"

# ONE TENANT'S LIVE CARTESIA AGENTS. `status = 'live'` is the column every gate in this tree
# already branches on (`compliance/service.check_dispatch`, `campaigns/service.
# launch_blockers`); `draft`, `paused` and `archived` agents answer no calls and hold no
# concurrency. See `count_live_cartesia_agents` for why BOTH provider columns count.
_LIVE_CARTESIA_SQL: Final = (
    "SELECT count(*) FROM agents "
    "WHERE status = 'live' AND deleted_at IS NULL "
    "AND 'cartesia' IN (tts_provider, live_tts_provider) "
    "AND (CAST(:skip AS uuid) IS NULL OR id <> CAST(:skip AS uuid))"
)


async def count_live_cartesia_agents(*, exclude_agent_id: UUID | None = None) -> int:
    """LIVE agents on the Cartesia voice tier, across every tenant — the cap's measurement.

    The module docstring says why this is a directory read under `app.admin` followed by one
    count per tenant under that tenant's own GUC: it is the only shape RLS permits without
    widening a policy, and it is the shape `tenant_overview` and the admin copilot's
    platform tools already have. `tts_provider` is the column `set_agent_voice` writes
    beside the voice, and it is what `voice_tier()` would derive from the id, so counting on
    it does not introduce a second definition of the tier.

    `exclude_agent_id` is the agent whose voice is being SET: a live Cartesia agent moving
    to a different Cartesia persona is not a further agent on the tier, and counting it
    against itself would refuse a change that adds nothing to the plan.

    **CONFIGURED *OR* PUBLISHED, AND THE `OR` IS THE WHOLE ACCURACY OF THIS NUMBER.** An
    agent carries two provider columns: `tts_provider`, what an operator CHOSE, and
    `live_tts_provider`, what `publish_agent` recorded actually sending
    (`agents/models.py:225,247`). Counting the first alone misses a live agent whose row was
    switched back to Sarvam but which has not been republished — still speaking Cartesia on
    every call it answers. Counting the second alone misses a live agent already switched to
    Cartesia and about to be republished, which is precisely the agent the cap exists to stop
    before it forces the next plan. The tier's cost is driven by whichever of the two is
    Cartesia, so the count is the union, and it is deliberately conservative: this cap
    protects a monthly plan whose concurrency ceiling returns **429 with no queueing** —
    dead air on a live call — rather than an overage line on an invoice
    (`docs.cartesia.ai` concurrency docs, read 7 Sep 2026 and relayed in
    `docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md` ADDENDUM 1; gate 53 is the load test that
    replaces this rule of thumb with a measurement).
    """
    async with admin_session() as directory:
        tenants = [row[0] for row in (await directory.execute(text(_DIRECTORY))).all()]
    live = 0
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as scoped:
            live += int(
                (
                    await scoped.execute(text(_LIVE_CARTESIA_SQL), {"skip": exclude_agent_id})
                ).scalar_one()
            )
    return live


async def offered_catalogue(
    *,
    exclude_agent_id: UUID | None = None,
    voices: tuple[Voice, ...] | None = None,
    audience: VoiceReasonAudience = "operator",
) -> tuple[OfferedVoice, ...]:
    """The catalogue with its live verdicts — what `GET /v1/agents/voices` and the voice
    write both read, so the picker and the backstop cannot disagree.

    The count is measured only when it could decide anything: with no Cartesia key or no
    attested price the verdict is already known, and a deployment with no Cartesia voices
    in its catalogue opens no session at all.

    `audience` decides ONLY the wording of a refusal (see `unofferable_reason`), so the two
    realms read the same catalogue, get the same verdicts, and differ in exactly one
    sentence — the route picks it from the caller's realm.
    """
    voices = catalogue() if voices is None else voices
    curation = await read_curation()
    needs_count = cartesia_tier_could_be_offered() and any(
        voice.provider == "cartesia" for voice in voices
    )
    live = await count_live_cartesia_agents(exclude_agent_id=exclude_agent_id) if needs_count else 0
    return offerable_voices(
        cartesia_live_agents=live, curation=curation, voices=voices, audience=audience
    )


__all__ = [
    "ARCHIVED_REASON",
    "CLIENT_NOT_OFFERED_REASON",
    "DISABLED_REASON",
    "NOT_CURATED_REASON",
    "NO_ATTESTED_TTS_PRICE_REASON",
    "NO_CARTESIA_CREDENTIAL_REASON",
    "OfferedVoice",
    "TtsPriceReader",
    "VoiceCuration",
    "VoiceReasonAudience",
    "cartesia_cap_reached_reason",
    "cartesia_credential_installed",
    "cartesia_tier_could_be_offered",
    "client_unofferable_reason",
    "count_live_cartesia_agents",
    "curation_unofferable_reason",
    "default_tts_price_is_billable",
    "install_tts_price_reader",
    "offerability_of",
    "offerable_voices",
    "offered_catalogue",
    "read_curation",
    "tts_price_is_billable",
    "unofferable_reason",
]
