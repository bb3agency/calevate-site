"""The object-store lifecycle rule: the mechanism three modules name, now checkable.

`apps/workers/retention.py` ("the object-store lifecycle rule removes the bytes"),
`apps/workers/storage.py` ("so a bucket policy or a lifecycle rule can be scoped per
tenant") and `apps/api/compliance/deletion.py` (`ERASURE_LIMITATIONS`, handed to a data
principal on every deletion response) all describe a lifecycle rule as the thing that
deletes recording AUDIO. For a long time nothing configured one. `infra/` now does, and
this file is what stops that configuration from quietly becoming wrong again.

The failure modes it is aimed at, in order of how badly they would end:

1. **A rule that deletes recordings before 90 days.** The TRAI floor
   (SECURITY-COMPLIANCE §1) is already enforced on the pointer — a DB CHECK on
   `retention_policies.ttl_days` and `RECORDING_FLOOR_DAYS` in `apply_retention`. The
   lifecycle rule is the only one of the three that touches BYTES, so it is the only
   one whose breach destroys the evidence that a call was compliant. Nothing about it
   is recoverable.
2. **A ceiling that undercuts a tenant's own policy.** `retention_policies.ttl_days`
   has no upper bound in the schema, and SECURITY-COMPLIANCE §1 names sectoral
   overlays (RBI's two years) that lawfully exceed the 180-day default. A bucket rule
   below a live policy silently becomes that tenant's retention mechanism, at the
   wrong number.
3. **Silent prefix drift.** The rules are scoped to `recordings/` and
   `engine-payloads/` because that is what `recording_key()` and `payload_key()`
   produce. Change either key layout and the lifecycle rule keeps reporting itself as
   configured while matching zero objects — a failure indistinguishable from success
   until someone counts the bytes years later.

What this file deliberately does NOT do: resolve the erasure-vs-90-day-floor tension in
SECURITY-COMPLIANCE §4. That is an open decision with a decision-log entry owed to it.
These tests only ensure that whatever is built cannot silently violate the floor while
the decision is still open.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import ModuleType
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from apps.workers.retention import RECORDING_FLOOR_DAYS
from apps.workers.storage import delivery_body_key, payload_key, recording_key
from scripts.seed import DEFAULT_RETENTION_POLICIES

REPO_ROOT = Path(__file__).resolve().parents[1]
INFRA = REPO_ROOT / "infra" / "object-lifecycle"
POLICY_PATH = INFRA / "policy.json"


def _load_applier() -> ModuleType:
    """Import the applier by path.

    `infra/object-lifecycle` is a hyphenated directory and deliberately not a package —
    it is operator tooling, not application code, and nothing in `apps/` may import it.
    Loading it by path keeps that boundary while still letting the guard logic be
    tested rather than trusted.
    """
    spec = importlib.util.spec_from_file_location(
        "calevate_apply_lifecycle", INFRA / "apply_lifecycle.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


applier = _load_applier()


@pytest.fixture
def policy() -> dict:
    return json.loads(POLICY_PATH.read_text())


def _enabled_expiry_rules(policy: dict) -> list[tuple[str, str, int]]:
    """(id, prefix, days) for every enabled rule that expires objects."""
    out = []
    for rule in policy["Rules"]:
        days = rule.get("Expiration", {}).get("Days")
        if rule["Status"] == "Enabled" and days is not None:
            out.append((rule["ID"], rule.get("Filter", {}).get("Prefix", ""), int(days)))
    return out


# --- 1. The floor. The one that destroys evidence if it is wrong. -------------------


def test_no_rule_expires_recordings_before_the_trai_floor(policy: dict) -> None:
    """Any enabled rule whose prefix can REACH a recording is subject to the floor.

    Deliberately not "the rule whose prefix is exactly recordings/": a catch-all rule
    at the bucket root deletes recordings just as thoroughly, and that is precisely the
    edit someone makes when they want to tidy up storage costs.
    """
    for rule_id, prefix, days in _enabled_expiry_rules(policy):
        reaches_recordings = "recordings/".startswith(prefix) or prefix.startswith("recordings/")
        if reaches_recordings:
            assert days >= RECORDING_FLOOR_DAYS, (
                f"rule {rule_id!r} (prefix {prefix!r}) expires recordings after {days}d, "
                f"below the TRAI {RECORDING_FLOOR_DAYS}-day floor (SECURITY-COMPLIANCE §1)"
            )


def test_applier_floor_constant_matches_the_application(policy: dict) -> None:
    """The applier duplicates RECORDING_FLOOR_DAYS so it can run without importing the
    app. Duplication is fine; drifting is not."""
    assert applier.RECORDING_FLOOR_DAYS == RECORDING_FLOOR_DAYS


def test_guard_refuses_a_policy_that_breaches_the_floor() -> None:
    """The guard is a refusal, not a comment. Proven by making it refuse."""
    hostile = {
        "Rules": [
            {
                "ID": "tidy-up-storage-costs",
                "Status": "Enabled",
                "Filter": {"Prefix": "recordings/"},
                "Expiration": {"Days": 30},
            }
        ]
    }
    with pytest.raises(applier.PolicyError, match="floor"):
        applier.check_policy(hostile, max_tenant_ttl_days=90)


def test_guard_refuses_a_bucket_root_catch_all_under_the_floor() -> None:
    """The subtle version of the same mistake: no mention of recordings anywhere."""
    hostile = {
        "Rules": [
            {
                "ID": "expire-everything",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "Expiration": {"Days": 45},
            }
        ]
    }
    with pytest.raises(applier.PolicyError, match="floor"):
        applier.check_policy(hostile, max_tenant_ttl_days=90)


# --- 2. The ceiling must sit above every live tenant policy -------------------------


def test_ceiling_is_above_every_seeded_retention_default(policy: dict) -> None:
    """A new tenant's seeded policies must all fit under the bucket ceiling.

    Not a proof about production — the live maximum is a database question the runbook
    answers before every apply. It is a proof about the DEFAULTS, which is the one part
    of the answer that lives in this repository and can therefore regress in a pull
    request.
    """
    ceiling = applier.recordings_expiration_days(policy)
    assert ceiling is not None, "no rule covers recordings/ — the bytes are deleted by nothing"
    longest_seeded = max(int(p["ttl_days"]) for p in DEFAULT_RETENTION_POLICIES)
    assert ceiling >= longest_seeded, (
        f"bucket ceiling {ceiling}d is below the longest seeded retention default "
        f"({longest_seeded}d): the lifecycle rule would delete data a tenant's own "
        "policy says to keep"
    )


def test_guard_refuses_a_ceiling_below_a_live_tenant_policy(policy: dict) -> None:
    """The BFSI case: a client lawfully configured to two years, a ceiling at one."""
    with pytest.raises(applier.PolicyError, match="longest configured tenant"):
        applier.check_policy(policy, max_tenant_ttl_days=99_999)


def test_the_shipped_policy_passes_its_own_guards(policy: dict) -> None:
    longest_seeded = max(int(p["ttl_days"]) for p in DEFAULT_RETENTION_POLICIES)
    applier.check_policy(policy, max_tenant_ttl_days=longest_seeded)


# --- 3. Prefix drift ----------------------------------------------------------------


def test_rule_prefixes_match_the_keys_storage_actually_writes(policy: dict) -> None:
    """The rules are scoped to prefixes; `storage.py` owns the keys. If those two ever
    disagree the lifecycle rule matches nothing and reports itself healthy."""
    written_recording = recording_key(uuid4(), uuid4())
    written_payload = payload_key("bolna", "exec-1")
    written_body = delivery_body_key(
        tenant_id=uuid4(), subject_type="lead", subject_id=str(uuid4()), delivery_id=uuid4()
    )

    prefixes = {rule.get("Filter", {}).get("Prefix", "") for rule in policy["Rules"]}
    assert applier.RECORDINGS_PREFIX in prefixes
    assert applier.PAYLOADS_PREFIX in prefixes
    assert applier.BODIES_PREFIX in prefixes

    assert written_body.startswith(applier.BODIES_PREFIX), (
        f"delivery_body_key() now writes {written_body!r}, which no lifecycle rule "
        "matches — an orphaned CRM payload would sit in the bucket forever"
    )

    assert written_recording.startswith(applier.RECORDINGS_PREFIX), (
        f"recording_key() now writes {written_recording!r}, which no lifecycle rule "
        "matches — the bytes would never expire"
    )
    assert written_payload.startswith(applier.PAYLOADS_PREFIX), (
        f"payload_key() now writes {written_payload!r}, which no lifecycle rule matches"
    )


def test_every_written_prefix_is_covered_by_some_rule(policy: dict) -> None:
    """Both things we put in the bucket must expire eventually. `engine-payloads/` is
    the one that is easy to forget: raw vendor payloads carry phone numbers and
    transcript text, no `retention_policies` category covers them (the enum is
    recording/transcript/lead/consent_log), and nothing in `apps/` ever deletes them.
    """
    covered = {
        rule.get("Filter", {}).get("Prefix", "")
        for rule in policy["Rules"]
        if rule["Status"] == "Enabled" and rule.get("Expiration", {}).get("Days") is not None
    }
    for written in (recording_key(uuid4(), uuid4()), payload_key("bolna", "exec-1")):
        assert any(written.startswith(prefix) for prefix in covered), (
            f"nothing expires {written!r} — it accumulates forever"
        )


# --- 4. It is a valid S3 lifecycle document -----------------------------------------


def test_policy_is_a_valid_s3_lifecycle_configuration(policy: dict) -> None:
    """Validated against botocore's own S3 service model — the same shape check the SDK
    runs before the request goes on the wire. Offline, no credentials: a malformed rule
    fails in CI rather than half-way through a production deploy.

    Note what this does NOT prove: R2, DO Spaces and MinIO each implement a SUBSET of
    S3's lifecycle grammar (tag-based filters, in particular, are not portable). A
    document that is valid S3 can still be refused by the store. The only proof of that
    is the dry run against the real bucket in runbooks/object-lifecycle.md.
    """
    applier.validate_against_s3_model(policy)


def test_rule_ids_are_unique_and_statuses_are_real(policy: dict) -> None:
    ids = [rule["ID"] for rule in policy["Rules"]]
    assert len(set(ids)) == len(ids)
    assert {rule["Status"] for rule in policy["Rules"]} <= {"Enabled", "Disabled"}


# --- 5. Terraform reads the same document -------------------------------------------


def test_terraform_consumes_the_same_policy_file() -> None:
    """One source of truth. Two representations of a lifecycle rule that can disagree
    is how the rule ends up being whichever one was applied last."""
    main_tf = (REPO_ROOT / "infra" / "terraform" / "main.tf").read_text()
    assert "../object-lifecycle/policy.json" in main_tf


# --- 6. Optional: the round trip against a real S3-compatible store ------------------


def _endpoint_reachable(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    if not parsed.hostname:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(
    not _endpoint_reachable("http://localhost:9000"),
    reason="local MinIO not running (`make up`); the offline checks above still apply",
)
def test_minio_accepts_and_returns_the_policy(policy: dict) -> None:
    """The one check that proves the store ACCEPTS this document rather than that it is
    well-formed. Requires `make up` and AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY set to
    the local MinIO root credentials from docker-compose.yml — no credential is
    committed here, deliberately.

    MinIO is not R2. This proves the document survives a real S3 implementation's
    parser, which is strictly more than the offline check proves and strictly less than
    a dry run against the production bucket.
    """
    import os
    from unittest import mock

    # DECLARED, not borrowed. `tests/conftest._no_ambient_credentials` strips the
    # machine's `AWS_*` for the whole suite so local matches CI, and these are the MinIO
    # root credentials from `docker-compose.yml` — not a secret, and the only values
    # that can work against the local store anyway. The skip below is now about whether
    # MinIO is RUNNING, which is the real precondition; it used to be about whether the
    # developer happened to have exported something.
    with mock.patch.dict(
        os.environ,
        {"AWS_ACCESS_KEY_ID": "calevate", "AWS_SECRET_ACCESS_KEY": "calevate123"},
    ):
        _run_minio_policy_check(policy)


def _run_minio_policy_check(policy: dict) -> None:
    from botocore.exceptions import ClientError

    client = applier._client("http://localhost:9000")
    bucket = f"lifecycle-test-{uuid4().hex[:12]}"
    client.create_bucket(Bucket=bucket)
    try:
        client.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration=policy)
        roundtripped = applier.current_policy(client, bucket)
        assert roundtripped is not None
        returned_ids = {rule["ID"] for rule in roundtripped["Rules"]}
        assert {rule["ID"] for rule in policy["Rules"]} <= returned_ids
    finally:
        with contextlib.suppress(ClientError):
            client.delete_bucket(Bucket=bucket)
