"""The Voices panel's API — the voices this platform has ADDED, and their states (D-590).

    GET   /v1/ops/voices          the voices somebody decided about (`?scope=all` for every
                                   cached row), each with its state, its provenance, when it
                                   was last seen and how many live agents are on it
    POST  /v1/ops/voices          ADD ONE VOICE by typing its facts — verified against the
                                   voice platform's own list before it is accepted (audited)
    PATCH /v1/ops/voices          move ONE voice to enabled | disabled | archived (audited)

The refresh that fills the cache is `POST /v1/ops/voices/refresh`
(`apps/api/ops/routes.py`), which already existed and is unchanged.

⚠ **THIS PANEL USED TO BE A CURATION SCREEN AND IS NOW AN ADD SCREEN (D-590, superseding the
console half of D-588).** D-588 opened with "Offered 4 of 418" and 414 vendor personas to
switch off. The founder's answer: *"these are too much. we will not actually be using any
voices provided by either sarvam or cartesia and will only be using cloned voices … I should
be able to add voices … where I can provide you everything that you need a voice to be added
and working."*

**Bolna's voice API is READ-ONLY** — two GET routes and no create, update or delete anywhere
in their published API (VERIFIED-VENDOR-DOCS, hash-pinned mirror,
`bolna-findings/mirror/pages/api-reference/voice/overview.md:10-18`, enumerated 11 Sep 2026)
— and that premise is unchanged. What changed is the conclusion drawn from it: a voice is
CLONED in their Playground's Voice Lab, and then ADDED HERE by typing the facts the
synthesizer block needs, which we CHECK against their own list before writing the row
(`apps/api/agents/voice_admission.py` carries the full argument, including why an unreadable
platform is a refusal rather than an unverified row).

WHY `ops:manage` AND NOT `platform:config` OR `admin:tenants`
---------------------------------------------------------------
`POST /v1/ops/voices/refresh` — the other half of this one screen, and the thing this panel
is built around — is already `ops:manage`, and a panel whose Refresh an operator may press
and whose Enable they may not would be a screen that half works for exactly one role.

It is not `platform:config`: that permission is the vendor-credential and platform-settings
surface (`ops/config_routes.py`, `ops/secret_routes.py`), where the blast radius is pointing
the platform at another vendor account. It is not `admin:tenants` either, which `core/rbac`
defines as "act on ONE client" — this decides what EVERY client may choose, which is the
distinction that permission exists to keep. Both `ops:manage` and `platform:config` are
superadmin-only (`core/rbac.SUPERADMIN_ONLY_PERMISSIONS`), so "only the super admin reaches
this panel" holds either way; what the choice settles is which panel it belongs to.

WHY THE VOICE ID IS IN THE BODY AND NOT IN THE PATH
-----------------------------------------------------
Every other single-object ops write in this tree names its subject in the path
(`/v1/ops/model-prices/{model}`, `/v1/ops/tts-prices/{provider}`), and the reason is good:
the access log, the console's URL and the audit row then show the same string.

This one does not, and it is a deliberate exception rather than an oversight. A catalogue id
is `<tts_model>:<speaker>` and **we own only the first half**: the second is whatever the
voice platform calls a voice, including a name the founder typed when cloning one. We have
no vendor statement about that alphabet — their voice schema types `voice_id` as a bare
string (`api-reference/voice/get_all.md`) — so a path segment would be a bet that no voice
id ever contains a `/` or a `%`, settled by a 404 on the one clone it breaks. Hard rule 12:
the check is not available, so do not act on the guess. `voice_id` is bounded and the audit
row carries it, which is the property the path was wanted for.

That also makes the write ONE route rather than three. Enable, disable and archive are one
transition with three destinations, and three routes would be three audit actions, three
console hooks and three places for the vocabulary to drift from `voices.CurationState`.

WHY NO STEP-UP GATE
---------------------
Argued in full, and pinned, in `tests/authn_stepup_test.py::_OPS_WRITES_WITHOUT_STEP_UP` —
which is where an exemption on this router has to be stated rather than remembered. In
short: this write cannot reach a call. It touches no agent row, calls no vendor, and cannot
move an agent off the voice it is speaking (a published agent holds its voice on the engine,
and `voices.catalogue()` keeps resolving a disabled id on the publish path). Its widening
direction cannot bypass money either — enabling a voice clears offerability ground zero and
leaves grounds 1-3 exactly where they were, so an unpriced Cartesia minute is still refused
by `voice_offer.py` (hard rule 7). And it is a CURATION screen: an operator reviewing a
freshly synced catalogue toggles rows in one sitting, which is precisely the surface where a
typed confirmation becomes a reflex and stops meaning anything on `outbox/replay`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, get_args

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.voice_admission import (
    OUR_PROVIDERS,
    UNPUBLISHABLE_CLONING_PROVIDERS,
    VOICE_LAB_URL,
    VoiceFacts,
    admit_voice,
    unpublishable_provider_reason,
)
from apps.api.agents.voice_curation import (
    CuratedVoice,
    VoiceScope,
    count_cached_voices,
    count_offered_voices,
    list_curated_voices,
    set_curation_state,
)
from apps.api.agents.voice_offer import offerability_of
from apps.api.agents.voice_sync import load_voice_catalogue
from apps.api.agents.voices import (
    CurationState,
    Language,
    TtsModel,
    Voice,
    VoiceOrigin,
    catalogue_source,
    tts_models_for_provider,
)
from apps.api.billing.rates import voice_tier_label
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.rbac import permission_meta
from apps.api.engine import get_engine

router = APIRouter(prefix="/v1/ops/voices", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
VoiceCurator = Annotated[Principal, Depends(requires("ops:manage", realm="admin"))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CuratedVoiceOut(Strict):
    """One row of the Voices table.

    A SUPERSET of the catalogue `Voice` rather than an envelope around it, for
    `OfferedVoiceOut`'s reason in `agents/voice_routes.py`: the operator's table and the
    client's picker describe one voice, and nesting it would give the console two shapes to
    render the same thing in.
    """

    #: The catalogue id — what `agents.tts_voice` holds and what this API's PATCH names.
    voice_id: str
    #: What the voice platform calls this voice. A WIRE value as well as a human one.
    label: str
    #: The VENDOR. Shown on this console and nowhere a client can read, because an operator
    #: reconciling an invoice needs it (the same rule `ModelPricingPanel` states).
    provider: str
    #: What a CLIENT is told the quality is called ("Clear", "Studio") —
    #: `billing/rates.voice_tier_label`. On the wire beside `provider` rather than looked up
    #: in the browser: a second copy of a client-visible name is how the two drift.
    tier_label: str
    tts_model: str
    #: The identifier the engine wants in its synthesizer block.
    engine_voice_id: str
    languages: list[str]
    #: `platform` (one of the voice platform's stock voices) or `custom` (imported or cloned
    #: on our own account). The engine's OWN vocabulary, carried rather than re-derived —
    #: `api-reference/voice/get_all.md:172-179` defines the two values.
    source: str
    #: `enabled` | `disabled` | `archived` — `voices.CurationState`.
    state: CurationState
    #: `operator` (somebody typed this voice's facts here and the platform confirmed them) or
    #: `synced` (a sync read it off the platform's list and nobody has attested it) —
    #: `voices.VoiceOrigin`. The console groups on it: added voices are the product, cached
    #: ones are the substrate.
    origin: VoiceOrigin
    #: Would this voice clear offerability GROUND ZERO? `state == "enabled"` and still
    #: listed by the platform. NOT the whole verdict: a Cartesia voice can be enabled and
    #: still unofferable for an unattested price, which `GET /v1/agents/voices` answers per
    #: audience. Derived server-side so a screen cannot compose it from two fields and get
    #: the withdrawn case wrong.
    offered: bool
    #: When the sync that last SAW this voice ran.
    synced_at: datetime
    #: When an operator last moved `state`, or null for a voice nobody has reviewed. The
    #: console renders those two differently, which is the whole reason it is nullable
    #: rather than defaulted to the row's creation.
    curated_at: datetime | None
    #: When the voice platform stopped listing this voice, or null while it still does. A
    #: withdrawn voice cannot be offered whatever `state` says, and no click here restores
    #: it — it comes back if and when the platform lists it again.
    withdrawn_at: datetime | None
    #: LIVE agents across every tenant configured with, or published on, this voice. Shown
    #: beside the controls so an operator archives with the number in view. It is NEVER a
    #: veto: see `agents/voice_curation.py` for why refusing would be the worse failure.
    live_agents: int

    @classmethod
    def of(cls, row: CuratedVoice) -> CuratedVoiceOut:
        voice: Voice = row.voice
        return cls(
            voice_id=voice.id,
            label=voice.label,
            provider=voice.provider,
            tier_label=voice_tier_label(voice.provider),
            tts_model=voice.tts_model,
            engine_voice_id=voice.speaker,
            languages=list(voice.languages),
            source="custom" if row.is_custom else "platform",
            state=row.state,
            origin=row.origin,
            offered=row.offered,
            synced_at=row.synced_at,
            curated_at=row.curated_at,
            withdrawn_at=row.withdrawn_at,
            live_agents=row.live_agents,
        )


class CuratedVoicesOut(Strict):
    """The whole cached catalogue AND what an operator needs to read it.

    NO FIELD HAS A DEFAULT, for `VoiceCatalogueOut`'s reason: a Pydantic default makes the
    field optional in the generated TypeScript, and every one of these is a fact the console
    must be able to trust rather than treat as falsy when absent.
    """

    #: Every cached voice — still-listed first, withdrawn last. NEVER filtered: a voice
    #: missing from this response is indistinguishable from a voice the platform does not
    #: have, and telling those apart is the whole job of this screen.
    voices: list[CuratedVoiceOut]
    #: `"engine"` (a sync has read the platform's list) or `"unsynced"` (none ever has, so
    #: this process offers no voices at all). `agents/voices.CatalogueSource`.
    source: str
    #: How many voices this process is currently offering, i.e. how many cleared ground
    #: zero. Zero with `source: "engine"` means "synced, nothing enabled" — a different
    #: state from "never synced", and the one a Refresh will not fix.
    offered: int
    #: Which rows `voices` holds — `decided` (the default: added voices plus any synced voice
    #: somebody moved off the arrival state) or `all`.
    scope: VoiceScope
    #: How many voices are in the cache ALTOGETHER. Reported beside a `decided` list so an
    #: operator reading three rows is TOLD the platform lists four hundred rather than shown
    #: a short list pretending to be the whole one (D-590).
    cached: int
    #: One sentence the console prints verbatim, saying which of those states this is.
    note: str
    #: Everything the Add-a-voice form needs, from the server — see `AddVoiceFormOut`. On the
    #: LIST response rather than on a route of its own because the page renders the form and
    #: the table together, and two round trips for one screen is two chances to render half
    #: of it.
    form: AddVoiceFormOut


class VoiceProviderOptionOut(Strict):
    """ONE PROVIDER THE ADD FORM OFFERS — including the ones it offers only to REFUSE.

    **ELEVENLABS IS ON THIS LIST ON PURPOSE, WITH `selectable: false` AND ITS REASON.** The
    voice platform clones on ElevenLabs or Cartesia; this product runs Sarvam and Cartesia.
    An operator who has just spent a voice sample cloning on ElevenLabs and finds no such
    option concludes the console is broken and tries again; an operator who finds it greyed
    out with a sentence learns, in the one place it matters, that the clone has to be redone
    on Cartesia. Omitting it would be the silent failure, not the tidy one.
    """

    provider: str
    #: What a CLIENT is told this quality is called, or null for a provider we do not run
    #: (there is no tier, which is precisely why we cannot publish it).
    tier_label: str | None
    #: The TTS models this product runs on this provider, in catalogue order. Empty for a
    #: provider we do not run.
    models: list[TtsModel]
    selectable: bool
    #: Non-null exactly when `selectable` is false — the sentence the form prints beside the
    #: disabled option.
    unavailable_reason: str | None


class AddVoiceFormOut(Strict):
    """EVERYTHING THE ADD FORM NEEDS, from the server.

    The browser composes none of it. Which providers exist, which models run on them, which
    languages this product sells and why ElevenLabs is refused are all facts with a single
    source in `agents/voices.py` and `agents/voice_admission.py`, and a second copy in
    TypeScript is the copy that goes stale the day a model changes.
    """

    providers: list[VoiceProviderOptionOut]
    #: The product's languages, Telugu first — `voices.Language`, in picker order.
    languages: list[Language]
    #: Where the operator gets the voice id and the name. A URL in server-composed copy
    #: rather than in the page, so it is stated once.
    voice_lab_url: str


def _form() -> AddVoiceFormOut:
    """The form's options, derived from the catalogue rather than typed.

    `OUR_PROVIDERS` comes from the model registry and `UNPUBLISHABLE_CLONING_PROVIDERS` from
    the cloning-provider reading, so this function adds no fact of its own — it only decides
    the ORDER, which is ours: what you can pick first, what you cannot pick last.
    """
    return AddVoiceFormOut(
        providers=[
            VoiceProviderOptionOut(
                provider=provider,
                tier_label=voice_tier_label(provider),
                models=list(tts_models_for_provider(provider)),
                selectable=True,
                unavailable_reason=None,
            )
            for provider in OUR_PROVIDERS
        ]
        + [
            VoiceProviderOptionOut(
                provider=provider,
                tier_label=None,
                models=[],
                selectable=False,
                unavailable_reason=unpublishable_provider_reason(provider),
            )
            for provider in sorted(UNPUBLISHABLE_CLONING_PROVIDERS)
        ],
        languages=list(get_args(Language)),
        voice_lab_url=VOICE_LAB_URL,
    )


class AddVoiceIn(Strict):
    """THE FACTS FOR ONE CLONED VOICE, as an operator types them.

    Every field is BOUNDED here and VERIFIED in `agents/voice_admission.py`: this layer stops
    a megabyte of junk reaching a vendor call, and that layer decides whether the voice
    platform agrees. `provider` and `tts_model` are bare strings rather than Literals on
    purpose — a Literal would make an ElevenLabs choice a 422 from the framework with a
    schema dump for a body, and the whole point is that it is refused with a SENTENCE.
    """

    #: Who synthesises the voice. Cross-checked against `tts_model`, then discarded — the
    #: billing tier is derived from the voice id's model prefix and nothing else (hard
    #: rule 7, `voices.voice_tier`).
    provider: str = Field(min_length=1, max_length=64)
    #: The model the voice runs on — the vendor's `model` key.
    tts_model: str = Field(min_length=1, max_length=64)
    #: The id the voice platform knows it by — their `voice_id`, the provider-specific
    #: identifier, NOT the name. Opaque: never parsed, never normalised.
    engine_voice_id: str = Field(min_length=1, max_length=128)
    #: The name the voice platform shows. A WIRE value as well as a human one — it travels
    #: in the vendor's required `voice` key on every publish — so it is checked against the
    #: platform's own spelling rather than accepted.
    label: str = Field(min_length=1, max_length=200)
    #: Which of this product's languages the voice serves. At least one, or the voice appears
    #: on no picker at all; each is checked against the languages the platform lists it under.
    languages: list[Language] = Field(min_length=1, max_length=8)


class AddVoiceOut(Strict):
    """The voice as it now stands, and whether anybody can actually be put on it yet."""

    voice: CuratedVoiceOut
    #: How many voices this platform offers AFTER the add.
    offered: int
    #: Can an agent be put on this voice right now? Adding it clears offerability ground zero
    #: and nothing else, so a Cartesia voice can be added and still refused for an unattested
    #: price, a missing key, or the Cartesia agent cap.
    offerable: bool
    #: Non-null exactly when `offerable` is false: the OPERATOR's ground, naming what to fix.
    unofferable_reason: str | None
    #: One sentence the console prints verbatim — what this add did, and what is left.
    next_step: str


class SetCurationIn(Strict):
    """One voice, one destination state.

    `extra="forbid"` so a caller cannot smuggle a second field into a request whose whole
    point is one decision — and so a console still sending an older spelling is told,
    instead of having it dropped while the row moves anyway.
    """

    #: Bounded before it is looked up, so a megabyte of junk is a validation error rather
    #: than a dictionary probe. Membership in the cache is the real check, and it answers
    #: 404. See the module docstring for why this is a body field and not a path segment.
    voice_id: str = Field(min_length=1, max_length=128)
    #: The three states, typed from `voices.CurationState` — one vocabulary, so a fourth
    #: value could never be accepted here and refused by the database's CHECK constraint.
    state: CurationState


class SetCurationOut(Strict):
    """The row as it now stands, plus what changed in this process because of it."""

    voice: CuratedVoiceOut
    #: How many voices this process offers AFTER the change. The console prints it so an
    #: operator disabling the last enabled voice sees the consequence immediately rather
    #: than discovering it on a client's picker.
    offered: int
    #: One sentence the console prints verbatim — what this click did and did not do.
    next_step: str


def _note(*, offered: int, shown: int) -> str:
    """The Voices page's own state sentence. Composed here, never in the browser, for the
    reason every `note` in this tree is: a screen that paraphrases "added but not offerable"
    as "no voices" is how a working platform gets reported as broken.

    **IT NO LONGER BRANCHES ON `catalogue_source` (D-590).** "Nobody has synced" used to be
    the interesting empty state, because a sync was the only way a voice could exist. Adding
    a voice needs no sync — the operator types the facts and we verify them live — so the
    empty state now has exactly one cause and one action, and telling an operator to press
    Refresh would send them to the wrong button.
    """
    if shown == 0:
        return (
            "No voice has been added yet, so no client and no admin can choose a voice for "
            "any agent. Add the voices you have cloned on the voice platform — you will "
            "need the voice id and the name it shows there."
        )
    if offered == 0:
        return (
            "Voices have been added, but none can currently be offered — the picker says "
            "why for each one. A voice can be added and still unofferable for a separate "
            "reason: an unattested price, a missing vendor key, or the Cartesia agent cap."
        )
    return (
        "These are the voices this platform has added. Only these can be chosen for an "
        "agent, by a client for their own or by an admin for anyone's."
    )


def _next_step(row: CuratedVoice) -> str:
    """What this click did, in one sentence, INCLUDING what it deliberately did not do.

    The live-agent sentence is the important one and it is the reason this is not a generic
    "saved": an operator who has just archived a voice with agents on it needs to read that
    nothing broke, in the same breath as the confirmation, rather than go looking.
    """
    if row.withdrawn:
        return (
            "Saved, but the voice platform no longer lists this voice, so it cannot be "
            "offered whatever state it is in here. The state is kept for the day it "
            "returns."
        )
    if row.state == "enabled":
        return (
            "Clients and admins can now choose this voice for an agent. A voice may still "
            "be unavailable for a separate reason — an unattested price or a missing vendor "
            "key — which the picker states per voice."
        )
    held = row.live_agents
    if held:
        return (
            f"This voice can no longer be chosen for an agent. {held} live agent(s) are "
            "already on it and are NOT affected — they keep speaking it on every call, and "
            "they keep publishing it. Moving them is a separate, deliberate act on each "
            "agent."
        )
    return "This voice can no longer be chosen for an agent. No live agent is on it."


@router.get(
    "",
    response_model=CuratedVoicesOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="The voices this platform has added (admin realm)",
    description=(
        "By default, the voices somebody has decided about: every voice added here, plus "
        "any voice a sync cached that an operator moved off the arrival state. Voices the "
        "platform has since stopped listing are shown last and marked.\n\n"
        "Only `enabled` voices can be chosen for an agent, by a client or by an admin. "
        "`cached` says how many voices are in the cache altogether; `?scope=all` returns "
        "them, which is a reference list rather than a to-do list — a voice does not have "
        "to be cached before it can be added."
    ),
)
async def list_voices(
    session: GlobalSession,
    _: VoiceCurator,
    scope: Annotated[
        VoiceScope,
        Query(description="`decided` (default) or `all` — see the response's `scope`."),
    ] = "decided",
) -> CuratedVoicesOut:
    """The table. One read of the cache, plus one live-agent count per tenant.

    The count is the only expensive part and it is bounded by the tenant directory, which
    is this product's client list. It runs on an operator's page load and nowhere else —
    never on a picker render, never on a call path.
    """
    rows = await list_curated_voices(session, scope=scope)
    offered = sum(1 for row in rows if row.offered)
    return CuratedVoicesOut(
        voices=[CuratedVoiceOut.of(row) for row in rows],
        source=catalogue_source(),
        offered=offered,
        scope=scope,
        cached=await count_cached_voices(session),
        note=_note(offered=offered, shown=len(rows)),
        form=_form(),
    )


def _added_next_step(row: CuratedVoice, *, reason: str | None) -> str:
    """What the add did, in one sentence, INCLUDING what is still in the way.

    The unofferable case is the one that earns this function. An operator who has just added
    their third cloned voice and is told only "saved" will go looking for the agent picker
    and find nothing — the Cartesia agent cap, an unattested price or a missing key is the
    actual state, and it is a decision somebody has to make rather than a fault. So the
    ground is printed here, in the same breath as the confirmation.
    """
    if reason is not None:
        return (
            f"{row.voice.label} was added and verified against the voice platform, but no "
            f"agent can be put on it yet: {reason}."
        )
    return (
        f"{row.voice.label} was added, verified against the voice platform, and can now be "
        "chosen for an agent — by a client for their own, or by an admin for anyone's."
    )


@router.post(
    "",
    response_model=AddVoiceOut,
    status_code=201,
    openapi_extra=permission_meta("ops:manage"),
    summary="Add one voice by its facts, verified against the voice platform (audited)",
    description=(
        "Adds ONE voice — normally one cloned in the voice platform's Voice Lab — by the "
        "facts its synthesizer block needs: the provider, the model, the voice id that "
        "platform knows it by, the name it shows there, and which of this product's "
        "languages it serves.\n\n"
        "**Every fact is checked against the voice platform's own list before the voice is "
        "accepted.** An id that platform does not list is refused by name, because "
        'publishing an agent on it would fail at create time with "not available for the '
        "provider\" — on a client's phone line rather than on this screen. If that list "
        "cannot be read, the add is REFUSED and retryable: an unverified voice is the exact "
        "failure this check exists to prevent.\n\n"
        "An added voice arrives ENABLED — typing its facts is the decision to offer it. It "
        "can still be unofferable for a separate reason (an unattested price, a missing "
        "vendor key, the Cartesia agent cap), and the response says which.\n\n"
        "Idempotent: adding a voice already in the cache adopts it — the row becomes an "
        "operator-attested, enabled one, and any withdrawal stamp is cleared."
    ),
)
async def add_voice(
    payload: AddVoiceIn,
    session: GlobalSession,
    request: Request,
    principal: VoiceCurator,
) -> AddVoiceOut:
    """The add. Verify, write the row, audit it, then install the new catalogue.

    **THE SNAPSHOT IS RELOADED HERE AND DELIBERATELY IS NOT IN `set_voice_curation`**, and
    the asymmetry is the point rather than an oversight. Curation changes no voice's
    EXISTENCE — `voices.catalogue()` is the lookup layer and keeps resolving a disabled id so
    a live agent goes on publishing — and offerability reads curation from the table on every
    render, so that write needs no install. This one adds a row the snapshot does not have,
    and until the snapshot has it `speech_for_voice_id` cannot split the id and the picker
    cannot render it. `load_voice_catalogue` reads back inside this transaction, exactly as
    `refresh_voice_catalogue_route` does; other API processes pick it up within one poll of
    `ops/pricing_snapshot`'s refresher.

    **THE AUDIT ROW IS IN THE SAME TRANSACTION AS THE WRITE** (BACKEND-PATTERNS §4). The
    provenance of a typed row is the one fact in this table that re-running the sync cannot
    reconstruct, and a row claiming an operator attested a voice with no record of which
    operator would be worse than no row at all.
    """
    row = await admit_voice(
        session,
        get_engine(),
        VoiceFacts(
            provider=payload.provider.strip(),
            tts_model=payload.tts_model.strip(),
            engine_voice_id=payload.engine_voice_id.strip(),
            label=payload.label.strip(),
            languages=tuple(payload.languages),
        ),
    )
    await load_voice_catalogue(session)
    await write_audit(
        session,
        action="ops.voice_added",
        actor=principal,
        object_type="platform_voice_catalog",
        object_id=row.voice.id,
        ip=client_request_ip(request),
        # Ids, a model and a provider. No client detail and no tenant (hard rule 6) — this
        # is a platform-wide row and names nobody.
        summary={
            "voice_id": row.voice.id,
            "tts_model": row.voice.tts_model,
            "provider": row.voice.provider,
            "is_custom": row.is_custom,
        },
    )
    reason = await offerability_of(row.voice, state=row.state)
    return AddVoiceOut(
        voice=CuratedVoiceOut.of(row),
        offered=await count_offered_voices(session),
        offerable=reason is None,
        unofferable_reason=reason,
        next_step=_added_next_step(row, reason=reason),
    )


@router.patch(
    "",
    response_model=SetCurationOut,
    openapi_extra=permission_meta("ops:manage"),
    summary="Enable, disable or archive one voice for the whole platform (audited)",
    description=(
        "Decides whether ANY agent, in any client account, may be put on this voice. "
        "Only `enabled` voices are offered.\n\n"
        "**It changes no agent and no call.** An agent already speaking this voice keeps "
        "speaking it — on the call in progress, on the next call, and on its next publish. "
        "Disabling or archiving removes it from the picker; moving an agent off it is a "
        "separate, deliberate act on that agent. `live_agents` on the response says how "
        "many are affected.\n\n"
        "A voice the platform has stopped listing can still be curated — the state is kept "
        "against the day it returns — but it cannot be offered whatever state it is in.\n\n"
        "Idempotent: setting the state a voice is already in is a success, not a conflict."
    ),
)
async def set_voice_curation(
    payload: SetCurationIn,
    session: GlobalSession,
    request: Request,
    principal: VoiceCurator,
) -> SetCurationOut:
    """The one write. Row, audit row and snapshot install, in that order.

    **THE AUDIT ROW IS IN THE SAME TRANSACTION AS THE WRITE** (BACKEND-PATTERNS §4). The
    cache itself carries no history — it is refreshed whole by the sync — so this row is
    the only place "Sri stopped offering Priya at 14:02" will ever exist, and a curation
    decision without one is the single fact in this table that re-running the sync cannot
    reconstruct.

    **NOTHING RELOADS THE CATALOGUE SNAPSHOT HERE, AND THAT IS CORRECT RATHER THAN
    MISSING.** The first version of this route called `load_voice_catalogue` after the
    audit row, and it was wrong twice: this write cannot change the snapshot's contents (the
    snapshot is the voice LIST, and curation is deliberately not in it —
    `agents/voices.catalogue()` keeps a disabled voice so a live agent's id goes on
    resolving), and it installed process state from an UNCOMMITTED transaction, so a
    rollback would have left the process ahead of the database.

    What makes the click take effect is that offerability reads curation from the TABLE on
    every render (`voice_curation.read_curation`): the moment this commits, every API
    process answers the new verdict. There is no poll to wait for and nothing to warm.
    """
    row = await set_curation_state(session, voice_id=payload.voice_id, state=payload.state)
    await write_audit(
        session,
        action="ops.voice_curation_set",
        actor=principal,
        object_type="platform_voice_catalog",
        object_id=payload.voice_id,
        ip=client_request_ip(request),
        # Ids, a state and a count. No prompt text, no client detail, no tenant (hard
        # rule 6) — `live_agents` is a platform-wide total and names nobody.
        summary={
            "voice_id": payload.voice_id,
            "state": payload.state,
            "live_agents": row.live_agents,
        },
    )
    return SetCurationOut(
        voice=CuratedVoiceOut.of(row),
        # ONE COUNT, not a second pass over the whole table: `list_curated_voices` walks
        # every tenant to fill `live_agents`, which is right for the page load above and
        # absurd for a number this response prints.
        offered=await count_offered_voices(session),
        next_step=_next_step(row),
    )


__all__ = [
    "AddVoiceFormOut",
    "AddVoiceIn",
    "AddVoiceOut",
    "CuratedVoiceOut",
    "CuratedVoicesOut",
    "SetCurationIn",
    "SetCurationOut",
    "VoiceProviderOptionOut",
    "router",
]
