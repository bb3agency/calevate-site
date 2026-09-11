"""The Voices panel's API — which synced voices this platform offers (D-588).

    GET   /v1/ops/voices          every voice the voice platform lists for our account,
                                   with its curation state, whether we cloned it, when it
                                   was last seen, and how many live agents are on it
    PATCH /v1/ops/voices          move ONE voice to enabled | disabled | archived (audited)

The refresh that fills the cache is `POST /v1/ops/voices/refresh`
(`apps/api/ops/routes.py`), which already existed and is unchanged — the console's Refresh
button calls it and then re-reads this list.

WHY THIS IS A CURATION PANEL AND NOT AN "ADD VOICE" PANEL
----------------------------------------------------------
**Bolna's voice API is READ-ONLY** — two GET routes and no create, update or delete
anywhere in their published API (VERIFIED-VENDOR-DOCS, hash-pinned mirror,
`bolna-findings/mirror/pages/api-reference/voice/overview.md:17-18`, enumerated 11 Sep
2026). A voice is ADDED in their Playground, by importing a voice id or cloning a 1-2
minute sample (`pages/import-voices.md`, `pages/clone-voices.md`). So this panel cannot
offer an Add button, and the honest thing — the thing that stops an operator hunting for
one — is to say where the button actually is. `apps/api/agents/voice_curation.py` carries
the full argument; the console prints it above the table.

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
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.voice_curation import (
    CuratedVoice,
    count_offered_voices,
    list_curated_voices,
    set_curation_state,
)
from apps.api.agents.voices import CurationState, Voice, catalogue_source
from apps.api.billing.rates import voice_tier_label
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.rbac import permission_meta

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
    #: One sentence the console prints verbatim, saying which of those states this is.
    note: str


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


def _note(*, source: str, offered: int) -> str:
    """The Voices page's own state sentence. Composed here, never in the browser, for the
    reason every `note` in this tree is: a screen that paraphrases "synced but nothing
    enabled" as "no voices" is how a working platform gets reported as broken."""
    if source == "unsynced":
        return (
            "This platform has never read the voice platform's catalogue. Press Refresh to "
            "read it, then enable the voices clients should be able to choose."
        )
    if offered == 0:
        return (
            "The catalogue has been read, but no voice is enabled — so no client and no "
            "admin can choose a voice for any agent. Enable the ones this platform should "
            "offer."
        )
    return (
        "These are every voice the voice platform lists for our account. Only the enabled "
        "ones can be chosen for an agent, in either console."
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
    summary="Every synced voice, with its curation state (admin realm)",
    description=(
        "The voices the voice platform lists for our account, as of the last refresh — "
        "including ones it has since stopped listing, which are shown last and marked. "
        "Only `enabled` voices can be chosen for an agent, by a client or by an admin.\n\n"
        "A NEW voice cannot be added here: the voice platform's API is read-only. Import "
        "or clone one in its Playground, then press Refresh."
    ),
)
async def list_voices(session: GlobalSession, _: VoiceCurator) -> CuratedVoicesOut:
    """The table. One read of the cache, plus one live-agent count per tenant.

    The count is the only expensive part and it is bounded by the tenant directory, which
    is this product's client list. It runs on an operator's page load and nowhere else —
    never on a picker render, never on a call path.
    """
    rows = await list_curated_voices(session)
    source = catalogue_source()
    offered = sum(1 for row in rows if row.offered)
    return CuratedVoicesOut(
        voices=[CuratedVoiceOut.of(row) for row in rows],
        source=source,
        offered=offered,
        note=_note(source=source, offered=offered),
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


__all__ = ["CuratedVoiceOut", "CuratedVoicesOut", "SetCurationIn", "SetCurationOut", "router"]
