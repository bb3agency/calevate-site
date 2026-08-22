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
import re
import socket
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any
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
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


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
    written_payload = payload_key(
        tenant_id=uuid4(), call_id=uuid4(), engine="bolna", execution_id="exec-1"
    )
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
    transcript text and no `retention_policies` category covers them (the enum is
    recording/transcript/lead/consent_log). A DPDP erasure now deletes them by
    `{tenant}/{call}` prefix (D-126, `retention._erase_engine_payloads`), which is a
    different clock from expiry: an object belonging to nobody who asked to be forgotten
    still has this rule and nothing else.
    """
    covered = {
        rule.get("Filter", {}).get("Prefix", "")
        for rule in policy["Rules"]
        if rule["Status"] == "Enabled" and rule.get("Expiration", {}).get("Days") is not None
    }
    for written in (
        recording_key(uuid4(), uuid4()),
        payload_key(tenant_id=uuid4(), call_id=uuid4(), engine="bolna", execution_id="exec-1"),
    ):
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
    main_tf = (REPO_ROOT / "infra" / "terraform" / "main.tf").read_text(encoding="utf-8")
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


#: Rules MinIO cannot be asked about, and why. Not an exemption list — the two tests
#: below assert this set from BOTH directions, so an entry cannot outlive its reason.
#:
#: MinIO does not implement `AbortIncompleteMultipartUpload` in `PutBucketLifecycle`; its
#: own S3-compatibility page says so and `minio-go`'s lifecycle package repeats it. Every
#: shape was tried against `RELEASE.2025-09-07T16-13-09Z` before writing this —
#: `Filter: {"Prefix": ""}`, `Filter: {}`, no `Filter`, the legacy top-level `Prefix`, and
#: a non-empty prefix — and all five are rejected `InvalidArgument`.
#:
#: THE RULE STAYS IN `policy.json`. Production is Cloudflare R2 (DEPLOYMENT §1), which
#: implements the action, and deleting a real growth control so a local emulator goes
#: green would be weakening the thing to fit the test. What was wrong was the test's
#: CLAIM — "the document survives a real S3 implementation's parser" — which was never
#: true of this document and had never been executed to find out, because MinIO was down
#: on every previous run and the whole check skipped.
MINIO_UNSUPPORTED_RULE_IDS: frozenset[str] = frozenset({"abort-incomplete-multipart-uploads"})


@contextlib.contextmanager
def _minio_client() -> Iterator[Any]:
    """DECLARED credentials, not borrowed, and held for the WHOLE body.

    `tests/conftest._no_ambient_credentials` strips the machine's `AWS_*` for the session
    so local matches CI; these are the MinIO root credentials from `docker-compose.yml` —
    not a secret, and the only values that can work against the local store anyway.

    A CONTEXT MANAGER rather than a factory, because a factory that returned the client
    after leaving the patch would put the credential resolution and the requests on
    opposite sides of it. That is a variant of the ambient-credential class this suite
    already closed once, and it is easier to reintroduce than to notice.
    """
    import os
    from unittest import mock

    with mock.patch.dict(
        os.environ,
        {"AWS_ACCESS_KEY_ID": "calevate", "AWS_SECRET_ACCESS_KEY": "calevate123"},
    ):
        yield applier._client("http://localhost:9000")


@contextlib.contextmanager
def _scratch_bucket(client: Any) -> Iterator[str]:
    from botocore.exceptions import ClientError

    bucket = f"lifecycle-test-{uuid4().hex[:12]}"
    client.create_bucket(Bucket=bucket)
    try:
        yield bucket
    finally:
        with contextlib.suppress(ClientError):
            client.delete_bucket(Bucket=bucket)


@pytest.mark.skipif(
    not _endpoint_reachable("http://localhost:9000"),
    reason="local MinIO not running (`make up`); the offline checks above still apply",
)
def test_minio_accepts_the_rules_it_implements(policy: dict) -> None:
    """Every rule MinIO CAN parse survives a real S3 implementation's parser.

    Strictly more than the offline check proves and strictly less than a dry run against
    the production bucket. Scoped to the supported rules so the check has a definite
    subject: asserting the whole document only ever proved that MinIO and R2 differ,
    which is a fact about MinIO and not about our policy.
    """
    checked = [rule for rule in policy["Rules"] if rule["ID"] not in MINIO_UNSUPPORTED_RULE_IDS]
    assert checked, "every rule is excluded — this check has no subject left"

    with _minio_client() as client, _scratch_bucket(client) as bucket:
        client.put_bucket_lifecycle_configuration(
            Bucket=bucket, LifecycleConfiguration={"Rules": checked}
        )
        roundtripped = applier.current_policy(client, bucket)
        assert roundtripped is not None
        returned = {rule["ID"] for rule in roundtripped["Rules"]}
        assert {rule["ID"] for rule in checked} <= returned


@pytest.mark.skipif(
    not _endpoint_reachable("http://localhost:9000"),
    reason="local MinIO not running (`make up`); the offline checks above still apply",
)
def test_the_excluded_rule_is_excluded_because_minio_still_refuses_it(policy: dict) -> None:
    """The exclusion above is MEASURED on every run, not asserted once and inherited.

    An exclusion list nobody re-checks becomes permanent, and this one has an expiry
    condition: the moment MinIO implements the action, this test fails and tells whoever
    is reading to delete the entry. The failure is the good news.
    """
    excluded = [rule for rule in policy["Rules"] if rule["ID"] in MINIO_UNSUPPORTED_RULE_IDS]
    assert len(excluded) == len(MINIO_UNSUPPORTED_RULE_IDS), (
        "MINIO_UNSUPPORTED_RULE_IDS names a rule that is not in policy.json — an "
        "exclusion for a rule that no longer exists hides the next real one"
    )

    with _minio_client() as client:
        for rule in excluded:
            _assert_minio_refuses(client, rule)


def _assert_minio_refuses(client: Any, rule: dict) -> None:
    """One rule, one throwaway bucket, and the vendor's own error code.

    `InvalidArgument` specifically, not "any ClientError": a 403 from a credential
    mix-up is also a `ClientError`, and accepting it would let this test go green for
    the wrong reason — which is exactly what happened before `_client` stopped using
    boto3's process-global session.
    """
    from botocore.exceptions import ClientError

    with _scratch_bucket(client) as bucket:
        with pytest.raises(ClientError) as caught:
            client.put_bucket_lifecycle_configuration(
                Bucket=bucket, LifecycleConfiguration={"Rules": [rule]}
            )
        assert caught.value.response["Error"]["Code"] == "InvalidArgument", (
            f"MinIO answered something new for {rule['ID']}; re-measure before trusting either list"
        )


@pytest.mark.skipif(
    not _endpoint_reachable("http://localhost:9000"),
    reason="local MinIO not running (`make up`); the offline checks above still apply",
)
def test_minio_silently_drops_the_abort_action_when_it_is_not_alone() -> None:
    """THE TRAP, pinned — and the reason the two tests above are shaped the way they are.

    MinIO rejects a rule whose ONLY action it cannot implement. Combine that action with
    one it can, and it ACCEPTS the rule and discards the action: the PUT returns 200 and
    the stored rule comes back carrying the `Expiration` alone.

    That is the obvious way somebody makes this failure go away — fold the abort into an
    existing expiration rule — and it produces a green suite, a 200 from the store, and a
    lifecycle policy where the multipart growth control does not exist. A loud rejection
    is recoverable; a silent drop is the failure mode that gets discovered by a storage
    bill. If MinIO ever starts preserving the action, this fails and the exclusion above
    can go.
    """
    merged = {
        "ID": "merged-probe",
        "Status": "Enabled",
        "Filter": {"Prefix": "recordings/"},
        "Expiration": {"Days": 2555},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
    }
    with _minio_client() as client, _scratch_bucket(client) as bucket:
        client.put_bucket_lifecycle_configuration(
            Bucket=bucket, LifecycleConfiguration={"Rules": [merged]}
        )
        stored = applier.current_policy(client, bucket)
        assert stored is not None
        rule = next(r for r in stored["Rules"] if r["ID"] == "merged-probe")
        assert rule.get("Expiration") == {"Days": 2555}
        assert "AbortIncompleteMultipartUpload" not in rule, (
            "MinIO now PRESERVES the abort action when combined with an expiration — "
            "re-measure the standalone case; the exclusion may no longer be needed"
        )


# --- where the bucket physically IS, and the four places people will try to set it -----
#
# D-450 decided R2's `CreateBucket` location hint for both production buckets: `apac`. Two
# properties of that decision have no other guard, because neither has any code to hold it:
#
#  * R2 honours a hint only at the FIRST creation of a bucket NAME — delete and recreate
#    the same name and it silently reuses the original placement — so the decision has no
#    undo short of copying every object to a differently-named bucket and re-applying the
#    policy in this directory. Its only home is a human checklist.
#  * `AWS_REGION`/`region` is the SigV4 credential SCOPE and has nothing to do with
#    placement. R2 requires `auto`. Someone who reads "we want APAC" and edits one of these
#    four sites moves no bytes and breaks every request with `SignatureDoesNotMatch` — a
#    symptom that looks like a bad token, so the search starts in the wrong place.

#: R2's documented location hints. Any of them appearing as a REGION would be the mistake.
R2_LOCATION_HINTS = ("wnam", "enam", "weur", "eeur", "apac", "oc")

#: Every place in this repository that supplies a region to an S3 client for R2.
SIGV4_REGION_SITES = (
    "apps/workers/storage.py",
    "infra/object-lifecycle/apply_lifecycle.py",
    "infra/terraform/versions.tf",
    "infra/backup/walg.json.template",
)


def test_the_sigv4_region_is_auto_at_every_site_and_is_never_a_location_hint() -> None:
    """All four region sites still say `auto`, and none has been "corrected" to a hint.

    FAILS IF: someone sets `AWS_REGION=apac` (or any other hint) in the worker client, the
    lifecycle applier, the Terraform provider or the wal-g template — the edit that reads as
    obviously right, moves nothing, and returns `SignatureDoesNotMatch` from every call.
    Also fails if a site stops naming a region at all, which is worse: botocore silently
    falls back to `us-east-1` for s3, i.e. a signature scoped to a region nobody chose.
    """
    hint_as_region = re.compile(
        r"""(AWS_REGION|region_name|["']?region["']?)\s*[:=]\s*["']("""
        + "|".join(R2_LOCATION_HINTS)
        + r""")["']""",
        re.IGNORECASE,
    )
    for rel in SIGV4_REGION_SITES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert '"auto"' in text, f"{rel} no longer supplies the `auto` SigV4 region scope"
        assert not hint_as_region.search(text), (
            f"{rel} assigns an R2 LOCATION HINT where a SigV4 credential scope belongs. "
            "Placement is set once at CreateBucket by a human (infra/README.md §5 item 2); "
            "this value only changes what the signature is computed over."
        )


def test_the_terraform_declares_no_bucket_and_therefore_cannot_place_one() -> None:
    """The module configures a lifecycle rule on an EXISTING bucket and creates nothing.

    FAILS IF: an `aws_s3_bucket` resource is added here. That is the tempting way to "own"
    the placement in IaC, and it is wrong in the one direction that cannot be undone: the
    AWS provider has no way to send R2's location hint, so the bucket would be created in
    whatever place R2 picks, permanently, from a file that looks like it decided.
    """
    hcl = "\n".join(
        (REPO_ROOT / "infra" / "terraform" / name).read_text(encoding="utf-8")
        for name in ("main.tf", "variables.tf", "versions.tf")
    )
    assert 'resource "aws_s3_bucket"' not in hcl


def test_both_bucket_checklists_name_the_hint_and_both_are_separate_one_shots() -> None:
    """The recordings bucket and the wal-g backup bucket are two independent one-shot
    decisions, and each has to say so where the human creating it will read it.

    FAILS IF: either checklist loses the `apac` hint, or the backup checklist stops flagging
    that it is a SEPARATE decision from the recordings bucket — the specific way this gets
    half-done, because the two buckets are created in different steps on different days by
    someone who has already "done the R2 bucket".
    """
    recordings = (REPO_ROOT / "infra" / "README.md").read_text(encoding="utf-8")
    backups = (REPO_ROOT / "infra" / "backup" / "README.md").read_text(encoding="utf-8")
    for name, text in (("infra/README.md", recordings), ("infra/backup/README.md", backups)):
        assert "`apac`" in text, f"{name} no longer names the location hint (D-450)"
    assert "SEPARATE one-shot" in backups
