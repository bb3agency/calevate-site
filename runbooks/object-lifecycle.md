# Runbook — applying the object-store lifecycle rule

When: first-time setup of a bucket; after any edit to
`infra/object-lifecycle/policy.json`; and whenever a client's `recording` retention
policy is raised (step 1 is the reason).

What this configures: a BACKSTOP that deletes recording **audio** and archived vendor
payloads from the bucket. It is no longer the only thing that removes the bytes, and that
correction is the reason to read this paragraph rather than skim it. Since migration
`9c1d3e7a05f4`, `apps/workers/retention.py` deletes the audio object itself — on the
tenant's own `recording` policy in the sweep, and on the earliest lawful date in a DPDP
erasure (`recording_erasure_holds`). This rule is what catches an object those paths never
saw: one whose reference was lost, or written before that code existed. Read
`infra/README.md` §3 first if you have not — in particular, **this rule is a ceiling on
growth, not per-tenant retention**, and treating it as retention is how it gets set to a
dangerous number.

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
- **This is not per-tenant retention.** It never became per-tenant retention; the
  per-tenant mechanism was built next to it instead (`apps/workers/retention.py`, migration
  `9c1d3e7a05f4`), so a tenant on a 180-day policy now has their audio deleted on day 181
  by the nightly sweep, and this rule is the ceiling that catches whatever the sweep never
  saw. If you are asked "when is this client's audio deleted?", the answer is their
  `retention_policies` row, never the number in `policy.json`.
- **A DPDP erasure has its own clock.** An erasure destroys the audio it may destroy and
  schedules the rest in `recording_erasure_holds` — nothing about that waits on this
  bucket rule, and lowering or raising the ceiling does not move a scheduled destruction.
  To answer "has the deferred audio actually gone?", read `erased_at` on the hold row.

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
   report it against the retention obligation.
5. **Rule out the two paths that now delete legitimately before calling it an incident.**
   The nightly sweep deletes on the tenant's `recording` policy, and an erasure destroys or
   schedules by subject. Both are logged with counts and no keys:
   `retention_sweep` (`recordings`, `recording_holds`) and `deletion_executed`
   (`recordings=`, `floor_recordings=`). A drop that matches a sweep count is the system
   doing its job; a drop that matches nothing is the incident.
