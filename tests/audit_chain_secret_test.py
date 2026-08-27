"""The audit chain's signing key: required, floored, and survivable across a change.

`audit_chain_secret` used to fall back to the constant `local-dev:{app_env}` in EVERY
environment. A production deploy that forgot the variable therefore signed its
tamper-evident ledger with a string printed in `apps/api/compliance/audit.py`, which
makes the chain unverifiable as evidence — anyone who could read the repository could
have written any of it — and made the idempotency fingerprints derived from the same
material a rename of two ids rather than a pseudonym for them.

Requiring the secret is the easy half. The hard half is that `audit_log` is append-only
(hard rule 4) and every existing entry was signed with whatever key was in force when it
was written, so a verifier that knows only the CURRENT key reports the entire history as
edited — not one break at the boundary, but `content` on every prior row, because the
hash is recomputed per entry and not only across links. A tamper-evidence tool that
manufactures tamper evidence on our own deploy is worse than one that is merely absent:
an operator who learns that breaks come from deploys stops reading breaks.

So the assertions below come in two groups:

  1. the REFUSALS — absent outside `local`, and configured-but-too-short refused with
     the SAME code, matching what `tests/impersonation_grant_test.py` established for
     the view-as key;
  2. the BOUNDARY — what `verify_chain` reports when the log spans a key change. That is
     the number an operator acts on, so it is pinned in both directions: a change that
     keeps the outgoing key in the ring adds no break, and one that loses it does.

**EVERY ASSERTION IS A DELTA, AND NOTHING HERE IS LEFT BEHIND.** This suite runs against
a long-lived database whose `audit_log` already carries permanent, unrepairable breaks
from an earlier era (`runbooks/stale-dev-database.md`; a developer database legitimately
answers `ok: false`), so a test that demanded a globally clean chain would be green only
on a freshly migrated one. Entries written under a non-default key would ALSO be a scar
this suite made — a row nobody can re-sign, in a table nobody can edit — so every one of
them is written inside a transaction that aborts, exactly as
`tests/audit_chain_concurrency_test.py::test_a_break_does_not_stop_the_walk` does.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import pytest
from apps.api.compliance import audit as audit_module
from apps.api.compliance.audit import lock_chain, verify_chain, write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.settings import MIN_HMAC_KEY_BYTES
from apps.api.db.session import untenanted_session
from apps.api.reliability import service as reliability_module
from apps.api.reliability.service import scope_key
from sqlalchemy import text

# Long enough to clear the floor; the value is irrelevant, only its length and its
# difference from the other keys here.
ACTIVE_SECRET = "active-audit-chain-secret-material-0123456789"
RETIRED_SECRET = "retired-audit-chain-secret-material-9876543210"


class _AbortError(Exception):
    """Raised to unwind a transaction the way a real failure would."""


@dataclass(frozen=True, slots=True)
class _Stub:
    """Just the fields the key resolution reads.

    A stub rather than `monkeypatch.setattr(settings, ...)` on the real object: the
    module under test caches nothing, so patching its `get_settings` is enough, and the
    process-wide Settings singleton is never mutated by a suite that runs alongside
    others sharing it.
    """

    app_env: str = "local"
    audit_chain_secret: str | None = None
    audit_chain_secret_retired: str | None = None
    idempotency_scope_secret: str | None = None


def _use(monkeypatch: pytest.MonkeyPatch, stub: _Stub) -> None:
    monkeypatch.setattr(audit_module, "get_settings", lambda: stub)


async def _verdict() -> tuple[int, int]:
    """(breaks, entries) under whatever settings are currently in force."""
    async with untenanted_session() as session:
        result = await verify_chain(session)
    return result.breaks_found, result.entries_checked


# --- who each half of the refusal is for --------------------------------------

#: Anything a person in the client console cannot act on. Both codes this resolver
#: produces are raised on client paths — `audit_chain_not_configured` on a campaign launch
#: and on a raw-transcript read, `idempotency_not_configured` on ANY client POST carrying
#: an `Idempotency-Key` — so the BODY is read by somebody with no environment to edit and
#: no secrets manager to reach. `core/envelope.py`'s `_OPERATOR_ONLY` list, for this
#: resolver's vocabulary.
_OPERATOR_ONLY = (
    "AUDIT_CHAIN_SECRET",
    "IDEMPOTENCY_SCOPE_SECRET",
    "IMPERSONATION_GRANT_SECRET",
    "DEV-SETUP",
    "secrets manager",
    "RFC 2104",
    "NIST",
    "deployment",
    "HMAC",
)


def _hmac_log(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    """The one refusal record — where the operator's fix now lives."""
    records = [
        r for r in caplog.records if r.getMessage() in ("hmac_key_missing", "hmac_key_too_short")
    ]
    assert len(records) == 1, [r.getMessage() for r in caplog.records]
    return records[0]


def _operator_fix(caplog: pytest.LogCaptureFixture) -> str:
    return str(getattr(_hmac_log(caplog), "fix", ""))


def _assert_reader_can_act_on_it(problem: ProblemError) -> None:
    """The body says what happened and who is fixing it, in nobody's environment.

    This is the assertion that stops the regression: the operator sentence was correct and
    useful, it was simply pointed at the wrong reader, and nothing but a test keeps it
    from drifting back once somebody wants the body to be more specific.
    """
    body = f"{problem.title} {problem.detail} {problem.remediation}"
    for token in _OPERATOR_ONLY:
        assert token not in body, f"{token!r} is operator vocabulary in a client-read body"
    assert "nothing for you to fix" in (problem.remediation or "")


# --- 1. the refusals ----------------------------------------------------------


def test_an_absent_secret_is_refused_outside_local(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """No key, no chain — and the OPERATOR's half of the refusal names the variable.

    ⚠ **THE VARIABLE MOVED FROM THE BODY TO THE LOG, AND THIS TEST MOVED WITH IT.** It
    used to assert `AUDIT_CHAIN_SECRET` in `remediation`, which is how an environment
    variable came to be printed to a shop owner: this refusal fires on a CLIENT campaign
    launch and on a client reading a raw transcript. `core/envelope.py::_unusable_kek`
    made the same correction for `PLATFORM_KEK`; `_unusable_hmac_key` is that shape.

    This is the whole finding: the fallback applied in `prod` too, so the failure mode
    was silence rather than an outage. Failing closed is severe on purpose — every
    audited action stops, and hard rule 5 puts raw-transcript reads on that list — but an
    unverifiable audit trail is not a degraded audit trail, it is an absent one, and
    `runtime_config_missing_keys` makes it a red readiness probe before the deployment
    ever takes traffic.
    """
    for env in ("staging", "prod"):
        caplog.clear()
        _use(monkeypatch, _Stub(app_env=env))
        with caplog.at_level(logging.ERROR), pytest.raises(ProblemError) as raised:
            audit_module._active_key()
        # The CODE still distinguishes this from every other dependency refusal — the
        # audience split is about the words a person reads, never about collapsing states.
        assert raised.value.code == "audit_chain_not_configured"
        assert "AUDIT_CHAIN_SECRET" in _operator_fix(caplog)
        _assert_reader_can_act_on_it(raised.value)


def test_a_configured_secret_below_the_hmac_key_size_is_refused_the_same_way(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A weak key is not a warning to read later — it is the same condition as no key.

    RFC 2104 §3 says a key shorter than the hash output (32 bytes for SHA-256) "is
    strongly discouraged as it would decrease the security strength of the function",
    and NIST SP 800-107 Rev. 1 §5.3.4 sets an absolute floor of 128 bits. Failing closed
    on an ABSENT secret while accepting a present-but-short one would leave the refusal
    guarding the easier half of one mistake: an operator who pastes a short string into
    the secrets manager gets a signing key an attacker can search, and the only signal is
    a log line. Refused with the SAME code as absence — to this module "no usable key" is
    one condition, and two codes would invite a caller to handle one and not the other.
    """
    short = "x" * (MIN_HMAC_KEY_BYTES - 1)
    _use(monkeypatch, _Stub(app_env="prod", audit_chain_secret=short))
    with caplog.at_level(logging.ERROR), pytest.raises(ProblemError) as raised:
        audit_module._active_key()
    assert raised.value.code == "audit_chain_not_configured"
    assert str(MIN_HMAC_KEY_BYTES) in _operator_fix(caplog), (
        "the refusal must name the requirement to the person who can meet it"
    )
    _assert_reader_can_act_on_it(raised.value)

    # The positive half, so this pins a THRESHOLD rather than a blanket refusal.
    _use(monkeypatch, _Stub(app_env="prod", audit_chain_secret="y" * MIN_HMAC_KEY_BYTES))
    assert audit_module._active_key() == b"y" * MIN_HMAC_KEY_BYTES


async def test_the_whole_walk_refuses_rather_than_reporting_an_unverifiable_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`verify_chain` resolves the key BEFORE it reads a row.

    The alternative — walk, fail to reproduce anything, and return a verdict listing
    every entry as broken — would answer a question about our configuration with an
    accusation about the ledger. `ok: false, breaks_found: 40000` and "you forgot a
    variable" must not look the same.
    """
    _use(monkeypatch, _Stub(app_env="prod"))
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await verify_chain(session)
    assert raised.value.code == "audit_chain_not_configured"


async def test_local_still_works_without_any_secret() -> None:
    """A dev box with no secrets manager writes and verifies a chain end to end.

    The convenience the fallback existed for is preserved; what changed is that it is
    now scoped to the one environment where it is a convenience rather than a key.
    """
    before, _ = await _verdict()
    async with untenanted_session() as session:
        await write_audit(session, action=f"test.local_key.{uuid.uuid4().hex[:8]}")
    after, entries = await _verdict()

    assert after == before, "writing under the local constant added a break"
    assert entries >= 1


# --- 2. the boundary ----------------------------------------------------------


async def test_entries_signed_before_the_secret_was_required_still_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE TEST THIS SLICE EXISTS FOR.

    A deployment that had been running on the fallback now injects a real
    AUDIT_CHAIN_SECRET. Its whole history was signed with `local-dev:{app_env}` and every
    new entry is signed with the real key. What an operator must see at
    `GET /v1/ops/audit/verify` afterwards is the verdict they saw before — same breaks,
    same count — because the deploy changed how entries are signed, not whether the old
    ones are genuine.

    The delta is the claim. The absolute count is whatever this database already carried.
    """
    marker = f"test.key_boundary.{uuid.uuid4().hex[:12]}"
    before, _ = await _verdict()

    with pytest.raises(_AbortError):
        async with untenanted_session() as session:
            # Held for the rest of the transaction, so no other writer interleaves and
            # the shape asserted below is the one built here.
            await lock_chain(session)

            # `app_env` stays `local` so the ring's generation 0 is the key this
            # database's existing entries were actually signed with. Changing it would
            # test a different database than the one that exists.
            _use(monkeypatch, _Stub(audit_chain_secret=ACTIVE_SECRET))
            for i in range(3):
                await write_audit(session, action=f"{marker}.{i}", actor_type="system")

            verdict = await verify_chain(session)

            assert verdict.breaks_found == before, (
                f"configuring the secret added {verdict.breaks_found - before} break(s): "
                f"{verdict.breaks}"
            )
            assert verdict.complete, "the boundary must not truncate the walk"

            # And the era is VISIBLE rather than merely survived: everything except the
            # three entries just written verified under a retired key. That number is
            # what tells an operator exporting this log as evidence where the weakly
            # attested prefix ends.
            assert verdict.entries_under_retired_key == verdict.entries_checked - 3, (
                verdict.entries_under_retired_key,
                verdict.entries_checked,
            )
            assert verdict.entries_under_retired_key > 0

            raise _AbortError

    async with untenanted_session() as session:
        left = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE action LIKE :like"),
                {"like": f"{marker}.%"},
            )
        ).scalar()
    assert left == 0, "entries signed with a test key must not survive into the ledger"


async def test_a_rotation_that_keeps_the_outgoing_key_verifies_and_one_that_loses_it_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rotation is a supported operation, and forgetting half of it is a loud one.

    `AUDIT_CHAIN_SECRET_RETIRED` is the mechanism: entries signed by the outgoing key
    keep verifying under it while new entries are signed by the incoming one. Both
    directions are pinned, because the failure mode of the second is exactly the one this
    slice was written to prevent and a comment in `.env.example` is not an enforcement.
    """
    marker = f"test.key_rotation.{uuid.uuid4().hex[:12]}"
    before, _ = await _verdict()

    with pytest.raises(_AbortError):
        async with untenanted_session() as session:
            await lock_chain(session)

            # Era 1: signed with what will become the retired key.
            _use(monkeypatch, _Stub(audit_chain_secret=RETIRED_SECRET))
            await write_audit(session, action=f"{marker}.before", actor_type="system")

            # Era 2: rotated, with the outgoing key retained for verification.
            rotated = _Stub(
                audit_chain_secret=ACTIVE_SECRET, audit_chain_secret_retired=RETIRED_SECRET
            )
            _use(monkeypatch, rotated)
            await write_audit(session, action=f"{marker}.after", actor_type="system")

            kept = await verify_chain(session)
            assert kept.breaks_found == before, (
                f"a rotation that kept its outgoing key added "
                f"{kept.breaks_found - before} break(s): {kept.breaks}"
            )

            # ...and the same log read by a deployment that dropped the outgoing key.
            # The pre-rotation entry can no longer be reproduced by any admissible key,
            # so it reports as `content` — which is the honest answer (we cannot tell a
            # lost key from an edited row without the key) and the reason the retired
            # slot exists.
            _use(monkeypatch, _Stub(audit_chain_secret=ACTIVE_SECRET))
            lost = await verify_chain(session)
            assert lost.breaks_found == before + 1, (lost.breaks_found, before)
            assert any(b.kind == "content" for b in lost.breaks), lost.breaks

            raise _AbortError


async def test_an_entry_signed_with_the_public_legacy_key_after_the_chain_moved_on_is_a_break(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The downgrade the key ring would otherwise permit.

    Generation 0 is `local-dev:{app_env}` — a constant in the source, not a secret. So a
    forger who can write to `audit_log` but does not hold AUDIT_CHAIN_SECRET could edit a
    recent entry, re-sign it with the key from this repository, and be accepted by a
    verifier that simply tries every key it knows. `_matching_generation` refuses a
    generation the chain has already moved past, which confines forgery to the prefix
    that was already forgeable and cannot be un-forged.

    Simulated the way it would really arrive: an entry written while the process had no
    configured secret, landing after entries that had one.
    """
    marker = f"test.key_downgrade.{uuid.uuid4().hex[:12]}"
    before, _ = await _verdict()

    with pytest.raises(_AbortError):
        async with untenanted_session() as session:
            await lock_chain(session)

            configured = _Stub(audit_chain_secret=ACTIVE_SECRET)
            _use(monkeypatch, configured)
            await write_audit(session, action=f"{marker}.genuine", actor_type="system")

            # The forgery: signed with the public constant, chained correctly onto the
            # real head, so its LINK is perfect. Only the key gives it away.
            _use(monkeypatch, _Stub())
            await write_audit(session, action=f"{marker}.forged", actor_type="system")

            _use(monkeypatch, configured)
            verdict = await verify_chain(session)

            assert verdict.breaks_found == before + 1, (verdict.breaks_found, before)
            forged = [b for b in verdict.breaks if b.kind == "content"]
            assert forged, f"a downgraded entry must not pass as intact: {verdict.breaks}"

            raise _AbortError


# --- 3. the fingerprint that shared the key -----------------------------------


def test_the_idempotency_fingerprint_has_its_own_key_and_the_same_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`scope_key` no longer moves when the audit chain's key does.

    It is a PSEUDONYM (BACKEND-PATTERNS §4 forbids raw ids in `idempotency_records`), and
    a keyed hash is a pseudonym only while the key is secret — so it needed the same
    requirement. It did NOT need the same key: the fingerprint has to stay stable,
    because changing it makes every in-flight `Idempotency-Key` miss its stored record
    and a client retry re-execute, which for `POST /v1/leads/{id}/call` is a second call
    placed to a real person. Sharing meant an audit-chain rotation did that silently.

    Note what is NOT claimed here: guessing this fingerprint does not let anyone collide
    with a client's idempotent write. `scope` is never accepted from the wire — both call
    sites derive it from the verified principal — so a predictable value cannot be
    submitted.
    """
    tenant, user = uuid.uuid4(), uuid.uuid4()
    scoped = _Stub(app_env="prod", idempotency_scope_secret="s" * MIN_HMAC_KEY_BYTES)

    monkeypatch.setattr(reliability_module, "get_settings", lambda: scoped)
    fingerprint = scope_key(tenant_id=tenant, user_id=user)

    # The audit chain rotates underneath it; the fingerprint does not notice.
    rotated = _Stub(
        app_env="prod",
        idempotency_scope_secret="s" * MIN_HMAC_KEY_BYTES,
        audit_chain_secret=ACTIVE_SECRET,
        audit_chain_secret_retired=RETIRED_SECRET,
    )
    monkeypatch.setattr(reliability_module, "get_settings", lambda: rotated)
    assert scope_key(tenant_id=tenant, user_id=user) == fingerprint

    # Absent and too-short are refused outside `local`, same ladder as every other key.
    for broken in (_Stub(app_env="prod"), _Stub(app_env="prod", idempotency_scope_secret="short")):
        monkeypatch.setattr(reliability_module, "get_settings", lambda s=broken: s)
        with pytest.raises(ProblemError) as raised:
            scope_key(tenant_id=tenant, user_id=user)
        assert raised.value.code == "idempotency_not_configured"

    # Local keeps working without a secrets manager, and still separates tenants.
    monkeypatch.setattr(reliability_module, "get_settings", lambda: _Stub())
    assert scope_key(tenant_id=tenant, user_id=user) != scope_key(
        tenant_id=uuid.uuid4(), user_id=user
    )
