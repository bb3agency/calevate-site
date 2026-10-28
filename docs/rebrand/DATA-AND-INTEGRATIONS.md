# Rebrand: names held in data and at outside services

Companion to `docs/REBRAND-MAP.md`. This file covers only the names that a find-and-replace
over source files would not fix, or would break: values already written into Postgres, Redis,
object storage, job payloads, client spreadsheets, and the systems of ThinnestAI, Razorpay,
Meta, Google, Cashfree and Supermemory. Line numbers are against commit `6ef0c49e`.

How to read the last column:

- **Keep** — an internal label nobody outside sees, where renaming breaks stored data. The
  recommendation is to leave it as it is, permanently.
- **Dual-read** — the new name can be written from the switch onward, but readers must
  accept the old one for as long as objects carrying it can come back.
- **Switch at deploy** — no stored data depends on it beyond seconds-to-hours; rename in one
  deploy, with the stated precaution.
- **Free** — no stored or outside dependency.

Two corrections to `REBRAND-MAP.md` §2C come out of this read:

1. The ThinnestAI call metadata keys `calevate_call_id`, `calevate_lead_id` and
   `calevate_forwarding_leg` are **written and never read back** (no reader anywhere in
   `apps/` or `packages/`). Calls are matched by `reference`. They need no dual-read. The
   real ThinnestAI hazards are the idempotency prefixes during a retry, the workspace
   `externalId` lookup and the name-based agent lookups (§7).
2. The map does not list the cryptographic labels (§1), the Razorpay `notes` keys (§8), the
   Google Sheets key column header (§10), invoice serials (§14) or the stored consent
   wording (§14). Several of those are the most dangerous items in the whole rename.

---

## 1. Cryptographic domain labels (never rename)

These are HKDF `info` strings and hash domains. The string is an input to the key or the
hash, so a different string produces different bytes and every value stored under the old
one stops matching. None is visible to anyone.

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| `b"calevate/password-pepper/v1"` (`PEPPER_INFO`) | `apps/api/authn/hashing.py:153`, used `:252` | Derives the pepper every stored password hash is computed with | **Yes: every password hash** in the credentials table | **Keep.** Changing it makes every password fail to verify. A real change would be a new pepper generation with re-hash on next login, which buys nothing here |
| `b"calevate/auth-code-key/v1"` (`CODE_KEY_INFO`) | `apps/api/authn/codes.py:74`, used `:98` | Key for hashing emailed codes and email tokens | Yes: outstanding OTP challenges and email tokens (invites live 72 h, `authn/tokens.py:56`) | **Keep.** Renaming voids every open invite, reset link and code |
| `calevate/auth-otp/v1/{purpose}` | `apps/api/authn/otp.py:76` | Hash domain of stored OTP challenges | Yes, until each expires | **Keep** (same reason) |
| `calevate/auth-email-token/v1/{purpose}` | `apps/api/authn/tokens.py:79` | Hash domain of stored email tokens | Yes: password reset 1 h, email verify 24 h, invite 72 h | **Keep** |
| `b"calevate/auth-session/v1/"` (`_FINGERPRINT_DOMAIN`) | `apps/api/authn/sessions.py:151` | Hash domain of stored session fingerprints | Yes: every live session | **Keep.** Renaming signs every user out, on top of the cookie-name change in REBRAND-MAP §2C |
| `b"calevate/caller-memory-subject/v1"` (`CALLER_REF_INFO`) | `apps/api/compliance/caller_ref.py:102`, used `:193`, `:211` | Derives `caller_ref`, the key caller memory and caller retrieval chunks are filed under (`subject_ref_kek_id` columns, migration `c6b1f0d47e83:343,549`) | **Yes: every remembered caller** | **Keep.** Renaming orphans all caller memory, and an erasure would no longer find what is filed under the old ref: a DPDP erasure gap, not just lost data |
| `b"calevate/platform-kek-id/v1\x00"` | `apps/api/core/envelope.py:333` | Fingerprint stored as `kek_version` beside every sealed secret | Yes: every `platform_secrets`, client credential, webhook and action secret row | **Keep.** Decryption still works (the id is a hint, `envelope.py:448`), but every row would read as "not on the active key" in the ops console (`ops/secret_routes.py:560`) and the rewrap sweep would treat the whole store as stale |
| `b"calevate/engine-intake-kek-id/v1\x00"` | `apps/api/reliability/engine_intake_keys.py:77` | Same, for the engine-intake ring | Yes | **Keep** |
| `calevate:google-sign-in`, `b"calevate:google-sign-in:v1"` | `apps/api/authn/google.py:77-78` | Audience and KDF label of the signed Google sign-in state | Only states in flight (minutes) | Switch at deploy; a sign-in started across the deploy fails once and is retried |
| `calevate:{google-calendar,google-sheets,zoho-crm,hubspot}-oauth-state` (+ `:v1` KDF) | `apps/api/actions/oauth.py:149-162` | OAuth `state` sent to Google, Zoho, HubSpot | In-flight consent screens only | Switch at deploy |
| `calevate:whatsapp-signup-state` (+ `:v1`) | `apps/api/whatsapp/signup.py:77-78` | Embedded Signup state sent to Meta | In-flight only | Switch at deploy |
| `calevate:impersonation`, `calevate:copilot-proposal`, `calevate:admin-copilot-proposal`, `b"calevate:copilot-proposal:v1"` | `core/impersonation.py:130`, `copilot/write_tools.py:176,228`, `copilot/admin_actions.py:63` | Audiences of short-lived signed grants and proposals | Grants and proposals open at the moment of deploy | Switch at deploy; an open view-as grant or Pip proposal must be re-issued |
| `calevate/timing-equalisation/not-a-credential` | `apps/api/authn/hashing.py:171` | Dummy password for timing equalisation | No | Free (but pointless) |
| `calevate-local-dev-*` fallback seeds | `core/envelope.py:112`, `reliability/engine_intake_keys.py:49`, `local_fallback=` in `actions/oauth.py:247`, `authn/google.py:149`, `copilot/write_tools.py:274`, `core/impersonation.py:256`, `agents/trial_calls.py:137`, `forwarding/save_number.py:88`, `reliability/service.py:125` | Local development only | Local dev data only | Free; a local DB's sealed values become unreadable, so `make db-reset` after |

## 2. Postgres objects

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| Database `calevate` | `.env.example:64-65`, `.github/workflows/ci.yml:43-44`, `docker-compose.yml:34`, `infra/backup/walg.json.template:43`, `docs/DEPLOYMENT.md:1419` | Production database on the VPS | It is the database | **Keep** (REBRAND-MAP §2C). If ever done: `ALTER DATABASE … RENAME` needs no other session connected, so every service down; then every DSN, `walg.json` `PGDATABASE`, restore drill and backup scripts |
| Owner role `calevate` | `.env.example:65`, `ci.yml:44`, `docs/DEPLOYMENT.md:1419`, `scripts/dev_bootstrap.sh:46` | Runs migrations | Owns every object | **Keep.** `ALTER ROLE … RENAME` keeps ownership by OID, but clears an MD5 password (SCRAM survives), and the restore drill and docs name it |
| App role `calevate_app` | Created in migration `05bba2f3c19c:593-607` (grants), dropped in its downgrade `:707-721`, checked in `c5a9e34b71d0:110`; `apps/api/core/settings.py:83` (dev credential guard), `scripts/db_reset.py:71`, `scripts/dev_bootstrap.sh:23`, `scripts/restore_drill.py:1403,1573`, `scripts/check_deploy_env.py:296` | Every app connection | Grants and policies attach by OID | **Keep.** Rename would leave 20 migrations creating and granting the old name on every fresh database (CI, restore drill), so a fresh chain and production would disagree |
| Trigger functions `calevate_forbid_mutation`, `calevate_forbid_truncate`, `calevate_forbid_slug_change`, `calevate_preference_scrub_append_only`, `calevate_credit_lot_terms_frozen`, `calevate_platform_ai_usage_append_only`, `calevate_deletion_request_subject_ref` | `05bba2f3c19c:549,567`, `a1c8e40f27b9:290`, `c9f3a71e58d2:101`, `e5c9a2d71f38:72`, `f4a8e1c07b62:169`, plus ~50 later migrations attaching them | Postgres functions behind hard rule 4's ledger triggers | Yes, they are the live triggers | **Keep.** `check_ledger_immutability` matches on behaviour, not name (`scripts/check_ledger_immutability.py:410`), so a rename is possible, but it would be a migration that replaces trigger functions on every append-only table: high risk, zero benefit |
| Column `forwarded_lines.calevate_number_id` and FK `fk_forwarded_lines_calevate_number_id_phone_numbers` | `alembic/versions/d6f2b8a41c73_forwarded_lines.py:116,160`; `apps/api/forwarding/models.py:100`; raw SQL `forwarding/service.py:180,183,332,391`, `copilot/account_actions.py:435` | Column, and API field `calevate_number_id` / `calevate_number_e164` / `calevate_numbers` (`forwarding/schemas.py:34-75`) read by the web client | Yes, every forwarded line | Optional. If renamed: migration `ALTER TABLE … RENAME COLUMN` + FK rename in one release (raw SQL strings move with it), and the API field rename is a contract change regenerated into `apps/web/src/lib/api`. Hard rule 8 (two-step) does not bite a rename done in one migration, but every raw SQL string must change in the same deploy |
| CHECK `whatsapp_templates.origin IN ('calevate','client')` | Migration `c8e5a2f7d914:49,202`; `apps/api/whatsapp/models.py:37,124`; written `whatsapp/templates.py:362` | Column value on every template row we install | **Yes**: every standard template row has `origin = 'calevate'` | **Keep** the stored value (it means "ours", nobody sees it). If renamed: one migration that widens the CHECK, `UPDATE`s rows, then narrows the CHECK, with the code constant moved in the same release |
| Dev/drill database names `calevate_drill_*`, `calevate_wt*`, `calevate_bal_big` | `scripts/restore_drill.py`, `Makefile:487`, migration docstrings | Throwaway databases | No | Free |

## 3. Seeded rows and settings that hold the name

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| Reserved slug `calevate` | `scripts/seed.py:54` | `reserved_slugs` table | Yes | **Add** the new name to `RESERVED_SLUGS` and re-run the (idempotent) seed; **keep** `calevate` reserved. Before choosing the name, check no `organizations.slug` already equals it |
| Password blocklist words `{"calevate", "calevate.tech"}` | `apps/api/authn/policy.py:126` | In code; applied at password set | No | Add the new name and domain; keep the old ones |
| `notifications_from` default `support@calevate.tech` | `packages/shared/src/calevate_shared/config.py:1335` | Console-managed, LIVE (`core/platform_config.py:340`); From address of every email via Resend | A `platform_settings` row may hold an override | Change in the ops console once the new domain is verified at Resend; then change the default |
| `notifications_reply_to` default `calevate.voice@gmail.com` | `config.py:1353` | Console-managed, LIVE (`platform_config.py:341`); Reply-To on every email | Possible override row; **the mailbox itself is an outside account named after the brand** | Create the new reply-to mailbox, set it in the console, keep the Gmail account forwarding for a year |
| `webhook_base_url` | `config.py:395` | Console-managed; the URL ThinnestAI posts to (see §7) | Override row | Console, in the domain step (REBRAND-MAP §2B) |
| WhatsApp template names on our own account: `calevate_hot_lead_v1`, `calevate_alarm_page_v1`, `calevate_line_notice_v1`, `calevate_line_restored_v1` | `config.py:1412-1419`; LIVE settings `platform_config.py:361-366` | Name sent to Meta on every send; must equal an approved template | Possible override rows; the approved templates at Meta | See §9 |
| No migration or seed inserts brand text into a data row | checked: `alembic/` (155 hits are docstrings, role/trigger names, the CHECK above) and `scripts/seed.py` (only the reserved slug); vertical templates and spoken style carry no brand (`spoken_style.json` mentions only a module path) | — | — | Nothing to do |
| Operator sign-in emails on the brand domain (e.g. `ops@calevate.tech`, mentioned at migration `b3d9f6a2c815:178`) | Admin user rows | Email is the sign-in identity and the step-up code destination | Yes, if operators use `@calevate.tech` addresses | Create the new mailboxes first, change each operator's email through the console flow, keep the old mailboxes forwarding |

## 4. Redis keys

Production Redis lives in the compose volume `calevate_redis-data` (`compose.prod.yml:24,96,252`).
A rename of these prefixes leaves the old keys to expire; the question is what is lost in the
gap and whether old and new processes overlap during a deploy.

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| `calevate:campaign_dispatch:tick` (tick lease) | `apps/workers/campaign_dispatch.py:203` | Lease that makes only one worker dispatch | Live lease | Switch at deploy **with old workers stopped before new ones start**: two processes holding two different lease keys both dispatch, i.e. double dials |
| `calevate:byok-check:{workspace}` (lease) | `apps/workers/engine_workspace_events.py:80` | Lease | Live lease | Same: no overlap of old and new workers |
| `calevate:fleet-walk:{walk}`, `calevate:workspace-walk:{sweep}`, `calevate:set-aside:{sweep}` | `workers/fleet_walk.py:173`, `workers/workspace_walk.py:32`, `workers/set_aside.py:29` | Sweep cursors | Yes | Switch at deploy; sweeps restart from the beginning once |
| `calevate:platform_config_version` | `apps/api/core/platform_config.py:106` | Cross-process sentinel that tells every process to reload console settings | Yes | Switch at deploy with all processes restarted together; a mixed fleet would not see each other's config changes |
| `calevate:platform_state` | `core/loadshed.py:143` | Cached big-red-switch / platform state | Yes | Switch at deploy; first read repopulates |
| `calevate:live:` (pub/sub channel prefix) | `apps/api/live/topics.py:298` | Live dashboard updates between processes | Transient | Switch at deploy; all processes together |
| `calevate:rl` (rate limits), `calevate:authn:fail` (login throttle) | `core/ratelimit.py:59`, `authn/throttle.py:78` | Counters | Yes | Switch at deploy. Every counter resets, which gives an attacker a fresh login-guess budget once; acceptable, or read both prefixes for one throttle window |
| `calevate:stepup-proof` | `authn/stepup.py:167` | Step-up proofs | Live proofs (minutes) | Switch at deploy; an operator mid-step-up confirms again |
| `calevate:copilot:proposal:used:{jti}` | `copilot/write_tools.py:210` | One-use record for Pip proposals | Yes, for the proposal TTL | Switch at deploy together with the audience in §1, so a proposal signed before the deploy fails rather than being replayable |
| `calevate:adminread:seen:*`, `calevate:imp:seen:*` | `core/auth.py:551,601` | "Already audited" markers | Yes | Switch at deploy; one extra audit row per open session |
| `calevate:wh:{engine}:…` | `apps/voice-runtime/webhook_routes.py:735,875` | Fast-path webhook dedupe | Yes | Switch at deploy; the database inbox is the real dedupe, the fast path just misses once |
| `calevate:engine:dial_backoff`, `calevate:copilot:fair-use:alerted:*`, `calevate:copilot:answering:*`, `calevate:own_model_setup_failures`, `calevate:own_model_prompt_basis`, `calevate:own_model_cache_share`, `calevate:voice-preview`, `calevate:fx:last_check` | `engine/dial_lines.py:106`, `copilot/fair_use.py:45`, `copilot/live_sync.py:47`, `agents/own_model.py:458`, `billing/own_model_prompt.py:94`, `ops/own_model_cache.py:41`, `agents/voice_tuning.py:121`, `ops/fx_rates.py:290` | Caches, counters, alert de-duplication | Yes | Switch at deploy; at worst one repeated alert or a recomputed cache |
| ARQ queue, job ids, retrieval cache | `apps/api/core/health.py:70` (`arq:queue`), `core/queue.py:82`, `retrieval/cache.py:88` | — | — | **No brand.** Nothing to do |

## 5. Job payloads

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| `_calevate_traceparent` (`TRACE_KWARG`) | `apps/api/core/observability.py:276`, added `:797-798`, popped `:658` | A kwarg inside every traced ARQ job in Redis | **Yes: every queued, deferred and retrying job** | **Dual-read** if renamed: pop both names in `traced_job` for at least the longest job deferral, then drop the old. A job carrying a name the worker does not pop reaches the job function as an unexpected kwarg and fails. Simplest: keep |

## 6. Object storage and backups

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| Main bucket `calevate-call-recordings` | Value of `OBJECT_STORE_BUCKET` / console `object_store_bucket` (LIVE, `core/platform_config.py:326`); named in `docs/DEPLOYMENT.md:107` | Cloudflare R2; every recording, raw payload, KB upload, voice preview and consent, KYC document | Yes, all of it | **Keep.** A bucket cannot be renamed; a new one means copying every object and a switchover. Object keys carry no brand (`apps/workers/storage.py:246,270,687,846,892,934,1433`), so the bucket name is the only brand |
| Pip uploads bucket | `copilot_upload_bucket` (LIVE, `platform_config.py:328`) | R2 | Yes | Keep (same) |
| Backup bucket `calevate-db-backups` | REBRAND-MAP §2C; `WALG_S3_PREFIX` is a secret ref (`infra/backup/walg.json.template:13`) | R2, wal-g chain | Yes: the whole backup chain | **Keep.** A new bucket means a new base backup and keeping the old chain readable for its retention window |
| Offsite rclone remote `calevate-offsite:calevate-dr` and dump names `calevate-<stamp>.dump.age` | `infra/backup/systemd/calevate-dump-offsite.service:17`, `scripts/backup/dump-offsite.sh:33,61,112-137` | Offsite provider (D-927 retired this path) | Old dumps, if any remain | Keep or retire with the unit |
| Dev/CI buckets `calevate-dev`, `calevate-ci` | `.env.example:105`, `.github/workflows/ci.yml:47` | Local MinIO, CI | Local only | Free |

## 7. ThinnestAI

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| Customer workspace `externalId` `calevate-{tenant_id}` | `apps/api/tenancy/engine_workspace.py:62`; stored `tenant_engine_workspaces.external_ref` (`engine_workspace.py:173`, migration `d93b6f2a4c18:83,135`) | Sent as `externalId` on `POST /customers` and used for `GET /customers?externalId=` | **Yes: every client workspace at ThinnestAI and every row** | **Keep.** Provisioning recomputes the ref from the function, not from the stored column (`apps/workers/engine_workspaces.py:210-232`), so a new prefix would not find an existing, archived or half-made workspace and would create a second one (a paid workspace slot). If it must change: make provisioning read the stored `external_ref`, and only new tenants get the new prefix |
| Idempotency keys `calevate-call-`, `calevate-customer-`, `calevate-fwd-`, `calevate-rent-` | `engine/thinnest.py:3405,2771`, `engine/thinnest_customers.py:203`, `engine/thinnest_numbers.py:433` | `Idempotency-Key` header on place-call, create-customer, forwarding test, rent-number | Held at the vendor for its replay window | Switch at deploy **with no retries in flight**: a retry that crosses the deploy under a new key places a second call or rents a second number. Drain campaign dispatch and the outbox first, or keep the prefixes |
| Call metadata `calevate_call_id`, `calevate_lead_id`, `calevate_forwarding_leg` | `engine/thinnest.py:3395,2761` | `metadata` on calls at ThinnestAI | Yes, on old calls | **Free.** Nothing reads them back (see the correction at the top) |
| Trial-line agent name `Calevate shared trial number (no answer)` | `apps/api/engine/trial_line.py:16`; looked up **by name** `engine/thinnest.py:2577`, created `:2618` | Agent in our developer workspace | Yes: the live agent the shared trial number points at | **Dual-read.** A new name finds nothing and creates a second agent, while the trial number stays on the old one. Look up both names (adopt and rename the old agent with a PATCH), or keep. This name is also what a caller's phone provider may show nowhere, so keeping costs nothing |
| Forwarding-test agent names `Calevate forwarding test, line 1/2 (automated)` | `apps/api/engine/forwarding_probe.py:19-22`; looked up by name `engine/thinnest.py:2710-2733` | Agents in the developer workspace | Yes | Same as the trial line: dual-read or keep; a rename leaves two orphan agents counting against the 100-agent developer cap |
| DNC reason `Opted out with this business (Calevate do-not-call list)` | `apps/api/engine/thinnest_customer_data.py:54` | Reason on every DNC entry pushed to a client workspace | Yes, on existing entries | Change the constant; old entries keep the old text. Nothing reads it back. Visible to anyone viewing the vendor console, not to clients |
| Customer workspace `name` | `engine/thinnest_customers.py:205` (the client's business name) | ThinnestAI | — | No brand |
| Webhook endpoints at `hooks.calevate.tech` | `reliability/engine_webhooks.py:204-213` | One endpoint per agent at ThinnestAI | Yes, per agent | Domain step: registration deletes only endpoints at **the current** URL, so after `webhook_base_url` changes, endpoints at the old host are not cleaned up and keep delivering to the old host. Keep the old host serving voice-runtime until every agent is re-registered, and add a cleanup for the old URL |

## 8. Razorpay

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| `notes.calevate_tenant_id` | `apps/api/billing/payments.py:201`; written `payment_routes.py:828`, `payments.py:2079`, `auto_recharge.py:392,396,722`, `platform_fee_routes.py:248`; **read** `payment_events.py:105`, `payments.py:1070-1074,1448,2155`, `reconciliation.py:71` | `notes` on every order, customer, mandate and refund at Razorpay; webhooks return it | **Yes: every payment object ever created** | **Dual-read, indefinitely.** Refunds, disputes and late captures on an old payment arrive months later carrying the old key; that key is how the tenant is found. Write the new key, read new-then-old. Simplest: keep the key (clients never see `notes`) |
| `notes.calevate_pack_id` | `payments.py:206`, read `:1095`, `reconciliation.py:177` | Same | Yes | Dual-read, or keep |
| `notes.calevate_platform_fee_charge_id` | `billing/platform_fee.py:56`, `platform_fee_routes.py:248` | Same | Yes | Dual-read, or keep |
| `notes.calevate_purpose` | `billing/auto_recharge.py:392,722` | Same | Yes | Written only, never read: free |
| Receipt prefixes `clv_`, `clvm_`, `clva_`, `clvfee` | `payments.py:251,662`, `auto_recharge.py:399,724`, `platform_fee_routes.py:166` | `receipt` on orders; `clv_…` is also the `idempotency_records` key and the reference a client quotes on a bank transfer (`payments.py:609-614`) | Yes, on old orders and old transfer references | Free for new orders (nothing parses the prefix), but an old `clv_` reference a client quotes must still be recognised by whoever reconciles bank transfers. Optional: "clv" is an abbreviation, not the name |
| `User-Agent: Calevate/1.0 (+https://calevate.tech)` | `payments.py:243`, used `:736`, `razorpay_api.py:177` | Every Razorpay API call | No | Free |
| Checkout `name: "Calevate"` | `apps/web/src/lib/razorpayCheckout.ts:282` | Shown in the Razorpay payment window | No | Free; change with the visible name (and the Razorpay dashboard business name, REBRAND-MAP §3) |

## 9. Meta / WhatsApp

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| Standard templates in **each client's** WABA: `calevate_booking_confirmed`, `calevate_details_you_asked_for`, `calevate_payment_link`, `calevate_call_back_time` | `apps/api/whatsapp/templates.py:74,93,113,135`, installed `:348-366` | Submitted to Meta per client; row per template in `whatsapp_templates` (unique on account+name+language, migration `c8e5a2f7d914:223-227`) | **Yes: approved templates at Meta and rows** | New names only apply to new installs. For existing accounts: insert and submit the new-named templates, wait for Meta approval, switch sends to them, then delete the old ones at Meta. The bodies carry no brand, so keeping the names is also acceptable (clients see template names in WhatsApp Manager) |
| Templates on **our own** WABA: `calevate_hot_lead_v1`, `calevate_alarm_page_v1`, `calevate_line_notice_v1`, `calevate_line_restored_v1` (settings), `calevate_missed_call_follow_up_v1`, `calevate_save_our_number_v1`, `calevate_account_closed_v1` (constants) | `config.py:1412-1419`; `apps/workers/whatsapp.py:824`; `apps/api/forwarding/save_number.py:50`; `apps/workers/account_closure.py:428` | Name must match a Meta-approved template | Approved templates at Meta (some not yet submitted: `account_closure.py:420-427`) | Submit new names, wait for approval, then switch: the four settings in the console (LIVE), the three constants by deploy. Sending a name Meta has not approved fails every send |
| Opt-in wording `I agree that Calevate may send WhatsApp messages…` (`whatsapp-alerts-v1`) | `apps/api/compliance/whatsapp_optin.py:116-122` | `notice_version` stored on every opt-in row | Yes: granted rows name `whatsapp-alerts-v1` | Do not edit the v1 text: rows must keep evidencing what was shown. Add `whatsapp-alerts-v2` with the new name. Ask the lawyer whether consent given to "Calevate" covers messages from the renamed sender (new entity) or needs re-asking |
| WABA display name, Meta app name, business verification | outside the repo | Meta | — | REBRAND-MAP §3 |

## 10. Google, Zoho, HubSpot, Cashfree, Supermemory

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| Sheet key column header `Calevate call` | `apps/api/actions/sheets.py:38`; matched by header text `apps/api/actions/execution.py:934-949` | Header cell in each client's Google Sheet used by the sheet action | **Yes: every connected sheet** | **Dual-read.** The column is found by its header text. A new header makes the code add a second key column and stop updating rows written before the switch. Look up the old header first, fall back to the new one, never write a second column |
| Sheet delivery column `Calevate Delivery ID` | `apps/api/integrations/service.py:1566,1670` | Last column of every row the sheet integration appends | Yes, in clients' sheets | Free for appends (nothing reads it back today), but a renamed header misaligns with existing sheets' header row. Treat as dual-read if a reader is ever added; otherwise keep |
| Calendar event description `Booked on a phone call by your Calevate agent.` | `apps/api/actions/execution.py:832` | Each booking in the client's Google Calendar | Yes, old events | Free; old events keep the old text |
| Cashfree DigiLocker `verification_id` `clv-<hex>` | `apps/api/compliance/kyc_providers/cashfree.py:172` | Cashfree; our run row stores it | Yes | Free: runs are looked up by the stored id |
| Zoho / HubSpot field names, lead source | `apps/api/actions/*` | — | — | **No brand** found in what we send |
| Supermemory metadata keys `calevate_source_label`, `calevate_source_id`, `calevate_agent_id`, `calevate_document_version` | `apps/api/retrieval/supermemory_wire.py:133-136` | Written into and read back from Supermemory records | Only if `retrieval_provider = "supermemory"` was ever used (default `compiled-facts`, `config.py:979`) | Dual-read if any records exist; otherwise free |
| LLM structured-output schema names `calevate_call_extraction`, `calevate_business_copy`, `calevate_business_type`, `calevate_script_draft` | `apps/workers/extraction.py:560`, `workers/business_copy.py:190`, `workers/business_type.py:80`, `workers/script_assist.py:918` | Sent to Azure/Gemini/Sarvam as the JSON-schema name | No | Free |
| Azure OpenAI resource name | console `azure_openai_resource` (`platform_config.py:450`) | Part of the endpoint host | UNKNOWN: the production value is not in the repo | If it contains the brand, keep it (an Azure resource cannot be renamed) |
| KB PDF file name `calevate-kb-<id>.pdf` | `packages/shared/src/calevate_shared/engine.py:5737` (Bolna only, engine removed) | — | — | Free |

## 11. Email (Resend) and operator alerts

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| From / Reply-To | §3 | Every email | — | §3 |
| Subjects naming the product (`Your Calevate sign-in code`, etc.) | `apps/workers/email_render.py:172-179`, `account_closure.py:95-97`, `comp_notices.py:81-115`, `rate_card_notice.py:101`, `razorpay_jobs.py:129-130`, `maintenance.py:120-123` | Email | Sent mail only | Free (visible text, REBRAND-MAP §2A). Tell support to expect both names in mailbox searches |
| Operator alert subject `[Calevate {severity}] …` and tag `calevate/{env}/{service}` | `apps/api/core/alerting.py:778`, `core/alert_email.py:78` | Alert emails to ops | Sent mail | Free, but **update any mailbox filter or forwarding rule that matches `[Calevate`**, or alerts land unsorted |
| Backup alert relay `/etc/calevate/alerts.env` | `infra/backup/systemd/*.service` | Host file with SMTP settings | Yes, on the VPS | Host step, REBRAND-MAP §2C |

## 12. Logs, metrics, traces, headers

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| OTel `service.name = calevate-{service}`, tracer `calevate` | `apps/api/core/observability.py:967,992` | Trace backend | Yes, historic traces | Switch at deploy; update saved queries/dashboards in the trace backend, or history and new data split |
| Logger names `calevate.alert`, `calevate.metric`, `calevate.provider_health`, `calevate.billing.cost_unit` | `core/alerting.py:120-121`, `core/alert_admission.py:110`, `core/alert_records.py:64`, `core/provider_health.py:53`, `billing/cost_unit.py:56` | Log records | Historic logs | Switch at deploy; update any log search or alert rule that filters on the logger name (`grep metric=` style searches, `alerting.py:872`) |
| Syslog tags `calevate.backup`, `calevate.alert` | `scripts/backup/backup-health.sh:343-376`, `basebackup.sh:75`, `notify.sh:59-97` | journald on the VPS | Historic journal | Free in code (nothing in the repo reads by tag); update any operator habit of `journalctl -t calevate.backup` |
| Backup state stamps `.calevate-wal-verify-stamp`, `.calevate-health-heartbeat`, `.calevate-heartbeat-state`, `.calevate-dump-size` | `scripts/backup/backup-health.sh:76-81`, `dump-offsite.sh:43` | Files on the VPS | **Yes** | Rename the files in the same step as the script change, or the health check reads "never ran" and alerts (or loses its staleness clock) |
| Sentry | `core/observability.py:1417-1489` | Tags carry `service` only | — | No brand in code; project name is outside (REBRAND-MAP §3) |
| `User-Agent: calevate-backup-heartbeat` | `scripts/host_heartbeat.py:196` | Healthchecks | No | Free |
| Webhook `User-Agent: Calevate-Webhooks/1` | `apps/api/integrations/service.py:1335` | Clients' webhook receivers | No, but receivers may allow-list it | See §13 |
| `x-calevate-permission` OpenAPI extension | `apps/api/core/rbac.py:864,933`; read by `scripts/check_openapi_fresh.py:93`, `check_public_routes.py:690`, `check_redaction_exposure.py:513,597` | Generated `apps/web/src/lib/api/openapi.json` | Snapshot file | Free; rename everywhere at once and regenerate the snapshot (`check_openapi_fresh` will demand it) |
| Test-only headers `X-Calevate-Fake-Signature`, `x-calevate-kyc-signature` | `engine/fake.py:424`, `compliance/kyc_providers/fake.py:50` | Fakes only | No | Free |

## 13. Outbound webhooks to clients' systems

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| `X-Calevate-Signature`, `X-Calevate-Timestamp`, `X-Calevate-Event`, `X-Calevate-Delivery` | `apps/api/integrations/service.py:217-220`; documented to clients `apps/web/src/app/c/[slug]/integrations/AddDestinationDrawer.tsx:74` and marketing mockups | Headers on every webhook delivery; the client's receiver verifies the signature header by name | No stored data, but **every client receiver is coded against these names** | Pre-launch with no signed clients, a straight rename is fine. Once any client has a receiver: send both header sets for a deprecation period, announce, then drop the old |

## 14. Generated documents and stored wording

| Name/value | Where (file:line) | Stored/sent where | Existing data carries it? | How to rename safely |
|---|---|---|---|---|
| Invoice serial prefix `CAL` | `apps/api/billing/invoice.py:610` | Printed invoice/bill-of-supply number, derived (not stored) from period + tenant | Derived on every render | Invoices are **built on demand, not stored** (`invoice.py:1-6`): changing `CAL`, the supplier settings (`gst_supplier_*`, `config.py:1876+`) or `GST_STATUS_SENTENCE` (`billing/gst.py:84-87`) **re-renders every past month with the new number and new entity**. Past documents must stay as issued (REBRAND-MAP §4). Before the switch, make supplier identity and the serial prefix effective-dated by billing month (old entity for months before the switch), or store issued documents |
| Erasure certificate wording ("Calevate's erasure…", "Calevate holds no account…") | `apps/api/compliance/deletion.py:421-875`, `compliance/tenant_erasure.py:190-432`; version `deletion_proof.notice_version` hashes the text (`deletion_proof.py:128`) | Certificate rendered on request from the stored proof (`deletion_proof.py:144`) | The stored proof has no wording; the wording is re-rendered | Changing the text re-renders old certificates with the new name and a new `notice_version`. Acceptable if the new entity is the successor; otherwise keep a frozen copy of the pre-switch register for old certificates. Ask the lawyer which |
| Outbound pledge text (names "Calevate's AI voice agent…") | `apps/api/compliance/outbound_pledge.py:37-56` | `outbound_pledge_acceptances.version` + `text_sha256` (migration `a7c3e91d5f20:231`) | Yes | Changing the text is a new `PLEDGE_VERSION`, and every account then shows "pledge outdated" and **outbound stops until the owner re-accepts** (`outbound_pledge.py:122`). Do it together with the legal re-acceptance (REBRAND-MAP §4), and keep the v2 text producible somewhere, since rows evidence it |
| Legal acceptance statement (provisional wording names Calevate) | `apps/api/legal/statements.py:54-61` | `statement_version` on acceptance rows | Yes | Do not edit the existing wording (the module exists so it stays producible); the reviewed statement carries no brand |
| Voice-clone consent scope `Calls made by Calevate clients' agents.` | `apps/api/agents/hosted_voices.py:648` | Recorded on every clone consent record (D-721) | Yes | Do not rewrite existing records. A consent scoped to "Calevate clients" given to the old enterprise may not cover the new entity: lawyer's question; a new scope string applies to new consents only |
| Pip consent | `copilot_consents.text_sha256` (migration `b4d7e2a9c815:45`) | Hash of the text shown | Yes | Same rule: new wording, new version; old rows keep naming the old |
| CSV download names `calevate-transactions-<date>.csv`, `calevate-contacts-sample.csv` | `apps/web/src/app/c/[slug]/billing/TransactionsTab.tsx:55`, `campaigns/ContactEditor.tsx:144` | Files on clients' machines | Old downloads only | Free |

## 15. Names held in browsers

Covered by REBRAND-MAP §2C; listed here because they are data on users' devices and are
named in the cookie policy (`apps/web/src/lib/legal/cookies.ts`), which must change in the
same release.

| Name/value | Where (file:line) | Existing data carries it? | How to rename safely |
|---|---|---|---|
| Cookies `__Host-calevate_admin_session`, `__Host-calevate_client_session`, `__Host-calevate_google_signin` | `apps/api/authn/cookies.py:162-163`, `authn/google.py:76` | Yes | Renaming signs everyone out once; or accept both names for one session lifetime |
| Storage keys `calevate.oauth.start`, `calevate.oauth.return`, `calevate.google-invite`, `calevate.pip.attachNotice`, `calevate.kyc.pendingRun`, `calevate:view-as-grant:*`, `calevate.authn.had-session.*`, event `calevate:desktop-alerts` | `apps/web/src/app/c/[slug]/integrations/oauthReturn.ts:21-22`, `lib/authn/clientAuthn.ts:124`, `lib/copilot/attachments.ts:372`, `lib/desktopAlerts.ts:27`, `lib/legal/cookies.ts:31` and the files that define the other prefixes | Yes | Free; a user mid-OAuth or mid-KYC at the deploy restarts that step |

## 16. In-process names with no stored or outside dependency

Free to rename in the code pass: `calevate_principal`, `calevate_tenant_quota_charged`
(`core/auth.py:824,923`), `calevate_permission`, `calevate_realm` (`core/rbac.py:745-746`),
`calevate_tenant_id` connection-info key and ContextVars (`db/session.py:40,205,518`,
`core/settings.py:419`, `core/fx.py:165`), `_calevate_traced`, `calevate_db_spans`
(`core/observability.py`), `calevate_live_*` (`live/capture.py:51-53`),
`calevate.feature_flag_overrides` (`flags/service.py:84`), thread name `calevate-alerts`
(`core/alerting.py:530`), API enum value `"calevate"` for `actor` / `waiting_on`
(`legal/readiness.py:78`, `admin/health.py:224`, `admin/account_routes.py:102`) and
`blocked_on_calevate` (`admin/account_routes.py:115`), `calevate_tm_id` / `calevate_tm_active`
(`compliance/registration_routes.py:102-107`), error codes `phone_forwards_to_calevate`,
`forwarding_needs_calevate_number`, `forwarding_number_is_calevate` (`forwarding/service.py`).
The API ones are contract changes: regenerate the web client in the same change.

---

## Renames that need a migration, a dual-read period, or an ordered switch

In the order they should be done, if they are done at all. Items marked **keep** are the
recommendation; the rest are safe only as described.

1. **Before choosing the name:** check no tenant slug equals it; add it to `reserved_slugs`
   (seed) and `SERVICE_WORDS`. Keep `calevate` in both.
2. **Never rename** (§1): the password pepper, code key, OTP/token/session domains, caller-ref
   label and both KEK-id fingerprints. These are invisible; renaming any of them invalidates
   stored hashes, signs users out, or orphans caller memory and weakens erasure.
3. **Invoices and generated documents** (§14): make supplier identity, `GST_STATUS_SENTENCE`
   and the `CAL` serial prefix effective-dated by billing month **before** the switch, so past
   months re-render as issued. Needs a lawyer/accountant answer on the new number series.
4. **Stored consent and pledge wording** (§9, §14): new versions alongside the old, never edits
   in place; the pledge re-acceptance stops outbound until accepted, so it rides with the legal
   re-acceptance.
5. **Razorpay `notes` keys** (§8): dual-read (new, then old) with no end date, or keep.
6. **Google Sheets key header** `Calevate call` (§10): dual-read the header, or keep.
7. **ThinnestAI by-name agents** (§7): trial line and two forwarding-test agents: adopt the old
   agent under the new name, or keep. **Workspace `externalId`**: keep; if changed, provisioning
   must read the stored `external_ref` first.
8. **Job kwarg `_calevate_traceparent`** (§5): pop both names for one full deferral window, or
   keep.
9. **WhatsApp templates** (§9): submit new names, wait for Meta approval in every WABA, then
   switch settings/constants, then delete old.
10. **Redis prefixes** (§4): one deploy, with old workers stopped before new ones start
    (leases), and no ThinnestAI retries in flight (idempotency prefixes, §7).
11. **Domain-bound vendor state** (§7 webhooks, §3 settings and operator emails): keep the old
    host serving voice-runtime until every agent's webhook is re-registered, and clean up
    endpoints at the old URL.
12. **Postgres column / CHECK value** (§2): only if wanted; one reversible migration each, with
    raw SQL and the API contract moved in the same release. Database, roles, trigger
    functions, buckets and the Redis volume: **keep**.
