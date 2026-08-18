# Audit — every claim this repository makes about itself

**Read-only pass, 17 August 2026.** Scope: the doc set (`docs/*.md`), the published legal
documents (`apps/web/src/lib/legal/**` served at `/legal/*`), the decision log (ROADMAP §6),
and the module docstrings that act as specifications — audited against the code, the
migrations, the infra templates and the tests. Nothing was fixed; nothing outside this file
was edited.

**Method.** Both sides of every finding were opened. Where a claim is mechanical it was
proved by a script or a grep rather than by reading (`check_docs_drift` passes: 149 command
claims, 164 decisions, 43 SEC-COMP §3 blocker names, 6 rate zones, 2 TTS rungs, 52
capability-constant sentences, 0 deferred mirrors). Two mechanical sweeps were run
specifically for this pass and are reported under "What was cleared": every HTTP path named
in prose resolved against a live router, and every backticked file path in the doc set was
existence-checked.

**Not re-reported.** A document that says a thing is *not* built, and it is not built, is
correct. `docs/LEGAL-SURFACE.md` §5 F-2, F-3, F-5, F-6, F-8, F-9, F-10 and
`docs/SECURITY-COMPLIANCE.md` §4's open retention question are all live, honestly stated,
and stay out of the list below except where the *framing around them* has since become
wrong (F-8 below).

**In flight, marked not settled.** A sibling session is removing Clerk. Every sentence in
the doc set that describes Clerk as the live auth mechanism (`docs/README.md:104`,
`docs/AGENTS.md:21`, `docs/SECURITY-COMPLIANCE.md` §"Two realms, two Clerk apps",
`docs/FLOWS.md` §2) is therefore **not assessed here**. Note also that
`docs/AUTH-MIGRATION.md` — named in the audit brief — **does not exist in this worktree and
nothing in the tree references it**; if it is the sibling's deliverable, that is expected,
but no doc currently points at it.

---

## Severity counts

| Severity | Count | Findings |
|---|---|---|
| HIGH | 2 | F-1, F-2 |
| MEDIUM | 6 | F-3, F-4, F-5, F-6, F-7, F-8 |
| LOW | 4 | F-9, F-10, F-11, F-12 |

Total: **12**.

---

## F-1 — The BRD instructs sales to make the exact data-residency claim the landing page was made to stop making · **HIGH**

**Doc:** `docs/BRD.md:141-142` — in the competitive-positioning section, listed as a
verifiable sales wedge against Outpero:

> **data may be processed outside India** (we are India-resident by design)

**Code / doc it contradicts:**
- `docs/DEPLOYMENT.md:13` — the site stack (web, api, workers **and the PostgreSQL holding
  every transcript, lead and phone number**) runs on a *"general-purpose VPS
  (Hetzner-class); India co-location is NOT required for it."*
- `docs/DEPLOYMENT.md:36` — object storage is Cloudflare R2, `AWS_REGION=auto`.
- `apps/web/src/app/page.tsx:49-66` — the identical sentence was **deliberately deleted**
  from the marketing page, with a fifteen-line comment explaining that nothing in the
  repository supports it, and `apps/web/tests/publicLanding.test.tsx:61-87` bans the shape
  from ever returning; only *"The AI runs on Indian endpoints"* survives, because
  `scripts/check_model_residency.py` enforces that one.

**Which is wrong:** the BRD. This is the same misrepresentation that `docs/LEGAL-SURFACE.md`
§5 F-1 rated a live Consumer Protection Act exposure. It was removed from the surface a
customer reads and left standing in the surface a **salesperson** reads — and the BRD tells
them it is *"the sharpest, most verifiable sales wedge"*, i.e. it is written to be said out
loud to a prospect. A promise made in a sales call is a contractual representation whether
or not the website repeats it.

**What would fix it:** narrow the parenthetical to the claim the build enforces — model
endpoints pinned to an Indian region, checkable by `check_model_residency.py` — and add the
same "the hosting region is undecided" sentence the landing-page comment carries. The
competitor half of the row (their data may leave India) is sourced and can stand; it is our
half that overclaims.

---

## F-2 — `docs/README.md` asserts an "India-resident data plane" that `docs/DEPLOYMENT.md` denies, inside the authoritative set · **HIGH**

**Doc:** `docs/README.md:105` — the one-line summary of the locked stack:

> a Hetzner-class VPS with an India-resident data plane (D-25 moved hosting off
> DigitalOcean; nothing is provisioned yet)

**Doc it contradicts:** `docs/DEPLOYMENT.md:13`, quoted above. Also `docs/ROADMAP.md:347`
(D-25 itself: *"India co-location NOT required for it"*) and `docs/AGENTS.md:24`, which
states the correct position.

**Which is wrong:** `docs/README.md`. `docs/LEGAL-SURFACE.md:253-257` flagged this exact
conflict — but only for the root `CLAUDE.md`, and resolved it by saying "docs win". It did
not notice that a **doc** carries the same sentence, which makes the conflict internal to the
authoritative set rather than a docs-beats-manual case. `docs/README.md` is the first file a
new agent or hire reads, and it is the file that seeds the sentence in F-1.

**What would fix it:** replace "India-resident data plane" in `docs/README.md:105` with the
`AGENTS.md:24` formulation (India co-location required only for in-call-path services;
nothing provisioned). Root `CLAUDE.md` needs the same edit and is separately owed one.

---

## F-3 — SECURITY-COMPLIANCE claims the engine source-IP allowlist is enforced at nginx; no nginx template enforces it · **MEDIUM**

**Doc:** `docs/SECURITY-COMPLIANCE.md:522-524`:

> **Bolna (D-31) does not sign**: strict source-IP allowlist (their static egress
> 13.203.39.153) **enforced at nginx AND in-app**

**Code:**
- `infra/nginx/snippets/calevate-origin.conf:37-80` — the only `allow`/`deny` in the nginx
  tree is the **Cloudflare** origin lock (edge ranges + `deny all`). No engine address
  appears anywhere under `infra/nginx/`; `grep -r 13.203.39.153 infra/` returns nothing.
- `infra/nginx/snippets/calevate-origin.conf:12-20` — the snippet's own header says nginx's
  job here is `real_ip` restoration so that *"voice-runtime's SOURCE-IP ALLOWLIST, **which is
  the ENTIRE authenticity check** for an unsigned engine"*, can see the true address.
- `apps/voice-runtime/engine_intake.py:121-141` and
  `packages/shared/src/calevate_shared/config.py:60` — the allowlist lives in the
  application, and only there.
- `infra/nginx/README.md:82-86` confirms it: the allowlist is a claim about config until
  pilot gate 1's edge half is run.

**Which is wrong:** the doc. This is a compliance-facing document describing defence in depth
that does not exist on the only control standing between the internet and an unsigned
engine's webhooks. `docs/TRD.md:336,599-600,1045` describe the same control correctly (no
nginx leg), so the doc set disagrees with itself as well.

**What would fix it:** either strike "at nginx AND" from §3 and say the allowlist is
in-app, guarded by the real-ip chain that nginx makes trustworthy; or add an
`allow`/`deny` block for the engine egress on the `hooks.` server in
`infra/nginx/calevate.conf.template` and keep the sentence. The second is the stronger
posture but is a config change, not a doc edit, and would need the engine's address list to
become a deploy-time variable.

---

## F-4 — Two documents state a flat 5-minute presigned-URL TTL that D-153 replaced with a per-call window up to 7,500 seconds · **MEDIUM**

**Docs:**
- `docs/TRD.md:56` — *"Storage: R2/Spaces, SSE encryption, presigned URLs (5-min TTL), never
  public."*
- `docs/SECURITY-COMPLIANCE.md:514` — *"presigned URLs 5-min TTL; bucket public-access
  blocked at account level."* (in §5's security-measures list, i.e. offered as a control.)

**Code:** `apps/api/crm/routes.py:109-144` — `RECORDING_LINK_FLOOR_S = 300`,
`RECORDING_LINK_CEILING_S = 2 * CALL_CAP_MAX_S + RECORDING_LINK_FLOOR_S` (= **7,500 s**,
just over two hours), and `recording_link_ttl_s()` returns `min(max(300, duration_s*2),
7500)`; `routes.py:211-212` passes it into `presigned_url(..., ttl_s=...)`.
`apps/workers/storage.py:48` keeps `PRESIGN_TTL_S = 300` as the default for *other*
artefacts only. This is D-153 (`docs/ROADMAP.md:506`), which explicitly rejected raising the
shared constant and derived the recording window instead.

**Which is wrong:** both docs. `docs/SURFACES.md:78` was updated for D-153 (*"a presigned
link whose life is derived from…"*), so the doc set is internally inconsistent, and the
inconsistency is in the direction that understates the widest credential window the platform
mints — the number a security reviewer would be given.

**What would fix it:** state the two windows separately in both places — 5 minutes for
exports and payload refs, twice the call duration floored at 5 minutes and ceilinged at
`RECORDING_LINK_CEILING_S` for recording playback — and cite D-153 so the next reader gets
the reasoning rather than the number.

---

## F-5 — LEGAL-SURFACE's headline finding F-1 ("BREACH TODAY") and two of its five follow-ups were closed before this pass, and the document still directs counsel to them · **MEDIUM**

**Doc:** `docs/LEGAL-SURFACE.md:231-273` (F-1, headed **BREACH TODAY**),
`docs/LEGAL-SURFACE.md:534-536` (§10.1: *"the only item here that is arguably a live
breach"*), `docs/LEGAL-SURFACE.md:564-565` (FOLLOW-UP-1 and FOLLOW-UP-2).

**Code:**
- `apps/web/src/app/page.tsx:49-66` — the residency sentence is gone, with the removal
  reasoned in place; `apps/web/tests/publicLanding.test.tsx:61-87` pins its absence.
  FOLLOW-UP-2 is done.
- `apps/web/src/app/page.tsx:750-770` — the footer now iterates `LEGAL_DOCUMENTS` into a
  `<nav aria-label="Legal">` of eight `/legal/<slug>` links. FOLLOW-UP-1's central claim —
  *"Nothing on the site links to `/legal` today, so the documents are unreachable except by
  typing the URL"* — is no longer true.

**Which is wrong:** the doc. Under-claiming and over-claiming are both defects here, and
this is over-claiming a breach: §10 is written for an advocate, and it spends their first
question on a resolved item while the same residency claim survives unflagged in the BRD and
`docs/README.md` (F-1, F-2 above). The audit's value is its findings list; a findings list
that has stopped tracking the tree stops being read.

**What would fix it:** strike F-1 through to a `~~CLOSED~~` heading naming the commit that
closed it (as F-7 already models), retarget it at `docs/BRD.md:141-142` and
`docs/README.md:105` where the claim actually still lives, mark FOLLOW-UP-1/2 done, and
demote §10 item 1 accordingly.

---

## F-6 — LEGAL-SURFACE F-7 is headed CLOSED and still carries a "what closes it" instruction and an open follow-up for work already done · **MEDIUM**

**Doc:** `docs/LEGAL-SURFACE.md:373` heads F-7 *"**CLOSED (D-164)**"* and lines 381-386
describe the closure accurately — then lines 391-395 continue *"**What closes it:** add the
backup clause to `ERASURE_LIMITATIONS` … **I could not make it** … it should be the first
Python change after this one. FOLLOW-UP-3."*, and line 566 repeats it as an open row in the
§11 follow-ups table.

**Code:** `apps/api/compliance/deletion.py:252` (`BACKUP_WINDOW_DAYS = 35`), `:301-306` (the
prose clause inside `ERASURE_LIMITATIONS`), `:446-463` (the index-aligned `ERASURE_EXCEPTIONS`
entry keyed `backup`, outcome `expires_with_backup` at `:215`). Done, and pinned by test
across `infra/backup/README.md:317-318`, `/legal/dpa` and the certificate.

**Which is wrong:** the doc, in three places against its own heading. A reader who scans the
follow-ups table — which is what a follow-ups table is for — is told to make a change that
exists, and the likely outcome is a duplicate clause.

**What would fix it:** delete the stale "what closes it" paragraph from F-7, and either
remove FOLLOW-UP-3 or mark it done with the constant it landed as.

---

## F-7 — D-50 records the erasure/backup question as still open; D-164 decided it, and D-50 is not marked · **MEDIUM**

**Doc:** `docs/ROADMAP.md:390` (D-50) ends: *"…And whether `ERASURE_LIMITATIONS` gains a
backup clause, which is a legal call recorded as open in SEC-COMP §4. **Partly superseded:
the external dead-man heartbeat named as open here is BUILT (D-54)** … the
`ERASURE_LIMITATIONS` question **stays open**."*

**Doc/code that closed it:** `docs/ROADMAP.md:518` (D-164), `docs/SECURITY-COMPLIANCE.md:359-361`
(*"**DECIDED (D-164)** … It is now disclosed"*), and `apps/api/compliance/deletion.py:301-306,
446-463`.

**Which is wrong:** D-50. The entry already demonstrates the right pattern — it carries a
"Partly superseded" marker for the heartbeat leg that D-54 closed — and simply did not get
the second marker when D-164 closed the other leg. The decision log is described in
`scripts/check_docs_drift.py` as *"the closest thing this repo has to a constitution"*, and
`check_docs_drift` cannot see this class: D-164 resolves as a reference, so the sweep is
green while the two entries assert opposite states of the same question.

**What would fix it:** append a second supersession marker to D-50 naming D-164, in the same
form as the D-54 one, so both open legs of the entry are now closed and say so.

---

## F-8 — SECURITY-COMPLIANCE §4 says the client DPA quotes its retention numbers; the DPA quotes the code's numbers instead, so the described client-facing breach is no longer live · **MEDIUM**

**Doc:** `docs/SECURITY-COMPLIANCE.md:345-348`:

> This matters beyond tidiness: the client-facing **DPA quotes this document**, while
> `apply_retention` obeys the rows — so **today we tell clients one retention period and run
> another, in both directions.**

**Code:**
- `apps/web/src/lib/legal/dpa.ts:249-258` — §8 of the published DPA states **no period at
  all** except the 90-day recording floor; it delegates: *"The defaults … are set out in the
  Privacy Policy, section 9."*
- `apps/web/src/lib/legal/privacy.ts:642-661` — §9 publishes **90 / 365 / 1095 days**, i.e.
  `scripts/seed.py:80-87`'s `DEFAULT_RETENTION_POLICIES`, which is what
  `apps/workers/retention.py` enforces. `privacy.ts:10-12` says so explicitly.

**Which is wrong:** the doc, on the consequence rather than on the underlying mismatch. The
underlying disagreement is real and correctly open (SEC-COMP §4's table says 180/730/730; the
seed says 90/365/1095) — but the *published* documents and the code now agree with each
other, so we do not "tell clients one period and run another". The only document out of step
is SEC-COMP §4 itself. Leaving the stronger sentence in place misprices the item: it reads as
a live client-facing misstatement requiring a DPA amendment, when it is an internal
reconciliation plus one table edit.

**What would fix it:** rewrite the consequence sentence to say what is true — the published
notice and the sweep agree, and §4's own table is the outlier — while keeping the founder
decision open. `docs/LEGAL-SURFACE.md:344-360` (F-5) already states it correctly and can be
the model.

---

## F-9 — `docs/DEV-SETUP.md` sends a developer to a test file that does not exist · **LOW**

**Doc:** `docs/DEV-SETUP.md:87` — *"the source-IP allowlist is exercised separately in
`tests/webhook_receiver_test.py`."*

**Code:** no such file. `ls tests/ | grep -i receiv` is empty. The coverage the sentence
promises lives in `tests/voice_runtime_security_test.py` and
`tests/signing_engine_intake_security_test.py`.

**Which is wrong:** the doc. This is the class `check_docs_drift` deliberately declined to
cover (its "no every-backticked-path-exists check" note), and it is exactly the failure that
note predicted would survive: the sentence is the only thing telling a new developer that the
allowlist *is* tested, so a reader who checks and finds nothing concludes it is not.

**What would fix it:** name `tests/voice_runtime_security_test.py`.

---

## F-10 — FLOWS §6 states a flat 30-second retry for the recording copy; the pipeline uses the 30s/120s ladder · **LOW**

**Doc:** `docs/FLOWS.md:265-266` — *"Outbound webhook deliveries wait **30s then 120s** … a
failed recording copy waits 30s flat."*

**Code:** `apps/workers/pipeline.py:186` — `RETRY_BACKOFF_S: tuple[float, ...] = (30.0,
120.0)`, with the comment at `:182-185` stating it is *"the same ladder, and the same
reasoning, as `outbound_webhooks.RETRY_BACKOFF_S`"*; `_retry_after()` at `:204-206` and both
`raise Retry(defer=_retry_after(attempt))` sites at `:244` and `:572`.

**Which is wrong:** the doc. Harmless operationally, but FLOWS §6 is the page an operator
reads to answer "how long before this is definitely lost", and the real ceiling is 150s of
backoff, not 60s.

**What would fix it:** say "the same 30s/120s ladder" for the recording copy.

---

## F-11 — `docs/README.md` describes the decision log as "D-01…D-39"; it holds 164 entries through D-164 · **LOW**

**Doc:** `docs/README.md:33`.

**Code/artefact:** `docs/ROADMAP.md` §6 — 164 rows, tail `D-164` at line 518;
`uv run python -m scripts.check_docs_drift` reports *"164 decisions with no dangling
reference"*.

**Which is wrong:** the doc. The same sentence usefully warns that the tail is not in numeric
order, so it has been read and edited since — the range simply was not re-counted. Consequence
is a reader who stops at D-39 and misses D-127 (Gemini region), D-163 (disclosure toggles) and
D-164 (backup disclosure), all of which change compliance behaviour.

**What would fix it:** drop the range, or state it as "D-01 onwards; 164 entries as at
D-164".

---

## F-12 — D-95 says `.env` drops to six keys; `.env.example` carries eight · **LOW**

**Doc:** `docs/ROADMAP.md:442` (D-95) — *"`.env` drops from ~54 keys to 6."*
`docs/README.md:26` and `docs/PLATFORM-CONFIG.md` §4 refer to "the six bootstrap keys", which
is correct.

**Code:** `scripts/check_bootstrap_keys.py:61-76` — `BOOTSTRAP_KEYS` is six, and the guardrail
holds. But `.env.example` carries **eight** assignments: the six plus
`OBJECT_STORE_ENDPOINT` and `OBJECT_STORE_BUCKET` (`.env.example:90-91`), whose own preceding
comment (`.env.example:86-89`) records that they are outside `BOOTSTRAP_REQUIRED` and that
adding them is somebody else's ownership.

**Which is wrong:** the D-95 sentence, narrowly — six is the number of *guarded* bootstrap
keys, not the number of lines in the file. Recorded because the file is what a deployer
copies, and the gap is already self-documented as an unfinished seam rather than as a
disagreement.

**What would fix it:** phrase it as "six env-only bootstrap keys" rather than as a file
count, or close the seam the `.env.example` comment names.

---

## What was checked and found accurate

Listed so the next pass does not re-spend the time. Each was verified against code, not read.

**Compliance invariants (SECURITY-COMPLIANCE §2, hard rule 5, CLAUDE.md):**
- The unconditional truthful answer: `TRUTHFUL_ANSWER_DIRECTIVE` is a `Final` in
  `packages/shared/src/calevate_shared/engine.py:476`, appended after the client's script by
  `compose_engine_prompt` (`:614`), composed from no column.
- D-163's two toggles exist exactly as §2.1/§2.2 describe:
  `agents.ai_disclosure_line` / `recording_notice_line` NOT NULL with non-blank CHECKs
  (`apps/api/agents/models.py:74-78,168-169`), `PATCH /v1/agents/{agent_id}/disclosure`
  gated on `org:manage` (`apps/api/agents/routes.py:267-298`), and the audit action naming
  toggle **and** direction (`apps/api/agents/publishing.py:367-384` →
  `agent.ai_disclosure_disabled` etc.).
- The dial gate still refuses an agent with no AI sentence:
  `apps/api/compliance/service.py:331-346`, `rule="disclosure_missing"`.
- Calling window `DEFAULT_WINDOW = (09:00, 21:00)` IST as SEC-COMP T-7 states.
- 90-day recording floor is a real DB CHECK, not only a constant:
  `alembic/versions/05bba2f3c19c_db_core_with_rls.py:269`
  (`data_category != 'recording' OR ttl_days >= 90`), plus `ttl_days > 0`
  (`9c1d3e7a05f4:183`) and `RECORDING_FLOOR_DAYS = 90`
  (`apps/api/compliance/deletion.py:171`). The DPA's *"the database refuses a shorter
  period"* (`dpa.ts:258`) is literally true.

**Numbers that appear in more than one place and DO match:**
- **35-day backup window** — `infra/backup/README.md:317-318` (both chains),
  `apps/api/compliance/deletion.py:252`, `/legal/privacy` §9 and §12.4
  (`privacy.ts:701,956`), `/legal/dpa` Annex B (`dpa.ts:518`),
  `docs/DEPLOYMENT.md:652`, `docs/SECURITY-COMPLIANCE.md:377`. Pinned by test. The
  30-day R2 bucket lock is deliberately *below* it and says why
  (`infra/backup/README.md:360`).
- **`archive_timeout = 300`** — `infra/backup/postgresql-archiving.conf:38`,
  `docs/DEPLOYMENT.md:634`, `docs/ROADMAP.md:390`, against OPERATIONS §5's 15-minute RPO.
- **Retry budget 3** — one constant, `WORKER_MAX_TRIES` (`apps/api/core/queue.py:43`), read
  by `docs/FLOWS.md:262`, `docs/AGENTS.md:54` and CLAUDE.md consistently; outbound backoff
  `(30.0, 120.0)` in `apps/workers/outbound_webhooks.py:69`.
- **Signup quota 5/user/hour, 30/IP/hour** — `apps/api/tenancy/signup.py:85-86` vs
  `docs/SURFACES.md:502`, including the "consumed on every ATTEMPT" detail
  (`signup.py:215-237`).
- **Gemini flags** — `GEMINI_DEFAULT_LLM_RETIRES = date(2026,10,16)` and
  `GEMINI_MODEL_CONFIRMED_IN_REGION = False`
  (`packages/shared/src/calevate_shared/engine.py:351,405`),
  `GEMINI_EXTRACTION_DEFAULT = False` (`apps/workers/extraction.py:114`) — matching CLAUDE.md,
  `docs/README.md`, `docs/AGENTS.md`, `docs/OPERATIONS.md` §2 gate 14 and BRD R-04 exactly.
  The load-bearing "this is still a decision, not an observation" caveat is present in every
  one of them.
- **Bolna egress `13.203.39.153`** — `packages/shared/src/calevate_shared/config.py:60`
  and the pilot harness; the *number* is consistent everywhere (only the enforcement
  location is wrong — F-3).

**Route claims:** every `GET|POST|PATCH|PUT|DELETE /v1|/hooks|/tools/...` path written in the
doc set (102 distinct) resolves to a mounted router — including the ones most likely to be
half-wired: `/v1/compliance/deletion-requests`, `/v1/compliance/messaging-consent`,
`/v1/compliance/subject-export`, `/v1/ops/dnc/global`,
`/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/preference-scrub`,
`/v1/compliance/whatsapp-alerts`, `/hooks/v1/razorpay`, `/v1/lead-sources`. **No unmounted
route was found.**

**Legal surface:**
- All 19 `{{PLACEHOLDER}}` tokens in `apps/web/src/lib/legal/placeholders.ts` are still
  genuinely unfilled and still needed; none has become silently wrong. `PRIMARY_HOSTING_LOCATION`
  correctly documents itself as the F-1 hosting decision rather than an administrative blank
  (`placeholders.ts:156-165`).
- `PENDING_LEGAL_REVIEW = true` (`placeholders.ts:38`) with the marker constant and the test
  guard — `docs/legal/README.md`'s account of the mechanism is accurate.
- `docs/legal/README.md`'s core claim — that the eight documents have exactly one source of
  truth and no markdown copy exists — holds: `docs/legal/` contains only the README.
- The DPA's 48-hour breach clause vs the 72-hour Rule 7 duty (`dpa.ts:166,230-232`) is
  consistent with SEC-COMP and with LEGAL-SURFACE F-6, which correctly reports the missing
  procedure behind it.

**Deployment/CD:** `.github/workflows/deploy.yml` exists and is disabled behind the
`VPS_DEPLOY_ENABLED` repo Variable exactly as `docs/DEPLOYMENT.md:173-174` and
`docs/README.md:49` describe; `infra/nginx/rate-zones.conf.template` has landed and
`check_docs_drift`'s deferred-mirror rule correctly reports 0 deferrals with 6 zones
mirrored.

**Doc-referenced file paths:** all 283 backticked paths in the doc set were existence-checked.
The only genuine miss is F-9; `apps/api/core/transport.py`
(`docs/PRODUCTION-READINESS.md:95,142`) is a *proposed move target*, not a claim, and reads
correctly in context.

**Guardrail:** `uv run python -m scripts.check_docs_drift` passes on this branch.

---

## What this pass could NOT determine

- **Whether `docs/SECURITY-COMPLIANCE.md` §4's retention table or the seed is the intended
  commitment.** Correctly open in two documents; it is a founder decision, not a drift, and it
  is named here only so the F-8 correction is not mistaken for closing it.
- **Whether the `infra/nginx` engine-allowlist gap (F-3) is a doc error or a config
  omission.** Both readings are defensible from the tree: TRD describes an in-app-only
  control, SEC-COMP describes two layers, and no decision-log entry chooses. Recorded as a
  doc error because TRD is the architecture document and it is the more specific of the two,
  but the founder may have intended the nginx leg.
- **Anything Clerk-shaped**, per the in-flight note above.
