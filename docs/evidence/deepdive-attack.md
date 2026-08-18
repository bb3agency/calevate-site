# Deep-dive attack pass — object-level authorization (D-193)

**Posture.** A legitimate client-realm user of tenant A (`staff` or `owner`), and an
admin-realm operator holding the least privilege that realm grants. Every claim below is
marked **PROVEN** (an attack that was executed over HTTP against the live app and whose
result is quoted) or **REASONED** (read, not run).

**Scope note.** Prior passes cleared the egress guard, `client_address`, all six session
flavours, `TENANT_TABLES`/exemptions, realm separation, impersonation, envelope crypto,
constant-time comparisons, redaction/observability, CORS, the dial paths' `check_dispatch`
calls, and every migration's `FORCE` clause. This pass deliberately went elsewhere: the
**object level**, and specifically the **write** side of it.

---

## Method

The route table was enumerated from the live app rather than from grep, three ways:

1. **204 routes** with their declared permission (`openapi_extra`) — `iter_api_routes(app)`.
2. **The realm each route's auth dependency actually pins**, walked out of the FastAPI
   `Dependant` tree (`calevate_realm` on the `requires()` closure).
3. **All 76 request-body models**, with their fields and `model_config["extra"]`.

That produced the three inventories the findings came out of, and also the negative
results in "What did not break".

---

## FINDING 1 — a tenant could name a neighbour's row in something it wrote (**PROVEN**)

**Class:** OWASP API1:2023 Broken Object Level Authorization, on the write path.
**Severity:** high for the consent case (append-only, legal record), moderate for the
campaign cases (stored cross-tenant reference; no disclosure reachable today).
**Status:** FIXED, with a test that fails without the fix.

### The mechanism

PostgreSQL runs **referential-integrity checks with row security bypassed**. That is
deliberate upstream — integrity must not be defeasible by visibility — and the
consequence here is exact:

- a policy's `WITH CHECK` enforces the `tenant_id` **of the row being written**, so
  tenant B cannot forge a row *into* tenant A; but
- a **foreign key inside B's own row** is validated against the whole table, so B's row
  may point at A's agent, A's registered calling number, A's DLT template, or A's call —
  and the `INSERT` succeeds.

This was already understood in the repo: `kb/service.py::_assert_agent_is_ours` stated it
correctly in its own docstring, and `ingest/service.py::_agent_is_ours` applied the same
guard. Two other write paths never called either one.

### Reproduction — campaign against a neighbour's agent

Tenant B's valid owner session, tenant A's real `agent_id`:

```
POST /v1/campaigns
Authorization: Bearer <tenant B owner>
X-Org-Slug: <tenant B slug>

{"agent_id": "<TENANT A's agent id>", "name": "stolen agent",
 "classification": "service", "concurrency": 1}
```

Before the fix:

```
201 Created
{"id":"01a01276-6687-78b3-8bf3-a2373028428a","status":"draft"}
```

The resulting campaign was then **visible in tenant B's own `GET /v1/campaigns` list**
(verified: `foreign-agent campaign visible in own list? True`) and its detail route
answered **200** — while `GET /v1/campaigns/{id}/launch-check` answered **404 "Campaign
not found"**, because `_campaign_facts` INNER JOINs `agents` and that join runs under B's
own RLS. A row the client owns, can see, and can never launch or explain.

### Reproduction — campaign dialling from a neighbour's DLT-registered header

```
POST /v1/campaigns
{"agent_id": "<B's own agent>", "name": "stolen number",
 "classification": "promotional",
 "number_id": "<TENANT A's 140-series, dlt_status=registered>",
 "dlt_template_id": "<TENANT A's approved voice template>",
 "concurrency": 1}
```

Before the fix:

```
201 Created
{"id":"01a01276-6670-75c0-8525-bd755d8498e3","status":"draft"}
```

A 140-series header and an approved voice template are registered to the **client's own
Principal Entity**. A campaign of B's citing A's is traffic under the wrong PE, which is
whose complaint count it lands on (SEC-COMP §1).

**Honest limit (PROVEN, not assumed):** this one does **not** reach a live dial. The
launch gate's joins run under the caller's own session, so A's number reads back NULL and
the gate answers `number_missing`; A's template answers `dlt_template_missing`; and
`compliance/service.py::check_dispatch` scopes the agent with an explicit
`WHERE id = :aid AND tenant_id = :tid`, answering `agent_missing`. The gate fails closed.
What survived was the **stored reference** — one un-scoped `JOIN` away from a disclosure,
and `campaigns/service.py:1197` already carries a hand-written
`AND p.tenant_id = c.tenant_id` on one such join, i.e. the hazard was being patched at the
read side, one query at a time, instead of at the source.

### Reproduction — the append-only one, and the worst of the three

```
POST /v1/compliance/messaging-consent
{"phone": "+919000000123", "status": "granted",
 "source": "inbound_call_verbal",
 "call_id": "<TENANT A's call id>",
 "evidence": {"form": "ivr", "version": "1"}}
```

Before the fix:

```
201 Created
{"status":"granted","source":"inbound_call_verbal","captured_at":"...","messageable":true}
```

and the row was confirmed present in `consent_ledger` naming tenant A's call
(`consent_ledger row in tenant B naming tenant A's call: True`).

`consent_ledger` is in `db/registry.APPEND_ONLY_TABLES` (**hard rule 4**). A spoken opt-in
must name the conversation it happened in (`_assert_grant_is_evidenced`); before this fix
that conversation could be **anybody's**, and the row is a DPDP consent record that can
never be corrected — only compensated by a second row that still cannot say the first lied
about whose call it was.

### The fix

`apps/api/db/ownership.py` — one primitive, `assert_visible(session, ref, row_id)`, that
resolves a caller-supplied id **under the caller's own RLS session** before anything is
stored, and answers `404` (never `403`, for the reason the IDOR sweep pins: from inside a
tenant, "not yours" and "no such row" are the same fact).

Rather than adding a third and fourth copy of a guard that already existed twice, both
existing copies moved onto it in the same change — CLAUDE.md's "one way per problem, and
migrate rather than accumulate":

| site | before | after |
|---|---|---|
| `kb/service.py::submit_source` | `_assert_agent_is_ours` (local) | `assert_visible(..., "agent", ...)` |
| `ingest/service.py::create_lead_source` | `_agent_is_ours` (local) | `assert_visible(..., "agent", ...)` |
| `campaigns/service.py::create_campaign` | **nothing** | agent + phone_number + dlt_template |
| `compliance/consent.py::record_messaging_consent` | **nothing** | call |

The reference kinds are a `Literal`, and the SQL is a dict of literal strings — not a
table-name parameter, which would put a caller-chosen identifier into SQL and is exactly
what `scripts/check_raw_sql.py` exists to refuse.

`None` is a deliberate no-op: `number_id` and `dlt_template_id` are nullable and a
half-filled draft must still save. Refusing an absent number here would move the launch
gate's `number_missing` blocker to creation time — a product change dressed as a security
fix. `tests/cross_tenant_reference_test.py` pins that too.

### Verification

`tests/cross_tenant_reference_test.py` — 5 tests. With the three `assert_visible` lines
removed, **3 fail and the 2 non-vacuity tests still pass**:

```
FAILED tests/cross_tenant_reference_test.py::test_a_campaign_cannot_name_a_neighbours_agent
FAILED tests/cross_tenant_reference_test.py::test_a_campaign_cannot_dial_from_a_neighbours_registered_number
FAILED tests/cross_tenant_reference_test.py::test_a_consent_grant_cannot_cite_a_neighbours_call
3 failed, 2 passed
```

With the fix in place, all five pass and the three attacks answer:

```
CAMPAIGN foreign number+template -> 404 "Phone number not found"
CAMPAIGN foreign agent           -> 404 "Agent not found"
CONSENT  foreign call_id         -> 404 "Call not found"
```

---

## FINDING 2 — the IDOR sweep had six blind routes (**PROVEN**, no vulnerability)

`tests/adversarial_pass_test.py` drives every `{id}` route in the client path space with a
neighbour's real ids. Comparing its 34-entry table against the live route inventory, six
mounted `{id}` routes were **not** in it:

```
PATCH  /v1/agents/{agent_id}/disclosure
POST   /v1/calls/{call_id}/assist
POST   /v1/campaigns/{campaign_id}/contacts
GET    /v1/compliance/deletion-requests/{request_id}
GET    /v1/kb/sources/{source_id}/preview
POST   /v1/leads/{lead_id}/call
```

All six were driven with tenant A's real ids and tenant B's session. **All six already
refused correctly** — 404 `not_found` in every case, RLS doing it rather than a Python
comparison:

```
PATCH  /v1/agents/{agent_id}/disclosure              -> 404 "Agent not found"
POST   /v1/calls/{call_id}/assist                    -> 404 "Call not found"
POST   /v1/campaigns/{campaign_id}/contacts          -> 404 "Campaign not found"
GET    /v1/compliance/deletion-requests/{request_id} -> 404 "Deletion request not found"
GET    /v1/kb/sources/{source_id}/preview            -> 404 "Knowledge source not found"
POST   /v1/leads/{lead_id}/call                      -> 404 "Lead not found"
```

They are now in the sweep, so that stays true. Two of them (`assist`, `leads/{id}/call`)
refuse a request with **no `Idempotency-Key` before they look at the id**, so the sweep's
tuple grew a `headers` element — without it those two would have asserted `400` and proved
nothing about tenancy, which is the same vacuity the existing "a 422 fails too" rule
guards against. `POST /leads/{id}/call` also carries an id **in its body** (`agent_id`), so
the driver now substitutes neighbour ids into bodies as well as paths.

---

## What did not break — attempted and refused

Each of these was attacked or inventoried; none yielded.

**Mass assignment / over-posting (PROVEN).** All **76** request-body models the live app
accepts declare `extra="forbid"` — swept programmatically, zero open. Every declared field
that *looked* dangerous was then read: `AiExtraIn.accept_amount_inr` is compared against
`AI_OVERAGE_BLOCK_INR` and a mismatch is refused rather than clamped;
`TopUpIntentIn.amount_inr` is range-checked and the wallet is credited from the
Razorpay-signed captured amount, not the requested one; `MemberRoleIn.role` carries an
`expected_role` CAS.

**Caller-supplied assignee (REASONED, guard read).** `LeadUpdateIn.assigned_to` and
`LeadBulkIn.assign_to` both route through `crm/service.py::_assert_assignable`, which
resolves the user through the **RLS-scoped `memberships`** table and also checks
`deactivated_at`. Both call sites confirmed (`service.py:1092`, `service.py:1328`).

**Realm separation on the admin console (PROVEN by inventory).** Every one of the 54
`/v1/admin/*` routes pins `realm="admin"` on its auth dependency — walked out of the live
`Dependant` tree, not grepped. No client-realm principal holding `org:read` or `calls:read`
can reach the admin surface.

**Admin least privilege on the QA queue (REASONED).** `GET /v1/admin/qa-samples/{id}` is
gated `calls:read`, which the least-privileged admin role (`operator`) holds — but it calls
`crm.get_call(..., raw=False)`, the same function with the same argument that serves the
client's own screen, so the transcript is `text_redacted`. There is no raw variant on that
router, and the redacted read is itself audited (`qa_sample.read`) inside the same
transaction.

**Staff vs owner on the trust surfaces (REASONED).** `/v1/quality/reports` is `agents:read`
(staff-reachable) and contains no call content by construction. `GET /v1/integrations/
endpoints` and `GET /v1/lead-sources` are `org:read` (staff-reachable) and return
**fingerprints, never secrets** — the signing secret is shown exactly once at creation.

**SQL injection through the facet filters (REASONED).** `f=<key>:<value>` keys are checked
against the agent's own extraction schema at the route and are then passed as **bound
parameters** (`l.data ->> :ff_k{i} = ANY(:ff_v{i})`), not interpolated — the code says
"validated upstream is a fact about today's caller" and binds anyway.

**Password-length DoS on the public surface (REASONED).** Every password field is
`Field(min_length=MIN_PASSWORD_CHARS, max_length=MAX_PASSWORD_CHARS)`, capped before the
Argon2id verification, and the module cites the OWASP Password Storage Cheat Sheet for the
parameter choice.

**The public ingest webhook's 404-vs-401 split (PROVEN by reading the handler; NOT
actioned, and here is why).** `POST /hooks/v1/ingest/{webhook_id}` answers **404** for an
unknown or inactive id and **401** for a live id with a bad secret, so the two are
distinguishable. `check_public_routes.UNAUTHENTICATED_ROUTES` claims the 404 means "a
prober cannot enumerate live endpoints", and strictly the split is an oracle. It is not a
reachable one: `webhook_id` is `uuid7()`, which fixes 48 bits to a millisecond timestamp
and leaves ~74 bits random, so a prober cannot produce a candidate id to ask about — and
anyone who already holds one does not learn a secret from the answer. Collapsing the 401
into a 404 would cost a real client the ability to tell "wrong URL" from "wrong secret",
which is an interface regression for no security gain (`ingest/routes.py` already
distinguishes the two deliberately in its Meta twin's refusal, for the same reason). Left
as it is, recorded rather than silently passed over.

**Unbounded row creation (REASONED, spot-checked).** Saved views are capped per user
(`MAX_SAVED_VIEWS_PER_USER`, enforced with a count before insert); `tests/rate_limit_
census_test.py` asserts every live route resolves a limiter rule and every rule is reached
by a live route.

---

**All four reference kinds really are RLS-scoped (PROVEN).** `assert_visible` is only a
control if the tables it reads are policied — a guard over a global table would be a
silent no-op. `agents`, `calls`, `dlt_templates` and `phone_numbers` are all in
`db/registry.TENANT_TABLES` and none is in the RLS guardrail's exempt list
(`RLS COVERAGE: OK (44 tenant-column tables, 48 policied ...)`), and the tests prove it
end to end rather than by inspection: each of the three attacks answers 404 *because the
neighbour's row was invisible to the statement*, which is only true if the policy is on.

---

## Residual, named

The `assert_visible` reference table currently covers `agent`, `call`, `dlt_template` and
`phone_number` — the four kinds a client can name today. It is a `Literal`, so adding a
fifth is a line in one file; the thing that would let a fifth be *forgotten* is a new
request-body FK field, and the sweep that found these (body models → UUID fields →
permission) is reproducible from the method section above rather than from a stored script.
Nothing here waits on anything outside the repo.
