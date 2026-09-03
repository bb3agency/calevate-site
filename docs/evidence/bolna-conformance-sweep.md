# Bolna end-to-end conformance sweep — what sixteen lanes left, and what moved

**Date:** 3 Sep 2026. **Lane:** the whole seam at once — every literal we send, every
field we read, every status ordering, the webhook contract, the error ladder, the limits,
the built-ins we configure rather than rebuild, and the surfaces added recently enough
that no lane had ever diffed them.

**Evidence class throughout: VERIFIED-VENDOR-DOCS** — `bolna-findings/mirror/pages/`, the
read-only 333-page mirror with a per-page SHA-256 manifest. Every verdict cites a page and
a line. `api.bolna.ai` and `www.bolna.ai` are egress-blocked from this container; nothing
below was measured against a live account and nothing here claims to have been.

**How this lane was scoped.** Sixteen `docs/evidence/bolna-*.md` reports already cover
this vendor by category (lanes A–J), by REQUEST (`bolna-request-contract.md`) and by
RESPONSE (`bolna-response-contract.md`). Re-running any of those axes would have produced
a second opinion, not a finding. So the scope was chosen by *coverage arithmetic*:

1. **Mirror pages nothing in this tree cites.** Every `.md` under `pages/` was matched by
   basename against the union of `docs/`, `apps/api/engine/`, `apps/voice-runtime/`,
   `apps/workers/`, `packages/shared/` and `tests/`. 272 of 333 are cited somewhere. Of
   the 61 that are not, all but a handful are marketing templates (`voice-agents/*`),
   integration tutorials (`zapier`, `make-com`, `n8n`, `viasocket`), the CLI, the
   graph-agent editor and provider pages for vendors we do not use.
2. **Request sites added AFTER the lane that would have covered them.**
   `bolna-request-contract.md` diffed 13 `self._request(...)` call sites; D-488 added
   four more (the knowledge-base routes) and no lane has diffed them. That is where F-1
   below came from.
3. **Citation integrity.** All 1,181 `<page>.md:<line>` references in this tree resolve to
   a file in the mirror and to a line inside it (script kept out of the tree; it is eight
   lines of `pathlib` and a regex). No dangling citation exists. This checks RANGE, not
   content, and is reported as what it is.

---

## 0. One-line verdicts

| # | Question | Verdict |
|---|---|---|
| 1 | Wire values — every provider name, field name, enum, status string | **No new mismatch.** Every literal re-checked against a machine-readable occurrence; the `azure-openai` correction (D-417) holds and `tests/bolna_contract_test.py` pins it. |
| 2 | Request shapes | **One defect, fixed: `GET /knowledgebase/all` was read unpaged.** F-1, D-516. |
| 3 | Response shapes and STATUS LIFECYCLES | **Correct, including `make.md`'s warning.** `call-disconnected` maps to our `completed` for the CALL ROW but is deliberately NOT in `_TERMINAL_RAW`, and `billable_ready` is `raw_status == "completed"` alone. §2. |
| 4 | Webhooks — signing, retries, duplicates, ordering | **Matches TRD §5 and the docs still support it.** The dedupe key is `{execution_id}:{raw_status}`, which is what "multiple events per call" requires; keying on the execution alone would have dropped `completed`. §3. |
| 5 | Error responses | **No change.** The ladder was rebuilt in `bolna-failure-contract.md` and re-verified here. §4. |
| 6 | Limits | **The mirror DOES say something about concurrency and we do not read it — and that is a known, correctly-classified external blocker, not a new finding.** §5. |
| 7 | Built-ins we configure rather than rebuild | **No rebuilding found; one vendor SILENCE that our design already routes around.** §6. |
| 8 | Recently added surfaces (`user_data`, inbound caller data, in-call tools, engine KB) | **Three clean, one defect (the KB path).** §7. |
| 9 | Hard rule 2 — does anything outside `engine/` see a vendor shape? | **No payload shapes leak. One module constructs a vendor REQUEST outside the wall, deliberately and by design — and it had drifted from the adapter it cites.** F-2, D-517. §8. |

---

## F-1 — `GET /knowledgebase/all` is a PAGE and we read it as the ACCOUNT · **FIXED** (D-516)

**Class:** MISSING-PARAM → a false statement to a client. **Severity: P0 on the KB path.**

Two pages, and they disagree in the way that hides this:

> *"The endpoints also support pagination using the `page_number` and `page_size` query
> parameters."* … *"`page_size` (integer, optional): The number of results per page.
> Defaults to `20`."*
> — `bolna-findings/mirror/pages/api-reference/pagination.md:9,13-14`

> the route's own OpenAPI block declares **no** `parameters` and answers a bare
> `KnowledgebaseList` array — no `has_more`, no `total`
> — `.../api-reference/knowledgebase/get_knowledgebases.md:29-44,47-51`

So truncation is not detectable from the response, and the only evidence paging exists on
this route is `pagination.md`'s "the endpoints". **That is the identical evidentiary
position `_agent_refs` was in**, where D-430/F-1 settled it by walking the pages under an
argument that is correct whichever way the vendor behaves.

`BolnaEngine._rag_id_of` sent the request with no parameters at all. It is the only route
carrying both the `vector_id` we hold as a handle and the `rag_id` the DELETE route takes
(`get_knowledgebases.md:63-94`), and there is no route that reads a knowledge base BY
vector id — so this listing is the whole of `detach_kb`'s evidence.

**Why twenty rows is not a distant ceiling.** One Bolna account holds every tenant's
knowledge bases; the object has **no update route**, so every republish of a source is a
fresh CREATE (`.../knowledgebase/overview.md:11-16`); and three crash windows leave
unreferenced ones behind that nothing sweeps (gate 43e).

**Why this is worse than the agent-roster case it copies.** There, the walk stopping early
truncated a reconciliation report and (after D-430) refused to claim completeness. Here the
absence of a row is read as a POSITIVE fact:

```
rag_id = await self._rag_id_of(kb)
if rag_id is None:
    raise ProblemError(..., detail="The voice platform does not hold that knowledge base.")
```

A client's 21st knowledge base is therefore reported as one the platform does not hold —
about a document it is holding, retrieving from and billing for — and no retry can ever
succeed.

**Fixed** by walking pages with the constants `_agent_refs` already uses, and by splitting
the answer into three rather than two: the id; `None` **only** after a short page (the one
exit that can claim absence, because the vendor returned fewer rows than we asked for);
and `engine_kb_listing_incomplete` when the walk could not be finished. An unlocatable
reference must not look like a cleared one (D-41), and nothing is written on an
inconclusive read.

**A second, smaller lie in the same six lines.** A row whose `vector_id` MATCHED but whose
`rag_id` was missing or blank returned `None` — i.e. "already gone" — and deleted nothing.
`rag_id` is declared on that row (`get_knowledgebases.md:65-70`), so its absence is
`engine_bad_response`, not an absence.

**Tests:** `tests/bolna_kb_listing_test.py`, 7 clauses, all seven verified RED against the
restored old implementation and green after — including a reverse clause that fails if
either bare-array listing ever loses its pagination parameters again.
`runbooks/alarm-index.md` carries the new code; `scripts/check_alarm_wiring` refused the
build until it did.

**Not extended to `GET /providers`, on `bolna-request-contract.md` F-2's reasoning**, which
is re-read and still holds: the vendor ENUMERATES that store's key vocabulary
(`providers.md`), an account cannot overflow one page, and a miscount surfaces as a wrong
verdict in a log line. Knowledge bases have no such bound.

---

## F-2 — the one vendor request built outside the engine wall had drifted from it · **FIXED** (D-517)

Hard rule 2 holds for payload SHAPES: nothing outside `apps/api/engine/` (and
`apps/voice-runtime/engine_intake.py`) parses a vendor payload, and import-linter's
"engine isolation" contract enforces the import ban.

What the grep for *"anything that constructs a request to the vendor"* turned up is
different and legitimate: `apps/api/ops/secret_probes.py` builds one authenticated GET per
vendor so the operator console can answer "is this credential real?". It carries no payload
parsing — it reads a status code — and its registry opens by promising:

> *"Every endpoint and header shape below is READ FROM THIS REPO'S OWN ADAPTERS — the code
> that already calls these vendors in production — rather than from memory, so a probe
> cannot be authenticating differently from the thing it is testing."*

**The Cartesia probe was.** It sent `X-API-Key` with `Cartesia-Version: 2024-06-10` and
cited `apps/api/engine/cartesia.py (BASE_URL, API_KEY_HEADER)` — a constant that file has
not carried since **D-271** moved the adapter to `Authorization: Bearer`, on the strength
of both of the vendor's generated clients, with an explicit note that sending BOTH forms
was rejected. So the console's credential check tested a superseded auth form: a working
key refused, and an operator told to rotate it.

The Bolna probe was checked in the same pass and is correct — `https://api.bolna.ai` is
`BASE_URL`, `GET /v2/agent/all` is a route the adapter really calls, and the header is
`Authorization: Bearer`.

**Fixed**, and pinned by a test rather than by an import: `apps.api.ops` may not name
`apps.api.engine.cartesia`, so the literals stay literals and
`tests/platform_secrets_test.py::test_every_probe_authenticates_the_way_its_adapter_does`
asserts the RENDERED header map of both probes against the adapters' own constants. Red
against the restored defect.

**What this is an instance of.** `test_every_probe_names_where_its_endpoint_came_from` has
existed for as long as the registry has, and checks that `source` is NON-EMPTY. Nobody ever
checked that it was TRUE. That is hard rule 12's closing bullet exactly — *"a repo-internal
claim is not evidence of itself, and this includes attribution"*.

---

## 1. Wire values — re-checked, nothing moved

Spot-checked every literal the adapter puts on the wire against a machine-readable
occurrence rather than a label, which is the discipline D-417 was written in blood for.
`llm_config.provider: "azure-openai"` is printed twice on its own provider page
(`providers/llm-model/azure-openai.md:20,59`) and `tests/bolna_contract_test.py` pins it;
`transcriber.provider/model/language`, `tools_config.input/output`,
`toolchain.pipelines`' array-of-arrays, `task_type`, `agent_type` and `agent_flow_type` all
match the enums in `api-reference/agent/v2/create.md`. The two known exceptions —
`synthesizer.provider: "sarvam"` and its `provider_config` — remain **WRONG-ENUM /
WRONG-SHAPE as documented** and are argued at `bolna-request-contract.md` F-3; this lane
found no new evidence either way and did not re-open them.

The KB create body was diffed for the first time and MATCHES:
`chunk_size`/`overlapping`/`similarity_top_k` are the vendor's own documented defaults and
`language_support: multilingual` is the single-member enum
(`.../knowledgebase/create.md:53-80`); `KB_MAX_DOCUMENT_BYTES` is exactly the documented
*"PDF file to upload (max 20 MB)"* (`create.md:44`); the part is `bytes` and multipart, and
`url` is correctly not sent beside `file` (*"Provide either `file` or `url`, not both"*,
`create.md:31-33`).

## 2. Status lifecycle — the `make.md` warning is honoured

> *"**Wait for `completed`, not `call-disconnected`.** The `call-disconnected` event fires
> the instant the line drops, but `conversation_duration`, `total_cost`, `recording_url`,
> and `extracted_data` are not yet populated."*
> — `api-reference/calls/make.md:55`, repeated at `api-reference/errors.md:59` and
> `build-with-ai/agents-md.md:31-33`

We honour it in the two places it can be got wrong, and they are separate:

* `ExecutionSnapshot.billable_ready = (raw_status == "completed")` — `call-disconnected`
  never sets it, so nothing bills or files a recording off the disconnect;
* `_TERMINAL_RAW` does **not** contain `call-disconnected`, so the poller keeps asking.

`_STATUS_MAP` maps `call-disconnected → completed` for the CALL ROW, which is correct for a
screen (the line really did drop) and is exactly why `billable_ready` is a separate field
rather than a function of the mapped status.

The other three timing caveats in the vendor's own gotcha list were checked too:
`scheduled_at` must use `+00:00` not `Z` (we send no `scheduled_at` at all, asserted by
`tests/bolna_call_flow_test.py`); `toolchain.pipelines` is an array of arrays (it is);
`POST /v2/agent` returns **201** and its status field is `state` not `status`
(`agents-md.md:23-24`) — `vendor_request` treats every non-4xx/5xx as success and
`create_agent` reads only `agent_id`/`id`, so neither bites.

## 3. Webhooks

`api-reference/limits.md:55-61` is the tightest statement of the contract in the mirror and
it corroborates TRD §5 on all four axes: three source IPs (*"whitelist all three on your
server"*), **multiple events per call** (*"queued → in-progress → call-disconnected →
completed"*), *"Expected response HTTP `200` — return fast"*, and *"Bolna retries on
non-2xx or timeout"*. No signature anywhere in 333 pages.

The consequence worth naming, because it is the one a reasonable implementer gets wrong:
**"multiple events per call" makes the execution id the wrong dedupe key.** Keyed on the
execution alone, the `completed` delivery — the only one carrying cost, recording and
extracted data — is discarded as a duplicate of `call-disconnected`. `webhook_routes.py`
keys both the Redis fast path and the durable inbox claim on
`{execution_id}:{raw_status}` and says so in a comment citing this. Verified, unchanged.

## 4. Error responses

`bolna-failure-contract.md` §1 rebuilt this ladder from `api-reference/errors.md:11-20`
and it is unchanged: 400/401/403/404 are `engine_rejected` and never retried; 429 is
`transient` with `Retry-After` honoured as a floor; 5xx counts into `platform_engine_health`
and is not retried. Re-verified against the same page. One addition from this lane: the KB
oversize refusal is raised BEFORE the request precisely so a 400 does not go through the
throttle ladder three times with the same 20 MB body.

## 5. Limits — the mirror does say something, and we still do not read it

`PLATFORM_LINES_TOTAL = 10` is a typed-in belief about somebody else's number. The mirror
answers it: *"Check your current concurrency in `GET /user/me`"* with
`{"concurrency": {"max": 10, "current": 3}}` (`api-reference/limits.md:11-19`), and the
tier text says the ceiling *"scal[es] automatically with monthly usage"*
(`pricing/outbound-calling-concurrency.md:18`) — so a correct constant decays silently.

**This is already found, already classified and already correctly blocked**
(`bolna-subaccounts-platform.md` §2.6 Finding D; the constant's own comment names the
replacement, the port shape and the blocker). It is repeated here only to record that this
lane re-read the pages and agrees: **the vendor's documented default and our constant
coincide, so we currently dial strictly fewer lines than they will accept**, and the
direction that would matter — an account ceiling LOWER than ours — cannot arise from the
documented default. Reading the live value needs a Bolna account. **Blocked outside this
repo on: a Bolna account.**

The rest of the limits page carries no number we violate: batch/CSV limits apply to a
surface we do not use, and the rate-limit section publishes a mechanism (429 + backoff)
rather than a threshold.

## 6. Built-ins: configured, not rebuilt — and one conspicuous silence

* **Campaigns.** We do not use `POST /batches`. That is deliberate and pre-existing: the
  batch surface is a **CSV upload** whose `contact_number` column is a copy of the client's
  contact list on the vendor's side, and the compliance gate (`check_dispatch`) must run
  per contact at DIAL time, not at upload time. Our dispatcher places one `POST /call` per
  contact under a global budget.
* **Knowledge base.** Configured, not rebuilt (D-488) — and the vendor's KB is the T0
  in-call tier by design.
* **Custom functions / in-call tools.** `_one_api_tool` builds the vendor's
  `tools`/`tools_params` shape; `tools` is a JSON STRING per the field's own description.
  Unchanged this lane.
* **Transfers.** Refused by capability, on a SHAPE mismatch rather than missing evidence:
  Bolna transfers through an in-call tool the LLM fires, and no route instructs an
  execution already in flight — which is what `VoiceEngine.transfer(call_id, ...)`
  promises.
* **Consent / DNC.** Ours, and must stay ours: their auto-retry, `calling_guardrails`
  rescheduling and concurrency QUEUE all place a dial at a time our per-contact gate did
  not clear (`bolna-subaccounts-platform.md` §2.7). We send no `retry_config` and no
  `scheduled_at`.

**THE SILENCE, and it is gate 8's:** `DELETE /knowledgebase/{rag_id}` documents only
*"Delete a knowledgebase"* (`.../knowledgebase/delete.md:31`) and says nothing about the
agents referencing it — while the **dispositions** delete route in the same API explicitly
promises to *"Permanently delete a disposition and remove its link to any associated
agents"* (`api-reference/dispositions/delete.md:40`). The contrast is evidence about the
docs, not about the behaviour. **UNKNOWN — the docs do not state this.** Our `detach_kb`
does not depend on the answer: it un-references on the AGENT first and deletes second, so a
delete that clears nothing is harmless and a delete that clears everything is redundant.
Gate 8 keeps the question.

## 7. The recently added surfaces

* **`user_data` on call creation.** MATCHES. It is `type: object` with
  `additionalProperties: true` and is documented as *"Additional user dynamic variables as
  defined in the agent prompt"* (`calls/make.md:119-124`), rendered into the prompt and
  welcome message (`:32`). We send only truthy values plus `lead_name`/`context_note`.
  `from_phone_number` is OMITTED rather than sent null when there is none, which is right
  for an optional string (`:106-112`).
* **Inbound caller data.** Not built, and correctly not built. Of the three data-source
  variants (`customizations/identify-incoming-callers.md:23-90`), Google Sheets requires a
  *"publicly accessible"* sheet of consumers' names and numbers — a DPDP breach on data we
  process — and CSV puts a stale copy of the client's contact list on the vendor's side.
  The Internal-API variant is the right seam and its three constraints are already recorded
  (`bolna-call-flows.md:415-440`). No code change; nothing half-wired.
* **In-call tool / function calling.** `apps/voice-runtime/tool_routes.py` exposes one
  route (`POST /tools/v1/{engine}/opt-out`) and `tests/kb_tiers_test.py` pins the
  voice-runtime route inventory as an EQUALITY, so the surface cannot grow unnoticed.
* **Engine KB path.** F-1.

## 8. Hard rule 2

No vendor payload shape is parsed outside `apps/api/engine/` and
`apps/voice-runtime/engine_intake.py`; import-linter's contract lists the business modules
and forbids the three adapter modules directly. The one construction of a vendor REQUEST
outside the wall is the credential probe registry, which is deliberate, documented, reads
only a status code — and had drifted. F-2.

---

## What this lane did NOT settle

* **Whether the platform honours `page_number` on `/knowledgebase/all`** — the walk is
  correct either way, but the VERDICT differs. This is OPERATIONS §2 gate 30's question on
  a second endpoint; one live account settles both. **Blocked outside this repo on: a
  Bolna account.**
* **Gates 43a–43g** — every one of them needs an upload against a live account. Nothing in
  the mirror answers any of them, and this lane closed none by inference. Gate 43b's
  sub-question is sharpened rather than answered: `error` is declared on the CREATE
  response's status enum (`create.md:110-113`) and absent from `Knowledgebase`'s
  (`get_knowledgebases.md:95-101`), so one of the adapter's two `error` arms may be
  unreachable — which of them is a measurement.
* **Gate 16f** — whether `AZURE_OPENAI_API_VERSION` is real on the v1 surface. Two of the
  vendor's own pages still disagree; the mirror cannot resolve its own contradiction.
* **Gate 8's KB-delete silence** — §6.
* **`PLATFORM_LINES_TOTAL`** — §5.

## Existing `docs/evidence/bolna-*.md` claims checked for staleness

Nothing in the sixteen reports was found WRONG. Two are narrower than they read, and the
narrowing is this lane's finding rather than theirs:

* `bolna-request-contract.md` says *"13 `self._request(...)` call sites … No other module
  in this tree issues a Bolna request"*. The count is now **21**: D-488 added the four
  knowledge-base routes (and the reads around them) after that lane ran, and F-1 is the defect that lived in the gap.
  The "no other module" half is re-verified and still true for payload shapes; §8 records
  the one status-code probe outside the wall.
* `bolna-request-contract.md` F-2's argument for leaving `GET /providers` unpaged is
  re-read and still holds — but it reasons about `/providers` only, and its sentence *"the
  same doubt applies"* was never carried to `/knowledgebase/all`. F-1.
