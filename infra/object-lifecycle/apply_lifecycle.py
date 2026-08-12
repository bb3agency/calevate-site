"""Apply the object-store lifecycle configuration to an S3-compatible bucket.

WHY THIS EXISTS. `apps/workers/retention.py`, `apps/workers/storage.py` and
`apps/api/compliance/deletion.py` all name "the object-store lifecycle rule" as the
mechanism that removes recording AUDIO. Until this directory existed, nothing
configured one: `apply_retention` cleared `calls.recording_url` and the bytes were
deleted by nobody. This script is the thing those comments point at.

WHAT IT IS NOT. It is NOT per-tenant retention, and it cannot be. A bucket lifecycle
rule is static and prefix-scoped; `retention_policies` is per tenant, editable at
runtime, and has NO upper bound in the schema (the only CHECK is
`data_category != 'recording' OR ttl_days >= 90`). One bucket-wide rule therefore
cannot "follow the retention policy" for N tenants at once. What it can do is put a
CEILING on unbounded growth, set high enough that it is never the reason an object
disappears before that tenant's own policy allows. See `infra/README.md` §3.

SAFETY. Two guards, both refusals rather than warnings:

1. The `recordings/` expiration may never be below `RECORDING_FLOOR_DAYS = 90` — the
   TRAI floor from SECURITY-COMPLIANCE §1, already enforced in a DB CHECK and in
   `apply_retention`. This is the third place, and it is the one that touches bytes.
2. The `recordings/` expiration may never be below the longest recording TTL any
   tenant has configured, which the operator passes as `--max-tenant-ttl-days` after
   running the query in `runbooks/object-lifecycle.md`. A ceiling below a live policy
   would delete a BFSI client's recordings before their regulator's minimum.

Dry-run is the default. Credentials come from the standard AWS environment variables
and are never read from a file in this repository.

Usage:
    python infra/object-lifecycle/apply_lifecycle.py \
        --endpoint https://<account>.r2.cloudflarestorage.com \
        --bucket <bucket> --max-tenant-ttl-days 180
    # ... review the printed diff, then re-run with --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

POLICY_PATH = Path(__file__).with_name("policy.json")

# Duplicated from `apps/workers/retention.RECORDING_FLOOR_DAYS` on purpose: this script
# runs outside the application (an operator laptop, a deploy step) and must not depend
# on the app being importable to know the floor. `tests/object_lifecycle_test.py` pins
# the two together so they cannot drift.
RECORDING_FLOOR_DAYS = 90

# Prefixes owned by `apps/workers/storage.py`. The test asserts these still match what
# `recording_key()` and `payload_key()` actually produce — if someone changes the key
# layout, a lifecycle rule scoped to the old prefix silently stops matching anything,
# which is a failure that looks exactly like success.
RECORDINGS_PREFIX = "recordings/"
PAYLOADS_PREFIX = "engine-payloads/"


class PolicyError(Exception):
    """A refusal. The lifecycle configuration is unsafe or malformed."""


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    with path.open() as handle:
        policy: dict[str, Any] = json.load(handle)
    return policy


def recordings_expiration_days(policy: dict[str, Any]) -> int | None:
    """Days after which the `recordings/` rule expires an object, or None if no rule
    covers that prefix."""
    for rule in policy.get("Rules", []):
        prefix = rule.get("Filter", {}).get("Prefix", "")
        if prefix != RECORDINGS_PREFIX:
            continue
        days = rule.get("Expiration", {}).get("Days")
        if days is not None:
            return int(days)
    return None


def check_policy(policy: dict[str, Any], *, max_tenant_ttl_days: int) -> None:
    """Raise PolicyError unless the configuration is safe to apply. Refusals only."""
    rules = policy.get("Rules")
    if not isinstance(rules, list) or not rules:
        raise PolicyError("policy has no Rules")

    ids = [rule.get("ID") for rule in rules]
    if len(set(ids)) != len(ids):
        raise PolicyError(f"duplicate rule IDs: {ids}")
    for rule in rules:
        if rule.get("Status") not in {"Enabled", "Disabled"}:
            raise PolicyError(f"rule {rule.get('ID')!r} has invalid Status {rule.get('Status')!r}")

    # Any rule that can delete under `recordings/` — including a catch-all at the bucket
    # root — is subject to the floor. Checking only the exact-prefix rule would miss a
    # rule with Prefix "" and an Expiration, which deletes recordings too.
    for rule in rules:
        if rule.get("Status") != "Enabled":
            continue
        prefix = rule.get("Filter", {}).get("Prefix", "")
        days = rule.get("Expiration", {}).get("Days")
        if days is None:
            continue
        covers_recordings = RECORDINGS_PREFIX.startswith(prefix) or prefix.startswith(
            RECORDINGS_PREFIX
        )
        if not covers_recordings:
            continue
        if int(days) < RECORDING_FLOOR_DAYS:
            raise PolicyError(
                f"rule {rule.get('ID')!r} expires recordings after {days}d, below the "
                f"TRAI {RECORDING_FLOOR_DAYS}-day floor (SECURITY-COMPLIANCE §1)"
            )
        if int(days) < max_tenant_ttl_days:
            raise PolicyError(
                f"rule {rule.get('ID')!r} expires recordings after {days}d, below the "
                f"longest configured tenant recording TTL ({max_tenant_ttl_days}d). "
                "The bucket ceiling must never delete below a tenant's own policy."
            )

    validate_against_s3_model(policy)


def validate_against_s3_model(policy: dict[str, Any]) -> None:
    """Validate the document against botocore's S3 service model, offline.

    This is the same shape check the SDK performs before putting the request on the
    wire, so a malformed rule fails here rather than half-way through a deploy. It
    needs no network and no credentials.
    """
    import botocore.session
    from botocore.validate import ParamValidator

    operation = (
        botocore.session.get_session()
        .get_service_model("s3")
        .operation_model("PutBucketLifecycleConfiguration")
    )
    report = ParamValidator().validate(
        {"Bucket": "validation-placeholder", "LifecycleConfiguration": policy},
        operation.input_shape,
    )
    if report.has_errors():
        raise PolicyError(f"not a valid S3 lifecycle configuration: {report.generate_report()}")


def _client(endpoint: str) -> Any:
    import boto3
    from botocore.config import Config

    missing = [
        name for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") if not os.environ.get(name)
    ]
    if missing:
        raise PolicyError(f"credentials not in environment: {', '.join(missing)}")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        # R2 ignores the region but the SDK insists on one; "auto" is what Cloudflare
        # documents for the S3 API. DO Spaces and MinIO accept it too.
        region_name=os.environ.get("AWS_REGION", "auto"),
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def current_policy(client: Any, bucket: str) -> dict[str, Any] | None:
    from botocore.exceptions import ClientError

    try:
        response = client.get_bucket_lifecycle_configuration(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {
            "NoSuchLifecycleConfiguration",
            "NoSuchLifecycleConfigurationError",
        }:
            return None
        raise
    return {"Rules": response.get("Rules", [])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("OBJECT_STORE_ENDPOINT"))
    parser.add_argument("--bucket", default=os.environ.get("OBJECT_STORE_BUCKET"))
    parser.add_argument(
        "--max-tenant-ttl-days",
        type=int,
        required=True,
        help=(
            "The longest recording ttl_days any tenant has configured. Get it with the "
            "query in runbooks/object-lifecycle.md — do not guess."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually PUT the configuration. Without it this is a dry run.",
    )
    args = parser.parse_args(argv)

    policy = load_policy()
    try:
        check_policy(policy, max_tenant_ttl_days=args.max_tenant_ttl_days)
    except PolicyError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    print("desired configuration:")
    print(json.dumps(policy, indent=2))

    if not args.endpoint or not args.bucket:
        print(
            "\nno --endpoint/--bucket given: validated the policy only, nothing contacted.",
            file=sys.stderr,
        )
        return 0

    try:
        client = _client(args.endpoint)
        existing = current_policy(client, args.bucket)
    except PolicyError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    print(f"\ncurrent configuration on {args.bucket}:")
    print(json.dumps(existing, indent=2) if existing else "  (none — nothing expires today)")

    if not args.apply:
        print("\ndry run — re-run with --apply to write this configuration.")
        return 0

    client.put_bucket_lifecycle_configuration(Bucket=args.bucket, LifecycleConfiguration=policy)
    print(f"\napplied to {args.bucket}.")
    # Deliberately stated: expiry is asynchronous on every S3-compatible store we might
    # use. An object is eligible for deletion after N days; the store removes it on its
    # own schedule after that. Never certify a deletion from this timestamp alone.
    print("note: expiry is asynchronous — eligibility, not a deletion receipt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
