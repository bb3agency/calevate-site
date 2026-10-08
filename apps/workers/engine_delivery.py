"""Where the post-call pipeline reads a call's truth from, when it is not `get_execution`.

D-31 makes the authenticated fetch the truth and the webhook a hint. ThinnestAI's first docs
broke that premise for inbound calls: `GET /calls/{id}` answered 404 for a call the API did
not place (`thinnest-findings/mirror/pages/api-reference/get-call.md:50-52`), leaving its
transcript only in the signed `call.analysed` delivery. The current docs say the endpoint
takes the call reference of any call (`snapshots/2026-10-07/pages/api-reference/calls/
get-call.md:7`), so the fetch usually answers now; the fallbacks below are for when it does
not. A delivery whose HMAC verified is authenticated, which is the property D-31 wanted the
fetch for.

So, in order:

1. a SEALED DELIVERY on the job (voice-runtime verified it and sealed it under the engine
   intake key) is opened and read by the adapter;
2. otherwise `get_execution`;
3. and when the engine will not serve the call by id (404) and a delivery for it was
   archived on an earlier run, that archive is read instead — a reconciliation re-drive
   of an inbound call carries no delivery.

Nothing here reads a vendor field: the adapter turns the document into a snapshot
(`snapshot_from_delivery`), and the document's bytes travel as `raw_document` so the
archive holds the signed original.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final, Protocol, runtime_checkable
from uuid import UUID

from calevate_shared.engine import ExecutionSnapshot, VoiceEngine
from calevate_shared.engine_scope import split_handle
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.reliability.engine_intake_keys import open_delivery, seal_delivery
from apps.workers.storage import read_engine_payload


@runtime_checkable
class ReadsDeliveries(Protocol):
    """An adapter that can read a verified delivery body (`ThinnestEngine` today)."""

    def snapshot_from_delivery(
        self, payload: dict[str, Any], *, workspace: str | None = None
    ) -> ExecutionSnapshot: ...


def _unreadable(detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="engine_delivery_unreadable",
        title="A queued engine delivery could not be read",
        detail=detail,
    )


def snapshot_of_document(
    engine: VoiceEngine, document: bytes, *, execution_id: str
) -> ExecutionSnapshot:
    """The adapter's snapshot of one delivered document, refused if it names another call."""
    if not isinstance(engine, ReadsDeliveries):
        raise _unreadable(f"the {engine.name} adapter cannot read a delivered document")
    try:
        payload = json.loads(document)
    except ValueError as exc:
        raise _unreadable("the delivered document is not JSON") from exc
    if not isinstance(payload, dict):
        raise _unreadable("the delivered document is not an object")
    # The receiver scoped the job's execution id to the delivering agent's workspace
    # (D-687), so the snapshot is read in the same one.
    snapshot = engine.snapshot_from_delivery(payload, workspace=split_handle(execution_id)[1])
    if snapshot.engine_call_id != execution_id:
        raise _unreadable("the delivered document names a different call than its job")
    return snapshot.model_copy(update={"raw_document": document})


def delivered_document(
    engine_name: str, execution_id: str, delivery: Mapping[str, Any] | None
) -> bytes | None:
    if delivery is None:
        return None
    if not isinstance(delivery, Mapping):
        raise _unreadable("the job's delivery is not an envelope")
    return open_delivery(delivery, engine=engine_name, execution_id=execution_id)


#: The sealing unit name of a LISTING row carried on a re-drive (see `seal_listing`).
_LISTING_UNIT: Final = "listing"


def seal_listing(engine: VoiceEngine, snapshot: ExecutionSnapshot) -> dict[str, Any]:
    """A reconciliation listing row, sealed for the ingest job — `{}` for an engine whose
    every call can be fetched by id.

    For an inbound ThinnestAI call whose webhook was lost, the call list is the ONLY record
    left (no transcript, no recording: list-calls.md:250-252), so the poller's re-drive must
    carry the row. It is OUR snapshot (no vendor field), sealed because it holds the caller's
    number (hard rule 6).
    """
    if not isinstance(engine, ReadsDeliveries):
        return {}
    return {
        "listed": seal_delivery(
            snapshot.model_dump_json(),
            engine=engine.name,
            execution_id=snapshot.engine_call_id,
            event_name=_LISTING_UNIT,
        )
    }


def _listed_snapshot(
    engine_name: str, execution_id: str, listed: Mapping[str, Any] | None
) -> ExecutionSnapshot | None:
    if listed is None:
        return None
    if not isinstance(listed, Mapping):
        raise _unreadable("the job's listing row is not an envelope")
    document = open_delivery(listed, engine=engine_name, execution_id=execution_id)
    try:
        snapshot = ExecutionSnapshot.model_validate_json(document)
    except ValueError as exc:
        raise _unreadable("the job's listing row is not a snapshot") from exc
    if snapshot.engine_call_id != execution_id:
        raise _unreadable("the job's listing row names a different call than its job")
    return snapshot


async def execution_truth(
    engine: VoiceEngine,
    execution_id: str,
    delivery: Mapping[str, Any] | None,
    *,
    listed: Mapping[str, Any] | None = None,
) -> ExecutionSnapshot:
    """The ingest job's read: a delivery, else the fetch, else (404) the listing row."""
    document = delivered_document(engine.name, execution_id, delivery)
    if document is not None:
        return snapshot_of_document(engine, document, execution_id=execution_id)
    try:
        return await engine.get_execution(execution_id)
    except EngineRejectedError as exc:
        fallback = _listed_snapshot(engine.name, execution_id, listed) if _absent(exc) else None
        if fallback is None:
            raise
        _settled_without_delivery(engine.name, execution_id)
        return fallback


def _settled_without_delivery(engine_name: str, execution_id: str) -> None:
    """The call list knows this call and no signed delivery reached us: it settles with no
    transcript and no recording, and that loss is worth an operator's eye."""
    alert(
        "WORKER_DELIVERY",
        "engine_call_settled_without_delivery",
        detail=(
            f"engine={engine_name}: settled from the call list because its signed delivery "
            "never arrived and the engine would not serve it by id. Status and minutes are "
            "recorded and the recording is copied from the engine's recording endpoint; the "
            "transcript is not recoverable."
        ),
        execution_id=execution_id,
    )


def _absent(exc: EngineRejectedError) -> bool:
    return exc.vendor_status == 404


async def post_call_truth(
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    call_id: UUID,
    execution_id: str,
    delivery: Mapping[str, Any] | None,
    listed: Mapping[str, Any] | None = None,
) -> ExecutionSnapshot:
    """The post-call read: a delivery, else the fetch, else (404) the archived delivery,
    else the listing row."""
    document = delivered_document(engine.name, execution_id, delivery)
    if document is not None:
        return snapshot_of_document(engine, document, execution_id=execution_id)
    try:
        return await engine.get_execution(execution_id)
    except EngineRejectedError as exc:
        if not _absent(exc) or not isinstance(engine, ReadsDeliveries):
            raise
        async with tenant_session(tenant_id) as session:
            key = (
                await session.execute(
                    text(
                        "SELECT engine_payload_ref FROM calls WHERE id = :id AND tenant_id = :tid"
                    ),
                    {"id": call_id, "tid": tenant_id},
                )
            ).scalar()
        archived = await read_engine_payload(str(key)) if key else None
        if archived is not None:
            return snapshot_of_document(engine, archived, execution_id=execution_id)
        fallback = _listed_snapshot(engine.name, execution_id, listed)
        if fallback is None:
            raise
        _settled_without_delivery(engine.name, execution_id)
        return fallback


__all__ = [
    "ReadsDeliveries",
    "delivered_document",
    "execution_truth",
    "post_call_truth",
    "seal_listing",
    "snapshot_of_document",
]
