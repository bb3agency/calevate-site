"""The voice catalogue, read from the ENGINE and cached — the sync half of D-585.

WHY THIS MODULE EXISTS
----------------------
`agents/voices.py` used to BE the catalogue: 44 speaker names compiled from Sarvam's own
SDK enum. Two facts killed that, and only one of them was ever discoverable from source:

1. **We publish through the ENGINE, not through Sarvam**, and the engine's Sarvam provider
   offers a DIFFERENT subset. A live publish on 11 Sep 2026 came back `400 POST /v2/agent`
   — *"Provided voice: Anushka is not available for the provider: sarvam"*. `anushka` is
   the first name in the SDK enum. The compiled list was offering a voice that fails on a
   real client's phone line, and nothing in this tree could have known.
2. **A CLONED voice cannot be in a compiled list at all, by construction.** The founder
   clones a voice on the engine account after this code ships; its id exists nowhere in our
   source and never will.

So the catalogue is READ (`VoiceEngine.list_voices`, whose adapter walks the engine's
two-step voice-config API), CACHED in `platform_voice_catalog`, and INSTALLED as a process
snapshot (`voices.install_voice_catalogue`).

THE THREE-STEP SHAPE, AND WHY IT IS THREE
-----------------------------------------
`sync_voice_catalogue` (engine -> rows) and `load_voice_catalogue` (rows -> snapshot) are
separate on purpose, and the ARQ job calls both. A worker that syncs is not the process
that serves the picker: the API workers must be able to pick the new catalogue up from the
TABLE without calling the vendor, and a process that cannot reach the engine must still be
able to serve the last good answer. Folding them would make every API boot a vendor round
trip and every vendor outage an empty picker.

WHAT MAKES THIS SAFE UNDER FAILURE (the part that reaches a client's phone line)
--------------------------------------------------------------------------------
* **AN INCOMPLETE LISTING NEVER PRUNES.** A page the adapter could not read looks exactly
  like a shorter catalogue, and pruning on it would withdraw voices that live agents are
  currently speaking. `EngineVoiceListing.complete` is carried for this one decision: an
  incomplete read still UPSERTS what it saw (a voice that is really there is not made less
  true by a page we missed) and leaves the rest of the table alone.
* **AN EMPTY LISTING IS REFUSED, NEVER APPLIED.** Zero voices is what a broken credential,
  a changed route and a genuinely empty account all look like, and only the last is a
  catalogue. This module refuses to write it and alerts instead, so the previous TABLE
  stands. (`voices.install_voice_catalogue` used to refuse `()` as a second backstop; since
  D-588 deleted the seed, "no voices in force" is a real state — a deployment nobody has
  synced — and the refusal that matters is the one HERE, at the only place that can tell an
  empty account from a broken credential.)
* **A VOICE THAT DISAPPEARS IS NOT DELETED FROM ANY AGENT.** `agents.tts_voice` is free
  text and `voices.speech_for_voice_id` passes an unrecognised id through verbatim, which
  is unchanged: an agent whose voice the vendor withdrew keeps speaking it and reads back
  as itself. What it loses is a place on the PICKER, which is correct — it is a voice the
  engine no longer offers.
* **AND IT IS NOT DELETED FROM THIS TABLE EITHER (D-588).** A complete listing that no
  longer names a voice stamps `withdrawn_at` instead of deleting the row, because the row
  now carries the one fact in it that a re-sync cannot re-derive: the operator's
  `curation_state`. Deleting it meant a voice that vanished from one listing and returned
  came back as a fresh un-curated row — silently disabled if it had been enabled, silently
  un-archived if it had been put away. A returning voice clears the stamp and keeps its
  state. ⚠ **AND THE STAMP IS AN OFFER DECISION, NOT A LOOKUP ONE (D-617).** This bullet
  used to end "`read_cached_catalogue` drops withdrawn rows, so the PICKER sees exactly
  what a delete used to leave it" — but that function feeds the LOOKUP snapshot and not
  the picker, so the drop also unnamed the voice a live agent was already speaking. It no
  longer drops them; `read_curation` excludes them and `voice_offer`'s ground zero refuses
  them, which is where the picker's answer actually comes from. See
  `read_cached_catalogue`.
* **CURATION IS NEVER WRITTEN BY A SYNC.** The upsert below names every column it
  refreshes, and `curation_state` is not among them: re-reading the vendor's list can
  neither offer a voice nor withdraw one. A sync reports what the platform has; an operator
  decides what we sell.
* **THE TIER NEVER COMES FROM THIS TABLE.** `voices.voice_tier` derives an agent's billing
  tier from the id's own model prefix (hard rule 7), so a row missing from this cache
  cannot re-price a minute. The `provider` column here is a derived convenience for readers
  and is computed from `tts_model` through the one registry that maps the two.

EVIDENCE
--------
The vendor route, its parameters and its `VoiceItem` shape are VERIFIED-VENDOR-DOCS in the
hash-pinned mirror, read 11 Sep 2026: `bolna-findings/mirror/pages/api-reference/voice/
overview.md`, `.../get_providers.md`, `.../get_all.md`. ⚠ **No live response of those two
routes has been read from this container** — `api.bolna.ai` is egress-blocked here — so the
adapter's parsing is exercised against the pinned shapes and the conformance stub, and
OPERATIONS §2 gate 3 is what closes it against the real account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, get_args

from calevate_shared.engine import EngineVoice, EngineVoiceListing, VoiceEngine
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.languages import PRODUCT_LANGUAGES
from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voices import (
    TtsModel,
    Voice,
    catalogue_note,
    install_voice_catalogue,
    provider_of_tts_model,
    voice_id_for,
    voice_tier,
)
from apps.api.billing.rates import VOICE_TIERS
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: What an operator is told when a sync read nothing. Authored, stable, and it names the
#: one thing they can act on — this string is an alert label, not prose.
EMPTY_LISTING_REASON: Final = "voice_catalogue_empty"


def _offered_model(tts_model: str) -> TtsModel | None:
    """`tts_model` as a member of our catalogue's `TtsModel`, or None.

    An identity lookup through `get_args(TtsModel)` rather than a `cast`: a cast is an
    assertion the type checker cannot check, and what arrives here is a string an engine
    (or a cached row written by an older build) chose. This narrows on evidence.
    """
    return next((model for model in get_args(TtsModel) if model == tts_model), None)


@dataclass(frozen=True, slots=True)
class VoiceSyncResult:
    """What one sync did, in the four numbers an operator's console shows.

    `pruned is None` is not zero: it means the listing was INCOMPLETE and pruning was
    deliberately not attempted, which is a different fact from "nothing needed pruning" and
    the only one that explains a catalogue that keeps a voice the vendor withdrew.

    "Pruned" is still the right word for a number the console prints, and it is now a
    WITHDRAWAL rather than a delete (D-588): the rows leave the picker and keep their
    curation state. The count is of rows newly stamped, so a voice withdrawn last week is
    not counted again this week — an operator reading `pruned: 0` is reading "the platform
    dropped nothing since the last run", which is the question they are asking.
    """

    seen: int
    written: int
    pruned: int | None
    complete: bool
    incomplete_reason: str | None = None
    #: Why no sync was ATTEMPTED, or None if one was (D-615).
    #:
    #: NOT `written == 0`, which is this module's other zero and means the opposite thing:
    #: that the engine was asked and answered with nothing usable, which is an ALARM and a
    #: standing catalogue. This one means nobody was asked, because on this engine there is
    #: nobody to ask — see `sync_voice_catalogue`. The console and the cron read it to say
    #: so, and `installed` stays False either way because neither writes a catalogue.
    skipped_reason: str | None = None

    @property
    def installed(self) -> bool:
        """Did this sync produce a catalogue the process can serve? False means the
        previous answer — or nothing at all, on a deployment that has never synced — is
        still standing, by design."""
        return self.written > 0


def voice_from_engine(entry: EngineVoice) -> Voice | None:
    """One normalized engine voice -> one catalogue entry, or None if we cannot offer it.

    THREE REASONS A ROW IS DROPPED, and each is a voice we could not honestly sell:

    * **A model whose provider no registry knows.** The provider decides the agent's voice
      TIER and therefore what a minute costs (hard rule 7, plan §2.3 invariant 7), so a
      model `model_lifecycle.TTS_MODEL_LIFECYCLE` cannot place is a minute nothing prices.
      The adapter already filters on our catalogue; this is the second gate, here because
      this function is what a future adapter's rows would also come through.
    * **No product language.** We sell Telugu, Hindi and Indian English; a voice the engine
      returned under none of them is a voice no picker in this product has a row for.
    * (Nothing else. In particular a voice with a gender we cannot map is NOT dropped —
      `gender` stays None, for the reason `voices.Voice.gender` gives: a name is not
      evidence of a voice, and neither is a vendor's enum we have not mapped.)

    `verified=True`, AND IT IS THE FIRST TIME ANY ENTRY IN THIS PRODUCT HAS CARRIED IT.
    `voices.Voice.verified` was False on all 44 seed entries with the reason written into
    the module: "what BOLNA's Sarvam provider accepts is their business, and the confirming
    read is a live listing on the account". This IS that read. A voice that came back from
    the engine's own catalogue for a model we offer is selectable on the account by the
    engine's own statement — which is precisely what OPERATIONS §2 gate 3 asked for.
    """
    model = _offered_model(entry.tts_model)
    provider = provider_of_tts_model(entry.tts_model) if model is not None else None
    if model is None or provider is None:
        return None
    languages = tuple(
        language for language in PRODUCT_LANGUAGES if language in set(entry.languages)
    )
    if not languages:
        return None
    return Voice(
        id=voice_id_for(entry.tts_model, entry.voice_id),
        # The ENGINE's own name, never `voice_id.capitalize()` — a cloned voice's name has
        # no derivable relationship to its id, and this string is a wire value as well as a
        # human one (`ModelConfig.tts_voice_label`).
        label=entry.label,
        provider=provider,
        tts_model=model,
        speaker=entry.voice_id,
        languages=languages,
        gender=None,
        verified=True,
        note=catalogue_note(provider),
    )


def offerable_pairs(listing: EngineVoiceListing) -> tuple[tuple[EngineVoice, Voice], ...]:
    """Each engine row paired with the catalogue entry it becomes, dropping what we cannot
    offer.

    THE PAIR EXISTS SO `is_custom` SURVIVES. `Voice` is the API response shape and has no
    such field by D-547's design (a client has no business knowing whose account a voice was
    cloned on), but the CACHE stores it because an operator reading the picker has to be
    able to tell their own clone from a stock persona. Re-deriving it from our seed — "a
    voice our compiled list never heard of" — was the first shape of this and it was wrong
    in the ordinary case: a stock persona the seed's partial sample never saw would have
    been filed as a clone. The engine's own `source` enum is the authority, so it is carried
    rather than inferred.
    """
    pairs = []
    for entry in listing.voices:
        voice = voice_from_engine(entry)
        if voice is not None:
            pairs.append((entry, voice))
    return tuple(pairs)


def catalogue_from_listing(listing: EngineVoiceListing) -> tuple[Voice, ...]:
    """Every offerable voice in one engine listing, in picker order.

    Sorted by provider then label so the picker's order is a property of the DATA rather
    than of the order three language passes happened to merge in. The VALUE rung first
    (plan §0 Q9): a client scrolling a list should reach the cheaper tier before the one
    that costs more per minute.
    """
    return _ordered([voice for _, voice in offerable_pairs(listing)])


def _ordered(voices: list[Voice]) -> tuple[Voice, ...]:
    """Picker order, in one place: cheaper tier first, then label.

    ⚠ **THE KEY WAS `provider != "sarvam"` UNTIL 18 Sep 2026 AND IS NOW DERIVED.** It was a
    vendor name doing a tier's job, which stopped being true the moment the Sarvam TTS leg
    was withdrawn and Gnani took the value rung. `voice_tier()` is the one derivation of a
    voice's rung, and `VOICE_TIERS` is card order (value first), so the sort now asks the
    same two functions the money lane does and cannot disagree with them about which
    column is cheaper.
    """
    return tuple(sorted(voices, key=_picker_key))


def _picker_key(voice: Voice) -> tuple[int, str]:
    return (VOICE_TIERS.index(voice_tier(voice.id)), voice.label)


async def sync_voice_catalogue(
    session: AsyncSession, engine: VoiceEngine, *, now: datetime | None = None
) -> VoiceSyncResult:
    """Read the engine's voices and make `platform_voice_catalog` say so. IDEMPOTENT.

    Idempotent at the ROW (BACKEND-PATTERNS §4): every voice is an upsert keyed on our
    catalogue id, so running this twice in a minute writes the same table twice and changes
    nothing but `synced_at`. There is no claim row and no lease — the operation is a
    convergent overwrite of a cache, so two workers racing produce the same table, and the
    ARQ cron's own `job_id` already single-flights a tick.

    The caller COMMITS. This function never does, for `BACKEND-PATTERNS`' reason: the ARQ
    job wants the write and the snapshot install to be one act, and an ops route wants the
    write inside the request's transaction with its audit row.

    **AND IT DOES NOTHING AT ALL ON AN ENGINE THAT IS US (D-615).** Everything above is an
    argument about a SECOND OPINION: the vendor's list is an authority we do not control,
    which is why an empty one is refused, an incomplete one never prunes, and a curated row
    is never overwritten. On `agent_hosting="owned_runtime"` there is no vendor —
    `PipecatEngine.list_voices` reads `platform_voice_catalog WHERE origin = 'operator'`,
    which is THIS TABLE — so a sync there reads its own output and writes it back, and the
    adapter records the circularity rather than leaving it to be found
    (`engine/pipecat.py::SqlControlPlane.voices`). Two things make that worse than merely
    pointless, which is why this is a refusal and not a shrug:

    * **the prune arm is live.** An operator-origin listing is complete, so every row the
      operator has not attested — every `synced` row a previous engine cached — is stamped
      `withdrawn_at` on the first tick after the engine changes. The table would be pruned
      against itself.
    * **the empty-listing alarm fires on a correct state.** A deployment whose operator has
      not attested a voice yet has no operator rows, which is not a revoked credential; the
      alarm's own remediation ("check the engine credential") names a credential this engine
      does not have (`PipecatEngine.credential_env_keys` is empty).

    The catalogue on such an engine is maintained by `voice_admission.admit_voice`, which is
    the operator attesting a voice — the only authority left once the vendor is gone.
    """
    if not engine.capabilities.lists_voices_independently():
        # A STATED NO-OP, the shape `workers/engine_violations._sweep` uses for an engine
        # with no violations surface: the caller gets a result that says which of "nothing
        # to do" and "we could not look" happened, rather than a zero that reads like both.
        reason = (
            "this voice platform has no catalogue of its own — its voices are the ones an "
            "operator attested here, so there is nothing to re-read"
        )
        log.info(
            "voice_catalogue_sync_skipped",
            extra={"engine": engine.name, "reason": "engine_has_no_independent_catalogue"},
        )
        return VoiceSyncResult(seen=0, written=0, pruned=None, complete=True, skipped_reason=reason)
    listing = await engine.list_voices()
    pairs = offerable_pairs(listing)
    voices = _ordered([voice for _, voice in pairs])
    if not voices:
        # REFUSED RATHER THAN WRITTEN. An empty catalogue is what a revoked key, a moved
        # route and a genuinely empty account all look like, and only the last is a
        # catalogue — while applying it would take the voice picker to zero entries and
        # make every agent's configured voice read as withdrawn. The previous table stands.
        alert(
            "CORE_LOGIC",
            EMPTY_LISTING_REASON,
            detail=(
                "the voice catalogue sync read no offerable voices from the engine, so the "
                "previous catalogue is still standing. Check the engine credential and run "
                "POST /v1/ops/voices/refresh."
            ),
            engine=engine.name,
            complete=str(listing.complete),
            returned=str(len(listing.voices)),
        )
        return VoiceSyncResult(
            seen=len(listing.voices),
            written=0,
            pruned=None,
            complete=listing.complete,
            incomplete_reason=listing.incomplete_reason,
        )

    stamp = now or datetime.now(UTC)
    rows = [
        {
            "voice_id": voice.id,
            "engine_voice_id": voice.speaker,
            "label": voice.label,
            "tts_model": voice.tts_model,
            "provider": voice.provider,
            "languages": list(voice.languages),
            # The ENGINE's own `source` enum, carried through the pair — see
            # `offerable_pairs` for why it is not re-derived from our seed.
            "is_custom": entry.is_custom,
            "synced_at": stamp,
        }
        for entry, voice in pairs
    ]
    statement = insert(PlatformVoiceCatalogEntry).values(rows)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[PlatformVoiceCatalogEntry.voice_id],
            set_={
                # Every column but the key: a renamed clone, a voice that gained a language
                # and a model re-pointed at another provider are all things the engine may
                # legitimately report, and a cache that kept the first answer would be a
                # second opinion about the vendor's own list.
                "engine_voice_id": statement.excluded.engine_voice_id,
                "label": statement.excluded.label,
                "tts_model": statement.excluded.tts_model,
                "provider": statement.excluded.provider,
                "languages": statement.excluded.languages,
                "is_custom": statement.excluded.is_custom,
                "synced_at": statement.excluded.synced_at,
                # `origin` IS ABSENT FOR THE SAME REASON `curation_state` IS (D-590). A
                # row an operator TYPED and we verified is an attestation, not a cache
                # line; re-reading the vendor's list is not entitled to reclassify it as
                # one. The column's server default (`synced`) is therefore what a genuinely
                # new row gets, and an adopted row keeps `operator` forever.
                #
                # A RETURNING VOICE IS UN-WITHDRAWN, AND KEEPS THE STATE IT WAS PUT AWAY
                # WITH. `curation_state` is deliberately absent from this list — see the
                # module docstring: a sync reports what the platform has and never decides
                # what we sell. Clearing the stamp is not that decision; it is the same
                # vendor statement as the row itself.
                "withdrawn_at": None,
            },
        )
    )

    pruned: int | None = None
    if listing.complete:
        # ONLY ON A COMPLETE LISTING. See the module docstring: a page we failed to read is
        # indistinguishable from a shorter catalogue, and pruning on one would withdraw
        # voices that live agents are speaking right now.
        #
        # A STAMP, NOT A DELETE (D-588). The row is the only place an operator's curation
        # decision exists, and it is the one thing here a re-sync cannot re-derive. Already
        # withdrawn rows are excluded so the count means "newly dropped by the platform"
        # rather than "still missing", which is the number the console prints.
        result = await session.execute(
            update(PlatformVoiceCatalogEntry)
            .where(
                PlatformVoiceCatalogEntry.voice_id.not_in([voice.id for voice in voices]),
                PlatformVoiceCatalogEntry.withdrawn_at.is_(None),
            )
            .values(withdrawn_at=stamp)
        )
        # `rowcount` is on the DBAPI cursor result; SQLAlchemy's async `Result` exposes it
        # for a DML statement, and mypy's stub does not know that of the generic `Result`.
        pruned = int(result.rowcount or 0)  # type: ignore[attr-defined]

    log.info(
        "voice_catalogue_synced",
        extra={
            "engine": engine.name,
            "seen": len(listing.voices),
            "written": len(rows),
            "pruned": pruned,
            "complete": listing.complete,
        },
    )
    return VoiceSyncResult(
        seen=len(listing.voices),
        written=len(rows),
        pruned=pruned,
        complete=listing.complete,
        incomplete_reason=listing.incomplete_reason,
    )


async def read_cached_catalogue(session: AsyncSession) -> tuple[Voice, ...]:
    """The cached rows as catalogue entries — no engine call.

    The `note` is COMPOSED from the provider rather than stored, for the reason
    `voices._NOTE` is composed from `voice_tier_label`: it is a client-facing sentence that
    names the tier, so a copy frozen into a cache row would still be saying "Studio" the
    day the tier was renamed. `verified=True` for `voice_from_engine`'s reason — these rows
    exist because the engine listed them.

    ⚠ **EVERY ROW IS RETURNED, WITHDRAWN ONES INCLUDED — AND THIS EXCLUDED THEM UNTIL
    D-617 (15 Sep 2026).** The exclusion read `WHERE withdrawn_at IS NULL`, and it is the
    one line that made a live client's configured voice unnameable on their own screen.

    The argument it was written on is the right argument aimed at the wrong layer. It said:
    a voice the PLATFORM no longer lists is not a voice any more, so it should "leave the
    catalogue exactly as a deleted row used to". But **this function does not feed the
    OFFER layer; it feeds the LOOKUP layer** — its one caller is `load_voice_catalogue`,
    which installs the process snapshot behind `voices.catalogue()`, `voices.get_voice()`
    and `voices.speech_for_voice_id()`. Those are read on every publish, every drift sweep
    and every read-back a console renders. The paragraph below already made the whole
    argument about a curated-OFF row and then did not apply it to a withdrawn one:

    * A voice an OPERATOR disabled or archived is still a real voice on the account, and it
      stays in the catalogue on purpose. `voices.catalogue()` is the LOOKUP layer: it is
      what resolves the id on a live agent's row through `speech_for_voice_id` and
      `get_voice`, on every publish and every drift sweep. Dropping a disabled voice here
      would leave a client's agent publishing its own composed id in the vendor's speaker
      slot the moment somebody clicked a toggle. Whether it may be OFFERED is
      `agents/voice_offer.py`'s fourth ground, and that is the only place it is decided.

    A WITHDRAWN row sits in exactly that position, and the cost was measured on a live
    client's agent: its voice (`sonic-3.5:b6dafaa0-…`) was withdrawn by a sync, so
    `get_voice` answered None and

    * the agent's panel printed the raw engine ref under BOTH "callers hear now" and
      "configured", with no sentence saying why — `publishing._reading` degrades to the id;
    * the picker lost the whole Studio tier, because `voicePicker.tsx` keeps the row an
      agent is ALREADY SET TO however it is refused, and a row that is not in the catalogue
      at all cannot be kept;
    * `speech_for_voice_id` returned `(None, "sonic-3.5:b6dafaa0-…")`, so the next publish
      would have sent our own COMPOSED catalogue id in the vendor's speaker slot with no
      model beside it — which on the Cartesia arm is a refused publish
      (`engine/bolna._refuse_cartesia_voice_incomplete`) and on the Sarvam arm is a string
      no vendor has ever heard of.

    **NOTHING BECOMES OFFERABLE BY THIS**, which is why the fix belongs here and not in a
    screen. `voice_curation.read_curation()` still excludes withdrawn rows, so a withdrawn
    voice reaches `voice_offer` with NO curation state — and `curation_unofferable_reason
    (None)` already exists for precisely this pairing, returns `NOT_CURATED_REASON` ("the
    voice platform no longer lists this voice on our account"), and its own docstring names
    the case: "a voice the catalogue snapshot holds and the live table does not". The two
    were designed to meet; the exclusion here is what stopped them. The picker then renders
    the tier, shows the configured voice, and prints the vendor's withdrawal as the reason
    it cannot be chosen again.
    """
    rows = (await session.execute(select(PlatformVoiceCatalogEntry))).scalars().all()
    return _ordered([voice for voice in map(voice_from_row, rows) if voice is not None])


def voice_from_row(row: PlatformVoiceCatalogEntry) -> Voice | None:
    """ONE CACHED ROW -> ONE CATALOGUE ENTRY, or None for a row this build cannot place.

    Public because `agents/voice_curation.py` renders the SAME voice in the operator's
    table that the client's picker renders, and a second translation there would be the
    place the two came to describe one voice differently — a different label, a different
    language list, a different tier name.

    TWO REASONS A ROW IS DROPPED, and each is the same refusal `voice_from_engine` makes on
    the way in. A model `TTS_MODEL_LIFECYCLE` cannot place has no provider, therefore no
    voice tier, therefore no price for a minute of it (hard rule 7). A row under none of the
    three product languages is a voice no picker in this product has a row for. Both are
    unreachable through today's sync, which applies the same two gates; they survive as the
    second gate for a row an older build wrote.
    """
    model = _offered_model(row.tts_model)
    provider = provider_of_tts_model(row.tts_model) if model is not None else None
    if model is None or provider is None:
        return None
    languages = tuple(language for language in PRODUCT_LANGUAGES if language in set(row.languages))
    if not languages:
        return None
    return Voice(
        id=row.voice_id,
        label=row.label,
        provider=provider,
        tts_model=model,
        speaker=row.engine_voice_id,
        languages=languages,
        gender=None,
        verified=True,
        note=catalogue_note(provider),
    )


async def load_voice_catalogue(session: AsyncSession) -> int:
    """Install the cached catalogue into THIS process. Returns how many voices are in force.

    Called at API and worker startup and after every sync. **A miss is not an error and
    must not be treated as one**: a deployment on which no sync has ever run has NO voices,
    says `source: "unsynced"` on every surface that renders a picker, and tells the reader
    to sync and then enable. D-588 deleted the compiled seed that used to answer here — see
    `voices.install_voice_catalogue` for why an empty catalogue is now a state rather than a
    refusal, and why the protection against a BROKEN read is in `sync_voice_catalogue`
    instead.
    """
    voices = await read_cached_catalogue(session)
    if not voices:
        log.info("voice_catalogue_unsynced", extra={"reason": "no cached rows"})
        install_voice_catalogue(None)
        return 0
    install_voice_catalogue(voices)
    return len(voices)


__all__ = [
    "EMPTY_LISTING_REASON",
    "VoiceSyncResult",
    "catalogue_from_listing",
    "load_voice_catalogue",
    "offerable_pairs",
    "read_cached_catalogue",
    "sync_voice_catalogue",
    "voice_from_engine",
    "voice_from_row",
]
