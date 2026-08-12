# infra/

Infrastructure that is not application code. Today this directory contains exactly one
thing: the **object-store lifecycle rule** — the mechanism three modules in `apps/` have
been naming for a while and which, until now, did not exist.

> **Nothing in this directory has been applied to anything.** No cloud credentials exist
> in the environment that wrote it. Read §5 before believing any of it works in
> production.

---

## 1. The finding this answers

Three modules describe an object-store lifecycle rule as the thing that deletes recording
**audio**:

| Where | What it promises |
|---|---|
| `apps/workers/storage.py` → `recording_key()` | Keys are tenant-prefixed "so a bucket policy or **a lifecycle rule** can be scoped per tenant". Keys are `recordings/{tenant_id}/{YYYY}/{MM}/{call_id}.wav`. |
| `apps/workers/retention.py` → `_apply_one()`, recording branch | "Clearing the pointer is the local half; **the object-store lifecycle rule removes the bytes**." The pointer clock is `max(policy ttl_days, 90)`, i.e. per-tenant and floored. |
| `apps/api/compliance/deletion.py` → `ERASURE_LIMITATIONS[0]` | "The stored audio itself is removed by **the object-store lifecycle rule, which is floored at 90 days**." This text is returned on every deletion-request response and is forwarded to a data principal. |
| `docs/SECURITY-COMPLIANCE.md` §4 | Names the same rule, and then says plainly that it is not built. |

None of them was true. `apply_retention` cleared `calls.recording_url`, the erasure path
cleared it again, and the audio was deleted by nobody: recordings accumulated forever.
The retention promise in the DPA and the erasure promise on the certificate were both
partly unkept — and, worse, the certificate's limitation text described a 90-day floor as
if a mechanism were enforcing it.

`engine-payloads/` is the quieter half of the same hole. Raw vendor payloads are written
by `archive_payload()`, they contain phone numbers and transcript text, **no
`retention_policies` category covers them** (the enum is
`recording|transcript|lead|consent_log`), and nothing in `apps/` has ever deleted one.

## 2. What is here

```
infra/object-lifecycle/policy.json          the lifecycle configuration — ONE source of truth
infra/object-lifecycle/apply_lifecycle.py   guarded applier; dry-run by default
infra/terraform/                            the same policy as IaC — UNVALIDATED, see §5
runbooks/object-lifecycle.md                the operator procedure
tests/object_lifecycle_test.py              the check anyone can run
```

`policy.json` is a plain S3 `LifecycleConfiguration` document. Both the applier and the
Terraform module read *that same file* — the Terraform does `jsondecode(file(...))` rather
than restating the rules — so the two representations cannot drift into disagreeing about
what the lifecycle rule is.

## 3. What the rule is, and what it is deliberately NOT

**It is a ceiling on unbounded growth. It is not per-tenant retention, and it cannot be.**

This is the important correction to the three comments above, and it is a fact about the
data model rather than an implementation shortcut:

- A bucket lifecycle rule is **static and prefix-scoped**. You set it once; it applies to
  every object under a prefix.
- `retention_policies` is **per tenant, editable at runtime, and unbounded above** — the
  only schema constraint is `data_category != 'recording' OR ttl_days >= 90`
  (migration `05bba2f3c19c`). The seeded default is 90 days, and
  SECURITY-COMPLIANCE §1 explicitly contemplates sectoral overlays that go much
  higher (RBI's two years for BFSI clients).

One bucket rule therefore cannot "follow the retention policy" for N tenants at once. Any
single number is either **too low** for somebody — deleting a BFSI client's recordings
before their regulator's minimum, which is the worse error, and irreversible — or **too
high** for everybody else, in which case the bytes outlive the pointer.

This module chooses too high, on purpose, and says so:

| Prefix | Days | What it is |
|---|---|---|
| `recordings/` | 2555 (7y) | A **ceiling**, set above every retention period the platform currently seeds (the longest is `consent_log` at 2555d), so the rule can never be the reason an object disappears before that tenant's own policy allows. It bounds infinite accumulation. It does not implement retention. |
| `engine-payloads/` | 90 | Debug artifacts with no retention category and no legal retention requirement, carrying phone numbers and transcript text. **This is a new retention decision** and needs a decision-log entry (ROADMAP §6) — it is not implied by any existing policy row. |
| (all) | abort MPU after 7d | Cost hygiene. No compliance content. |

**Per-tenant precision, if it is wanted, belongs in `apps/`, not here.** The key layout
already supports it (`recordings/{tenant_id}/…`, exactly as `recording_key()`'s comment
says), but a per-tenant rule set would have to be reconciled against the database every
time a client changed their policy — Terraform cannot track that, and object stores cap
rules per bucket. The honest shape is a worker that deletes the object in the same
transaction that clears the pointer, with the bucket rule left underneath as a backstop.
That is a change to `apps/workers/retention.py`, and it is not made here.

## 4. The 90-day floor

`RECORDING_FLOOR_DAYS = 90` (TRAI, SECURITY-COMPLIANCE §1) is enforced in four places
now. The first three touch a *pointer*; only the fourth touches *bytes*, which is why it
is written as a refusal in three independent layers:

1. DB `CHECK` on `retention_policies.ttl_days`.
2. `RECORDING_FLOOR_DAYS` clamping in `apply_retention`.
3. `check_policy()` in the applier — refuses, exit code 2.
4. `precondition` blocks in the Terraform — a plan that would breach the floor fails.

Both the applier and the Terraform treat a rule as reaching recordings if its prefix
*contains or is contained by* `recordings/`. A bucket-root catch-all with a short
expiration deletes recordings just as effectively as a rule that names them, and that is
exactly the edit someone makes while tidying up storage costs.

**This module does not resolve the erasure-vs-floor tension** in SECURITY-COMPLIANCE §4.
It cannot: that is an open decision that needs the Bolna erasure commitment from pilot
gate 12(f). What it does is make the tension *true* rather than aspirational — the
certificate's "removed by the object-store lifecycle rule, floored at 90 days" now
describes something that exists. Note that this makes the erasure position **weaker on
paper and stronger in fact**: previously the bytes were never deleted at all, so the
certificate's claim was worse than it read.

## 5. What a human must do before any of this is real

Everything below needs credentials and network access that did not exist where this was
written. Do not assume any of it works.

1. **Confirm the target.** Production object storage is **Cloudflare R2**
   (DEPLOYMENT.md §1, TRD §2). DEV-SETUP.md §3 also names DO Spaces as an alternative,
   and CLAUDE.md's repo-layout line says "Terraform (DO Bangalore)" — that refers to the
   *VPS*, not the bucket. Pin which one is live before applying anything. **No bucket
   name or account ID appears anywhere in this directory**; every one is a variable.
2. **Verify the store actually supports these rules.** "S3-compatible expiration" is not
   one thing. R2, DO Spaces and MinIO each implement a subset of S3's lifecycle grammar
   (tag-based filters, notably, are not portable; this policy deliberately uses prefixes
   only). Also confirm how the store treats `Filter: {"Prefix": ""}` for the abort-MPU
   rule — some implementations want the filter omitted entirely.
3. **Run the runbook**, not the script from memory: `runbooks/object-lifecycle.md`. It
   starts with the SQL that produces `--max-tenant-ttl-days`, which the guards need and
   which must not be guessed.
4. **Validate the Terraform.** `terraform init` and `terraform validate` were **never
   run** on `infra/terraform/` — `registry.terraform.io` was blocked by egress policy, so
   no provider schema was ever downloaded and **no resource attribute has been checked
   against a real provider**. `terraform fmt -check` passes and the config parses, which
   proves HCL syntax and nothing more. Run `terraform init && terraform validate`, then
   `terraform providers schema -json`, and reconcile before applying. If the schema has
   moved, prefer fixing this module over hand-editing the bucket.
   The Cloudflare provider's native R2 lifecycle resource may be the better long-term
   home; it was not used because its schema could not be verified here, and a resource
   nobody has checked is worse than one everybody knows.
5. **Decide the `engine-payloads/` number** (§3) and record it in the decision log.
6. **Do not certify a deletion from an expiry date.** Expiry is asynchronous on every
   S3-compatible store: the rule makes an object *eligible* for deletion after N days;
   the store removes it on its own schedule afterwards. The DPDP proof JSON must never
   claim a byte-level deletion timestamp it got from a lifecycle rule.

## 6. Verifying without credentials

```
uv run pytest tests/object_lifecycle_test.py           # 12 checks, no network, no creds
uv run python infra/object-lifecycle/apply_lifecycle.py --max-tenant-ttl-days <N>
terraform -chdir=infra/terraform fmt -check
```

The pytest is the real gate. It pins the applier's floor constant to
`apps/workers/retention.RECORDING_FLOOR_DAYS`, validates the document against botocore's
S3 service model offline, proves the guards *refuse* three hostile policies rather than
merely describing a refusal, and — the one most likely to catch a future regression —
asserts the rule prefixes still match what `recording_key()` and `payload_key()` actually
write. If someone changes the key layout, a lifecycle rule scoped to the old prefix keeps
reporting itself as configured while matching zero objects, which is a failure that looks
exactly like success.

One test is skipped unless local MinIO is up (`make up`) with S3 credentials in the
environment. It is the only check that proves a real S3 implementation *accepts* the
document rather than that it is well-formed. **It has never been run** — the MinIO image
could not be pulled where this was written.
