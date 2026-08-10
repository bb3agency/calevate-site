"""Object storage for recordings and raw vendor payloads.

Two rules from the blueprint drive this module:

1. **The recording copy runs FIRST in the pipeline, always** (TRD §8, FLOWS §3).
   Bolna's recording URLs are direct S3 links with no documented expiry and vendor-side
   retention is undocumented (pilot item) — so their copy is not our system of record,
   ours is. Everything downstream can be re-run; a recording we failed to copy may
   simply be gone, and TRAI's 90-day floor is our obligation, not theirs.
2. **Raw vendor payloads go to object storage as refs, never into typed columns**
   (hard rule 2). They exist for debugging and are never read by app code.

Presigned URLs only, 5-minute TTL, never public (TRD §2).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

PRESIGN_TTL_S = 300
DOWNLOAD_TIMEOUT_S = 60.0


class StorageUnavailableError(RuntimeError):
    """Raised so the ARQ retry ladder can do its job — a failed recording copy must
    retry, never be swallowed."""


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


def payload_key(engine: str, execution_id: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y/%m/%d")
    return f"engine-payloads/{engine}/{stamp}/{execution_id}.json"


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


def archive_payload(*, engine: str, execution_id: str, payload: dict[str, Any]) -> str | None:
    """Best-effort archive of the raw vendor payload. Returns the key, or None.

    Best-effort on purpose: this is a debugging aid. Failing a call's pipeline because
    a debug artifact could not be written would be the tail wagging the dog.
    """
    settings = get_settings()
    key = payload_key(engine, execution_id)
    try:
        _client().put_object(
            Bucket=settings.object_store_bucket,
            Key=key,
            Body=json.dumps(payload, default=str).encode(),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
    except (BotoCoreError, ClientError):
        log.warning("payload_archive_failed", extra={"engine": engine})
        return None
    return key


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
    "PRESIGN_TTL_S",
    "StorageUnavailableError",
    "archive_payload",
    "copy_recording",
    "payload_key",
    "presigned_url",
    "recording_key",
]
