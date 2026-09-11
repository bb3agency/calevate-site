"""WHICH SYNCED VOICES THIS PLATFORM ACTUALLY OFFERS — the curation half of D-588.

⚠ **THE "ADD" HALF WAS BUILT AFTER ALL — IT IS `agents/voice_admission.py` (D-590), AND THE
PARAGRAPHS BELOW SAYING IT CANNOT BE ARE SUPERSEDED.** Their premise is still true and their
conclusion was wrong: adding a voice to the VOICE PLATFORM needs a write they do not offer,
and adding a voice to THIS PRODUCT'S catalogue needs only the operator's facts and one read
to check them. This module is now the half that moves an EXISTING row between states —
enable, disable, archive, restore — and `voice_admission.py` is the half that creates one.
The founder does not want to curate 418 vendor personas; they want to add the handful they
cloned, which is why the console now opens on the rows somebody DECIDED about
(`list_curated_voices(scope="decided")`) rather than on the vendor's whole list.

WHY THIS MODULE EXISTS, AND WHY IT USED TO BE THE ONLY ANSWER
------------------------------------------------------------------
The founder asked for a Voices section in the admin console where they can add, delete and
archive voices end to end, and where **only the voices they add there are selectable** by
clients for their own agents and by admins for anyone's.

**THE "ADD" HALF CANNOT BE BUILT [SUPERSEDED — see above], AND THE REASON IS THE VENDOR'S
API, NOT OUR TIME.**
Bolna's published API has exactly two voice routes and both are GET — `/api/v1/voice-config
/tts` and `/api/v1/voice-config/tts/voices` (VERIFIED-VENDOR-DOCS, hash-pinned mirror,
`bolna-findings/mirror/pages/api-reference/voice/overview.md:17-18`; every documented method
under `pages/api-reference/` was enumerated on 11 Sep 2026 and there is no POST, PUT, PATCH
or DELETE for a voice anywhere in it). Adding one is a DASHBOARD act in their Playground:
IMPORT by voice id, optionally from a connected provider account (`pages/import-voices.md`),
or CLONE from a 1-2 minute sample (`pages/clone-voices.md`, which names ElevenLabs or
Cartesia as the cloning providers). Every surface this module feeds says so in as many
words, because an operator hunting for an "Add voice" button on our console is an operator
we sent to the wrong product.

So what is buildable — and what this module is — is CURATION over the sync (D-585): the
engine account's whole voice list is read and cached, and an operator says which of those
voices anybody may be put on. That delivers the half of the request that actually matters
("only what I enable is selectable") and is honest about the half that does not exist.

THE THREE STATES, AND THE ONE THAT IS NOT A STATE
--------------------------------------------------
`voices.CurationState` is `enabled | disabled | archived` and only `enabled` is offerable.
`disabled` and `archived` differ to a HUMAN — one is "not right now", the other is "put
away" — and not at all to `voice_offer.py`, which refuses both.

`withdrawn_at` is deliberately NOT a fourth state. It is the VENDOR's statement (this voice
is no longer on our account) rather than an operator's, and the two have to be readable
separately: "you switched this off" and "the voice platform dropped this" send a reader to
two different places, and only one of them is fixable from this console. A withdrawn row
keeps whatever curation state it had, so a voice that comes back comes back the way it was
put away rather than as a fresh un-curated row.

WHAT ARCHIVING DOES *NOT* DO, WHICH IS THE PART THAT REACHES A PHONE LINE
--------------------------------------------------------------------------
**An agent LIVE on a voice that is then archived keeps speaking it, and nothing here
changes that.** Three separate properties hold it:

1. `agents.tts_voice` is free text, and archiving writes nothing to any agent row.
2. A PUBLISHED agent holds its voice on the ENGINE. Nothing in this module calls the engine,
   so a call already ringing and a call that arrives a second later are both unaffected.
3. `voices.catalogue()` — the LOOKUP layer — still holds the voice, so `speech_for_voice_id`
   still resolves it, `publish_agent` still sends the right model/speaker pair and
   `agents/publishing.engine_drift_for` still compares like with like. Curation is applied
   only in `voice_offer.py`, and only to the question "may somebody be PUT on this".

So the deliberate answer to "does archiving refuse if an agent is on it?" is **NO, IT
ALLOWS IT — and tells the operator which accounts are affected.** The alternative (refuse
while any agent holds it) was rejected on two grounds. It makes a vendor's own withdrawal
unrepresentable — the voice is gone from their platform whatever our table says, so a
console that refuses to file it away just leaves it on every client's picker. And it turns a
curation click into a cross-tenant enumeration whose answer can change between the check and
the write, which is a lock this operation does not deserve. `CuratedVoice.live_agents` is
the number an operator reads BEFORE clicking; archiving is reversible in one click if they
misjudge it, and the thing it cannot do is make a caller hear silence.

WHY NO `tenant_id` AND NO RLS (hard rule 1)
---------------------------------------------
`platform_voice_catalog` is platform-scoped: one vendor account serves every tenant and its
voice list is the same list for all of them. The written reason `scripts/check_rls_coverage`
reads is in `db/registry.RLS_EXEMPT_TENANT_COLUMNS`. The one cross-tenant number this module
computes (`live_agents`) is measured the only way RLS permits — enumerate the directory
under `app.admin`, then enter each tenant with its own GUC — which is the shape
`voice_offer.count_live_cartesia_agents` and `admin/service.tenant_overview` already have.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, cast

from sqlalchemy import Select, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voice_sync import voice_from_row
from apps.api.agents.voices import (
    ARRIVAL_CURATION_STATE,
    CurationState,
    Voice,
    VoiceOrigin,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import admin_session, tenant_session

#: THE CURATION MAP: every voice the platform still lists, keyed by our catalogue id, with
#: the state an operator put it in. A voice ABSENT from it is withdrawn upstream — which is
#: what `voice_offer.curation_unofferable_reason` reads as "the platform no longer lists
#: this", and why that function fails closed on a missing key.
VoiceCuration = Mapping[str, CurationState]

#: WHICH ROWS THE CONSOLE IS ASKING FOR (D-590).
#:
#: * `decided` — rows somebody has made a decision about: every operator-ADDED voice, plus
#:   any synced voice an operator moved off the arrival state. This is the DEFAULT and it is
#:   the whole of the founder's correction to D-588: a screen that opens with 418 vendor
#:   personas and 414 switches to flip is a chore, not a product.
#: * `all` — every cached row, the undecided ones included. Kept, and reachable from the
#:   console behind one control, because "the platform lists 418 voices and I have added 3"
#:   is a fact an operator occasionally needs — and because a legacy row somebody enabled
#:   under D-588 must never become invisible while it is still being offered.
VoiceScope = Literal["decided", "all"]


@dataclass(frozen=True, slots=True)
class CuratedVoice:
    """ONE ROW OF THE ADMIN CONSOLE'S VOICES TABLE — the cached voice plus what an operator
    needs in order to decide about it.

    `voice` is the same `Voice` every picker renders, so the operator's table and the
    client's picker cannot come to describe one voice differently. Everything beside it is
    a fact a CLIENT deliberately never sees: whose account a voice was cloned on, what an
    operator decided, when the vendor dropped it, how many live agents are on it.
    """

    voice: Voice
    state: CurationState
    #: `source == "custom"` on the engine's row — cloned or imported on our own account,
    #: rather than one of the platform's stock personas. The one entry class no compiled
    #: list could ever have held, and the reason this column exists at all.
    is_custom: bool
    #: When the sync that last SAW this voice ran.
    synced_at: datetime
    #: When an operator last moved `state`, or None for a voice nobody has reviewed. NOT
    #: who — that is `audit_log`. The distinction this carries is "switched off on purpose"
    #: versus "never looked at", which the state column alone cannot express.
    curated_at: datetime | None
    #: When the voice platform stopped listing this voice, or None while it still does.
    withdrawn_at: datetime | None
    #: WHY THIS ROW EXISTS (D-590) — `voices.VoiceOrigin`. `operator` means somebody typed
    #: this voice's facts and the voice platform confirmed them; `synced` means a sync read
    #: it off that platform's list and nobody has attested anything about it.
    origin: VoiceOrigin
    #: LIVE agents across every tenant whose configured or published voice is this one.
    #: Shown beside the archive control so the decision is made with the number in view —
    #: see the module docstring for why it is information rather than a veto.
    live_agents: int

    @property
    def withdrawn(self) -> bool:
        return self.withdrawn_at is not None

    @property
    def offered(self) -> bool:
        """Would `voice_offer.py` clear GROUND ZERO for this voice? Not the whole verdict —
        a Cartesia voice can be enabled and still unofferable for an unattested price, and
        that is the offer seam's answer, not this table's."""
        return self.state == "enabled" and not self.withdrawn


async def read_curation() -> VoiceCuration:
    """WHICH VOICES AN OPERATOR HAS OFFERED — offerability ground zero's one measurement.

    Every row the voice platform still lists, keyed by our catalogue id. WITHDRAWN rows are
    excluded, so a voice the platform dropped is ABSENT here rather than present with a
    stale state.

    `admin_session()` for `voice_offer.count_live_cartesia_agents`' reason: this table is
    platform-scoped with no `tenant_id` and no RLS policy, and it answers the same list to
    every tenant on purpose. It is tens of rows, on a picker render and a voice write, never
    on a call path.

    NOT a snapshot behind a poll, unlike the price and credential grounds: an operator who
    enables a voice is standing in front of the screen, and a 30-second lag there is a bug
    report. The catalogue itself IS snapshotted, because it is on the publish path and must
    be answerable with no session; a verdict is not.
    """
    async with admin_session() as session:
        rows = (
            await session.execute(
                select(
                    PlatformVoiceCatalogEntry.voice_id,
                    PlatformVoiceCatalogEntry.curation_state,
                ).where(PlatformVoiceCatalogEntry.withdrawn_at.is_(None))
            )
        ).all()
    # `cast` rather than a narrowing loop: the column is `Text` to SQLAlchemy and a CHECK
    # constraint to Postgres (migration `e4b7a10c92d6`), so the three-member vocabulary is
    # enforced by the database on the way IN. A row holding anything else cannot exist, and
    # re-validating it here would be a second, weaker copy of that constraint.
    return {voice_id: cast("CurationState", state) for voice_id, state in rows}


# LIVE tenants only, by `deleted_at IS NULL` — spelled the same way as
# `voice_offer._DIRECTORY` and `admin/health.client_health` so the three cannot come to mean
# different populations.
_DIRECTORY: Final = "SELECT id FROM organizations WHERE deleted_at IS NULL"

# ONE TENANT'S LIVE AGENTS PER VOICE ID. CONFIGURED **OR** PUBLISHED, for the reason
# `voice_offer.count_live_cartesia_agents` gives about the provider columns: an agent
# switched back in the row but not yet republished is still SPEAKING the old voice on every
# call it answers, and an agent switched to a voice and about to be republished is the one
# an operator most needs to see before archiving it.
_LIVE_BY_VOICE_SQL: Final = (
    "SELECT voice, count(*) FROM ("
    "  SELECT tts_voice AS voice FROM agents "
    "   WHERE status = 'live' AND deleted_at IS NULL AND tts_voice IS NOT NULL "
    "  UNION ALL "
    "  SELECT live_tts_voice AS voice FROM agents "
    "   WHERE status = 'live' AND deleted_at IS NULL AND live_tts_voice IS NOT NULL "
    "     AND live_tts_voice IS DISTINCT FROM tts_voice"
    ") AS held GROUP BY voice"
)


async def count_live_agents_by_voice() -> dict[str, int]:
    """LIVE agents per voice id, across every tenant — the number beside the archive button.

    The directory-then-enter-each-tenant shape RLS forces, in ONE place, exactly as
    `voice_offer.count_live_cartesia_agents` does it for the Cartesia cap: `admin_session()`
    widens `organizations` and nothing else, so a single cross-tenant `SELECT` over `agents`
    would return zero rows — honestly, and misleadingly.

    The inner `UNION ALL` counts an agent ONCE when its configured and published voices
    agree and ONCE FOR EACH when they differ, which is the right answer to "how many live
    agents would an operator be surprising": both voices are real, and the second is the one
    callers are hearing right now.

    It is N+1 by construction and runs only on the admin console's Voices page — never on a
    picker render, never on a call path.
    """
    async with admin_session() as directory:
        tenants = [row[0] for row in (await directory.execute(text(_DIRECTORY))).all()]
    totals: dict[str, int] = {}
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as scoped:
            for voice_id, held in (await scoped.execute(text(_LIVE_BY_VOICE_SQL))).all():
                totals[str(voice_id)] = totals.get(str(voice_id), 0) + int(held)
    return totals


async def count_offered_voices(session: AsyncSession) -> int:
    """How many voices clear offerability GROUND ZERO — enabled and still listed.

    ONE COUNT, not `len([row for row in await list_curated_voices(...) if row.offered])`,
    and the difference is a cross-tenant enumeration: `list_curated_voices` walks every
    tenant to fill `live_agents`, which is right for the TABLE an operator is reading and
    absurd for a number the write response prints. The predicate is the same one
    `CuratedVoice.offered` applies, spelled once here as SQL because this is the only place
    it is asked without the rows.
    """
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(PlatformVoiceCatalogEntry)
                .where(
                    PlatformVoiceCatalogEntry.curation_state == "enabled",
                    PlatformVoiceCatalogEntry.withdrawn_at.is_(None),
                )
            )
        ).scalar_one()
    )


#: The SQL predicate for `scope="decided"` — an operator-added row, or a synced row an
#: operator moved off the arrival state. Spelled once, from the two constants that define
#: those words, so it cannot come to mean something different from `VoiceScope`'s docstring.
def _decided(
    statement: Select[tuple[PlatformVoiceCatalogEntry]],
) -> Select[tuple[PlatformVoiceCatalogEntry]]:
    return statement.where(
        or_(
            PlatformVoiceCatalogEntry.origin == "operator",
            PlatformVoiceCatalogEntry.curation_state != ARRIVAL_CURATION_STATE,
        )
    )


async def count_cached_voices(session: AsyncSession) -> int:
    """How many voices are in the cache ALTOGETHER, whatever anybody decided about them.

    The number beside the `decided` table, so an operator reading three rows is told the
    voice platform lists four hundred and can open them if they want. Reported rather than
    rendered, for the same reason every other count on this screen is composed on the server:
    a browser subtracting two lists is a browser that can be wrong about what it is not
    showing.
    """
    return int(
        (
            await session.execute(select(func.count()).select_from(PlatformVoiceCatalogEntry))
        ).scalar_one()
    )


async def list_curated_voices(
    session: AsyncSession, *, scope: VoiceScope = "decided"
) -> tuple[CuratedVoice, ...]:
    """The cached voices this console is asking about, withdrawn ones included, in reading
    order.

    **WITHIN A SCOPE IT IS NEVER A FILTERED LIST**, for `voice_offer.offerable_voices`'
    reason one layer down: a voice missing from the answer is indistinguishable from a voice
    the platform does not have, and telling those two apart is the operator's whole job here.
    Withdrawn rows are LAST rather than absent, because they are the ones whose presence
    needs explaining.

    ⚠ **THE SCOPE ITSELF IS A FILTER, AND THAT IS NOT A CONTRADICTION OF THE ABOVE** (D-590).
    `decided` hides only rows nobody has said anything about — never a row that is being
    OFFERED, never an added row, never a withdrawn row that somebody had decided about. The
    count of what it hides is reported beside the table (`count_cached_voices`), so the
    operator is told the vendor's list is larger rather than shown a shorter list that
    pretends to be the whole one.

    Order: still-listed before withdrawn, then the cheaper tier first (Sarvam, the default
    tier — plan §0 Q9), then label. The same key `voice_sync._ordered` uses for the picker,
    extended by the one column the picker has no rows for, so the operator's table and the
    client's picker do not sort one voice into two different places.
    """
    statement = select(PlatformVoiceCatalogEntry)
    if scope == "decided":
        statement = _decided(statement)
    rows = (await session.execute(statement)).scalars().all()
    live = await count_live_agents_by_voice()
    curated: list[CuratedVoice] = []
    for row in rows:
        voice = voice_from_row(row)
        if voice is None:
            # A row for a model this build no longer offers. Skipped rather than coerced,
            # exactly as `read_cached_catalogue` skips it: `Voice.tts_model` is a Literal,
            # and the honest reading of a row we cannot place is "not something this build
            # can describe", not "describe it as something else". It is unreachable today —
            # the sync drops such rows on the way in — and survives as the second gate for
            # a row an older build wrote.
            continue
        curated.append(_curated(row, live_agents=live.get(row.voice_id, 0)))
    return tuple(
        sorted(
            curated,
            key=lambda c: (c.withdrawn, c.voice.provider != "sarvam", c.voice.label),
        )
    )


async def set_curation_state(
    session: AsyncSession,
    *,
    voice_id: str,
    state: CurationState,
    now: datetime | None = None,
) -> CuratedVoice:
    """Move one voice's curation state. IDEMPOTENT; the CALLER commits.

    Idempotent because the write is a convergent overwrite of one column: enabling a voice
    that is already enabled writes the same row twice and changes nothing but `curated_at`.
    A double-clicked button is one outcome, not a conflict.

    **NO CAS TOKEN, AND THAT IS ARGUED RATHER THAN OMITTED.** BACKEND-PATTERNS' concurrency
    doctrine wants a compare-and-set wherever a screen can be stale about a value it is
    overwriting. Here the value is a three-member enum with no version a screen could hold,
    two operators racing produce one of the two states either of them asked for — both
    valid, both reversible in one click — and the losing writer's intent is recorded in
    `audit_log` either way. A token would buy a refusal dialog for an outcome that needs
    none. The same reading `set_agent_voice` records for a voice, and for the same reason.

    **IT DOES NOT LOOK AT AGENTS, AND DOES NOT REFUSE WHEN ONE IS ON THE VOICE.** See the
    module docstring: archiving cannot reach a live call, the count is shown to the operator
    BEFORE they click, and refusing would make a vendor's own withdrawal unfileable.

    The caller commits (BACKEND-PATTERNS §4) so the state change and its `audit_log` row are
    one act — a curation decision with no record of who made it is the one thing this table
    cannot reconstruct by re-running the sync.
    """
    stamp = now or datetime.now(UTC)
    result = await session.execute(
        update(PlatformVoiceCatalogEntry)
        .where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        .values(curation_state=state, curated_at=stamp)
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        # A voice id that is not in the cache at all. 404 rather than a business rule: the
        # operator is holding a stale table, and the fix is to refresh it — which is a
        # different action from anything the three buttons do.
        raise ProblemError.not_found("Voice")

    return await read_one_curated_voice(session, voice_id=voice_id)


def _curated(row: PlatformVoiceCatalogEntry, *, live_agents: int) -> CuratedVoice:
    """ONE ROW -> ONE `CuratedVoice`, given a voice this build can place.

    Extracted so the table, the curation write and the add write all describe a voice the
    same way — three copies of this constructor is three places a new column gets forgotten
    in two of them. The `cast`s are the database's CHECK constraints (migrations
    `e4b7a10c92d6` and `b8c3e50d4917`), which is where those two vocabularies are actually
    enforced; re-validating here would be a second, weaker copy of them.
    """
    voice = voice_from_row(row)
    if voice is None:  # pragma: no cover - callers narrow first
        raise ProblemError.not_found("Voice", row.voice_id)
    return CuratedVoice(
        voice=voice,
        state=cast("CurationState", row.curation_state),
        is_custom=row.is_custom,
        synced_at=row.synced_at,
        curated_at=row.curated_at,
        withdrawn_at=row.withdrawn_at,
        origin=cast("VoiceOrigin", row.origin),
        live_agents=live_agents,
    )


async def read_one_curated_voice(session: AsyncSession, *, voice_id: str) -> CuratedVoice:
    """The console's row for ONE voice, as it now stands — what a write answers with.

    Shared by `set_curation_state` and `voice_admission.admit_voice` so a voice that was just
    added and a voice that was just enabled come back in the same shape, through the same
    translation, with the same cross-tenant live count. It re-reads the row rather than
    echoing what was written, which is the property that makes it honest about the columns
    the caller did not set.
    """
    row = (
        await session.execute(
            select(PlatformVoiceCatalogEntry).where(PlatformVoiceCatalogEntry.voice_id == voice_id)
        )
    ).scalar_one()
    voice = voice_from_row(row)
    if voice is None:
        # Refused AFTER the write rather than before it, and deliberately: the row's state
        # is what the operator asked for and is not in doubt. What we cannot do is DESCRIBE
        # the voice, because its model has no provider and therefore no tier (hard rule 7),
        # and answering with a half-built row would put an unpriceable voice on a console
        # that prices everything it shows. Unreachable today — the sync drops such rows on
        # the way in.
        raise ProblemError(
            kind="business_rule",
            code="voice_model_unknown",
            title="That voice runs on a model this build cannot place",
            detail=(
                f"The cached voice {voice_id} names the model {row.tts_model}, which this "
                "build does not offer, so its voice tier — and therefore what a minute of "
                "it costs — cannot be determined."
            ),
            remediation="Refresh the voice catalogue, then try again.",
        )
    live = await count_live_agents_by_voice()
    return _curated(row, live_agents=live.get(row.voice_id, 0))


__all__ = [
    "CuratedVoice",
    "VoiceCuration",
    "VoiceScope",
    "count_cached_voices",
    "count_live_agents_by_voice",
    "count_offered_voices",
    "list_curated_voices",
    "read_curation",
    "read_one_curated_voice",
    "set_curation_state",
]
