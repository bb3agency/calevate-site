# Closing the loose ends: every deferral in `docs/evidence/bolna-*.md`, classified

**Scope.** All thirteen `docs/evidence/bolna-*.md` reports, read end to end, with every
item their authors marked "deliberately left alone", "reported, not fixed", "handed to",
"needs a founder decision" or "not built" extracted and given a verdict.

**The three verdicts, and what each obliges.**

| Verdict | Meaning | Obligation |
|---|---|---|
| **OURS-NOW** | The stated blocker was file ownership, a shared-tree risk, or a "don't run the full suite" instruction. Those are engineering constraints with no external clock. | **Fix it.** |
| **EXTERNAL** | Needs something outside this repo — a Bolna account, an Azure subscription, a Sarvam key, counsel, a DLT registration, a signed commercial term, or a sentence from a vendor. | Verify the named blocker is real, leave it, and make sure it is a GATE rather than a line in an evidence file. |
| **FOUNDER** | A product or commercial decision. | Leave it, and make sure it is stated where a founder will see it. |
| **CLOSED** | Already fixed by a sibling lane during the wave; re-verified in the tree here. | Nothing, except not fixing it twice. |
| **CORRECT-NO** | The lane declined to build something and the argument holds. | Nothing. Recorded so it is not re-opened by drift. |

**Headline.** Of ~90 extracted deferrals, **three were OURS-NOW and are fixed here**; one
was a judgement call handed to this lane and is **decided NO with the argument written
down**; and one item from OUTSIDE the sweep — 7 latent type defects in
`apps/api/agents/service.py`, surfaced by turning on `[tool.pydantic-mypy] init_typed` — was
handed to this lane mid-session and is fixed at the boundary (§2.5); the rest are EXTERNAL (49), FOUNDER (18), CLOSED (11) or CORRECT-NO (9). **Four
more are genuinely ours and are NOT fixed, and their blocker is not a vendor** — it is
that three other agents are writing in this repository right now and every one of those
four needs a file on the forbidden list. They are named in §4 with the exact diffs, because
"another agent holds the file this session" is an in-repo blocker with a horizon of hours,
not a schedule.

---

## 1. The classification table

### `bolna-agent-lifecycle.md`

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 1 | `toolchain.execution`: `parallel` vs `sequential` (F-5) | Two valid enum members; VERIFIED-OSS says one, VERIFIED-VENDOR-DOCS says the other; no way to observe the difference here | **EXTERNAL** — a Bolna account (gate 24). Inert with one pipeline; neither value is invalid. |
| 2 | `LlmAgentV2.routes`, WRITE side (F-2) | Not nullable, no default; `null` or `[]` would be a guess that could 400 every publish | **EXTERNAL** — the vendor documents no "off" value. Correctly not guessed. |
| 3 | `LlmAgentV2.routes`, READ side — `AgentSnapshot.static_response_routes` (F-2) | `packages/shared/.../engine.py` was Lane B's that wave | **OURS-NOW, NOT DONE — §4.1.** Hard rule 5. Blocked on `bolna.py` + `fake.py`, both under active edit by other agents right now. Exact diff already written in the lane report. |
| 4 | `calling_guardrails` / `auto_reschedule` (F-8, D-419) | Configuring them would move a dial outside our compliance gate | `auto_reschedule` is **CLOSED** (`_agent_body` now states `False`; verified at `bolna.py:2252`). `calling_guardrails` is **FOUNDER** — see #20. |
| 5 | `check_if_user_online` (F-6) | Both plausible values are product decisions | **FOUNDER** — gate 23. |
| 6 | `BOLNA_CAPABILITIES.knowledge_base = False` (F-7) | Lane G's flag | **EXTERNAL** — the vendor's `POST /knowledgebase` cannot ingest `KBSourceRef.text` at all. Not ours to close. |
| 7 | `config.py` webhook source-IP allowlist (F-3) | Cross-lane, four files | **CLOSED** — `DEFAULT_BOLNA_SOURCE_IPS` holds all three addresses; `gates_api.DOCUMENTED_EGRESS_IPS` matches; the mid-rename `NameError` the changelog lane warned about is gone. Re-verified. |
| 8 | Founder 1: what an agent says when a caller goes quiet | Product decision, no API field for the text | **FOUNDER** — and note the vendor's own guidance has the probe firing BEFORE our `hangup_after_silence: 10`. |
| 9 | Founder 3: engine-side multilingual agents | Needs a reviewed Telugu rendering of the truthful-answer directive — a legal review | **FOUNDER + counsel.** Same item as #29. |
| 10 | Founder 4: `KBSourceRef` grows a PDF/URL form | KB-tier decision | **FOUNDER** (which tier) **+ EXTERNAL** (a Bolna account to verify the round trip). |

### `bolna-call-flows.md`

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 11 | `ingest_source_config` | No documented null; sending one could break every publish | **EXTERNAL** — vendor. Gated instead. Correct. |
| 12 | `transcriber.endpointing` (250 → 400–500) and `synthesizer.buffer_size` (250 → 100–150) | The right value is a measurement gate 4 owns; changing what every caller hears from a doc audit would be a change nobody measured | **EXTERNAL** — a Bolna account and a stopwatch. **This is the cheapest latency win on the board and it is one integer**; make sure gate 4 carries it. |
| 13 | The IVR built-in | Three blockers, one (no Telugu voice) product-fatal today | **EXTERNAL** (vendor voice catalogue) **+ FOUNDER**. |
| 14 | §8 symptom 1 — the from-number never reached the dial | Needed `packages/shared/.../engine.py`, another lane's file | **CLOSED** — D-420 landed: `CallContext.from_e164`, `resolve_caller_id`, and the `number_not_bound_to_agent` rule. **Its remaining half is what this lane fixed — §2.1.** |
| 15 | §8 symptom 2 — inbound number→agent binding never reached the engine | Same file | **CLOSED** — `bind_inbound_number` / `unbind_inbound_number` on the port, both adapters, conformance. Verified present. |
| 16 | §8 symptom 3 — no published agent can carry a 140-series promotional campaign | `AgentConfig` carries no telephony provider; another lane's file | **OURS-NOW, NOT DONE — §4.2.** D-357 owns it. Needs `AgentConfig` (shared) + `_agent_body` (`bolna.py`, forbidden this session). Its *other* half is genuinely **EXTERNAL**: a 140-series number needs a Vobiz account and a DLT header registration. |
| 17 | `_STATUS_MAP` / `prepared` | Landed by a sibling lane first | **CLOSED** — verified at `bolna.py:272,292`. |
| 18 | The three webhook source IPs | Fixed as D-412/D-414 by a sibling | **CLOSED** — see #7. |
| 19 | ₹5,900 PE registration, the RBI/SEBI certificate, 140→Vobiz / 160→Plivo | Lane E's pages; decide whether the dial path can run at all | **EXTERNAL** — a DLT registration per client, and a counsel answer on whether the RBI/SEBI requirement is TRAI's or the TSP's. |
| 20 | `calling_guardrails` — send it as belt-and-braces? | An out-of-window dial is *parked for twelve hours* by the engine rather than refused, and could then be placed to a lead who went on DNC in between | **FOUNDER.** Note the corollary in `bolna-platform-changelog.md` §6.2: by sending nothing, the ENGINE is deciding our calling-hours compliance from a 9AM–9PM default it chose. |
| 21 | `inbound_limit` (default `-1`) and `disallow_unknown_numbers` | Not pinned in the agent body, for `_agent_body`'s own stated reason | **FOUNDER** — one persistent caller can burn unbounded minutes against a client's wallet and this product has no control of any shape for it. That is a product gap, not a vendor one. |

### `bolna-compliance-residency.md`

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 22 | The five Violations-API questions (what raises a flag; evidence deadline; what a `pending` flag does; what `accepted`/`rejected` mean; account vs sub-account attribution) | "For a human, not for code" | **EXTERNAL** — the vendor, in writing. Already gate 9v. Verified real: none is derivable from the mirror. |
| 23 | Recording residency | Handed to Lane D | **CLOSED** — client-facing documents corrected; `/legal/*` and `SECURITY-COMPLIANCE.md` §4 now state US-default orchestration. |
| 24 | The URN from header registration; "allocated but inactive" as a `dlt_status` value | "Adding it would be a column nobody reads" | **CORRECT-NO.** Re-opens the day a 160-series client exists. |
| 25 | The six counsel questions (DPDP §16 sufficiency; sector localisation mandates; DPDP-equivalent clauses in the sub-processor agreement; who answers a vendor "violation"; 160-series eligibility; vendor recording retention) | Legal, not code | **EXTERNAL** — counsel. All six verified as genuinely legal questions, not engineering ones. |
| 26 | §5 the residency fork (stay on Arm A / buy Enterprise residency and give up BYOK) | Stated so a decision can be taken rather than drifted into | **FOUNDER + EXTERNAL** — an Enterprise commercial term. |

### `bolna-executions-cost.md`

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 27 | Gate 7(b) — the CURRENCY of `total_cost` | Named in no first-party source; a payload capture cannot settle it | **EXTERNAL** — an invoice. **The corroboration this lane could apply is applied — §2.3.** |
| 28 | §6E — BYOK vs the bundled flat rate | Founder call, corrected by D-423 | **FOUNDER** — and the live question is the TTS rung, not BYOK. |
| 29 | §6F — `bulbul:v3` and `saaras:v3` are both OFF the preferred (flat-rate) list | D-36 is a quality decision; reversing it on price is not an adapter's call | **FOUNDER + EXTERNAL** (gate 12 negotiation; the list is "a snapshot"). |
| 30 | Gate 12(g) — is the knowledge base billed? | A pricing page that does not mention a charge is not a commitment that there is none | **EXTERNAL** — in writing from the vendor. |

### `bolna-kb-extraction.md`

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 31 | Gate 8 blockers (a) no text ingestion, (b) no `agent_id` on the KB object | Re-confirmed against the vendor's own docs | **EXTERNAL** — the vendor's API shape. |
| 32 | Does `DELETE /knowledgebase/{rag_id}` clear the agent's `vector_ids`? | The delete page is silent where the sibling dispositions page promises the cascade | **EXTERNAL** — a Bolna account. A dangling `vector_id` after an erasure is a DPDP finding, so this is the one KB question with teeth. |
| 33 | §4 — `languages_extra` is collected at intake, stored, displayed back, and never reaches the engine | "This is OURS — no external blocker — and it is a product decision, not a flag flip" | **FOUNDER.** The largest single finding in the wave. Half-wired today; the safety half is already in place (`multilingual_config: None` is stated on every publish, so no per-language prompt can silently drop `TRUTHFUL_ANSWER_DIRECTIVE`). **Building it casually is a hard-rule-5 breach the drift sweep cannot see.** See §5.1 for the founder-facing statement. |
| 34 | The disposition `test` endpoint as a third `--provider` for task #87 | Needs a credential | **EXTERNAL** — a Sarvam key or a Bolna account. |
| 35 | Is Telugu covered by the KB's `multilingual` mode? | "100+ languages" in the API description; no page enumerates Telugu | **EXTERNAL** — a probe on an account. |

### `bolna-platform-changelog.md`

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 36 | SIP FAQ contradicts the changelog | No impact (we use no SIP trunk) | **CORRECT-NO.** |
| 37 | Recording retention at the vendor is unstated | "Contact support for retention policy" | **EXTERNAL** — a contract clause. Same as #25(6). |
| 38 | Max CSV rows for a batch unstated | Only matters if batch upload is adopted | **CORRECT-NO** (we dispatch per contact). |
| 39 | `concepts/choosing-providers.md` names models found nowhere else | The page warns about itself | **CORRECT-NO.** |
| 40 | §6.2 — the engine's 9AM–9PM reschedule default is deciding our calling-hours compliance | → compliance lane | **FOUNDER** — merged with #20. |
| 41 | §6.3 — `CALL_CAP_MAX_S = 3600` may exceed the platform's own ceiling | No later page states a numeric ceiling | **EXTERNAL** — one vendor question or one long test call. **No defect either way**: ours is a cost-runaway ceiling and an engine that stops sooner is safe. |
| 42 | §7.1 — adopt sub-accounts as the per-tenant boundary | Enterprise plan, unpriced, human-gated | **EXTERNAL** — a signed commercial term. |
| 43 | §7.2 — Bolna's auto-retry vs our `retry_policy`, two ladders on one contact | Could not verify the field name from that lane's pages | **CLOSED** — the call-flows lane found it: `retry_config` is never sent (default `enabled: false`) and `auto_reschedule: False` is now stated on every publish. Grepped: zero `retry_config` references in `apps/`, `packages/`, `scripts/`. One ladder runs and it is ours. |
| 44 | §7.3 — the big red switch could reach the vendor's own queue (`stop_agent_queued_calls`) | "Worth wiring as a second arm" | **OURS-NOW, NOT DONE — §4.3.** Needs the shared `VoiceEngine` port and a caller in `apps/workers/campaign_dispatch.py`; both are other agents' files this session. Its evidence class is also weaker than the rest (an MCP tool list plus a changelog line, no `api-reference` page) — so it lands with a marked assumption or not at all. |
| 45 | §7.4 — take the webhook shared-secret header | Belongs with whoever owns `_agent_body` | **OURS-NOW, NOT DONE — §4.4.** `bolna.py` is forbidden this session. A genuine security improvement over IP-only trust. |
| 46 | `scripts/pilot/gates_api.py` mid-rename `NameError` | Reported to the D-414 lane | **CLOSED** — verified consistent. |

### `bolna-providers-llm.md`

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 47 | §4d / D-358 — `tts_voice` carries a MODEL string where a speaker belongs | Needs `ModelConfig.tts_model` **and** a real Sarvam speaker catalogue, which no page publishes | **EXTERNAL** — `GET /me/voices` on a live Bolna account. The uncertain half is now certain; the fix is still blocked. |
| 48 | §7a — move to `gpt-5.4-mini` | Its Azure list price and South India availability are both unknown here | **EXTERNAL** — an Azure subscription and Microsoft's regional price. |
| 49 | §7b — adopt `saaras:v4` for STT | Telugu code-mixed quality is unmeasured for v3 and v4 alike | **EXTERNAL** — a Sarvam account and gate 3's ear test. |
| 50 | Gate 16f — is `AZURE_OPENAI_API_VERSION` real on the v1 surface? | Two vendor pages disagree; no value is derivable | **EXTERNAL** — a Bolna account AND an Azure subscription. Correctly not invented. |
| 51 | §1b — GPT-5 models reject `temperature != 1` and draw reasoning tokens from `max_tokens` | Recorded in advance | **CORRECT-NO** — bites only if #48 is taken; the checklist already sits at the `Literal`. |

### `bolna-subaccounts-platform.md`

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 52 | §2.3 Finding A — caps but no floors, and the spend order never rotates (oldest tenant first, forever) | The durable fix is a `plans` column, which is a commercial promise; the narrower "rotate the spend order" patch was **considered and rejected** as a second mechanism the real fix must remove | **FOUNDER.** The rejection is correct and is this repo's own "one way per problem" rule applied against the author's own convenience. `runbooks/campaign-stall.md` §4a carries the operator half. |
| 53 | §2.4 Finding B — the inbound reserve may defend against a risk the vendor says does not exist (6 → 10 lines, free) | "Do not act on this from prose" — D-31/D-32/D-350 | **EXTERNAL** — one saturation test on an account (gate 13). The refusal to act on vendor prose is exactly right. |
| 54 | §2.5 Finding C — capacity splits evenly per telephony provider; our dispatcher has no notion of a provider | Not actionable until gate 13 establishes how many providers we dial through | **EXTERNAL** (the count is a pilot fact) — then **OURS**. |
| 55 | §2.6 Finding D — read `concurrency.max` from `GET /user/me` instead of typing `PLATFORM_LINES_TOTAL = 10` | Needs a `VoiceEngine` method, Lane B's file | **OURS-NOW, NOT DONE — §4.3** (same shape as #44, same two forbidden files). §2.7 raises its status: over-limit outbound is QUEUED by the vendor, so an over-high constant is a **calling-hours compliance defect**, not a throughput one. |
| 56 | §3 — the gate 10 decision | Not that lane's call | **FOUNDER + EXTERNAL.** The one question that would settle it: can an Enterprise org set `min_concurrency` on its MAIN account without sub-accounts? |
| 57 | §4 — is a plain agent's welcome message pre-cached the way a graph agent's static node is? | The mirror does not say | **EXTERNAL** — one vendor question or one time-to-first-audio measurement. |
| 58 | §6 — the `bolna-ai/skills` repo would answer the Azure credential-field question | Not fetched; a guess from an unread repo is still a guess | **CLOSED by other means** — D-417 answered the field names from `providers.md`. The repo remains an **EXTERNAL** convenience (egress). |
| 59 | §7 — Web Call SDK for cheap gate-8 probes | Beta, on request; the session-mint endpoint is an explicit placeholder in every sample | **EXTERNAL** — the vendor must enable it and publish the route. One line in the same email as gates 9 and 12. |
| 60 | §8 — voice cloning / importing | Sarvam is not a cloning provider | **CORRECT-NO.** |

### `bolna-telephony.md`

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 61 | §3c — `telephony_provider` is enumerated three different ways on one resource | No value inferred | **CORRECT-NO** — nothing parses it today; the standing instruction (treat it as an open string) is on file. |
| 62 | §3d — two `/call` request shapes | Not that lane's endpoint | **CLOSED by evidence** — the vendor publishes the tiebreak (the YAML is canonical) and our adapter already sends the OAS shape. |
| 63 | §4 — inbound linkage is not wired | `docs/PRODUCTION-READINESS.md` P4.4 owns it | **CLOSED** by D-420 for the port (#15). What remains is gate 25: **EXTERNAL** — does `/inbound/setup` accept a non-Twilio number, and what shape is `phone_number_id`? |
| 64 | §5 — Vobiz inbound is claimed with no published procedure | Vendor | **EXTERNAL.** |
| 65 | §6 — SIP / BYOT | Read in full, built nothing, "not ours" with the cost of changing that recorded | **CORRECT-NO** (revisit only on a commercial trigger). Note §2.8: BYOT SIP does **not** buy independent capacity. |
| 66 | §7a — Truecaller verification, and its "Delisting Pending" outage mode | No API; a dashboard form plus human review; **the price is published nowhere** | **FOUNDER + EXTERNAL.** The non-commercial half — a number can enter a multi-day state where every dial and every inbound call fails, with no webhook and no field we can read — is gate 27, and the interim control is procedural (never delist a number attached to a live agent). |
| 67 | §7f — the `_ASSUMED_MINOR_UNITS_PER_MAJOR` comment addition | Comment-only; deliberately not applied during a concurrent edit of `bolna.py` | **OURS-NOW — FIXED, §2.3** (with its framing corrected; see there). |
| 68 | §9 — `_agent_body`'s hardcoded `provider: "plivo"` | D-357 owns it; inventing the column mid-audit would be a second solution to a problem that has one | **Same as #16.** |
| 69 | §9 — widen `BOLNA_CAPABILITIES.number_series` to `{"standard"}` | "A decision-log entry, not a flag flip" | **CORRECT-NO.** The value stays right: 140 and 160 have no API. |
| 70 | §9 — `phone_numbers.engine_number_ref` is write-only | P4.4, closes with `PROVISIONING_IMPLEMENTED` | **EXTERNAL** — gates 25/26 (a Bolna account). The lane added the *content* the column will hold, which is the useful half. |
| 71 | §9 — `NumberPurchaseIn.series` / `.city` will have to change | Deciding needs the account, not an edit | **EXTERNAL** — gate 26. |

### `bolna-tools-integrations.md`

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 72 | Do the AI-disclosure and recording obligations follow the caller across a transfer to a human? | A legal question under the same TRAI/DPDP split D-163 separates | **EXTERNAL** — counsel. **"Transfer should not be offered to any client until it is answered"** — that sentence is the deliverable and it belongs in the sales script, not only here. |
| 73 | Cal.com booking | Would put a client's Cal.com API key in Bolna's console, outside `publish_agent` and outside our drift sweep | **FOUNDER** — and a sub-processor/DPA item if taken. |
| 74 | Which of the four uncovered verticals to seed first | Product | **FOUNDER.** Collections/EMI additionally needs an RBI recovery-agent read — **EXTERNAL (counsel)**. |
| 75 | `context_details.recipient_data` (D-422) | Needs a member on `ExecutionSnapshot`; the field carries lead PII, so where it lands is a data-model decision | **JUDGED THIS LANE — NO. §3.** |
| 76 | `error_message` on the webhook | "Not worth a field until one is observed" | **CORRECT-NO.** Superseded in detail by #83. |
| 77 | §2.3 — no tool-call timeout is documented anywhere | That absence IS the finding | **EXTERNAL** — one live observation. Our endpoint is already built for the pessimistic reading; no gap in `tool_routes.py`. |
| 78 | §2.4 — `api_token` would live in Bolna's console, not our secrets manager | Does not bite: our tool endpoint authenticates by source-IP | **CORRECT-NO**, and now a reason to keep it that way rather than an accident. |

### `bolna-request-contract.md` *(created mid-session by a sibling lane)*

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 79 | `from`/`to` sent as `+00:00` where every vendor example prints `Z` | Conformant to the declared `format: date-time`; swapping trades one unverified parser risk for another | **CORRECT-NO.** |
| 80 | `webhook_url: null` on a `type: string` | Unreachable in the publish path; omitting the key would break the sibling field's clearing semantics | **CORRECT-NO.** |
| 81 | A read-back detector for `calling_guardrails` | "Response-parsing code, owned by another lane this session" | **OURS-NOW, NOT DONE** — same blocker as §4.1/§4.4 (`bolna.py`). |

*(`toolchain.execution`, `synthesizer.provider_config` and `calling_guardrails` duplicate #1, #47 and #20.)*

### `bolna-response-contract.md` *(created mid-session by a sibling lane)*

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 82 | `AgentV2.agent_status` (`seeding` \| `processed`) is on the read-back and ignored | The vendor never says what `seeding` means, how long it lasts, or whether such an agent answers calls | **EXTERNAL** — gate 30. Building on an undefined meaning is the D-31/D-32 defect. |
| 83 | `error_message`, `hangup_by`, `hangup_reason`, `hangup_provider_code` unread | "Adding a column nobody reads is the defect that looks like progress"; `raw_document` retains the history to backfill from | **CORRECT-NO** — and the retention argument is what makes it correct rather than lazy. |
| 84 | `answered_by_voice_mail` unread | Surfacing it is a product decision about what a client's screen says | **FOUNDER** — gate 17 already holds it. |
| 85 | `GET /user/me` `wallet` — an emptying wallet fails every dial as plain `failed` | Needs a normalized port method, a shared model and a `campaign_dispatch.py` caller | **OURS-NOW, NOT DONE — §4.3.** Merged with #55: one port method answers both. |
| 86 | `apps/workers/kb_reconciliation.py:36` carries a stale cost model | "`apps/workers/` is outside this lane and the file is being edited concurrently" | **OURS-NOW — FIXED, §2.4.** The file was not in fact under edit; verified `git status` clean on it immediately before and after. |

### `bolna-pilot-scorecard.md`

| # | Item | Stated reason | Verdict |
|---|---|---|---|
| 87 | "Open items carried forward: _None recorded._" | — | Nothing to classify. |
| 88 | Four parallel asks to Sarvam (free-token permanence; Bulbul v3 beta rate; rpm→concurrency; Telugu v3-vs-v2 ear test) | Not Bolna gates | **EXTERNAL** — a Sarvam account. They move the cost model more than the Bolna gates do. |

---

## 2. What was fixed

### 2.1 The campaign gate now refuses a number bound to NO agent — hard rule 5

**File:** `apps/api/campaigns/service.py::_channel_blockers`.

D-420 landed half a claim. The gate refused a campaign whose approved number was bound to a
*different* agent, and let through one bound to *nobody* — which resolves to no caller ID at
all, so the dial goes out on the engine's own pool. The contradiction case is a console
misconfiguration; the absence case is **every campaign on the platform**, presenting the
vendor's number while our records show a registered client header approved. The lane that
found it left it only because every campaign fixture in `tests/` provisioned its number
unbound.

**The rule is now one equality, and that is the point:**

```python
if facts.number_agent_id != facts.agent_id:
```

The old form was `number_agent_id is not None and number_agent_id != agent_id`. The `is not
None` guard *was* the hole, so the fix deletes it rather than adding a second branch beside
it. **What remains cannot be loosened by deleting a clause, because there is no clause left
to delete** — `None` is refused because it is not equal, not because someone remembered to
handle it. A second `is None` branch would have re-created exactly the surface that failed.

`is None` survives only in the *wording*: a client who never assigned the number and a
client who assigned it elsewhere need different next actions. Both raise the same rule name
`number_not_bound_to_agent` — one violated claim, one name — with the two reasons kept as
module constants beside `NO_PROVENANCE_REASON` / `PURCHASED_LIST_REASON`, which is the
pattern that block already exists for ("so the same condition is never explained two
different ways").

Asked at BOTH gates, because `_channel_blockers` feeds `launch_blockers` *and*
`dispatch_blockers`: a number can be unassigned from an agent mid-campaign, and the tick is
what re-reads it.

**No new rule name was introduced**, deliberately: `apps/web` is not mine this session, and
`BLOCKER_COPY` there falls back to the server's `reason` for an unknown rule — so a new name
would have shipped a client-facing to-do list entry nobody wrote copy for.

**Test:** `tests/caller_id_and_inbound_routing_test.py::test_a_number_bound_to_nobody_cannot_be_the_campaigns_approved_header`
— asserts the rule at launch AND at dispatch, asserts the reason is the *unbound* one, and
asserts the two reasons differ.

**SABOTAGE — RED.** Restoring the `is not None` guard (`cp` backup, never `git checkout`):

```
SABOTAGED: restored the `is not None` guard that let an unbound number through
>       assert "number_not_bound_to_agent" in at_launch, (
E       AssertionError: the gate approved a header no agent dials from, so the campaign
        would have gone out on the engine's own pool with our own records showing it cleared
E       assert 'number_not_bound_to_agent' in {'agent_not_live': ..., 'dlt_template_missing': ...}
tests/caller_id_and_inbound_routing_test.py:337: AssertionError
FAILED tests/caller_id_and_inbound_routing_test.py::test_a_number_bound_to_nobody_cannot_be_the_campaigns_approved_header
1 failed, 10 passed, 1 warning in 0.92s
```

**RESTORE — GREEN.**

```
297:        if facts.number_agent_id != facts.agent_id:
11 passed, 1 warning in 0.94s
```

### 2.2 The shared fixtures now provision a BOUND number — 16 files

Sixteen files each carried their own `INSERT INTO phone_numbers`, all omitting `agent_id`.
Each now binds the number to the campaign's own agent. **Which tests changed meaning, and
why that is correct, is §2.6** — it is the important part and it is short, because only two
tests were ever *about* the unbound state and neither was one of the sixteen.

Two files got more than a bound column, and the difference matters:

- **`tests/compliance_audit_test.py`** and **`tests/dispatch_scale_test.py`** now SELECT an
  existing registered header for the agent and insert only if there is none. Both files call
  their campaign fixture **twice for one agent**, and `resolve_caller_id` **refuses** an
  agent carrying two registered headers (it cannot tell which traffic class is dialling).
  A header per campaign would have satisfied the launch gate by breaking the dial —
  see §2.6.
- **`tests/cross_tenant_reference_test.py`** was deliberately **left unbound**. Its two
  numbers exist to be refused at the ownership boundary before any gate runs; binding them
  would add a fact the test does not use.

`tests/caller_id_and_inbound_routing_test.py::_number` already took `agent_id` (the D-420
lane wrote it) and is the one helper that can still produce an unbound number — on purpose,
by explicit `agent_id=None`, which is what the new test passes.

### 2.3 `_ASSUMED_MINOR_UNITS_PER_MAJOR` — the telephony lane's §7f, with its framing corrected

`apps/api/engine/bolna.py`, comment only, no behaviour. Applied under gate 7's **(b) the
CURRENCY** paragraph rather than verbatim where §7f proposed it, and the difference is not
cosmetic: §7f was written against a version of that block that settled the UNIT by a
*precedence rule*, and argued it upgraded that reasoning. The block has since moved past
that — D-412 settled the unit with a **worked execution example** — so pasting §7f's framing
("rather than a precedence rule applied to two documents that contradict each other") would
have introduced a contradiction inside one comment. What the phone-number evidence uniquely
adds is the thing the execution example could **not** give: the vendor writing "cents" and
"$5.0" for the same price, i.e. a **dollar sign next to the word**. That is evidence for
(b), which is the half still open. The applied text says so, says it is a different schema
on a different endpoint so it is not proof about `AgentExecution.total_cost` (the D-350
mistake that block exists to prevent), and says it still does not close (b) — the wallet
unit "credits" is the residue, and gate 7 still has to read an invoice.

Verified inert: `ruff` clean, `tests/bolna_snapshot_test.py` 62 passed. Concurrent hunks in
that file were checked first and none is within 300 lines of this one.

### 2.4 `apps/workers/kb_reconciliation.py` — a cost model for a round trip that does not happen

Its docstring justified three tuning constants (`KB_SWEEP_BATCH_SIZE = 15`,
`KB_SWEEP_BUDGET_S = 180`, hourly) on the arithmetic of `bolna.list_kb` fetching the whole
account's knowledge list once per agent per tick. Since D-354, `BolnaEngine.list_kb` opens
with `require_capability("knowledge_base")` and raises — **the sweep makes no vendor call at
all on this engine.** That is not a harmless stale comment: the bounds below it are
*justified by* the amplification, and a reader tuning them would be tuning against
arithmetic that does not exist.

Corrected rather than deleted. The bounds are re-stated as being for the engine that *will*
answer `list_kb` — which is what they were designed for and what they must survive the day
the capability flips or a second adapter carries it — so nobody has to re-reason the sweep
then. `tests/kb_drift_reconciliation_test.py` 26 passed; the file was `git status`-clean
immediately before and after, contrary to the reporting lane's assumption.

### 2.5 `apps/api/agents/service.py` — 7 latent defects surfaced by `init_typed = true`

**Not from the deferral sweep** — handed to me mid-session by the coordinator because I own
the file. Another lane found that this repo declares `plugins = ["pydantic.mypy"]` and never
configured it, so `init_typed` defaulted to `false` and every Pydantic model's synthesised
`__init__` took `Any`: **argument PRESENCE was checked and argument TYPE never was.** Turning
it on surfaced 7 errors in `agents/service.py`, all one shape — `_load_agent` returned
`dict[str, object]` and `_to_config` fed those values straight into `AgentConfig` and
`ModelConfig`, including `direction`, whose field is `Literal["inbound","outbound","both"]`.

Fixed at the boundary, the way the type-sweep lane fixed `apps/api/engine/fake.py::_StoredCall`
— **not** with `cast()`, which silences the checker and leaves the row unguarded, and **not**
by widening any `Literal`:

- **`AgentRow` TypedDict** — the row declared where it is READ. Consumers (`posture_of`,
  `_assert_has_a_script`, `_to_config`, `_call_prompt_for`, `_variant_config`) take
  `AgentRow`, which a TypedDict makes deliberately non-assignable back to `dict[str, X]`, so
  the type cannot be widened halfway along the path by accident.
- **A TypedDict alone would have been a cast in disguise**, because the row is built from
  `row[i]` and SQLAlchemy hands back `Any` — the values would be *declared* rather than
  *known*. So the one field that lands on a `Literal` is narrowed by a real predicate with a
  real refusal at the read: `_is_agent_direction` (a `TypeGuard` — it ASKS, where a cast
  asserts) and a new `agent_direction_unrecognised` business-rule refusal.
- **`AgentDirection` in `agents/models.py`**, with `AGENT_DIRECTIONS = get_args(...)` derived
  from it (D-104's rule, in the only possible direction — a tuple cannot be turned back into
  a type). `ck_agents_direction_enum` renders from the tuple, so the CHECK constraint and the
  Literal cannot disagree; the rendered SQL is byte-identical to before.
- **`InCallLLM` TypedDict** for `in_call_llm`'s return. This one is why *seven* errors came
  from *one* mistake: `**in_call_llm(...)` splatted a `dict[str, object]` into
  `ModelConfig(...)`, and an `object` value unpacked through `**` widens **every** keyword at
  that call site — so the four speech fields beside it were unchecked too.
- `cast(int | None, agent.get("max_call_duration_s"))` deleted: the row now says `int | None`.

**Three tests, in `tests/agent_publish_hosting_test.py`.** The refusal arm HAD to be covered
rather than suppressed — an uncovered branch on this surface moves the ratchet, and
CLAUDE.md's own guidance is to ask whether the branch should exist before reaching for a
waiver. It should: `ck_agents_direction_enum` makes it unreachable through the front door,
but a restore that lands without constraints (`runbooks/restore-drill.md` walks that path), a
table rebuilt by a migration, or one hand-run UPDATE all produce the row it refuses. It is
driven with a **stub session** feeding `_load_agent` exactly what a constraint-less database
would return — rather than by dropping a CHECK on a database three other agents are sharing,
where DDL that escaped its own test would be unreproducible.

**SABOTAGE 1 — the predicate stops asking** (`return True`, i.e. the cast this guard replaced):

```
E           AssertionError: sideways
E           assert not True
E            +  where True = <function _is_agent_direction at 0x7f515f873c40>('sideways')
E       Failed: DID NOT RAISE ProblemError
FAILED tests/agent_publish_hosting_test.py::test_every_direction_the_vocabulary_admits_is_recognised_and_nothing_else_is
FAILED tests/agent_publish_hosting_test.py::test_a_direction_the_constraint_would_have_stopped_is_refused_at_the_read
2 failed, 8 passed, 3 warnings in 0.70s
```

**SABOTAGE 2 — the tuple is retyped by hand instead of derived:**

```
E       AssertionError: the tuple and the Literal have drifted, so the database and the type now admit different sets of directions
E       assert ('inbound', 'outbound') == ('inbound', '...ound', 'both')
FAILED tests/agent_publish_hosting_test.py::test_the_direction_vocabulary_has_one_source_and_the_check_constraint_renders_from_it
1 failed, 9 passed, 3 warnings in 0.64s
```

**RESTORE — GREEN:** `10 passed`, and `uv run mypy apps packages` → *Success: no issues found
in 238 source files*.

**One unplanned demonstration, worth recording — AND ITS PROVENANCE CORRECTED.** Minutes
after the fix landed, a concurrent `mypy` run produced `Extra key "stt_provdier" for
TypedDict "AgentRow"` — a one-character transposition in a column name. Before `AgentRow`
that typo would have type-checked, run, and delivered `stt_provider=None` to the engine on
every publish: an agent with no transcriber, discovered on a client's call. That is the
whole argument for declaring the row rather than annotating it `object`.

⚠ **BUT IT WAS NOT A LIVE DEFECT, AND THIS PARAGRAPH ORIGINALLY SAID IT WAS.** The
transposition was a SABOTAGE deliberately introduced at `service.py:389` by a second agent
verifying the very same guard, restored from a backup moments later; this lane's `mypy` run
happened to observe the tree mid-sabotage and read the result as a real typo somebody had
just made. `stt_provider` has been spelled correctly throughout, confirmed by sha256 against
the pre-edit backup. The demonstration stands as a demonstration — the guard did catch a
transposition it would previously have missed — but nothing was caught **in production
code**, and this file claimed otherwise for the length of one audit.

The correction is kept rather than the sentence quietly rewritten, because the failure mode
is the interesting part: **two agents sharing one working tree can read each other's
temporary states as findings.** An evidence file is only worth what its weakest claim is
worth, and "a concurrent run observed X" is not the same class of statement as "the code
contained X". The instrument that settled it was a hash, not a memory.

**The 8th error, in `packages/shared/tests/engine_conformance/contract_test.py`, is the
coordinator's** and was left alone; it is clear in the tree as of my last run.

### 2.6 Which tests changed meaning — the honest list

**Only one test went red from the fixture change, and its red was a real defect the fixture
had been hiding.**

`tests/dispatch_scale_test.py::test_two_campaigns_in_one_tenant_still_share_one_tenant_budget`

```
ERROR  apps.api.agents.service:service.py:1182 agent_caller_id_ambiguous
WARNING apps.workers.campaign_dispatch:campaign_dispatch.py:914 campaign_dial_failed
>       assert sum(dialing.values()) == 3, "the ceiling is the tenant's, not each campaign's"
E       assert 0 == 3
```

The naive fix — one bound header per campaign — gave that agent **two** registered headers,
which `resolve_caller_id` refuses by design (a coin toss between a promotional and a
transactional header is a DLT misclassification with the client's PE on the complaint). So
the dispatcher placed **zero** calls. Note what that would have done to the sibling test in
`compliance_audit_test.py`, which asserts `dialing <= 2`: **zero satisfies it.** That test
would have gone green while measuring nothing. Both files therefore reuse one header per
agent, which is also the only state production permits, and the assertions they made before
are the assertions they make now — `== 3` in the strict one, and `<= 2` in the other with
the strict one standing behind it.

**No test in the sixteen was exercising the unbound case.** Every one of them provisioned an
unbound number incidentally, because the column existed and nothing read it — which is
precisely why the hole survived. The unbound case now has exactly one owner, and it asserts
a refusal rather than relying on a default:

```python
number_id, _ = await _number(tenant_id, agent_id=None)  # the only unbound number in the suite
```

**One helper hardened against the class of mistake rather than the instance.**
`tests/campaigns_test.py::_number` takes `agent_id` as **keyword-only with no default**, so
the next launch-ready fixture cannot be silently un-launchable. A default would have
re-created the exact condition that made this hole invisible for the life of the gate.

**Nothing was weakened.** No assertion was relaxed, no test was deleted, no `for testing`
door was opened, and the gate is strictly stronger than before: it now refuses a superset of
what it refused, under the same rule name.

### 2.7 Verification

| Gate | Result |
|---|---|
| Every file that provisions a `phone_numbers` row, plus every file that launches or dispatches a campaign (34 files) | **611 passed** |
| Same 25-file set, before any change (baseline) | 397 passed |
| `packages/shared/tests/engine_conformance` | **202 passed** |
| `uv run mypy apps packages` | **Success: no issues found in 238 source files** — including the 7 errors of §2.5, and re-run after the sabotage was restored |
| `tests/agent_publish_hosting_test.py` (3 new) | **10 passed**; 2 sabotages RED, restore GREEN, §2.5 |
| Agent-path suites (11 files: publish, verification, disclosure, voice, variants, in-call LLM, edge routes, read-back) | **180 passed** |
| `uv run ruff check` / `format --check` on my files | clean; 18 files left unchanged |
| Sabotage | §2.1, RED and GREEN both pasted |

Two things in the tree are red and are **not mine**, both from agents running concurrently:

- `uv run ruff check .` reports `I001` in `apps/api/crm/models.py` and `ruff format --check`
  wants to rewrite `apps/api/engine/fake.py`. Both files are `M` in `git status` from other
  lanes' in-flight work. I did not run a repo-wide `ruff format` — CLAUDE.md's own warning
  about that command applies double while somebody else is mid-edit.
- `tests/docs_drift_guard_test.py::TestAnsweredAssumptions::test_the_live_roster_and_scorecard_agree_with_the_live_docs`
  fails: *"`docs/evidence/bolna-response-contract.md:566` marks an assumption against gate
  29, and OPERATIONS §2 has no gate 29."* That evidence file was created at 05:45 today by a
  sibling lane and its gate rows are yours to apply centrally. It clears the moment gates
  29–31 land.

**`make coverage-ratchet` was not run** — it is the coordinator's.

---

## 3. D-422 — `context_details.recipient_data`: the answer is NO

I was asked to judge whether to wire it. **No, and the entry should be closed rather than
left open**, for four reasons in descending order of weight.

1. **The check has no reachable failure mode.** `user_data` is built by us in
   `agents.service.dispatch_call` from our own rows, sent in one request, and echoed back by
   the vendor. The only way the comparison can ever disagree is if Bolna corrupted our own
   JSON in transit — which would surface far louder elsewhere, and which nothing has ever
   observed. CLAUDE.md's own ratchet note names this shape: a defensive arm that cannot be
   reached is usually a sign the data was fetched twice.
2. **The version that is free to build is the one that answers nothing; the version that
   answers something is not free.** Compare-and-discard costs nothing and finds nothing.
   Storing the echo puts `lead_name`, `context_note` and `prior_call_summary` — lead PII —
   into a **second** place, with its own retention clock, its own erasure obligation and its
   own redaction question, to duplicate a fact we already hold under DPDP.
3. **The question it is supposed to answer is already answered, and better.**
   "Did this call run with the context we intended?" is answerable from our side today: the
   `calls` row carries the ids, and `get_execution` seals the entire vendor document into
   `ExecutionSnapshot.raw_document`, which the pipeline archives. If the question is ever
   asked in anger, the evidence is already retained — without a typed column, and without a
   second copy of a lead's name.
4. **A sibling lane reached the same verdict independently**, from the response side rather
   than the tutorial side: `context_details` is *"unread, correctly … because we already
   know what we injected"* (`bolna-response-contract.md` §3.6).

**What would reopen it**, so this is a decision rather than a shrug: an observed call whose
extraction does not match the lead it was dialled for. That is a *data* symptom, it would
show up in the CRM before it showed up in a field diff, and the raw document needed to
diagnose it is already on disk. If it ever happens, the echo becomes worth reading — as a
compare-and-alert on ids only, never as a stored copy of the payload.

D-422's other instruction stands and is worth repeating because it is the trap: do **not**
start reading `context_details.recipient_phone_number`. `telephony_data.{from,to}_number` is
the OAS-backed spelling and a second one is the two-ways-of-doing-one-thing defect.

---

## 4. Ours, and NOT fixed — the blocker is another agent's file, not a vendor

These four are engineering, have no external dependency, and are the next things done. I did
not land them because each needs a file this session's brief puts off limits
(`apps/api/engine/bolna.py`, `apps/api/engine/fake.py`, `apps/workers/campaign_dispatch.py`)
and `git status` confirms other agents are writing in three of them **right now** — a
whole-file race in `tests/dispatch_budget_test.py` during this session (a sibling added
three tests between my read and my write) is the concrete evidence that the risk is not
theoretical.

### 4.1 `AgentSnapshot.static_response_routes` — the highest-value item left, and it is hard rule 5

Bolna's `LlmAgentV2.routes` answers a matched caller utterance from **configuration, with
the LLM never asked**. A route whose utterances include "are you a robot" or "is this
recorded" would answer untruthfully while `carries_prompt_marker` still reported the floor
present, because `TRUTHFUL_ANSWER_DIRECTIVE` is an instruction to a model that is not
consulted. `AgentSnapshot` has no field that can see the layer, so the publish read-back and
the drift sweep would both report the agent compliant — indefinitely.

The exact diff is already written out in `bolna-agent-lifecycle.md` §F-2: two fields on
`AgentSnapshot` (a COUNT and a `*_readable` flag, never the routes themselves — hard rule 2),
`_agent_static_routes` in `bolna.py`, `(0, True)` in `fake.py`, one conformance clause, and
one entry in `agents/verification.py::judge` where `False` is a REFUSAL. **Only the last of
those five is in my files.** Nothing was half-wired here: a snapshot field with no adapter
reading it is worse than the gap.

### 4.2 `AgentConfig` carries no telephony provider (D-357 / D-420 symptom 3)

`_agent_body` hardcodes `provider: "plivo"` for every agent, and 140-series is carried by
Vobiz. A promotional campaign passes every gate and is handed to an agent on the wrong
carrier. Needs `AgentConfig` (shared) and `_agent_body` (`bolna.py`). Note the *other* half
is genuinely EXTERNAL — a 140-series number needs a Vobiz account and a DLT header
registration — so this one does not become dialable the day the code lands.

### 4.3 One `VoiceEngine` method answers three findings at once

`GET /user/me` returns `concurrency: {max, current}` and `wallet`. That single normalized
read closes: `PLATFORM_LINES_TOTAL = 10` being typed in while the vendor's tier text says it
*"scal[es] automatically with monthly usage"* (#55); a free cross-check on our own
`total_active` arithmetic; and an emptying wallet currently failing every dial as an
anonymous `failed` (#85). §2.7 of the sub-accounts report is what raises it from tidiness to
compliance: over-limit outbound is **queued** by the vendor, so an over-high constant means
contacts cleared at 20:55 IST dialling after 21:00 from a queue we cannot see or scrub.
Suggested shape (hard rule 2 — the dispatcher is in `apps/workers/` and may not see a vendor
payload): `async def get_account_capacity(self) -> EngineCapacity` returning
`(max_concurrent, current_concurrent, wallet_balance)`. Needs `packages/shared`, both
adapters, conformance, and a caller in `campaign_dispatch.py`. The same port method makes
#44 (the big red switch reaching the vendor's own queue) a second, smaller step.

### 4.4 The webhook shared-secret header, and a `calling_guardrails` read-back detector

Both live in `_agent_body` / the response parser in `bolna.py`. The first is a real security
improvement over IP-only trust for an unsigned engine; the second sees a console-set
guardrail our publishes cannot see. Small, unblocked by any vendor, blocked by the file.

---

## 5. For the founder — the four that cost something to leave open

1. **Multilingual (#33).** A Telugu-first product publishes single-language agents while the
   engine supports per-language prompts, voices and switching. A client picks Telugu + Hindi
   + English at intake step 3 and gets one language. **The blocker is not the vendor — it is
   that our data model has one prompt and one voice.** And the warning that must travel with
   the decision: closing it without composing `TRUTHFUL_ANSWER_DIRECTIVE` into **every**
   per-language prompt is a hard-rule-5 breach the drift sweep structurally cannot see,
   because `AgentSnapshot` has no language dimension. Decide whether to build it; do not let
   it be built casually.
2. **Concurrency floors (#52).** We have caps and no floors, and the shared pool is spent in
   uuid_v7 order on every tick — oldest tenant first, forever. At the shipped constants the
   whole platform's outbound budget is 6 lines while one tenant's ceiling is 10. Client #12
   can be starved indefinitely while every tick reports `dialled=N`. A floor is a plan
   column *and a commercial promise*, which is why it is yours; the reference algorithm is
   published by the vendor whose scheduler we sit in front of.
3. **Transfer to a human (#72).** Do our AI-disclosure and recording obligations follow the
   caller across the transfer, and is an inverse disclosure required at the handoff?
   **Transfer should not be offered to any client until counsel answers.** The engineering
   after that is straightforward.
4. **160-series eligibility (#19/#25).** If the RBI/SEBI certificate requirement holds in
   practice, our SMB clients are **140-series only** and every campaign they run is
   promotional. Our code is already built that way and needs no change — **the sales copy
   does.** A `service` campaign on a 160 number is not something a non-BFSI SMB can have on
   this vendor's path.

---

## 6. Exact text for the central files

`docs/ROADMAP.md` and `docs/OPERATIONS.md` are not mine this session. Apply verbatim.
**The new row below was written with a `D-NEXT` placeholder rather than a number**, because
the log ran to D-424 and five sibling lanes filed evidence in the same wave that also proposed
rows — any number picked here would have collided or dangled, and a dangling citation is what
`docs_drift_guard::dangling_decisions` fails on. **APPLIED 21 Aug 2026 as D-427.** The D-422
replacement below keeps D-422: it amends the existing row in place rather than adding one.

### 6.1 `docs/ROADMAP.md` §6 — new decision-log row — APPLIED as D-427

> | D-427 | **THE DIAL GATE'S LAST HOLE IS CLOSED: an approved number bound to NO agent is now refused, and the rule is one equality so there is nothing left to delete.** | D-420 landed half a claim. `campaigns.service._channel_blockers` refused a campaign whose approved number was bound to a DIFFERENT agent and let through one bound to NOBODY — which `agents.service.resolve_caller_id` resolves to `None`, so the dial goes out on the engine's own pool (*"a `+91` prefix phone"*, VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/guides/outbound/making-outgoing-calls.md`). The contradiction case is a console misconfiguration; **the absence case is the default state of every number this product has ever provisioned**, so the 140/160 series check, the DLT header registration and the whole PE/TM model described one number while the vendor's dialled. The condition was `number_agent_id is not None and number_agent_id != agent_id`; it is now `number_agent_id != agent_id`. **The guard WAS the hole, so the fix deletes it rather than adding a branch beside it** — what remains cannot be loosened by removing a clause, because `None` is refused for being unequal rather than because someone remembered to handle it. `is None` survives only in the wording: `UNBOUND_NUMBER_REASON` and `OTHER_AGENT_NUMBER_REASON` sit beside `NO_PROVENANCE_REASON` under one rule name, `number_not_bound_to_agent` — one violated claim, one name, two next actions. Asked at launch AND on every dispatch tick, because a number can be unassigned mid-campaign. | **WHY IT WAITED, AND WHY THAT REASON EXPIRED.** The finding was left by the lane that made it because every campaign fixture in `tests/` provisioned its number unbound — sixteen files, in a tree three agents were writing in. Sixteen fixtures now bind the number to the campaign's own agent. **Two of them additionally REUSE one header per agent, and that is the part worth remembering**: `resolve_caller_id` refuses an agent carrying two registered headers, so a header per campaign satisfies the launch gate by breaking the dial — `dispatch_scale_test` went red with `agent_caller_id_ambiguous` and zero dials, while its sibling in `compliance_audit_test` would have gone GREEN on zero, since `dialing <= 2` is satisfied by nothing dialling at all. **The generalisable rule: a fixture that models a state production refuses does not fail, it measures nothing.** `tests/campaigns_test.py::_number` now takes `agent_id` keyword-only with NO default, so the next launch-ready fixture cannot be silently un-launchable — a default would re-create the exact condition that hid this hole for the life of the gate. Evidence and the full deferral sweep: `docs/evidence/bolna-deferrals-closed.md`. |

### 6.2 `docs/ROADMAP.md` §6 — REPLACEMENT for the D-422 row (it is decided, not open)

> | D-422 | **`context_details.recipient_data` is a real return channel and we DECLINE to read it. Closed, not deferred.** | Four Bolna tutorials show the post-call webhook echoing the `user_data` our `start_outbound_call` sent, under `context_details.recipient_data`. Reading it would let us verify which context a call actually ran with (the D-21 drift question). **The answer is no, on four grounds.** (1) **The check has no reachable failure mode** — we build `user_data` from our own rows, send it in one request, and the only way the echo can disagree is the vendor corrupting our own JSON; CLAUDE.md's own ratchet guidance names an unreachable defensive arm as a symptom, not a control. (2) **The free version answers nothing and the useful version is not free** — compare-and-discard costs nothing and finds nothing, while STORING the echo puts `lead_name` / `context_note` / `prior_call_summary`, i.e. lead PII, into a second place with its own retention clock and erasure obligation, to duplicate a fact we already hold. (3) **The question is already answered better**: `get_execution` seals the entire vendor document into `ExecutionSnapshot.raw_document` and the pipeline archives it, so the evidence is retained without a typed column. (4) A second lane reached the same verdict independently from the response side (`docs/evidence/bolna-response-contract.md` §3.6). **WHAT WOULD REOPEN IT:** an observed call whose extraction does not match the lead it was dialled for — a data symptom that surfaces in the CRM before it surfaces in a field diff, diagnosable from the raw document already on disk. It would then land as a compare-and-alert on IDS ONLY, never as a stored payload. **The standing trap is unchanged:** do NOT start reading `context_details.recipient_phone_number` — `telephony_data.{from,to}_number` is the OAS-backed spelling and a second one is the two-ways-of-doing-one-thing defect. | Evidence: `docs/evidence/bolna-tools-integrations.md` §4.1, `docs/evidence/bolna-response-contract.md` §3.6, decided in `docs/evidence/bolna-deferrals-closed.md` §3. |

### 6.3 `docs/OPERATIONS.md` §2 — one sentence to APPEND to gate 4 (latency)

> **TWO INHERITED KNOBS TO SET WHILE THE STOPWATCH IS OUT, and they are one integer each** (`docs/evidence/bolna-call-flows.md` §6). `transcriber.endpointing` defaults to 250 ms while the vendor's own latency guide says *"Increase to 400–500ms for callers who pause mid-sentence (non-native speakers, elderly)"* — which describes our callee population in its first clause. `synthesizer.buffer_size` defaults to 250 while the same guide says *"A buffer of 100–150 characters is typical"* and *"Smaller buffers start audio sooner"* — **their schema default is roughly double their own recommendation and we are on it.** Neither was changed from a document audit, because changing what every caller hears needs a measurement rather than a citation. Measure both against the default in the same session, and capture `latency_data.region` while you are there: it returns `in`, so the platform HAS a region concept and reports it per execution — which is worth having on file given how weak CLAUDE.md says the residency claim is.

---

## 7. What this lane did not do

- **Did not run `make coverage-ratchet`** (the coordinator's) or the full suite. 34 files
  were run: every file that provisions a `phone_numbers` row and every file that reaches
  `launch_campaign`, `launch_blockers`, `dispatch_blockers` or the dispatch tick.
- **Did not touch** `docs/ROADMAP.md`, `docs/OPERATIONS.md`, `CLAUDE.md`,
  `tests/fixtures/coverage_baseline.json`, `bolna-findings/**`, `runbooks/alarm-index.md`,
  `apps/workers/campaign_dispatch.py`, or `apps/web/**`.
- **Touched `apps/api/engine/bolna.py` once**, for the comment in §2.3, after checking that
  no concurrent hunk was within 300 lines of it, with an anchored single-string edit rather
  than a file rewrite.
- **Edited `apps/api/agents/service.py` and `apps/api/agents/models.py`** (§2.5) only after
  the coordinator asked for it — the file is in my ownership grant but was `M` from another
  lane, so every change is an anchored edit, never a whole-file rewrite.
- **Did not `git checkout`, `git stash` or `git commit` anything.** The one sabotage used a
  `cp` backup, restored from it, and the restore is verified in §2.1.
