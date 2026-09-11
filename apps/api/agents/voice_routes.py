"""Voice catalog endpoints: everyone READS the catalog, the account OWNS the voice.

⚠ **D-586 (11 Sep 2026) MOVED THE WRITE INTO THE CLIENT REALM AND MADE IT REACH THE
ENGINE. THIS MODULE USED TO SAY THE OPPOSITE OF BOTH HALVES**, at length and with
reasons, and the reasons are answered rather than deleted — read the two sections below
before restoring either.

Clients get an AI phone agent. Which voice it speaks in is a delivery choice about their
own business's phone line, made from a picker that plays the voice before it is picked,
and SURFACES §2b has always put it on the "applies straight away" side. So the write is
`agents:write` in the CLIENT realm — the owner, their staff, and an admin viewing as
them — and it re-publishes a live agent in the same transaction.

NOT mounted in `main.py`? It is — `main._mount_routers` includes it BEFORE
`agents.routes.router`, and that order is load-bearing (see below).

WHY THIS ROUTER HAS NO PREFIX
-----------------------------
Its paths live in two spaces — the client realm's `/v1/agents/...` and the admin
realm's `/v1/admin/tenants/{tenant_id}/...` — so a shared prefix could only describe one
of them. Same shape and same resolution as `agents/routes.py` and `agents/llm_routes.py`.

⚠ **MOUNT THIS ROUTER BEFORE `agents.routes.router`.** FastAPI matches in declaration
order and `/v1/agents/{agent_id}` happily matches the literal segment `voices`, so the
wrong order turns `GET /v1/agents/voices` into a 422 about `agent_id` not being a UUID.
Verified against the live app, and the same hazard is called out in
`campaigns/routes.py` for `/numbers` and `/templates`. `tests/agent_voice_test.py`
mounts both routers in the correct order so a regression here fails a test, not a demo.

WHY THERE ARE TWO DOORS AND ONE WRITER
---------------------------------------
`PATCH /v1/agents/{agent_id}/voice` (client realm) and
`PATCH /v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice` (admin realm) are the SAME
resource with two doors, and both call `agents/publishing.set_agent_voice`. That is
`agents/llm_routes.py`'s pattern, adopted rather than re-invented, and its argument
applies here unchanged: "what must never differ between them is the allow-list, the
price and the resolution — which is exactly what would drift if the operator's screen and
the client's screen were served by two files. What differs is who is admitted and whose
account is named, which is a `Depends` and a path parameter, not a second
implementation."

The admin door is NOT a duplicate of the client one reached by impersonation. It is the
door an operator uses AS THEMSELVES, during onboarding, before the client has ever signed
in — the wizard that mints an agent sets its voice (`admin/routes.py`), and there is no
client session in that flow to carry it. It keeps the tenant in its path for the reason
every mutating route under `/v1/admin/tenants/` does: an admin principal has no tenant of
its own, so naming it makes the audit row self-documenting.

WHY THE TENANT IS IN THE ADMIN PATH AND NOT IN A BODY
------------------------------------------------------
THE TENANT USED TO RIDE IN THE BODY, on the path `PATCH /v1/agents/{agent_id}/voice`,
and that shipped one admin-realm route in the CLIENT path space — the only one in the
app. Three things came with it and none of them is cosmetic: the route missed the
`/v1/admin` rate-limit profile (`core/middleware.py::RateLimitMiddleware.PROFILES`) and
took the generic `/v1` one; its audit trail was not self-documenting from the path; and
it was the shape the next author would copy. `tests/route_shape_test.py` asserts the rule
over the whole route table, so this cannot come back as a one-off.

⚠ That path — `PATCH /v1/agents/{agent_id}/voice` — is LIVE AGAIN under D-586, and it is
a genuinely different route rather than the old one restored: CLIENT realm, no tenant
anywhere in it (the tenant is the caller's own), and it reaches the engine. The rule the
move established is intact, because the rule was "no ADMIN-realm route in the client path
space", not "nothing may live at that path". `SetVoiceIn` keeps `extra="forbid"`, so a
caller still sending `tenant_id` in the body gets a 422 naming the field rather than a
silently ignored parameter.

WHERE THE CURRENT VOICE IS READ
-------------------------------
Not here. `GET /v1/agents/{agent_id}/pending` (`agents/publishing_routes.py`) carries
`voice.configured` and `voice.live` — the voice on the row and the voice the engine was
last sent — because that endpoint is already the one answering configured-vs-live for
the script and the call cap, and a voice is the third instance of that question rather
than a new one. The argument, including why `AgentOut` was the wrong home and why the
answer is client-readable at all, is in that module's docstring.

WHAT THIS ENDPOINT DOES — AND WHAT IT USED TO REFUSE TO DO
-----------------------------------------------------------
It writes `agents.tts_voice`/`tts_provider` AND, on a LIVE agent, re-publishes inside the
same transaction, so the voice reaches the phone line before the response is written. A
failed engine push rolls the column back with it; the row never claims a voice the engine
does not hold. `agents/publishing.set_agent_voice` carries the full argument, including
why a PAUSED agent is deliberately NOT republished.

⚠ **THIS SECTION USED TO BE HEADED "WHAT THIS ENDPOINT DOES *NOT* DO" AND SAID: "It does
not touch the engine ... Silently re-voicing a running agent is not a safe default. If
the integrator wants auto-republish for parity with prompts, that is a decision-log entry
(ROADMAP §6) and two lines here, not a quiet change."** That decision-log entry is D-586,
and the objection it overturns was an argument about WHO IS CHOOSING, not about voices:
it described an operator re-voicing somebody else's live phone line from a console the
client cannot see, on an ear test (pilot gate 3) nobody had run. Under D-586 the chooser
is the client, on their own agent, from a picker that plays the voice first — the request
IS the consent, and nothing about it is silent. What would be silent is the old
behaviour: a screen saying the voice changed over a line still speaking the old one.

`publish_agent` RECORDS what it sent, in `agents.live_tts_voice` (migration c8b3f14e7a29).
That is what makes `republish_required` a measurement rather than an assumption, and it is
what lets a re-selection of the voice the engine already holds publish NOTHING.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import publishing
from apps.api.agents.voice_offer import (
    OfferedVoice,
    VoiceReasonAudience,
    offered_catalogue,
)
from apps.api.agents.voices import (
    Voice,
    VoiceSelectionCapability,
    catalogue_source,
    voice_selection_capability,
)
from apps.api.billing.rates import voice_tier_label
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta

# No prefix — see the module docstring: the client-realm read and the admin mutation
# live in different path spaces, so a shared prefix could only describe one of them.
router = APIRouter(tags=["agents"])

# `Annotated` aliases rather than `Depends()` defaults: this file is `voice_routes.py`,
# not `routes.py`, so it sits outside the B008 per-file ignore in pyproject — the same
# situation, and the same resolution, as `prompt_routes.py` and `export_routes.py`.
CatalogReader = Annotated[Principal, Depends(requires("agents:read"))]
#: THE CLIENT DOOR'S LOCK (D-586). `agents:write`, held by `owner` and `staff` since the
#: founder decided an account's own team edits its agents' settings, and `realm` left at
#: its `"any"` default deliberately: `current_any` resolves a client principal from a
#: client session and an ADMIN principal only when the impersonation header is present,
#: which is exactly the population this write is for — the owner, their staff, and an
#: operator viewing as them. It is NOT `org:manage`: that is the owner's alone, and a
#: staff member who may not buy credit may still choose which voice answers the phone.
VoiceWriter = Annotated[Principal, Depends(requires("agents:write"))]
#: The ADMIN door's lock — an operator acting AS THEMSELVES, with the tenant in the path.
AdminVoiceSetter = Annotated[Principal, Depends(requires("agents:write", realm="admin"))]
# Reads the tenant DIRECTORY cross-tenant; the audit row is written on it. The actual
# agent write happens under `tenant_session`, in that tenant's own RLS scope.
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
#: The CLIENT door's session — its own tenant's RLS scope, which is where its audit row
#: belongs. The agent write itself opens a session of its own inside `set_agent_voice`.
Session = Annotated[AsyncSession, Depends(db)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetVoiceIn(Strict):
    """One field, because the tenant and the agent are both in the path now.

    `extra="forbid"` so a caller cannot smuggle a second config string (an llm_model, a
    tts_provider) into a request whose whole point is one curated choice — and so a
    caller still sending the old `tenant_id` body field is told, rather than having it
    silently dropped while the path decides the tenant.
    """

    # Bounded before it is looked up, so a megabyte of junk is a validation error
    # rather than a dictionary probe. Membership in the catalog is the real check.
    voice_id: str = Field(min_length=1, max_length=64)


class SetVoiceOut(Strict):
    agent_id: UUID
    voice: Voice
    agent_status: str
    # True when the agent already exists on the engine (`engine_agent_ref` is set).
    published: bool
    # DID THIS REQUEST REACH THE VOICE PLATFORM. It used to be a hard-coded `False` with
    # a comment saying this endpoint writes our row and nothing else; since D-586 it is
    # what actually happened. True means callers hear the new voice from their next call.
    # False on a draft or paused agent (there is nothing live to update), and on a
    # re-selection of the voice the engine is already holding (there is nothing to send).
    engine_synced: bool
    # What the engine was last SENT (`agents.live_tts_voice`, written by
    # `publish_agent`), or null when nothing is recorded — an agent that was never
    # published, or one published before migration c8b3f14e7a29. Returned so the write
    # answers the same two questions the read does: a response that named only the voice
    # it just stored would be the "one number called the voice" this column exists to
    # stop.
    live_voice_id: str | None
    # Published AND the stored voice differs from the one the engine holds. It used to
    # be `== published`, which assumed every write moved the voice — so re-selecting the
    # voice already running reported a republish nobody needed, and there was no way to
    # tell the two apart. A null `live_voice_id` counts as different: a sync we cannot
    # prove is not a sync.
    republish_required: bool
    # False when the row already held this voice — a double-clicked picker, or the retry
    # of a request whose response was lost. A success, not a conflict (RFC 9110 §9.2.2),
    # and the signal the audit ledger keys off so one decision writes one entry.
    changed: bool
    next_step: str


class OfferedVoiceOut(Voice):
    """A catalogue voice AND whether it may be chosen on this deployment right now (D-547).

    THE CATALOGUE AND THE VERDICT ARE TWO FACTS AND THEY TRAVEL TOGETHER, for
    `VoiceCatalogueOut`'s own reason one level up: a caller needs the rows and the verdict
    about them, and inferring the verdict from which rows arrived is the bug. `selectable`
    on the envelope answers "may a voice be chosen here AT ALL" (the engine's business,
    D-93); this answers "may THIS one" (the platform's — a key, a price, a cap), and the two
    are independent.

    **A SHORTER LIST WOULD BE THE WRONG ANSWER, AND FILTERING IS EXACTLY WHAT THIS SHAPE
    PREVENTS.** A Cartesia voice that is missing from the response is indistinguishable from
    a Cartesia tier this product does not sell — so the operator who pasted the key an hour
    ago has no way to see that the PRICE is what is still missing, and the client who asks
    for the premium voice is told nothing at all. Every voice is returned; `reason` says why
    an unavailable one is unavailable, in a sentence naming the one action that fixes it.

    A SUPERSET OF `Voice` rather than an envelope around it: the picker renders the same
    fields it always did, and the two new ones are additive on the wire.
    """

    #: `None` exactly when the voice may be chosen. Otherwise ONE sentence from
    #: `agents/voice_offer.py`, IN THE READER'S OWN LANGUAGE (`VoiceReasonAudience`): an
    #: operator reads the ground that has to be fixed first — the missing key, the
    #: unattested price, the platform-wide Cartesia cap — and a client reads the one action
    #: they have. This route is readable in BOTH realms, so which sentence it is comes from
    #: the caller's realm and never from the row.
    unavailable_reason: str | None
    #: WHETHER THIS REFUSAL MEANS "NOT ON OFFER" RATHER THAN "OFFERED AND CURRENTLY
    #: UNAVAILABLE", so a picker can omit the first and render the second.
    #:
    #: Both are `offerable: false` and both carry a sentence, but they are opposite facts
    #: about the product. "No attested price" / "no credential" / "the Cartesia cap is
    #: reached" describe a voice this platform MEANS to offer and cannot right now — the
    #: reason is worth reading, and the screen leaves the row reachable so it is announced.
    #: "The operator has not enabled it" describes a voice that was never on offer, and
    #: since the catalogue became the engine account's own list there are four hundred and
    #: sixteen of those: rendering them buried the two real choices under a wall of
    #: identical orange sentences.
    #:
    #: Carried from `OfferedVoice.not_on_offer`, which is computed from the OPERATOR
    #: ground — never recovered from `unavailable_reason`, which collapses all four
    #: grounds into one sentence for a client and made this field silently false for
    #: every client session.
    #:
    #: A BOOLEAN RATHER THAN THE GROUND ITSELF, deliberately. The screen's question is
    #: "render this row or not"; handing it the four grounds would invite a second copy of
    #: the offerability rules in the browser, which is the drift `useWriteAccess` was just
    #: cured of.
    not_on_offer: bool
    #: Derived from `unavailable_reason`, never beside it: a screen that could read a `True`
    #: flag next to a refusal sentence is a screen that can offer a voice the write refuses.
    offerable: bool
    #: WHAT A CLIENT IS TOLD THIS VOICE'S QUALITY IS CALLED — "Clear", "Studio" — from
    #: `billing/rates.voice_tier_label`. It crosses the wire beside `provider` rather than
    #: being looked up in the browser for the reason the marketing provenance rule exists:
    #: a second copy of the name in TypeScript is how the two drift until one client meets
    #: both. `provider` stays on the wire because that is what the ledger, the lot rows and
    #: a vendor invoice are reconciled against; it is simply not what a human is shown
    #: (founder, 7 Sep 2026).
    tier_label: str

    @classmethod
    def of(cls, offered: OfferedVoice) -> OfferedVoiceOut:
        """One verdict from `voice_offer.offered_catalogue()` onto the wire."""
        return cls(
            **offered.voice.model_dump(),
            unavailable_reason=offered.reason,
            not_on_offer=offered.not_on_offer,
            offerable=offered.offerable,
            tier_label=voice_tier_label(offered.voice.provider),
        )


class VoiceCatalogueOut(Strict):
    """The catalog AND whether it may be chosen from (D-93).

    IT USED TO BE A BARE `list[Voice]`, and that shape cannot express the one answer this
    endpoint now has to be able to give. On an engine that supplies its own voices the
    honest response is "no selection here, and that is normal" — and a bare list has
    exactly one way to say it, `[]`, which the console reads as "this agent has no voices
    available" and renders as a claim about the product. (The console's own comment in
    `VoicePanel` says exactly that, which is how the shape was found to be wrong.) An
    empty list and a closed choice are different facts, and the envelope keeps them
    different.

    The same argument `ExecutionListing` makes: the caller needs the rows AND the verdict
    about them, and inferring the verdict from the length of the rows is the bug.

    NO FIELD HERE HAS A DEFAULT. A Pydantic field with a default is OPTIONAL in the
    generated TypeScript, and every one of these is a field the console must trust: a
    `selectable` that can arrive undefined would be read as falsy and hide the picker on
    a perfectly capable engine.
    """

    #: Who chooses the TTS leg on this deployment's engine — `ours` or `engine`.
    control: str
    #: True when a voice may be set on an agent here. When False, `voices` is empty
    #: because there is nothing to offer, NOT because the catalog failed to load.
    selectable: bool
    #: EVERY voice in the catalogue, each with its own verdict — never a filtered list.
    #: See `OfferedVoiceOut` for why a shorter list would be the wrong answer.
    voices: list[OfferedVoiceOut]
    #: WHERE THESE VOICES CAME FROM — `"engine"` (a sync read them off the voice
    #: platform account) or `"unsynced"` (no sync has ever succeeded on this process, so
    #: there are none at all — D-588 deleted the built-in fallback that used to answer
    #: here, and `"seed"` is no longer a value this field can take). D-585: the catalogue
    #: is the ENGINE ACCOUNT's list,
    #: not a constant in our source, and an operator looking at a short picker has to be
    #: able to tell "this is what the platform offers" from "nobody has synced yet". It
    #: crosses the wire rather than being inferred from the row count for
    #: `VoiceCatalogueOut`'s own reason: a length is not a verdict.
    source: str
    #: One sentence a UI prints verbatim. Always present, so a surface never has to
    #: compose the explanation out of the two fields above and get the tone wrong — the
    #: closed case is a product fact, not an error, and it should not read like one.
    note: str


def _catalogue_note(capability: VoiceSelectionCapability, *, offerable: int) -> str:
    """One sentence a UI prints verbatim, for each of the four states this read has.

    ⚠ **THE "BUILT-IN STARTER LIST" SENTENCE IS GONE (D-588)** — there is no starter list
    any more, so a deployment nobody has synced has NO voices rather than nine. That is
    correct rather than broken (only what an operator enables is selectable), and it is why
    two of the four sentences below exist: an empty picker has two completely different
    causes, and the reader can only act on one of them at a time.

    `offerable` is a COUNT and not a list: the rows travel beside this note with their own
    per-voice verdicts, and a sentence that re-derived which ones are choosable would be a
    second opinion about the same fact.
    """
    if not capability.available:
        return (
            "The voice platform in use supplies its own voices, so a voice cannot be chosen "
            "here. Nothing is wrong with this agent."
        )
    if catalogue_source() == "unsynced":
        # NOBODY HAS SYNCED. The voices exist on the platform account; this deployment has
        # never read them. The person who can fix it is an administrator, in two steps, and
        # the sentence names both because doing only the first leaves the picker empty and
        # reads like a failed fix.
        return (
            "No voice can be chosen yet. The voice platform's own catalogue has not been "
            "read on this deployment, so there is nothing to choose from — an administrator "
            "reads it on the admin console's Voices page and then enables the voices this "
            "platform should offer."
        )
    if offerable == 0:
        # SYNCED, AND NOTHING IS ENABLED. A different sentence from the one above on
        # purpose: refreshing again changes nothing here, and telling an operator to sync
        # would send them round a loop that cannot end.
        return (
            "No voice can be chosen yet. The voice platform's catalogue has been read, but "
            "none of its voices has been enabled for this platform — an administrator "
            "enables the ones it should offer on the admin console's Voices page. Reading "
            "the catalogue again will not change that."
        )
    return (
        "Pick the voice this agent speaks in. A voice shown as unavailable is one this "
        "platform does not currently offer; the reason beside it says why."
    )


def _reason_audience(principal: Principal) -> VoiceReasonAudience:
    """WHOSE LANGUAGE THIS RESPONSE'S REFUSALS ARE IN, from the realm and nothing else.

    The three operator grounds name a vendor and two of them name one of our settings
    (`cartesia_api_key`, `cartesia_agent_cap`), and this route is `agents:read` in either
    realm — so a client realm principal must never receive them. It is read off the REALM
    rather than off a role for `llm_models.LlmReasonAudience`'s reason: a role is a
    permission, not an audience.

    **AN IMPERSONATING ADMIN IS AN OPERATOR HERE, AND THAT IS NOT THE ANSWER
    `llm_routes` GIVES.** There the two realms have two routes AND two audiences, so an
    operator opening the CLIENT's route deliberately reads the client's sentence. The
    catalogue READ is one route for both consoles, and `current_any` admits an admin
    principal ONLY when the impersonation header is present (`core/auth.py`) — so the admin
    console's voice picker reaches it as an impersonating admin, and treating that as a
    client would delete the operator ground from the only screen an operator installs a
    Cartesia key from. Realm decides, and impersonation does not change a realm.

    The WRITE has two routes since D-586 and uses this same selector rather than hard-coding
    an audience per route, which is what keeps the picker and the write telling one person
    one story: whichever door an operator comes through, they read the ground they can fix,
    and a client reads the one action they have.
    """
    return "operator" if principal.is_admin else "client"


@router.get(
    "/v1/agents/voices",
    response_model=VoiceCatalogueOut,
    openapi_extra=permission_meta("agents:read"),
    summary="The voices an agent may speak in, each with its availability (client-readable)",
)
async def list_voices(principal: CatalogReader) -> VoiceCatalogueOut:
    """The catalogue, plus one capability read and — only when it could decide anything —
    one platform-wide count.

    Client-realm readable on purpose — a client is legally the Principal Entity and
    should be able to see what their own agent sounds like, exactly as they can read
    its disclosure line (`AgentOut.disclosure_line`). `requires()` defaults to
    `realm="any"`, so an admin (including one impersonating, since this is a read) gets
    the same answer — one catalog, no realm-specific truth.

    ⚠ **"NO DB, NO NETWORK" USED TO BE THE FIRST LINE OF THIS DOCSTRING AND IS NOW WRONG
    TWICE OVER, WHICH IS WHY IT SAYS SO.** The Cartesia agent cap (D-547 §0 Q10) is a count
    of live Cartesia agents across every tenant, measured only when the two cheap grounds
    have already passed and the catalogue actually holds a Cartesia voice. And since D-588
    every render also reads the CURATION rows — one SELECT over a platform-scoped table of
    tens of rows — because only the voices an operator has enabled may be offered, and that
    is a decision somebody may have made ten seconds ago on the screen they are still
    looking at. Neither read is on a call path.

    **AN EMPTY `voices` LIST IS A REAL AND CORRECT ANSWER.** A deployment nobody has synced,
    or one where nobody has enabled anything, offers nothing — `note` says which of the two
    it is and what to do. Do not render it as a failure.

    The capability read is the SAME selector `set_agent_voice` uses, and that is the whole
    point: this endpoint is what the picker is built from, so if the two could disagree
    the console would offer precisely the choice the write refuses.
    """
    capability = voice_selection_capability()
    offered = await offered_catalogue(
        voices=tuple(capability.voices), audience=_reason_audience(principal)
    )
    return VoiceCatalogueOut(
        control=capability.control,
        selectable=capability.available,
        voices=[OfferedVoiceOut.of(row) for row in offered],
        source=catalogue_source(),
        note=_catalogue_note(capability, offerable=sum(1 for row in offered if row.offerable)),
    )


_APPLIES_NOW = (
    "Applies immediately: a live agent is re-published to the voice platform in the same "
    "transaction, so the screen never claims a voice the platform is not speaking. If "
    "that push fails nothing is saved. Callers hear it from the NEXT call — a call "
    "already in progress is not disturbed.\n\n"
    "A draft or paused agent is not published by this: there is nothing live to update, "
    "and the next publish carries the voice. `engine_synced` says which happened.\n\n"
    "An id outside the catalog is refused with `unknown_voice`. A catalogue voice this "
    "deployment cannot put a client on — no vendor key, no attested price, the "
    "platform-wide cap reached — is refused with `voice_not_available`, and the detail "
    "names the actual ground."
)


async def _apply_voice(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    voice_id: str,
    principal: Principal,
    audit_session: AsyncSession,
    request: Request,
) -> SetVoiceOut:
    """THE ONE WRITER BEHIND BOTH DOORS — `llm_routes.py`'s pattern, and its argument.

    What differs between the client route and the admin route is who is admitted and
    whose account is named. Everything that must never differ — the capability check, the
    catalogue lookup, the offerability verdict, the lock, the republish, the audit action
    — is here, once.

    `set_agent_voice` opens the tenant's own RLS scope and reaches the engine, so it runs
    OUTSIDE the audit session's transaction: a slow vendor call must not hold the audit
    row's transaction open, and the audit entry should describe what actually happened
    rather than what was about to be attempted. Same ordering, and the same reason, as
    `agents/routes.py::publish` and `set_disclosure`.
    """
    result = await publishing.set_agent_voice(
        tenant_id=tenant_id,
        agent_id=agent_id,
        voice_id=voice_id,
        # THE REALM DECIDES WHOSE LANGUAGE A REFUSAL IS IN, never a role — `llm_models.
        # LlmReasonAudience`'s rule, applied here for the same reason `_reason_audience`
        # above applies it to the read: a role is a permission, not an audience. An
        # impersonating admin is an operator, because the operator grounds name a vendor
        # and two of our settings and they are useless to anyone who cannot reach the ops
        # console.
        audience=_reason_audience(principal),
    )
    if result.changed:
        await write_audit(
            audit_session,
            action="agent.voice_set",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            # Catalog ids and booleans. No prompt text, no client detail (hard rule 6).
            summary={
                "voice_id": result.voice.id,
                "tts_model": result.voice.tts_model,
                "engine_synced": result.engine_synced,
                "republish_required": result.republish_required,
            },
        )
    return SetVoiceOut(
        agent_id=result.agent_id,
        voice=result.voice,
        agent_status=result.agent_status,
        published=result.published,
        engine_synced=result.engine_synced,
        live_voice_id=result.live_voice_id,
        republish_required=result.republish_required,
        changed=result.changed,
        next_step=_next_step(
            published=result.published,
            republish_required=result.republish_required,
            engine_synced=result.engine_synced,
        ),
    )


@router.patch(
    "/v1/agents/{agent_id}/voice",
    response_model=SetVoiceOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Choose the voice this agent speaks in (D-586)",
    description=(
        "Sets the voice on one of your own agents. Hear the options first with "
        "`GET /v1/agents/voices`; a voice returned there with `offerable: false` is "
        "refused here, with the same sentence that read said.\n\n" + _APPLIES_NOW
    ),
)
async def set_my_agent_voice(
    agent_id: UUID,
    payload: SetVoiceIn,
    session: Session,
    request: Request,
    principal: VoiceWriter,
) -> SetVoiceOut:
    """The client door. The tenant is the caller's own and is never in the path.

    `agents:write` rather than `org:manage`, and the difference is the founder's decision
    rather than a preference: `org:manage` is the OWNER's permission — billing, members,
    every account setting — and this must be reachable by their STAFF, who run the phone
    line day to day. `agents:write` is the permission that names exactly this authority,
    it already existed, and `rbac.py` now grants it to both client roles.

    It is in `MUTATING_PERMISSIONS`, which is what makes every guard in `requires()` apply
    here unchanged: an admin-realm token with no impersonation header is refused by the
    client verifier, an archived agent is refused by `guard_agent_write`, and whether an
    impersonating operator may write at all is D-22's answer, given in one place for every
    route rather than re-decided here.
    """
    assert principal.tenant_id is not None  # `requires()` resolves a tenant for this realm
    return await _apply_voice(
        tenant_id=principal.tenant_id,
        agent_id=agent_id,
        voice_id=payload.voice_id,
        principal=principal,
        audit_session=session,
        request=request,
    )


@router.patch(
    "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice",
    response_model=SetVoiceOut,
    openapi_extra=permission_meta("agents:write"),
    summary="Set an agent's voice from the catalog (admin realm — onboarding)",
    description=(
        "The operator's door onto the same write, for the onboarding wizard and for "
        "support acting as themselves: the tenant is named in the path because an admin "
        "principal has no tenant of its own, which also makes the audit row "
        "self-documenting. A client edits their own agent's voice on "
        "`PATCH /v1/agents/{agent_id}/voice` instead.\n\n" + _APPLIES_NOW
    ),
    tags=["admin"],
)
async def set_agent_voice(
    tenant_id: UUID,
    agent_id: UUID,
    payload: SetVoiceIn,
    session: AdminSession,
    request: Request,
    principal: AdminVoiceSetter,
) -> SetVoiceOut:
    """The admin door. Tenant existence first, then the shared writer.

    TENANT EXISTENCE COMES BEFORE ALL OF IT (D-133). The tenant id here is a uuid an
    operator copies off a console URL, and an absent one must answer 404 `not_found`
    rather than any business rule about the voice — a mistyped tenant hitting
    `unknown_voice` would send an operator hunting for the right catalog id in an account
    that does not exist. `admin.service.tenant_exists` is the one definition, read here on
    the cross-tenant admin session before the checks that would otherwise mask it.
    `tests/absent_tenant_answer_test.py` is the census that pins it. The client door needs
    no such read: its tenant came from a verified session.
    """
    from apps.api.admin import service as admin_service

    if not await admin_service.tenant_exists(session, tenant_id):
        raise ProblemError.not_found("Client")

    return await _apply_voice(
        tenant_id=tenant_id,
        agent_id=agent_id,
        voice_id=payload.voice_id,
        principal=principal,
        audit_session=session,
        request=request,
    )


def _next_step(*, published: bool, republish_required: bool, engine_synced: bool) -> str:
    """What happens now, in one sentence a UI prints verbatim.

    Four answers rather than three, because D-586 added the one that is now the common
    case: the voice HAS reached the phone line, and the only thing left to say is when
    callers hear it. The old third answer — "publish the agent to send this voice" — is
    kept for the states a voice write deliberately does not publish (a draft agent, a
    paused one), because telling those clients that callers already hear it would be the
    same lie in the other direction.
    """
    if engine_synced:
        return (
            "Callers hear this voice from the next call — the agent already speaking to "
            "someone finishes in the voice it started in."
        )
    if not published:
        return "The agent is not on the voice platform yet; publishing it will use this voice."
    if not republish_required:
        return (
            "Callers already hear this voice — the voice platform is holding it, so there "
            "was nothing to send."
        )
    return (
        "This agent is not on the frontline, so nothing was sent to the voice platform. "
        "It will speak in this voice from the moment it is put back on."
    )


__all__ = ["SetVoiceIn", "SetVoiceOut", "router"]
