"""Object storage for recordings and raw vendor payloads.

Two rules from the blueprint drive this module:

1. **The recording copy runs FIRST in the pipeline, always** (TRD §8, FLOWS §3).
   Bolna's recording URLs are direct S3 links with no documented expiry and vendor-side
   retention is undocumented (pilot item) — so their copy is not our system of record,
   ours is. Everything downstream can be re-run; a recording we failed to copy may
   simply be gone, and TRAI's 90-day floor is our obligation, not theirs.
2. **Raw vendor payloads go to object storage as refs, never into typed columns**
   (hard rule 2). They exist for debugging and are never read by app code — but they
   are PERSONAL DATA all the same (the raw payload carries the caller's number and the
   transcript), so their key names the tenant and the call and a DPDP erasure reaches
   them by prefix, exactly as it reaches a delivered body (D-126, see `payload_key`).
3. **Delivered webhook bodies are PERSONAL DATA with a clock and an erasure duty**
   (D-23, SEC-COMP §4). Unlike the two above they are read back — by support, by the
   retention sweep and by the DPDP erasure worker — so their key SHAPE is part of the
   contract: see `delivery_body_key`.

Presigned URLs only, 5-minute TTL, never public (TRD §2).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import boto3
import httpx
from arq import Retry
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

PRESIGN_TTL_S = 300
DOWNLOAD_TIMEOUT_S = 60.0
# A recording copy is worth waiting for: the vendor's S3 link has no documented expiry
# but no promise either, so a retry should be soon enough to beat a link going away and
# far enough out to let a storage blip finish.
RECORDING_RETRY_DEFER_S = 30.0


class StorageUnavailableError(Retry):
    """Raised so the ARQ retry ladder can do its job — a failed recording copy must
    retry, never be swallowed.

    It subclasses `arq.Retry` because that sentence was not true before: arq 0.28 only
    retries a job for `Retry`, `RetryJob` or `CancelledError`, and a plain
    `RuntimeError` — which is what this used to be — finishes the job after ONE attempt.
    The post-call pipeline re-raises this exception with the comment "Re-raise so ARQ
    retries", and it now does.

    Of everything in the pipeline this is the failure least tolerable to drop: the
    recording copy runs FIRST precisely because Bolna's recording URLs are direct S3
    links with no documented expiry, so a copy we quietly gave up on is a call recording
    that is simply gone — against a 90-day TRAI floor that is our obligation, not the
    vendor's.

    `Retry` is still a `RuntimeError`, so every existing `except StorageUnavailableError`
    and `except RuntimeError` keeps working.
    """

    def __init__(self, message: str, *, defer_s: float = RECORDING_RETRY_DEFER_S) -> None:
        super().__init__(defer=defer_s)
        self.message = message

    def __str__(self) -> str:
        # arq's Retry stringifies as "<Retry defer 30.00s>"; the alert in the pipeline
        # logs str(exc) and needs to say what actually broke.
        return self.message


def _client() -> Any:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.object_store_endpoint,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def recording_key(tenant_id: UUID, call_id: UUID) -> str:
    """Tenant-prefixed so a bucket policy or a lifecycle rule can be scoped per tenant,
    and so an accidental cross-tenant read is visible in the key itself."""
    stamp = datetime.now(UTC).strftime("%Y/%m")
    return f"recordings/{tenant_id}/{stamp}/{call_id}.wav"


ENGINE_PAYLOAD_PREFIX = "engine-payloads"


def payload_key(*, tenant_id: UUID, call_id: UUID, engine: str, execution_id: str) -> str:
    """`engine-payloads/{tenant}/{call}/{engine}-{execution}.json`.

    THE TENANT AND THE CALL ARE LOAD-BEARING, for the reason `delivery_body_key` spells
    out about its subject segment: a DPDP erasure arrives naming a PERSON, resolves them
    to calls, and can only reach an object it can enumerate. This key used to be
    `engine-payloads/{engine}/{YYYY}/{MM}/{DD}/{execution_id}.json`, which named neither
    — so the archive was a personal-data store (the raw payload carries the number and
    the transcript) that no erasure and no retention category could ever reach. Nothing
    was at risk only because nothing called this yet; the key is fixed BEFORE the first
    caller rather than after, because afterwards the unreachable objects already exist.

    The date segment is gone with no loss: the lifecycle rule expires on object age, not
    on a key, and `LastModified` answers "when was this written?" more honestly than a
    path an uploader chose.

    `execution_id` is vendor-controlled and stays LAST on purpose. Object keys are opaque
    byte strings — no store resolves `..` or collapses `/` — so the worst a hostile id
    can do is create a deeper path INSIDE this call's prefix, which the erasure's prefix
    listing still reaches. It cannot escape the tenant or the call.
    """
    return f"{ENGINE_PAYLOAD_PREFIX}/{tenant_id}/{call_id}/{engine}-{execution_id}.json"


def payload_call_prefix(*, tenant_id: UUID, call_id: UUID) -> str:
    """Every archived payload for one call. Ends in `/` so the prefix stops at the
    path segment.

    Weaker than `delivery_body_subject_prefix`'s reason and deliberately said so: two
    call ids are uuids of the same length, so neither can be a strict prefix of the
    other and the slash separates no two calls that exist today. What it bounds is the
    SEGMENT — a future key layout that appends to the call component (`{call}-raw/`, a
    per-attempt suffix) is outside this prefix rather than silently inside it, so an
    erasure's reach cannot widen because a key changed shape."""
    return f"{ENGINE_PAYLOAD_PREFIX}/{tenant_id}/{call_id}/"


async def copy_recording(*, source_url: str, tenant_id: UUID, call_id: UUID) -> str:
    """Stream the engine's recording into our bucket. Returns the object key."""
    settings = get_settings()
    key = recording_key(tenant_id, call_id)
    try:
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=True) as client:
            response = await client.get(source_url)
            response.raise_for_status()
            audio = response.content
    except httpx.HTTPError as exc:
        raise StorageUnavailableError(f"recording fetch failed: {type(exc).__name__}") from exc

    try:
        _client().put_object(
            Bucket=settings.object_store_bucket,
            Key=key,
            Body=audio,
            ContentType="audio/wav",
            # SSE at rest (TRD §2). The bucket also enforces it; belt and braces.
            ServerSideEncryption="AES256",
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailableError(f"recording upload failed: {type(exc).__name__}") from exc
    # Key only — never the URL, and never the phone number in the log line.
    log.info("recording_stored", extra={"call_id": str(call_id), "bytes": len(audio)})
    return key


def archive_payload(
    *, tenant_id: UUID, call_id: UUID, engine: str, execution_id: str, payload: dict[str, Any]
) -> str | None:
    """Best-effort archive of the raw vendor payload. Returns the key, or None.

    Best-effort on purpose: this is a debugging aid. Failing a call's pipeline because
    a debug artifact could not be written would be the tail wagging the dog.

    THE TENANT AND CALL ARE REQUIRED ARGUMENTS, and that is a deliberate constraint on
    whoever wires the first caller. The payload is personal data (D-126); an archive
    written where the call is not yet known would be an object no erasure can reach, and
    a defaulted or optional id is exactly how that happens. `calls.engine_payload_ref` —
    the column this key is stored in — says the same thing in the schema: the writer is
    the post-call pipeline, where the call row exists, not the webhook ack path, which is
    untenanted by design (hard rule 3).

    **THE WRITE ORDER IS PART OF THE CONTRACT, and it is the opposite of
    `store_delivery_body`'s.** Commit `calls.engine_payload_ref = payload_key(...)` FIRST,
    then call this. The reference is what tells `retention._erase_engine_payloads` there
    is anything under this call's prefix worth a listing, so:

      * reference committed, PUT never happened → the erasure lists a prefix and deletes
        nothing. Harmless: deleting an absent key is a no-op, and a debug reference that
        resolves to nothing is the same "gone" answer `read_delivery_body` already
        establishes as a real one rather than an error.
      * object PUT, reference never committed → an object holding a caller's number and
        transcript that the erasure has no reason to look for. That is the D-126 defect
        reintroduced one crash at a time.

    A delivered body can be written object-first because its key names the SUBJECT, so a
    listing finds it with no help from the database. This key names the call, and the
    erasure reaches calls, not archives — so here the reference is the index and it is
    written first.
    """
    settings = get_settings()
    key = payload_key(
        tenant_id=tenant_id, call_id=call_id, engine=engine, execution_id=execution_id
    )
    try:
        _client().put_object(
            Bucket=settings.object_store_bucket,
            Key=key,
            Body=json.dumps(payload, default=str).encode(),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
    except (BotoCoreError, ClientError):
        # Ids and an engine name. Never one byte of the payload — the thing that could
        # not be written is a phone number and a transcript (hard rule 6).
        log.warning("payload_archive_failed", extra={"engine": engine, "call_id": str(call_id)})
        return None
    return key


# --- delivered webhook bodies (D-23) ------------------------------------------
#
# WHAT THIS STORE IS, SAID PLAINLY: a copy of the CRM payload we POSTed to a client's
# own endpoint — the lead's name, their (usually masked) number and every extracted
# field. It exists because `webhook_deliveries` could previously prove only that a POST
# happened, so "you sent us the wrong lead" and "the field is empty in our CRM" were
# both unanswerable. Retaining it is therefore a deliberate act that ADDS a personal-data
# store, and three properties are what make it defensible rather than a liability:
#
#   * it is ERASABLE BY SUBJECT — the key names whose data it is, so the DPDP worker can
#     find every object for one person without a second index to keep in step;
#   * it EXPIRES on the tenant's own `retention_policies` row (`lead` category, the same
#     clock as `call_extractions.data`, which is the same class of thing);
#   * it is BOUNDED — `MAX_RETAINED_BODY_BYTES` per delivery, truncation declared inside
#     the object rather than guessed at by whoever reads it.
#
# NOT stored, ever: the endpoint URL (clients do put tokens in webhook query strings),
# the signing secret, the signature header. The forensic question is what we SENT, and
# none of those are part of it.

DELIVERY_BODY_PREFIX = "webhook-bodies"

# Per delivery. A lead payload is a few hundred bytes; 64 KiB is room for an unusually
# large extraction schema and still small enough that a client with a busy integration
# cannot turn this into a storage bill nobody noticed. Bodies above it are stored
# TRUNCATED and say so — a silent prefix would be a forensic record that lies.
MAX_RETAINED_BODY_BYTES = 64 * 1024

# S3's DeleteObjects caps one request at 1000 keys (AWS S3 API reference, DeleteObjects).
_DELETE_BATCH = 1000


def delivery_body_key(
    *, tenant_id: UUID, subject_type: str, subject_id: str, delivery_id: UUID
) -> str:
    """`webhook-bodies/{tenant}/{subject}/{delivery}.json`.

    THE SUBJECT SEGMENT IS LOAD-BEARING, and it is why this key is not shaped like
    `recording_key`'s date prefix. A DPDP erasure arrives naming a PERSON, not a date,
    and an object nobody can enumerate for that person is a breach waiting for its first
    request. Putting the subject in the key makes the object store itself the index the
    erasure walks (`keys_under`), so an object written by a worker that then
    crashed before recording the reference is still reachable — a DB-side index would
    have missed exactly those.

    The tenant segment is first for the reason `recording_key`'s is: a prefix is what a
    bucket policy can be scoped by, and a cross-tenant read is visible in the key.
    """
    return f"{DELIVERY_BODY_PREFIX}/{tenant_id}/{subject_type}-{subject_id}/{delivery_id}.json"


def delivery_body_subject_prefix(*, tenant_id: UUID, subject_type: str, subject_id: str) -> str:
    """Everything stored for one subject in one tenant. Ends in `/` deliberately: without
    it `lead-<uuid>` would also prefix-match a longer id that starts with the same bytes.
    """
    return f"{DELIVERY_BODY_PREFIX}/{tenant_id}/{subject_type}-{subject_id}/"


def build_delivery_body_document(
    *,
    delivery_id: UUID,
    endpoint_id: UUID,
    event: str,
    subject_type: str,
    subject_id: str,
    body: str,
) -> tuple[bytes, int, bool]:
    """The object we store, as `(bytes, original_bytes, truncated)`.

    Truncation is applied to the ENCODED bytes, because the cap is about storage and
    slicing a str would cap characters instead — 64k Telugu characters is 192 KiB. The
    partial character at the cut is DROPPED (`errors="ignore"`) rather than replaced:
    `errors="replace"` would put a U+FFFD in the record, which is a character we invented,
    is not what we sent, and is three bytes wide — so the "truncated" copy would come back
    slightly LARGER than the cap it was truncated to.

    The stored document stays valid JSON either way — the delivered body rides inside it
    as a STRING, so a truncated payload cannot make the record itself unparseable.
    """
    encoded = body.encode()
    original_bytes = len(encoded)
    truncated = original_bytes > MAX_RETAINED_BODY_BYTES
    kept = encoded[:MAX_RETAINED_BODY_BYTES].decode(errors="ignore") if truncated else body
    document = {
        "delivery_id": str(delivery_id),
        "endpoint_id": str(endpoint_id),
        "event": event,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "stored_at": datetime.now(UTC).isoformat(),
        "content_type": "application/json",
        "original_bytes": original_bytes,
        # Declared, not inferred. A reader comparing `len(body)` against a constant would
        # be reading OUR cap at the time they read, not the cap that applied when the
        # object was written.
        "truncated": truncated,
        "body": kept,
    }
    return json.dumps(document, separators=(",", ":")).encode(), original_bytes, truncated


def store_delivery_body(
    *,
    key: str,
    delivery_id: UUID,
    endpoint_id: UUID,
    event: str,
    subject_type: str,
    subject_id: str,
    body: str,
) -> str | None:
    """Best-effort. Returns the key, or None when the store refused.

    BEST-EFFORT IS THE WHOLE POINT: the delivery job exists to deliver, and a client's
    lead must reach their CRM whether or not we managed to keep a copy of it. So this
    never raises and never retries — the caller records the delivery either way, and the
    missing reference is made visible by the caller's alert rather than by a failed job.
    """
    document, original_bytes, truncated = build_delivery_body_document(
        delivery_id=delivery_id,
        endpoint_id=endpoint_id,
        event=event,
        subject_type=subject_type,
        subject_id=subject_id,
        body=body,
    )
    try:
        _client().put_object(
            Bucket=get_settings().object_store_bucket,
            Key=key,
            Body=document,
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
    except (BotoCoreError, ClientError) as exc:
        # Ids, byte counts and an exception TYPE. Never the key's subject segment as a
        # separate field and never one byte of the body (hard rule 6).
        log.warning(
            "delivery_body_store_failed",
            extra={
                "delivery_id": str(delivery_id),
                "bytes": original_bytes,
                "reason": type(exc).__name__,
            },
        )
        return None
    log.info(
        "delivery_body_stored",
        extra={"delivery_id": str(delivery_id), "bytes": original_bytes, "truncated": truncated},
    )
    return key


def read_delivery_body(key: str) -> dict[str, Any] | None:
    """The stored document, or None when the object is GONE.

    Gone and unreachable are DIFFERENT answers to "what did we send?" and this function
    refuses to merge them: an erased or expired body is a fact about our retention, a
    storage outage is a fact about today. `None` is the first; `StorageUnavailableError`
    is the second, and every caller has to say which it is telling the reader.
    """
    try:
        response = _client().get_object(Bucket=get_settings().object_store_bucket, Key=key)
        raw = response["Body"].read()
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        # `NoSuchKey` is S3's; MinIO answers the same, and a 404 status covers a store
        # that names it differently.
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        raise StorageUnavailableError(
            f"delivery body read failed: {code or 'ClientError'}"
        ) from exc
    except BotoCoreError as exc:
        raise StorageUnavailableError(f"delivery body read failed: {type(exc).__name__}") from exc
    try:
        document = json.loads(raw)
    except ValueError:
        # Something is in our bucket under our key that we did not write. Not a body we
        # can show anyone, and not an outage either.
        log.warning("delivery_body_unreadable")
        return None
    return document if isinstance(document, dict) else None


def keys_under(prefix: str) -> list[str]:
    """Every object under one prefix. RAISES on failure, deliberately.

    The DPDP erasure calls this, and an erasure that treats "the store did not answer"
    as "there was nothing there" writes a certificate claiming a deletion it did not
    perform. Loud and retried beats quiet and false.

    Not delivery-body-specific, and its name no longer says so — the archived engine
    payloads (D-126) are enumerated by their own `{tenant}/{call}` prefix through this
    same function, exactly as `delete_objects` is already shared by every store in this
    module. Two listings for one question is how the second one grows a different
    failure contract.
    """
    keys: list[str] = []
    try:
        paginator = _client().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=get_settings().object_store_bucket, Prefix=prefix):
            keys += [str(item["Key"]) for item in page.get("Contents", [])]
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailableError(f"object list failed: {type(exc).__name__}") from exc
    return keys


def delete_objects(keys: Sequence[str]) -> int:
    """Delete objects by key; returns how many were asked for. RAISES on failure.

    Raising rather than reporting a partial success is what lets every caller be correct
    with one implementation: the erasure must retry rather than certify, and the retention
    sweep must leave the reference (`payload_ref`, `recording_url`) pointing at an object
    it failed to delete — a cleared reference to a surviving object is an orphan nothing
    can ever reach again.

    Not delivery-body-specific and its messages no longer say so: recordings and the
    scheduled destructions of `recording_erasure_holds` come through here too.
    """
    if not keys:
        return 0
    bucket = get_settings().object_store_bucket
    client = _client()
    try:
        for chunk in _chunks(keys, _DELETE_BATCH):
            response = client.delete_objects(
                Bucket=bucket, Delete={"Objects": [{"Key": key} for key in chunk], "Quiet": True}
            )
            errors = response.get("Errors") or []
            if errors:
                # Keys are not logged: a delivery-body key contains the subject's row id,
                # and a recording key names one of the client's calls (hard rule 6).
                raise StorageUnavailableError(f"object delete refused {len(errors)} key(s)")
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailableError(f"object delete failed: {type(exc).__name__}") from exc
    return len(keys)


def _chunks(keys: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(keys), size):
        yield keys[start : start + size]


def presigned_url(key: str, *, ttl_s: int = PRESIGN_TTL_S) -> str | None:
    settings = get_settings()
    try:
        url = _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.object_store_bucket, "Key": key},
            ExpiresIn=ttl_s,
        )
    except (BotoCoreError, ClientError):
        log.warning("presign_failed")
        return None
    return str(url)


__all__ = [
    "DELIVERY_BODY_PREFIX",
    "ENGINE_PAYLOAD_PREFIX",
    "MAX_RETAINED_BODY_BYTES",
    "PRESIGN_TTL_S",
    "RECORDING_RETRY_DEFER_S",
    "StorageUnavailableError",
    "archive_payload",
    "build_delivery_body_document",
    "copy_recording",
    "delete_objects",
    "delivery_body_key",
    "delivery_body_subject_prefix",
    "keys_under",
    "payload_call_prefix",
    "payload_key",
    "presigned_url",
    "read_delivery_body",
    "recording_key",
    "store_delivery_body",
]
