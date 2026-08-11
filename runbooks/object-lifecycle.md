# Runbook — applying the object-store lifecycle rule

When: first-time setup of a bucket; after any edit to
`infra/object-lifecycle/policy.json`; and whenever a client's `recording` retention
policy is raised (step 1 is the reason).

What this configures: the rule that deletes recording **audio** and archived vendor
payloads from the bucket. `apps/workers/retention.py` clears `calls.recording_url`; this
rule is the only thing that removes the bytes it pointed at. Read `infra/README.md` §3
first if you have not — in particular, **this rule is a ceiling on growth, not per-tenant
retention**, and treating it as retention is how it gets set to a dangerous number.

Ground rules: production access through the audited admin path, read-only SELECTs
(SECURITY-COMPLIANCE §5). Credentials come from the secrets manager into the
environment; they are never written to a file in the repository, and the bucket name is
not committed anywhere. Nothing below prints a phone number or a transcript.

---

## 1. Get the ceiling input — do not guess it

The guards need the longest `recording` TTL any tenant has configured. This is not a
formality: `retention_policies.ttl_days` has no upper bound, and a BFSI client can
lawfully sit far above the default (RBI's two years, SECURITY-COMPLIANCE §1). A ceiling
below a live policy deletes that client's recordings before their regulator's minimum,
and the deletion is not reversible.

```sql
-- Admin/audited path. Cross-tenant by design: the bucket is shared.
SELECT max(ttl_days) AS max_recording_ttl_days
FROM retention_policies
WHERE data_category = 'recording';
```

Call that number `MAX_TTL`. If it exceeds the `recordings/` expiration in `policy.json`
(2555 days at the time of writing), **stop**: raise the ceiling in `policy.json` and open
a PR before applying anything. The applier will refuse anyway — that refusal is the
control working, not an obstacle to route around.

Sanity check while you are here: anything below 90 is impossible (a DB CHECK forbids it).
If the query returns one, you have a schema problem, not a lifecycle problem — escalate
rather than continuing.

## 2. Validate the policy offline

No credentials needed. Do this before touching a bucket.

```sh
uv run pytest tests/object_lifecycle_test.py
uv run python infra/object-lifecycle/apply_lifecycle.py --max-tenant-ttl-days "$MAX_TTL"
```

Exit code 2 means a guard refused. The message names which one. The two that matter:

- *"below the TRAI 90-day floor"* — a rule would delete recordings early. Do not apply.
  Do not "temporarily" lower it for a cleanup; there is no version of this that is
  temporary.
- *"below the longest configured tenant recording TTL"* — go back to step 1.

## 3. Dry run against the real bucket

```sh
export AWS_ACCESS_KEY_ID=...        # from the secrets manager, this shell only
export AWS_SECRET_ACCESS_KEY=...
uv run python infra/object-lifecycle/apply_lifecycle.py \
  --endpoint "$OBJECT_STORE_ENDPOINT" \
  --bucket "$OBJECT_STORE_BUCKET" \
  --max-tenant-ttl-days "$MAX_TTL"
```

This prints the desired configuration and whatever is on the bucket today, and changes
nothing. Read both.

- **"(none — nothing expires today)"** is the expected output on a bucket that has never
  been configured. It is also the finding that created this runbook: it means every
  recording ever copied is still there.
- If a configuration already exists and it is **not** what this repository says, find out
  who set it before overwriting. A hand-set rule on the bucket is the one place a shorter
  expiration could already have been deleting recordings, which is a compliance incident
  (OPERATIONS §7), not a config drift ticket.

This step is also the only real test that the store *accepts* the document. R2, DO Spaces
and MinIO each implement a subset of S3's lifecycle grammar; the offline checks prove the
document is valid S3, not that this store will take it.

## 4. Apply

```sh
uv run python infra/object-lifecycle/apply_lifecycle.py \
  --endpoint "$OBJECT_STORE_ENDPOINT" \
  --bucket "$OBJECT_STORE_BUCKET" \
  --max-tenant-ttl-days "$MAX_TTL" \
  --apply
```

Then re-run step 3 and confirm the bucket reports back what you sent.

The Terraform in `infra/terraform/` is the same policy as IaC and is the better long-term
home, but it has **never been `terraform validate`d against a real provider schema**
(`infra/README.md` §5). Until someone has done that, this script is the mechanism and
Terraform is the plan.

## 5. What you have NOT proven

Say this out loud when you report the change, because the wording matters legally:

- **Expiry is asynchronous.** The rule makes an object *eligible* for deletion after N
  days. The store removes it on its own schedule after that. You have configured a
  policy, not observed a deletion. Never put a lifecycle expiry date into a DPDP proof
  certificate as a byte-level deletion timestamp.
- **The engine's copy is untouched.** Bolna's recordings live on their S3 and their
  deletion API is undocumented (pilot gate 12(f)). `engine_deletion` stays
  `unconfirmed_pending_vendor_api` in every proof.
- **This is not per-tenant retention.** A tenant on a 180-day policy still has audio in
  the bucket on day 181; only the pointer is gone. That gap is the open decision in
  SECURITY-COMPLIANCE §4 and closing it is an `apps/` change, not a bucket setting.

## 6. If recordings are disappearing early

Treat as a compliance incident (OPERATIONS §7) immediately — the evidence that calls were
compliant is what is being destroyed.

1. Read the live bucket configuration (step 3, dry run). Compare against `policy.json`.
2. If the bucket has a rule this repository does not, someone set it by hand. Capture it
   verbatim before changing anything; it is the forensic record.
3. Re-apply the repository policy (step 4). This overwrites the whole configuration —
   `PutBucketLifecycleConfiguration` replaces, it does not merge.
4. Objects already expired are gone. Quantify the loss by call count and date range from
   `calls` (`recording_url IS NOT NULL` plus `ended_at`), not by listing the bucket, and
   report it against the TRAI retention obligation.
