"""The seam between the ops price store and the money/picker modules that read it.

The catalogue lane defined a deliberately narrow contract, in parts that are all the same
shape (its own words, `billing/rates.install_llm_price_attestations` and
`agents/llm_models.install_llm_credential_reader`):

    a SYNC, no-argument reader, installed once at startup, returning a value the money
    module and the picker can read WITHOUT importing this console module and WITHOUT a
    database.

    price attestations   () -> Mapping[str, billing.rates.LlmPriceAttestation]
    installed legs        () -> frozenset[calevate_shared.engine.LlmProvider]
    dashboard data use    () -> frozenset[calevate_shared.engine.LlmProvider]
    TTS price billable    (VoiceProvider) -> bool

The fourth (D-547) is the voice twin of the first, and it is a PREDICATE rather than a
mapping because its one caller asks one question: `agents/voice_offer.tts_price_is_billable`
decides whether a voice tier may be offered at all, and it has no use for the figure. The
figure itself never travels this way — `workers/pipeline.py` meters a Cartesia minute from
`attested_tts_prices` on its own session, at the instant the call happened, because a price
is effective-dated and a snapshot is not (see WHAT THE SNAPSHOT DOES NOT DO, below).

The third (D-477) is the same shape for the same reason and is deliberately NOT folded into
the second: "we hold a key for this leg" and "an operator has attested this leg's vendor does
not train on what we send it" are two facts with two owners, and a single set would make an
installed key look like a compliance clearance.

All three must be synchronous and take no session, because they are called several layers
deep in code that has no business opening a database — the picker on a request, the metering
path on a job, the assist selector inside a worker — and because they must stay exercisable
with no database at all (tests install a fake reader; the default is empty, which is the
honest "nothing attested yet" state). This module is the ops side of all three seams: it
keeps an in-process SNAPSHOT of the attested prices, the installed credentials and the
data-use attestations, refreshes it off the request path, and installs the readers over it.
The shape is `core/platform_config`'s: durable truth in Postgres, an in-memory snapshot in
front, a background poll that refreshes it.

WHY A SNAPSHOT AND NOT A LIVE QUERY. The readers are sync and the store is async — a sync
reader physically cannot await a query — so the value has to already be in memory when it
is asked for. That is the same reason `get_settings()` reads a snapshot rather than the
database, and the reason this poll exists rather than a query per price lookup.

WHAT THE SNAPSHOT DOES NOT DO: point-in-time resolution. The billing seam
(`attested_llm_prices`) is "the price live NOW", so this snapshot resolves at `now()`. The
effective-dated history in `platform_model_prices` is preserved for the routes (which show
today's price and could show any month's) and for a future point-in-time billing reader;
the current seam reads the current price, which is the catalogue lane's design and not
this module's to change.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import cast

from calevate_shared.engine import LlmProvider

from apps.api.agents.llm_models import (
    install_dashboard_data_use_reader,
    install_llm_credential_reader,
)
from apps.api.agents.voice_offer import default_tts_price_is_billable, install_tts_price_reader
from apps.api.agents.voice_sync import load_voice_catalogue
from apps.api.agents.voices import VoiceProvider
from apps.api.billing.rates import LlmPriceAttestation, install_llm_price_attestations
from apps.api.core.logging import get_logger
from apps.api.db.session import untenanted_session
from apps.api.ops.model_pricing import (
    TTS_PROVIDERS,
    AttestedModelPrice,
    attested_model_prices,
    dashboard_permitted_providers,
    installed_llm_legs,
    tts_price_is_billable,
)

log = get_logger(__name__)

#: How often this process re-reads the price store. Far slower than `platform_config`'s 3s:
#: a price is a deliberate, rare operator act, not a state that drifts, and nothing on a
#: latency-critical path reads it (the in-call LLM leg is not metered; the dashboard assist
#: is priced on a worker job, not a phone call). A newly attested price becomes offerable
#: within this interval, and the attestation route triggers a refresh itself so the common
#: case is immediate.
_POLL_INTERVAL_S = 30.0


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    """What this process last read from the ops store. Every field is a read-only view."""

    attestations: Mapping[str, LlmPriceAttestation]
    installed_providers: frozenset[LlmProvider]
    #: Legs whose LATEST data-use attestation permits the DASHBOARD assist. Empty means
    #: "nobody has attested", never "the operator said no" — see
    #: `agents/llm_models.dashboard_data_use_attested`.
    dashboard_data_use: frozenset[LlmProvider]
    #: Voice providers a minute may be METERED at a cost on (D-547) — the set form of
    #: `ops/model_pricing.tts_price_is_billable`. `sarvam` is in it with no attestation
    #: because the engine bills us for that leg and reports what it charged; a BYOK leg is
    #: in it only once an operator has read a price off the vendor's invoice.
    billable_tts: frozenset[str]


_EMPTY = PricingSnapshot(
    attestations=MappingProxyType({}),
    installed_providers=frozenset(),
    dashboard_data_use=frozenset(),
    # THE PICKER'S OWN DEFAULT, not an empty set, and the difference is a screen with no
    # voices on it. The three LLM fields above fail safe when empty ("nothing attested,
    # Azure-only"); this one does not — an empty set refuses EVERY voice, including the
    # Sarvam tier, whose cost the engine meters and which needs no attestation at all. So
    # the cold snapshot is built from the one function that states that rule
    # (`voice_offer.default_tts_price_is_billable`) rather than from a second spelling of
    # it here, and `install_pricing_readers()` before the first refresh answers exactly as
    # the uninstalled picker would.
    billable_tts=frozenset(
        # `cast`, because `TTS_PROVIDERS` is declared as plain strings (it spells the DB
        # column's values) while the picker's predicate is typed over the catalogue's
        # Literal. `tests/tts_price_attestation_test.py` is what holds the two vocabularies
        # equal, so this is a spelling of a fact a test already enforces, not a widening.
        p
        for p in TTS_PROVIDERS
        if default_tts_price_is_billable(cast("VoiceProvider", p))
    ),
)
_snapshot: PricingSnapshot = _EMPTY
_refresher: asyncio.Task[None] | None = None


def _to_attestation(record: AttestedModelPrice) -> LlmPriceAttestation | None:
    """One store row as the billing seam's record, or `None` if it cannot be one.

    `read_on` is the attestation's own date (`attested_at.date()`) — the store keeps no
    separate "read on" instant, and the date the operator wrote it is the best available
    reading of when they read it. Returns `None` rather than raising if the record cannot
    satisfy `LlmPriceAttestation`'s invariants (a non-positive price should be impossible
    after the write-path and CHECK both refuse it, but one malformed legacy row must not
    blank every OTHER model's price — the fail-safe direction).
    """
    try:
        return LlmPriceAttestation(
            model=record.model,
            input_usd_per_mtok=record.input_usd_per_mtok,
            output_usd_per_mtok=record.output_usd_per_mtok,
            read_on=record.attested_at.date(),
            attested_by=record.attested_by,
            source=record.source_note,
        )
    except ValueError:
        log.error("attested_price_unusable", extra={"model": record.model})
        return None


async def refresh_pricing_snapshot() -> PricingSnapshot:
    """Re-read the price store and the installed credentials into the process snapshot.

    Never raises — a price store this process cannot read must not take down the metering
    path or the picker; the last good snapshot (empty on a cold start, which bills Azure off
    its verified catalogue reading exactly as before this seam existed) keeps serving, and
    the failure is logged. Same fail-safe direction as `platform_config.refresh`.
    """
    global _snapshot
    try:
        async with untenanted_session() as session:
            priced = await attested_model_prices(session, at=datetime.now(UTC))
            # `installed_llm_legs` carries the stored-only credential rule (see its
            # docstring), so this reader reproduces
            # `agents.llm_models.installed_llm_providers()`'s default when nothing is
            # stored.
            #
            # ⚠ **THIS SAID "already carries the azure-always rule … and never makes an
            # Azure-catalogue model disappear from the picker". THERE IS NO SUCH RULE ANY
            # MORE AND THE SECOND HALF IS NOW BACKWARDS.** `model_pricing.installed_llm_legs`
            # adds `azure_openai` only when `azure_credentials()` returns all three of
            # resource, key and deployment — so on a deployment where those are unset,
            # making every Azure model disappear from the picker is exactly and correctly
            # what this does. A comment promising the opposite is how the defect that
            # change fixed — offering a model the kitchen cannot cook — would get
            # reintroduced by the next reader.
            installed = await installed_llm_legs(session)
            data_use = await dashboard_permitted_providers(session)
            # THROUGH THE DOOR, once per provider, rather than reading the price table and
            # re-deriving the rule here. `tts_price_is_billable` carries the one statement
            # of what makes a tier billable (an attested figure, or the engine's own
            # metered Sarvam leg); a second derivation over `attested_tts_prices` would be
            # the second definition, and the two would differ the day a third provider
            # arrives. Two round trips on a 30-second poll, off the request path.
            billable_tts = frozenset(
                [
                    provider
                    for provider in TTS_PROVIDERS
                    if await tts_price_is_billable(session, provider=provider, at=datetime.now(UTC))
                ]
            )
    except Exception as exc:
        log.error("pricing_snapshot_refresh_failed", extra={"reason": type(exc).__name__})
        return _snapshot

    attestations: dict[str, LlmPriceAttestation] = {}
    for model, record in priced.items():
        attestation = _to_attestation(record)
        if attestation is not None:
            attestations[model] = attestation
    _snapshot = PricingSnapshot(
        attestations=MappingProxyType(attestations),
        installed_providers=installed,
        dashboard_data_use=data_use,
        billable_tts=billable_tts,
    )
    return _snapshot


async def refresh_voice_catalogue_snapshot() -> None:
    """Re-read the cached voice catalogue into this process. NEVER RAISES.

    Same fail-safe direction as `refresh_pricing_snapshot`: a table this process cannot
    read must not take down the voice picker, so the catalogue already in force (or
    no voices at all on a cold start that has never synced) keeps serving and the failure is
    logged.
    This is also what makes `POST /v1/ops/voices/refresh` reach every API process rather
    than only the one that served the request.
    """
    try:
        async with untenanted_session() as session:
            await load_voice_catalogue(session)
    except Exception as exc:
        log.error("voice_catalogue_snapshot_refresh_failed", extra={"reason": type(exc).__name__})


def _read_attestations() -> Mapping[str, LlmPriceAttestation]:
    """The sync reader billing installs. Zero IO — the snapshot is already in memory."""
    return _snapshot.attestations


def _read_installed_providers() -> frozenset[LlmProvider]:
    """The sync reader the picker installs. Zero IO."""
    return _snapshot.installed_providers


def _read_dashboard_data_use() -> frozenset[LlmProvider]:
    """The sync reader the dashboard-assist eligibility gate installs. Zero IO."""
    return _snapshot.dashboard_data_use


def _read_tts_price_billable(provider: str) -> bool:
    """The sync reader the voice picker installs. Zero IO."""
    return provider in _snapshot.billable_tts


def install_pricing_readers() -> None:
    """Point the money module and the pickers at THIS process's snapshot.

    Idempotent — installing twice registers the same four functions. Called from startup,
    beside `start_pricing_refresher`; a process that installs but never refreshes serves the
    empty snapshot, which is the safe "nothing attested, Azure-only" default the catalogue
    lane designed for.
    """
    install_llm_price_attestations(_read_attestations)
    install_llm_credential_reader(_read_installed_providers)
    install_dashboard_data_use_reader(_read_dashboard_data_use)
    install_tts_price_reader(_read_tts_price_billable)


def uninstall_pricing_readers() -> None:
    """Reset all three seams to their empty default. For tests, which must not leak a
    snapshot between cases — the mirror of the catalogue lane's `install_*(None)`."""
    install_llm_price_attestations(None)
    install_llm_credential_reader(None)
    install_dashboard_data_use_reader(None)
    install_tts_price_reader(None)


async def _poll_forever() -> None:
    # Refresh first, then sleep, for `platform_config._poll_forever`'s reason: a process
    # that just started is the one most likely to be serving the empty default, and making
    # it wait a full interval before its first read would offer Azure-only for 30s after
    # every deploy for no reason. `refresh_pricing_snapshot` never raises, so this loop
    # cannot die.
    while True:
        await refresh_pricing_snapshot()
        # ⚠ THE VOICE CATALOGUE RIDES THIS POLL, AND THIS MODULE'S NAME IS NOW NARROWER
        # THAN ITS CONTENTS (D-585). It is a second platform-scoped fact this process
        # serves from an in-memory snapshot and refreshes off the request path — the
        # identical shape, the same session pool, the same 30-second budget — and the
        # alternative was a second task, a second start/stop pair and a second place for
        # a refresher to be forgotten at startup. It is here rather than in a module of
        # its own because BOTH processes that matter already start this one
        # (`apps/api/main.py`, `apps/workers/settings.py`); a third refresher would have
        # to be wired into both again, which is exactly the half-wired seam the voice
        # catalogue exists to stop being.
        await refresh_voice_catalogue_snapshot()
        await asyncio.sleep(_POLL_INTERVAL_S)


def start_pricing_refresher() -> None:
    """Begin polling the price store in this process. Idempotent.

    Installs the readers and starts the poll together, so a caller adopts the whole
    seam with one line — the shape `start_config_refresher` has. The task reference is held
    in a module global so it cannot be garbage-collected mid-flight.
    """
    global _refresher
    install_pricing_readers()
    if _refresher is not None and not _refresher.done():
        return
    _refresher = asyncio.get_running_loop().create_task(_poll_forever())


async def stop_pricing_refresher() -> None:
    """Cancel the poll. For shutdown and for tests that must not leak a task.

    `stop_fx_refresher`' shape, and it exists for the reason that one does: the two
    other refreshers in this fleet (`platform_config`, `fx_rates`) can be stopped and
    this one could not, so a worker shutting down cancelled two of its three background
    polls and left the third running against a session factory being torn down under it.
    One way per problem — a seam with a `start` and no `stop` is the half of the pair
    that the next reader has to discover from a traceback.

    The readers stay installed. Uninstalling them on shutdown would put the picker and
    the billing seam back on their fallbacks for the remainder of the process's life,
    which is the opposite of what a shutdown wants; `uninstall_pricing_readers` is the
    door for a test that needs the un-installed state.
    """
    global _refresher
    if _refresher is None:
        return
    _refresher.cancel()
    with suppress(asyncio.CancelledError):
        await _refresher
    _refresher = None


__all__ = [
    "PricingSnapshot",
    "install_pricing_readers",
    "refresh_pricing_snapshot",
    "refresh_voice_catalogue_snapshot",
    "start_pricing_refresher",
    "stop_pricing_refresher",
    "uninstall_pricing_readers",
]
