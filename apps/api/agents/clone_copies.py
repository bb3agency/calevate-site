"""Our cloned voices, cloned again into a client's own ThinnestAI workspace (D-693).

A ThinnestAI clone belongs to the workspace that made it (`POST /voice-clones` answers a
`voiceId` for that workspace; `thinnest-findings/mirror/snapshots/2026-10-08/pages/
api-reference/voice-clones/create-voice-clone.md:7`), and an operator clones in our developer
workspace. A client agent lives in the client's own workspace, so it can speak one of our
clones only through a copy made there, from the same recording, under the operator's same
two attestations.

So the operator's recording is kept, sealed under the platform key (it is a person's voice),
when the clone is first made (`keep_clone_sample`), and `workspace_voice_id` makes the copy
the first time a client agent on that voice is published, records the mapping
(`engine_voice_clone_copies`), and answers the copy's `voiceId` from then on.

The clone limit per workspace is not documented beyond the 409 the vendor answers at it
("You already have 10 voices, which is the limit", create-voice-clone.md:442-450); that 409
is refused here by name (`voice_clone_workspace_limit`), never retried.

Groundwork while Clear sells the Premium band, which has no clones (D-688): only a voice
whose catalogue row is one of our clones ever reaches this path.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.envelope import Envelope, seal_bytes, unseal_bytes
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.engine.catalogue import HostsVoices, ListsVoiceClones, VoiceCloneSample
from apps.api.engine.thinnest_workspace import in_workspace

log = get_logger(__name__)

#: A copy is found again by this tag in its name, so a publish retried after a lost
#: response finds the copy it made rather than making a second.
_TAG_PREFIX: Final = " #cvc-"
#: A clone's name is at most 40 characters (create-voice-clone.md:384-460, the 400 our
#: `_clone_refusal` words); the label is clipped so the tag always fits after it.
NAME_MAX: Final = 40
_LABEL_MAX: Final = NAME_MAX - len(_TAG_PREFIX) - 12


def _context(voice_id: str) -> str:
    return f"voice_clone_sample:{voice_id}"


def copy_name(label: str, voice_id: str) -> str:
    tag = hashlib.sha256(voice_id.encode()).hexdigest()[:12]
    return f"{label[:_LABEL_MAX]}{_TAG_PREFIX}{tag}"


def _missing_sample() -> ProblemError:
    return ProblemError.business_rule(
        "voice_clone_sample_missing",
        "This cloned voice cannot be used for this account yet: its original recording was "
        "not kept, so it cannot be cloned again in this account's voice workspace.",
        remediation="Choose another voice, or ask us to clone this voice again.",
    )


def _workspace_limit() -> ProblemError:
    return ProblemError.business_rule(
        "voice_clone_workspace_limit",
        "This cloned voice cannot be added to this account: its voice workspace already holds "
        "as many cloned voices as it may.",
        remediation="Choose another voice. If you need this one, contact us.",
    )


async def keep_clone_sample(
    session: AsyncSession,
    *,
    voice_id: str,
    filename: str,
    content_type: str,
    language: str | None,
    data: bytes,
) -> str:
    """Seal the recording a clone was made from, store it, and point the catalogue row at
    it. The object is one JSON document holding the envelope, so nothing else stores it."""
    from apps.workers.storage import store_voice_clone_sample, voice_clone_sample_key

    envelope = seal_bytes(data, context=_context(voice_id))
    document = json.dumps(
        {
            "v": 1,
            "filename": filename,
            "content_type": content_type,
            "language": language,
            "kek_id": envelope.kek_id,
            "nonce": base64.b64encode(envelope.nonce).decode(),
            "dek_wrapped": base64.b64encode(envelope.dek_wrapped).decode(),
            "dek_nonce": base64.b64encode(envelope.dek_nonce).decode(),
            "ciphertext": base64.b64encode(envelope.ciphertext).decode(),
        }
    ).encode()
    key = await store_voice_clone_sample(key=voice_clone_sample_key(voice_id), data=document)
    await session.execute(
        text("UPDATE platform_voice_catalog SET sample_object_key = :key WHERE voice_id = :vid"),
        {"key": key, "vid": voice_id},
    )
    return key


async def _load_sample(voice_id: str, key: str, *, label: str) -> VoiceCloneSample:
    from apps.workers.storage import read_voice_clone_sample

    raw = await read_voice_clone_sample(key)
    if raw is None:
        raise _missing_sample()
    try:
        doc = json.loads(raw)
        envelope = Envelope(
            ciphertext=base64.b64decode(doc["ciphertext"]),
            nonce=base64.b64decode(doc["nonce"]),
            dek_wrapped=base64.b64decode(doc["dek_wrapped"]),
            dek_nonce=base64.b64decode(doc["dek_nonce"]),
            kek_id=int(doc["kek_id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _missing_sample() from exc
    return VoiceCloneSample(
        filename=str(doc.get("filename") or "sample"),
        content_type=str(doc.get("content_type") or "audio/mpeg"),
        data=unseal_bytes(envelope, context=_context(voice_id)),
        name=copy_name(label, voice_id),
        language=doc.get("language") if isinstance(doc.get("language"), str) else None,
        # The operator gave both attestations when the voice was first cloned, and they are
        # recorded in the audit log with who and when (`ops.voice_cloned`); this copy is the
        # same recording of the same speaker under the same promises.
        consent_own_voice=True,
        consent_no_impersonation=True,
    )


_CLONE_ROW: Final = (
    "SELECT label, engine_clone_id, sample_object_key FROM platform_voice_catalog "
    "WHERE voice_id = :vid"
)
_COPY_ROW: Final = (
    "SELECT vendor_voice_id FROM engine_voice_clone_copies "
    "WHERE tenant_id = :tid AND voice_id = :vid AND workspace_id = :ws"
)


async def workspace_voice_id(
    session: AsyncSession,
    engine: object,
    *,
    tenant_id: UUID,
    voice_id: str,
    workspace: str,
) -> str | None:
    """The vendor `voiceId` an agent of this tenant in `workspace` speaks for our catalogue
    voice `voice_id`, or None when the voice is not one of our clones (it is then the same id
    in every workspace). Makes the copy the first time; the caller's session records it."""
    row = (await session.execute(text(_CLONE_ROW), {"vid": voice_id})).first()
    if row is None or not row[1]:
        return None
    held = (
        await session.execute(text(_COPY_ROW), {"tid": tenant_id, "vid": voice_id, "ws": workspace})
    ).scalar()
    if isinstance(held, str) and held:
        return held
    if not isinstance(engine, HostsVoices) or not isinstance(engine, ListsVoiceClones):
        return None
    label = str(row[0])
    name = copy_name(label, voice_id)
    with in_workspace(workspace):
        existing = next(
            (clone for clone in await engine.list_voice_clones() if clone.label == name), None
        )
        if existing is None:
            if not row[2]:
                raise _missing_sample()
            sample = await _load_sample(voice_id, str(row[2]), label=label)
            try:
                existing = await engine.create_voice_clone(sample)
            except ProblemError as exc:
                if exc.code == "voice_clone_limit_reached":
                    raise _workspace_limit() from exc
                raise
    await session.execute(
        text(
            "INSERT INTO engine_voice_clone_copies (id, tenant_id, voice_id, workspace_id, "
            "vendor_voice_id, vendor_clone_id, created_at, updated_at) VALUES (:id, :tid, "
            ":vid, :ws, :voice, :clone, now(), now()) ON CONFLICT (tenant_id, voice_id, "
            "workspace_id) DO UPDATE SET vendor_voice_id = EXCLUDED.vendor_voice_id, "
            "vendor_clone_id = EXCLUDED.vendor_clone_id, updated_at = now()"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "vid": voice_id,
            "ws": workspace,
            "voice": existing.voice_id,
            "clone": existing.clone_id,
        },
    )
    log.info("engine_voice_clone_copied", extra={"tenant_id": str(tenant_id)})
    return existing.voice_id


async def forget_clone(engine: object, *, voice_id: str, sample_key: str | None) -> int:
    """Our clone was deleted: delete every copy made of it in a client's workspace, and the
    kept recording. The operator's consent covered the copies; deleting the voice withdraws
    them all. Best effort per copy: a copy that would not go is logged and left recorded, so
    a second delete retries it. Returns the copies deleted."""
    from apps.api.db.session import tenant_session
    from apps.api.tenancy.engine_workspace import active_workspaces
    from apps.workers.storage import delete_objects

    deleted = 0
    if isinstance(engine, HostsVoices):
        for row in await active_workspaces():
            async with tenant_session(row.tenant_id) as session:
                copies = (
                    await session.execute(
                        text(
                            "SELECT id, workspace_id, vendor_clone_id FROM "
                            "engine_voice_clone_copies WHERE voice_id = :vid ORDER BY id"
                        ),
                        {"vid": voice_id},
                    )
                ).all()
            for copy_id, workspace, vendor_clone_id in copies:
                try:
                    with in_workspace(str(workspace)):
                        await engine.delete_voice_clone(str(vendor_clone_id))
                except ProblemError as exc:
                    log.warning("engine_voice_clone_copy_not_deleted", extra={"code": exc.code})
                    continue
                async with tenant_session(row.tenant_id) as session:
                    await session.execute(
                        text("DELETE FROM engine_voice_clone_copies WHERE id = :id"),
                        {"id": copy_id},
                    )
                deleted += 1
    if sample_key:
        await delete_objects([sample_key])
    return deleted


__all__ = ["copy_name", "forget_clone", "keep_clone_sample", "workspace_voice_id"]
