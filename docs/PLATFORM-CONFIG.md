# PLATFORM-CONFIG — the ops console, and where secrets actually live

**Status:** SPEC, approved for build (Aug 2026). Decision row: D-95.
**Surface:** `admin.calevate.tech/ops` — admin realm, first-party session
(`apps/api/authn/`, D-165/D-170/D-177 — this line said "existing Clerk app" until
20 Aug 2026), and the admin realm's mandatory second factor, which is an emailed one-time
code and is a frozen `MFA_REQUIRED_REALMS = {"admin"}` with no setting behind it.
**Reading order:** after SECURITY-COMPLIANCE §2 (secrets) and BACKEND-PATTERNS §1
(module anatomy). DATA-MODEL owns the table shapes once they land.

---

## 0. The problem, in the founder's words

> "env keys also can be managed via that route only instead of env file, that is very
> user friendly where we don't have to login into VPS every time to update keys."

That goal is legitimate and this spec delivers it. Rotating a Sarvam key, switching the
engine from `bolna` to `cartesia`, or turning off a vertical template must not require an
SSH session. What it must ALSO not do is put plaintext credentials in Postgres, which
CLAUDE.md forbids outright.

Both are achievable at once. The rest of this document is how, and what it costs.

## 1. Two problems wearing one coat

The request reads as one feature. It is two, with different rules, and conflating them is
the most likely way this ends badly.

| | **Core config** | **Secrets** |
|---|---|---|
| Examples | engine selection, calling windows, retry ladders, vertical templates, rate limits, the big red switch | Sarvam key, Bolna key, `AZURE_OPENAI_API_KEY` (D-410), Cartesia key, Google Sheets service account (D-23), Razorpay webhook secret, Meta page access tokens, R2 credentials. **No authentication credential appears here at all** — D-177 removed the vendor whose secret keys this cell used to name, and there is nothing in its place to configure |
| Storage | plaintext rows | ciphertext + wrapped DEK |
| Readable back in the UI | **yes** — you must be able to see what the value is | **never** — last-4, who, when |
| Blast radius if leaked | embarrassing | catastrophic |
| Already exists here | partly — `apps/api/flags/registry.py`, "feature flags via plain config rows, not a flag SaaS" | no |

**They share a screen and share nothing else.** One table each, one permission each, one
audit shape each. A single `settings` table holding both, with an `is_secret` boolean
deciding whether to encrypt, is the design that eventually leaks — because the boolean is
one bad migration or one mis-set default away from storing an API key in plaintext, and
nothing would notice.

## 2. What we are NOT building, and why

The standard answers were read before departing from them (CLAUDE.md: know the standard,
then beat it if you can).

- **HashiCorp Vault** — BSL since 2023, and its seal/unseal model is a genuine
  lock-yourself-out risk for a single operator at 2am. Rejected.
- **OpenBao** (MPL fork of Vault 1.14, OpenSSF-governed) — technically excellent, free
  dynamic credentials, but it is a second stateful deployable on a one-VPS estate.
  CLAUDE.md requires a decision-log entry for a new deployable and prefers Postgres
  first. Rejected **for now**, and this spec is deliberately shaped so that swapping the
  KEK provider for OpenBao or a cloud KMS later touches one module.
- **Infisical** (MIT, Postgres + Redis, free ≤5 identities, self-hostable) — the closest
  call, and the one to revisit if we ever run more than one environment or more than two
  operators. Same objection: a second deployable, plus Redis and Postgres of its own.
- **Doppler / cloud KMS SaaS** — a second vendor holding the key that unlocks every
  client's vendor credentials, and a second deployable's worth of failure modes with it.
  ⚠ **THE RESIDENCY HALF OF THIS OBJECTION IS SPENT AND THE ROW SAYS SO RATHER THAN
  KEEPING A REASON THAT EVAPORATED.** It read *"D-36 chose an all-India model stack; a
  US-hosted KMS ... is a strange place to give that up"* — true when the language leg was
  Indian, and false since **D-449** moved it to Azure OpenAI `eastus2` and WITHDREW the
  India warranty. Speech is still Sarvam and still Indian, but "we keep everything in
  India anyway" is not an argument this repository may make any more. **The rejection is
  unchanged on the grounds above**: it is a new sub-processor on the one secret that
  unlocks all the others, on a one-VPS estate that CLAUDE.md tells us to answer with
  Postgres first. Recorded rather than quietly re-justified, because a decision whose
  stated reason evaporates and keeps its conclusion is the shape that needs re-arguing
  out loud (the same discipline D-451 applied to its own priority letter).

**What we build instead:** envelope encryption inside our own Postgres, which is the
"boring solutions: Postgres before new infra" answer and the same shape the vendors
implement internally.

## 3. Key hierarchy

```
PLATFORM_KEK            (32 bytes, env var on the VPS — NEVER in the database)
   │  wraps
   ├── DEK per secret   (32 bytes, AES-256-GCM, generated fresh per secret VERSION)
   │      │  encrypts
   │      └── the secret value
   └── PLATFORM_KEK_RETIRED (verification/unwrap only, never wraps — mirrors D-86)
```

Rules, each with the reason it exists:

1. **AES-256-GCM**, nonce per encryption, never reused. The DEK is generated fresh per
   secret *version*, not per write of the same version, so re-reading never re-wraps.
2. **The KEK never enters the database.** If it did, the database would hold both the
   lock and the key, and encryption would be theatre.
3. **KEK rotation re-wraps DEKs only** — cheap, because the secrets themselves are not
   re-encrypted. This is why the envelope exists.
3a. **The KEK label is a FINGERPRINT of the key material, never an operator-maintained
   counter (D-96, amending §5's first draft).** A counter is only correct while somebody
   remembers to bump it on every rotation; forget once and new rows are stamped with the
   OLD generation, the rewrap job then skips exactly the rows that need it, and the
   following rotation renders them permanently unreadable — silent, unrecoverable data
   loss gated on human memory. A fingerprint derived from the key cannot disagree with
   reality. It is a LABEL, not a security control: unwrap performs trial decryption over
   the ring, which is sound because GCM's tag is a 128-bit MAC, so a mislabelled row
   still opens. **The rewrap job must therefore never use the fingerprint to decide which
   rows to process** — every row is unwrapped and re-wrapped, or the counter's failure
   mode returns wearing a hash.
4. **`PLATFORM_KEK_RETIRED` unwraps but never wraps**, exactly as
   `AUDIT_CHAIN_SECRET_RETIRED` verifies but never signs (D-86). One way per problem: the
   rotation story is already written, so it is reused rather than reinvented.
5. **Minimum 32 bytes, and a short key is refused exactly like an absent one** — the
   D-86 argument transfers verbatim: to a caller they are one condition, "there is no
   usable key here."
6. **A plaintext secret exists only in memory, only during a request**, and is never
   logged, never traced, never returned in a response body. Hard rule 6 applies to
   credentials as strictly as to phone numbers.

## 4. Precedence, and the bootstrap set

**Environment always wins over the database.** This is not a fallback, it is the escape
hatch, and it is load-bearing three times over:

- it prevents a bootstrap deadlock (the KEK cannot live in the store it unlocks);
- it means a broken or unreachable store never bricks the deployment — you can always
  boot from `.env`;
- it makes an emergency override possible without a database write, which is what you
  want at 3am when the console itself is what is broken.

Resolution order for every key: **`os.environ` → `platform_settings` / `platform_secrets`
→ code default → refuse.** The refusal is fail-closed and names the key.

**The bootstrap set can never move to the database**, and the guardrail enforces it:

| Key | Why it can never move |
|---|---|
| `APP_ENV` | decides whether dev tokens are accepted (D-49) — reading it from the DB means the DB decides the security posture |
| `DATABASE_URL` | it is how you reach the store |
| `ALEMBIC_DATABASE_URL` | migrations run before the store is guaranteed to exist |
| `PLATFORM_KEK` | it is the key that opens the store |
| `PLATFORM_KEK_RETIRED` | same |
| `REDIS_URL` | needed by workers before settings resolve |

Everything else is a candidate. **`.env` goes from ~54 keys to 6.** That is the outcome
the founder asked for, stated as a number so it can be checked — **and when it was checked
it came out at 8, not 6, for a mechanical reason this table does not cover**:
`OBJECT_STORE_ENDPOINT` and `OBJECT_STORE_BUCKET` are type-required `Settings` fields with
no default, so a process whose environment lacks them cannot construct `Settings()` and
therefore cannot boot far enough to look anything up. The console does manage them and
renders them read-only when the environment supplies them. `.env.example` carries those 8;
`tests/env_example_bootstrap_floor_test.py` proves both halves, and DEV-SETUP §4 is the
current census of what is on each side of the line (55 console-managed today, 37
core-config + 18 credentials, counted from `managed_fields()` rather than remembered).

## 5. Data model

Neither table is tenant-scoped. They are PLATFORM state, admin realm only, and they
therefore carry no `tenant_id` and are exempted in `check_rls_coverage` **with a written
reason**, the same way `audit_log` and `engine_agent_routes` already are. Per-tenant
credentials are a different table and a different problem — see §11.

```sql
-- Core config. Plaintext, readable, revertible.
CREATE TABLE platform_settings (
    key           text PRIMARY KEY,               -- matches the Settings field name
    value         jsonb        NOT NULL,          -- typed on read against the Settings model
    updated_at    timestamptz  NOT NULL DEFAULT now(),
    updated_by    uuid         NOT NULL REFERENCES admin_users(id),
    note          text                            -- why, for the next reader
);

-- Secrets. Ciphertext only. INSERT-only: a new value is a new VERSION.
CREATE TABLE platform_secrets (
    key            text        NOT NULL,
    version        integer     NOT NULL,
    ciphertext     bytea       NOT NULL,          -- AES-256-GCM(value, DEK, nonce)
    nonce          bytea       NOT NULL,
    dek_wrapped    bytea       NOT NULL,          -- AES-256-GCM(DEK, KEK)
    dek_nonce      bytea       NOT NULL,
    kek_id         integer     NOT NULL,          -- FINGERPRINT of the wrapping KEK, not a counter (D-96)
    last_four      text        NOT NULL,          -- the ONLY plaintext fragment stored
    created_at     timestamptz NOT NULL DEFAULT now(),
    created_by     uuid        NOT NULL REFERENCES admin_users(id),
    retired_at     timestamptz,                   -- set when superseded; never deleted
    PRIMARY KEY (key, version)
);

-- The sentinel every process polls. One row, ever.
CREATE TABLE platform_config_version (
    id       boolean PRIMARY KEY DEFAULT true CHECK (id),
    version  bigint  NOT NULL DEFAULT 1,
    bumped_at timestamptz NOT NULL DEFAULT now()
);
```

**`platform_secrets` is append-only and joins the hard-rule-4 family** (`usage_events`,
`consent_ledger`, `audit_log`, `credit_ledger`, `one_time_charges`), enforced by the same
trigger pattern and picked up by `check_ledger_immutability`. Rotation is a new version;
the old row is retired, never updated and never deleted. That is what makes "which key was
live when this call was billed?" answerable a year later.

**`last_four` is the only plaintext fragment that touches disk**, and it exists so the
console can show *which* key is installed without being able to show the key.

## 6. Resolution and propagation — no restart, no SSH

The problem: `get_settings()` is `@lru_cache`d today, and four processes read it (api,
voice-runtime, workers, plus the pilot CLI). A value changed in the console must reach all
of them quickly, and **voice-runtime must not pay a database round-trip per webhook**
(hard rule 3: ack < 500ms, no heavy work).

**The sentinel-key pattern** (as Azure App Configuration does it): every process holds a
cached snapshot plus the `platform_config_version` it was built from. A cheap poll — one
integer read, ≤5s interval, from Redis with Postgres as the source of truth — compares
versions. Equal: keep the snapshot, zero cost. Different: rebuild the snapshot once.

- **Propagation target: under 10 seconds**, everywhere, without a process restart.
- **voice-runtime reads the snapshot, never the database, on the request path.**
- A store that is unreachable **keeps serving the last good snapshot** and alerts — a
  config lookup must never be able to take the phone system down. This is the same
  fail-visible-not-fail-empty doctrine as §52.
- Secrets are resolved lazily and cached with a shorter TTL, because a rotation should
  take effect fast and secrets are read far less often than config.

## 7. API surface

All under the existing admin realm. Permission `platform:config` for §1's left column,
`platform:secrets` for the right — a new permission in `core/rbac.py`, not a reuse of
`admin:tenants`, because the blast radii are not comparable.

| Route | Permission | Notes |
|---|---|---|
| `GET /v1/ops/config` | `platform:config` | every key: current value, source (`env`/`db`/`default`), who set it, when |
| `PUT /v1/ops/config/{key}` | `platform:config` | validated against the `Settings` model before it is stored; a value the app would reject is refused at the boundary, not at the next boot |
| `DELETE /v1/ops/config/{key}` | `platform:config` | revert to code default |
| `GET /v1/ops/secrets` | `platform:secrets` | key, `last_four`, version, who, when, `kek_version`. **No plaintext, ever, on any route.** |
| `PUT /v1/ops/secrets/{key}` | `platform:secrets` | new version; step-up `X-Confirm-Action: set_secret:<key>` |
| `POST /v1/ops/secrets/{key}/test` | `platform:secrets` | **dry-run against the vendor** before the value goes live — see below |
| `POST /v1/ops/kek/rewrap` | superadmin | KEK rotation: re-wrap every DEK under the new KEK |

**There is no read-back route and there will not be one.** A console that can display a
credential is a console that leaks every credential through one screenshot or one
compromised session. If an operator needs the value, they hold it already — they are the
one who set it.

**`/test` is the feature that makes this safe to use.** Setting a wrong key today fails
silently until a call drops. The test route asks the vendor a cheap authenticated
question with the *candidate* value before storing it, and reports our own reason code.
Wrong key, refused at the screen, is the difference between this console being a
convenience and being a new outage source.

> ⚠ **AMENDED BY D-101.** Three things on this page are now stale and the code is right:
> the `PUT` is **conditional** — `If-Match` is required (428 without it, 412 when the
> value moved, carrying the current value and who set it), and an identical value is a
> true no-op with no sentinel bump and no audit row; `GET` also returns each key's `etag`
> and a `bootstrap` array naming the keys that can only change with an SSH session and a
> restart; and `applies` has **five** values, not two — `live`, `on_restart`,
> `needs_republish`, `env_only`, `unclassified`. §6's "secrets are cached with a shorter
> TTL of their own" was superseded by D-97: they ride the same sentinel, so a rotation
> propagates on the same poll as a config change.

## 8. The console

`admin.calevate.tech/ops` gains panels beside the existing ones (outbox replay, DLQ depth,
spend-cap recompute, audit-chain verify):

1. **Engine** — which adapter is live (`bolna` / `cartesia` / `fake`), its capability
   descriptor rendered from the API rather than hard-coded, and its credential status.
   This is the panel that makes the D-94 orchestrator switch a screen action.
2. **Core config** — grouped, each row showing value, source, who, when. A value coming
   from `env` is shown as **read-only with the reason**, because the DB cannot override it
   and a field that silently does nothing is worse than no field.
3. **Secrets** — key, last-4, version, who, when. Set (write-only), test, rotate.
4. **Key management** — KEK version, how many DEKs are wrapped under each, and the rewrap
   action with its progress.

Every destructive or credential-touching action follows the repo's existing step-up
pattern (`X-Confirm-Action`), and every one writes `audit_log` in the same transaction as
the change — money's rule, applied to credentials.

## 9. Audit

Every write records: actor, key name, action, old version → new version, source, IP, and
the operator's stated reason. It records **no value and no fragment beyond `last_four`**.

The audit rows land in the existing hash-chained `audit_log`, so "who changed the Bolna
key on the day the margin moved" is answerable and tamper-evident. New action names:
`platform.config_set`, `platform.config_reverted`, `platform.secret_set`,
`platform.secret_tested`, `platform.kek_rewrapped`.

## 10. The trade, stated plainly

**Today, stealing every vendor credential requires VPS access. After this, one
compromised admin session is enough.** That is a real reduction in security, bought with
real operational convenience, and it should be made knowingly rather than discovered.

Accepted because the mitigations are already in place and are not hypothetical:

- admin realm MFA is mandatory for every admin token (D-68);
- `platform:secrets` is a distinct permission, held by fewer people than `admin:tenants`;
- no route returns plaintext, so a session gives write access, not read access — an
  attacker can break the system but cannot quietly exfiltrate the keys;
- every write is audited into a hash-chained ledger;
- `env` still overrides the database, so an operator with VPS access can always take
  control back from a compromised console.

**Residual risk, unmitigated and recorded:** an attacker with an admin session can
*replace* a vendor key with one they control — e.g. pointing our engine at their own
account. The `/test` route makes that easier to do convincingly. Detection, not
prevention, is the answer: the audit row plus an alert on every `platform.secret_set` in
production.

## 11. Its twin: per-tenant credentials

The Meta Lead Ads slice needs a Page access token **per tenant** — the same problem one
level down. It must not grow a second mechanism. The rule: **`platform_secrets` is the
crypto implementation; a tenant-scoped `tenant_secrets` table reuses the same envelope
module, the same KEK, and the same append-only doctrine, and adds `tenant_id` + FORCEd
RLS.** Two tables because the access rules genuinely differ; one encryption module,
because two ways to encrypt a secret is how one of them ends up wrong.

## 12. Guardrails that must change

- **`check_env_parity`** compares `.env.example` against code reads. It must learn the
  new source of truth: a key managed in the console is *declared* there, not missing.
  Without this, the guardrail fails the day the first key moves — and the temptation
  would be to weaken it.
- **New guardrail: `check_bootstrap_keys`** — the §4 list may only be read from the
  environment. A future change that lets `APP_ENV` resolve from the database must fail
  CI, loudly, because that is a security-posture inversion that would look like a
  refactor.
- **`check_ledger_immutability`** picks up `platform_secrets` automatically once its
  trigger exists — verify it does rather than assuming.
- **`check_rls_coverage`** needs both new tables in its exempt-with-reason list, and the
  reason must say *platform-scoped, admin realm only*.

## 13. Build order

Each phase is independently shippable and independently useful. No phase leaves a
half-wired seam.

| Phase | What lands | Done when |
|---|---|---|
| **1** | envelope module (`core/envelope.py`), `PLATFORM_KEK` resolution reusing D-86's ladder, unit tests incl. wrong-key, short-key, tampered-ciphertext | encrypt/decrypt round-trips and every failure mode refuses by name |
| **2** | `platform_settings` + version sentinel + resolution order + the cached snapshot with sentinel polling | a value changed in psql reaches all four processes in <10s with no restart |
| **3** | config routes + the ops console config panel | an operator changes a calling window from the screen |
| **4** | `platform_secrets` + append-only trigger + secret routes + `/test` | a wrong key is refused at the screen, not at the next call |
| **5** | KEK rotation + rewrap + the key-management panel | a rotation completes and every old DEK is re-wrapped, verified by a test |
| **6** | guardrail changes (§12) + `.env.example` reduced to the bootstrap 6 + DEPLOYMENT and DEV-SETUP updated | `make guardrails` green with the new source of truth |

## 14. Open questions, honestly listed

1. **Where does `PLATFORM_KEK` itself come from on a fresh VPS?** Today: generated once
   and pasted into `.env` by the operator. That is acceptable and is what the backup
   runbook already assumes for the age identity — but it means the KEK is in the same
   backup-and-restore story as the `age` key, and §13 phase 1 should say so.
2. **Does a KEK rotation need the app quiesced?** Re-wrapping is a write per secret
   version. Almost certainly not, with a version column and read-old/write-new — but it
   is a money-adjacent concurrency question and gets a CAS, not a hope.
3. **Should `AUDIT_CHAIN_SECRET` move into the store?** It is the one credential whose
   compromise undermines the audit of the store itself. Leaning **no** — keep it in the
   bootstrap set. Decide before phase 4.
4. **Alerting on `platform.secret_set` in production** — which sink, and does it page?
   §10's residual risk rests on it, so it is not optional.
