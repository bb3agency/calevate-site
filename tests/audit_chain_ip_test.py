"""`audit_log.ip` is inside the hash, and the entries written before it are still genuine
(D-312).

SEC-COMP §5 asks every audit row for "actor, tenant, at, ip", and
`scripts/check_audit_ip.py` exists because that fourth field is the one that answers
WHERE an act came from — the question an impersonation dispute (D-22) or a breach
timeline turns on. It was the only one of the four the chain did not sign, so anybody who
could write this table could rewrite an operator's source address and every hash still
verified. That is tamper-evidence with a hole at the field somebody would want to change.

Asserted here without editing `audit_log`, deliberately: the table is append-only with an
`ENABLE ALWAYS` trigger (hard rule 4) and this suite shares a long-lived database with
others, so the tampering is performed against the hash function — which is what
`verify_chain` actually consults — rather than against rows nobody could clean up.
"""

from __future__ import annotations

import uuid

from apps.api.compliance import audit as audit_module
from apps.api.compliance.audit import verify_chain, write_audit
from apps.api.db.session import untenanted_session
from sqlalchemy import text

KEY = b"chain-key-for-the-ip-coverage-test-0123456789"


def _payload(ip: str | None) -> dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "actor_type": "admin",
        "actor_id": str(uuid.uuid4()),
        "tenant_id": None,
        "action": "admin.impersonation_started",
        "object_type": "organization",
        "object_id": str(uuid.uuid4()),
        "ip": ip,
    }


def test_changing_the_ip_changes_the_hash() -> None:
    """The finding, stated as arithmetic: before D-312 these two were equal."""
    entry = _payload("203.0.113.7")
    moved = {**entry, "ip": "198.51.100.9"}
    assert audit_module._entry_hash("prev", entry, KEY) != audit_module._entry_hash(
        "prev", moved, KEY
    )


def test_a_rewritten_ip_no_longer_reproduces_the_recorded_hash() -> None:
    """What `verify_chain` does per row: recompute, compare, report `content`."""
    ring = (audit_module._ChainKey(generation=0, material=KEY),)
    entry = _payload("203.0.113.7")
    recorded = audit_module._entry_hash("prev", entry, KEY)

    assert audit_module._matching_generation(ring, "prev", entry, recorded, floor=0) == 0, (
        "the untouched row must still verify"
    )
    tampered = {**entry, "ip": "198.51.100.9"}
    assert audit_module._matching_generation(ring, "prev", tampered, recorded, floor=0) is None, (
        "an edited source address must break the row"
    )


def test_entries_written_before_the_ip_joined_the_hash_still_verify() -> None:
    """An append-only ledger cannot be re-signed (hard rule 4), so the old payload shape
    stays admissible — and a change that turned the existing log red would have been
    indistinguishable from tampering on the day it deployed."""
    ring = (audit_module._ChainKey(generation=0, material=KEY),)
    entry = _payload("203.0.113.7")
    legacy_hash = audit_module._entry_hash("prev", audit_module._without_ip(entry), KEY)
    assert audit_module._matching_generation(ring, "prev", entry, legacy_hash, floor=0) == 0


async def test_a_live_write_verifies_end_to_end_with_an_ip() -> None:
    """The delta, against the real database: writing an entry that carries an ip adds no
    break to whatever this log already carried."""
    async with untenanted_session() as session:
        before = (await verify_chain(session)).breaks_found
    async with untenanted_session() as session:
        await write_audit(
            session,
            action=f"test.audit_ip.{uuid.uuid4().hex[:8]}",
            ip="203.0.113.7",
            object_type="probe",
            object_id=str(uuid.uuid4()),
        )
    async with untenanted_session() as session:
        after = await verify_chain(session)
        stored = (
            await session.execute(
                text("SELECT ip FROM audit_log ORDER BY at DESC, id DESC LIMIT 1")
            )
        ).scalar()
    assert after.breaks_found == before, "an ip-carrying entry must not read as tampered"
    assert str(stored) == "203.0.113.7"


async def test_the_writer_signs_over_the_ip_it_stored() -> None:
    """The half the shape-fallback would otherwise hide.

    `_matching_generation` still accepts the pre-D-312 payload, so a writer that dropped
    `ip` from the hash again would verify clean forever. This asserts the WRITER: the
    recorded hash of a row `write_audit` just produced reproduces under the ip-carrying
    shape and NOT under the legacy one, which is only true if the field is signed.
    """
    action = f"test.audit_ip_writer.{uuid.uuid4().hex[:8]}"
    ip = "203.0.113.42"
    async with untenanted_session() as session:
        await write_audit(session, action=action, ip=ip, object_type="probe", object_id="w")
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT id, actor_type, actor_id, tenant_id, action, object_type, "
                    "object_id, ip, prev_hash, entry_hash FROM audit_log WHERE action = :a"
                ),
                {"a": action},
            )
        ).one()
    entry = {
        "id": str(row[0]),
        "actor_type": row[1],
        "actor_id": str(row[2]) if row[2] else None,
        "tenant_id": str(row[3]) if row[3] else None,
        "action": row[4],
        "object_type": row[5],
        "object_id": row[6],
        "ip": str(row[7]),
    }
    key = audit_module._active_key()
    prev, recorded = str(row[8]), str(row[9])
    assert audit_module._entry_hash(prev, entry, key) == recorded
    assert audit_module._entry_hash(prev, audit_module._without_ip(entry), key) != recorded, (
        "the stored hash reproduces without the ip — the writer is not signing it"
    )
