# Calevate and ThinnestAI (Ashutosh K): the relationship from day 1, 23 Oct 2026

ThinnestAI hosts every Calevate call: numbers, telephony, speech recognition, the call loop and,
on Clear, the voice. Pipecat was removed (D-763), so there is no second engine.

**Evidence classes.** VERIFIED-VENDOR-DOCS = the hash-pinned mirror `thinnest-findings/mirror/`
or the live `app.thinnest.ai/openapi.json` read on the date given. VENDOR-STATED = Ashutosh's
emails, relayed by the founder (`docs/vendor/thinnest-replies-2026-10-12.md`, "replies" below;
`docs/evidence/thinnest-ai-evaluation.md`, "eval" below). VENDOR-PUBLISHED = thinnest.ai pages.
FOUNDER-RELAYED = the 6 Oct call. OBSERVED = our production. ESTIMATE / ASSUMPTION / UNKNOWN as
stated.

## 1. Timeline

| Date (2026) | We asked | Ashutosh answered or did | What it changed (D-number) |
|---|---|---|---|
| 6 Oct | First recorded contact: founder's call and email; 13 questions (eval §6) | ₹1/min BYOK incl. telephony, 30 s pulse, PAYG 5 concurrent calls, "limits raised on request", reselling permitted (eval §2, FOUNDER-RELAYED) | D-678 (ThinnestAI engine), D-681 |
| 7 Oct | The 13 questions | Voice-only BYOK ₹1.50; customer cap "PAYG 3, raised on request"; forwarding supported; will sign a DPA; training off on PAYG "on request, from day one"; offered live tests on Airtel/Jio/Vi/BSNL; `costMicro` added to Get Call (eval §10) | D-682, D-687 |
| 8 Oct | Follow-up list | Built per-agent `byok`, live transfer, business-details API, error `code`s, erasure incl. recordings (eval §12) | D-688, D-690, D-693 |
| 9 → 11 Oct | 20 questions | Caller lookup, fixed action IP, status endpoint, number move, id fixes; Pro = 10 concurrent and **"the concurrency limit is raised free on request"** (eval §10a; OPERATIONS T-7) | D-736, D-737, D-743 |
| 10 → 12 Oct | API field requests (`thinnest-api-requests-2026-10-10.md`) | Every Voice-page setting put on the API; `surfaces` writable; top-up fee only 2.36%; `GET /models` prices; BYOK voice paging (replies §2) | D-754 |
| 11 Oct | Gemini on our key | Offered our model + our voice + their STT at ₹1/min (replies §1) | — |
| 12 Oct | Consolidated email | Partial answers; **"We can negotiate if you have minimum monthly commitment with higher volume"** (replies §7-§8; rememory 60652b5b) | — |
| 13 Oct | Same, plus TRAI reg 4 | Scope `llm` built; then the fourth choice `llm_voice` at ₹1.00 built the same day; three of his bugs fixed (glued retries, false do-not-call, bracket text); first word cut to ~0.4-0.5 s; reg 4 relayed from Plivo, still open (replies §10-§11.7) | D-762, D-764 |
| 14 Oct | Follow-up | Per-agent scopes, per-call token `usage`, `call.problem` for key failures (replies §12) | D-769 |
| 14 → 15 Oct | Eight build requests A-H | **All eight built and live in a day**: per-call `billing`, `ttsCharacters`, estimated-token flag, shared clones, per-call content delete and shorter retention, `contact.erased`, `byok.changed`, `own` voices (replies §14) | D-796, D-797, D-798 |
| 16 → 18 Oct | 18 questions | List Calls `billing`; `languages`; docs error he called "a mistake in our API reference" fixed; prices: Scale 5% off, "no further volume rate", **not passed to client workspaces**; 140-series needs a ₹1 lakh carrier minimum (replies §16) | D-813, D-815 |
| 19 Oct | 17 questions | Releases live; the exact prompt text he adds; corrected his own forward-billing answer; fixed the webhook 500s we reported. DPA, training, Plivo not answered (replies §18) | D-834, D-835 |
| 21 Oct | 14 items (§20) | Built `ownRules`, Test Chat call mode, inbound `to`; volume price and carrier tests not answered (replies §21) | D-847 |
| 21 Oct | 5 items (§22) | Default call rules verbatim; per-second billing only on our own telephony (replies §23) | D-850 |
| 21 Oct | Latency (§24) | Built `earlyAnswers`; measured Google's ~1 s floor for us; offered per-turn logs (replies §25) | D-852 |
| 21 Oct | §26 | Accepted the logs offer; declined the priority opt-in (rememory 0d9429bf) | — |
| 23 Oct | §27 sent: plan PAYG → Scale at 10 → Enterprise at 50, raised limits | Trigger: production `409 "Pay as you go includes 2 agents"` (OBSERVED, rememory 4360ad72). **Answered the same day (replies §28):** plan accepted; 100 agents on the developer workspace (counted per workspace; client workspaces 2 each on PAYG, raised on request); 100 customer workspaces; 20 concurrent calls; Studio band and cloning on PAYG at ₹3/min, 25 clones; raises carry to Scale; Scale discounts reach client workspaces; credit pays for own-key minutes and numbers, rolls over 3 months; training exclusion in writing; DPA "shortly". Follow-up: how many Studio minutes, from when | D-859 (per-workspace agent count) |

## 2. Goodwill ledger: what he has done for us

| What | When | Evidence |
|---|---|---|
| Per-agent `byok` (Clear and Studio in one workspace) | 8 Oct | eval §12 item 1 |
| Live transfer built | 8 Oct | eval §12 item 2 |
| All Voice-page settings on the API, at our request | 12 Oct | replies §2 |
| The two set-ups the founder wanted (`llm`, `llm_voice` at ₹1.00) | 13 Oct | replies §11.2, §11.7 |
| Eight requests A-H built in a day | 15 Oct | replies §14; checked against the docs, `docs/evidence/thinnest-reply-2026-10-15.md` |
| `ownRules`, Test Chat call mode, inbound `to` | 21 Oct | replies §21; VERIFIED in live openapi.json 21 Oct (§23) |
| `earlyAnswers` switch | 21 Oct | replies §25; VERIFIED live openapi.json 21 Oct |
| Fixed bugs we reported (glued retries, false do-not-call, webhook 500s, docs errors) | 13-19 Oct | replies §11.2, §16.0, §18.0 |
| Corrected his own wrong answers in writing (forward billing twice, own-key failure) | 13, 19, 21 Oct | replies §11.1, §18, §21, §25 |
| Shared internal prompt text and timings | 18-21 Oct | replies §16.0, §18.0, §23.0, §25.0 |
| **Offers on the table:** limits raised on request; concurrency raised free; negotiation against a monthly minimum; carrier tests; per-turn logs; DPA signature; training off on PAYG | 6-21 Oct | eval §2, §10 items 2a, 3a, 11; §10a item 11; replies §8, §25 |

Pattern: requests with a concrete reason get built within a day; legal and commercial items
(DPA, training letter, volume price) do not get answered.

## 3. Still open

| Item | First asked | Status |
|---|---|---|
| Signed DPA and sub-processor list | 6 Oct (eval §6 item 10) | Promised 7 Oct; 23 Oct "being worked on, shared shortly" (replies §28). **Blocks any client call** (OPERATIONS T-5) |
| Written training exclusion for every workspace | 6 Oct; in writing 9 Oct | **Closed 23 Oct:** developer workspace and every customer workspace excluded, in his email (replies §28) |
| TRAI reg 4 notice and the access provider of our numbers | 12 Oct | 23 Oct: "no update from the operator" |
| Volume price for own-key minutes | 21 Oct (§20 item 13) | 23 Oct: needs a minimum monthly commitment, to be discussed. Founder decision |
| Live carrier tests (forwarded caller ID, F-1/F-4) | Offered by him 7 Oct; dates asked 21 Oct | Unanswered (again 23 Oct) |
| Per-turn timing logs for two calls | Offered 21 Oct; accepted §26 | Pending; not mentioned 23 Oct |
| Why only 28-35% of input is cached on our Gemini key | 21 Oct | Cause UNKNOWN (rememory 84048b66); "90%+ on OpenAI models"; not mentioned 23 Oct |
| §27 limits | 23 Oct | **Granted 23 Oct** (VENDOR-STATED, replies §28): 100 developer-workspace agents, 100 customer workspaces, 20 concurrent, Studio band + 25 clones on PAYG. Proof on our account: replies §28.3 |
| Client workspace agent count (2 on PAYG each) | 23 Oct (his answer) | Raise per workspace by email when a client needs a third agent |
| His question: Studio-band minutes we plan to use, from when | 23 Oct | Founder's figures needed |
| Offers we have not taken: Prana [Voice] test (12 Oct), prompt-order A/B on Telugu calls (21 Oct), minimum-commitment negotiation (12 Oct) | — | Not recorded as taken up |

## 4. Their published plans (VENDOR-PUBLISHED, thinnest.ai/pricing, founder-relayed 23 Oct 2026)

| | Trial | Pay As You Go | Pro | Scale | Enterprise |
|---|---|---|---|---|---|
| Monthly usage credit | – | – | ₹2,499 | ₹4,999 | Custom |
| Free voice minutes | 25 | … | … | … | Custom |
| Standard voices /min | ₹0 (trial) | ₹2 | ₹2 | ₹1.90 | Custom |
| Premium voices /min | ₹0 | ₹2.5 | ₹2.5 | ₹2.375 | Custom |
| Studio voices (voice clone) /min | – | – | ₹3 | ₹2.85 | Custom |
| Cloned voices | – | – | up to 10 | up to 20 | Custom |
| Concurrent calls | 1 | 5 | 10 | 15 (more on request) | Custom |
| Buy a number /month | – | ₹349 | ₹249 | ₹249 | Custom (import ₹0) |
| Max agents | 1 | 2 | 5 | 15 | Custom |
| Organizations | 1 | 1 | 2 | 100 | Custom |
| White label: resell to clients | – | 3 | 20 | 100 | Custom |
| Team members | 1 | 1 | 2 | 5 | Custom |
| Recording retention | – | 30 days | 49 | 75 | Custom |
| Support | | Email | Email | Priority | Dedicated |

Also: billing in 30-second pulses on all tiers; data residency India; rows for Ear mode,
GPT-Live-1, GPT-Realtime Mini, SSO and audit log and uptime commitment exist (tiers not
captured). Cards: Pro "₹2,499 of usage credit every month, Studio Voices, and higher limits";
Scale "₹4,999 of usage credit, team workspaces, 15 concurrent calls, and 5% off every voice
minute".

**Against our other sources:**

| Point | Finding |
|---|---|
| Customer workspaces | **Not on the page.** The API docs cap API customers at 3 (Free and PAYG), 100 (Pro), 1,000 (Scale), 10,000 (Enterprise), "Need more? Write to us" (`snapshots/2026-10-19/pages/api-reference/customers.md:221-226`). The page's "White label resell to clients 3/20/100" matches the **white-label console** product (`white-label/overview.md:46-47`), and a workspace with API customers cannot use white label (`customers.md:14-15`). So 3/20/100 should not bind us, but the page does not say so. **Confirm in writing.** |
| "Organizations 1/1/2/100" | **Answered 23 Oct (replies §28):** workspaces one owner can hold; does not limit API customers. White label 3/20/100 = white-label clients resold under our brand; also not a limit on API customers. |
| Max agents | PAYG 2 matches the production 409 (OBSERVED); Pro 5 matches `create-agent.md:668`. **Counted per workspace** (VENDOR-STATED 23 Oct, replies §28); ours: developer 100, each client workspace 2 on PAYG. |
| Studio voices on PAYG: none | Consistent with the docs and the 12 Oct email. **Conflicts with our product:** Clear is sold on the Studio band by default (D-792), and T-11 (Pro on our account) is not met. On PAYG no Studio-band voice and no clone can be listed ("What a red costs" in T-11). |
| Scale 5% | **Resolved 23 Oct (replies §28):** client workspaces follow our plan and get the 5% and the ₹249 number, including `byok: llm` agents; the flat own-key rates (₹1.00, ₹1.50) do not. Replaces the 18 Oct answer. |
| Usage credit | **Answered 23 Oct:** pays for everything the wallet is charged, own-key minutes and number rent included; rolls over up to 3 months while subscribed. PAYG has none. |
| Data residency India | Covers their own stack only; a Studio call speaks on Cartesia (US) and both rungs think on our Google key (eval §10a, second email). Not a residency claim for us. |
| Uptime | "No SLA on PAYG or Pro" (eval §10a item 16, VENDOR-STATED). |

## 5. How the limits bind us

Our shape: one customer workspace per paying client (D-693); trial agents and platform agents
in our developer workspace (D-697); one shared trial number, one test call at a time platform-wide
(THINNEST-INTEGRATION §3c); one rented number per client (eval §10 item 3b); one concurrency pool
across all workspaces (eval §10a item 11, VENDOR-STATED). Platform agents today: the trial-line
agent, plus two forwarding-test agents once F-5 runs (OPERATIONS F-5). **ASSUMPTION:** a client
has 1-3 agents and peaks at 1-2 simultaneous calls. T = trial accounts holding an agent (UNKNOWN).

| Limit | Needed at 10 / 50 / 100 clients | PAYG | Pro | Scale |
|---|---|---|---|---|
| Agents, if counted per account | 11-33 + T / 51-153 + T / 101-303 + T | 2 (blocking now) | 5 | 15 |
| Agents, if per workspace (developer workspace) | 1-3 + T at every size | 2 (blocking now) | 5 | 15 |
| Customer workspaces (+ closed clients for 30 days) | 10 / 50 / 100 | 3 | 100 | 1,000 |
| Concurrent calls (1 trial + clients) | 11-21 / 51-101 / 101-201 | 5 | 10 | 15 |
| Numbers (+ trial + test) | ~12 / ~52 / ~102 | ₹349 each | ₹249 | ₹249 |
| Studio-band voices and clones (Clear) | from client 1 | none | yes, 10 clones | yes, 20 |
| Recording retention | not binding: we keep our own copy and shorten theirs (`callRetentionDays`, D-798) | 30 d | 49 d | 75 d |

**Where the founder's plan (PAYG → Scale at 10 → Enterprise at 50) breaks without leniency:**
1. **Now, on PAYG:** trial agents cannot be made (2 agents); Clear cannot use its default band
   (no Studio voices); the 4th paying client is refused with 402 (T-8); 5 concurrent calls is
   4 client calls plus the trial line.
2. **Clients 4-10 on PAYG:** impossible without a written raise of the customer cap.
3. **Scale at 10 clients:** customer workspaces are fine. Agents (15) break if counted per account
   once clients average more than about 1.2 agents or trials hold agents. Concurrency (15) breaks
   if the ten peak above 14 calls together.
4. **Enterprise at 50:** every figure is "Custom", so the price is UNKNOWN.

So the plan needs leniency on PAYG now, and a written agent and concurrency allowance on Scale.
**Granted 23 Oct 2026 (replies §28, VENDOR-STATED):** points 1-2 are lifted (developer workspace
100 agents, 100 customer workspaces, Studio band and clones on PAYG, 20 concurrent calls), and the
raises carry over to Scale, which answers point 3. What still binds: **2 agents per client
workspace** on PAYG (raised per workspace on request) and 20 concurrent calls (about 19 client
calls plus the trial line; ask for the next step before clients peak there).
**Founder decision to weigh:** Pro (₹2,499, paid as usage credit) unlocks the Studio band,
10 clones and 100 customer workspaces today. Agents (5) and concurrency (10) would still need a
raise.

## 6. Costs

Rates are VENDOR-STATED (18 Oct email) and VENDOR-PUBLISHED (page). Our top-up fee is 2.36%
(D-754). Cartesia is ₹4.84 per 1,000 characters, operator-attested (rememory 12f1aa47). FX is
₹95 (D-768). Client prices: Clear ₹4.50, Studio ₹6.00 (D-728).

| Per minute | PAYG/Pro | Scale | Scale saves |
|---|---|---|---|
| Clear, Studio band (`llm`) | ₹3.00 → ₹3.071 with fee | ₹2.85 → ₹2.917 | ₹0.154 |
| Clear, Premium band | ₹2.50 → ₹2.559 | ₹2.375 → ₹2.431 | ₹0.128 |
| Studio (`llm_voice`) | ₹1.00 → ₹1.024 | no discount (own-key price) | ₹0 |

- **Our model is extra on both rungs** (D-834). On one 20 Oct call our Gemini cost ₹0.76/min
  (rememory 530cc6d6; one call, ESTIMATE). So Clear is about ₹3.83/min against ₹4.50: roughly
  15% gross, not the 31.8% that leaves the model out (ESTIMATE). We bring the model on Clear and
  still pay the full band. In Ashutosh's words, "LLM don't cost us much" (replies §8).
- **Studio:** ₹1.02 + Cartesia ₹2.76-3.87 (571-800 characters a minute) + Gemini ₹0.76 =
  about ₹4.55-5.65 (ESTIMATE). Measured: ₹5.74 (20 Oct) and ₹5.40 / ₹6.53 (21 Oct), against
  ₹6.00 (rememory 530cc6d6, bb7cfb2a). Cartesia is about two thirds. Scale does not touch it.
- **Pulse:** a 63-second call was billed 90 seconds (replies §22.1). Per-second billing is only
  available on our own telephony (§23).
- **Scale vs PAYG, monthly:**
  - Scale's ₹4,999 is usage credit. If the credit pays for our minutes (UNKNOWN), it costs
    nothing extra once our ThinnestAI spend reaches ₹4,999 a month: about 1,630 Clear minutes.
  - If the credit is only a fee, the break-even is ₹4,999 = ₹0.154 × Clear minutes + ₹100 × numbers.
    That is about 26,000 Clear minutes a month at 10 numbers, and at 50 numbers the number discount
    alone pays for it.
  - All of this assumes the Scale rates reach client workspaces, which the 18 Oct email denies (§4).
    If they do not, Scale saves only on numbers and trial minutes.

## 7. The ask, and what we can offer

**Ask now (PAYG):**

| # | Ask | Justification |
|---|---|---|
| 1 | Agent allowance of 100, or confirmation that it counts per workspace | Production 409 blocks every new trial (4360ad72); D-697 puts all trial agents in the developer workspace |
| 2 | Customer workspaces 3 → 100 | One per client (D-693); 4th paying client refused (T-8). Precedent: "PAYG 3, raised on request" (7 Oct); "Need more? Write to us" (`customers.md:226`) |
| 3 | Concurrent calls 5 → 100, staged if needed | One pool for all clients plus the trial line. Precedent: "raised free on request" (11 Oct, T-7) |
| 4 | **Studio-band voices and voice cloning on PAYG** at ₹3.00/min | Clear is sold on the Studio band (D-792), and client agents use our shared clones (D-797). Precise wording matters: the §27 draft says "Studio (premium) voices", but **Premium is already on PAYG**; the ask is the Studio band and clones |
| 5 | Written answers: does "white label 3/20/100" or "Organizations" limit API customers? Do Scale rates and ₹249 numbers reach customer workspaces? Does plan credit cover own-key minutes and number rent? | §4 discrepancies; they decide the Scale case |
| 6 | Price: a lower band rate on scope `llm` (we bring the model); a volume price on `llm_voice` | §6; his "LLM don't cost us much"; his offer to negotiate against a monthly minimum (12 Oct) |
| 7 | Open since 6-21 Oct: DPA and sub-processors, training letter, reg 4 and access provider, carrier test dates, per-turn logs | §3. The DPA blocks client calls (T-5) |

**What we can offer (each is a founder decision):**
- A written timeline: Scale at 10 active clients, Enterprise at 50 (founder plan, 23 Oct 2026).
- A minimum monthly commitment once our usage ledger shows a level we can safely meet (his own
  12 Oct opening).
- ThinnestAI as our only engine for every client and number (true today, D-763; stating it as a
  commitment is the founder's call).
- Continued detailed engineering feedback. Our reports found real faults he fixed: the webhook
  500s, the `byok-model` docs, the forward billing, and the glued retries.
- Telugu field data, starting with the Ear trial promised in §26.
- A case study or logo. This needs the founder's decision: our clients never see a provider name
  (D-679), but a ThinnestAI-side story about Calevate is separate.

## 8. Risks and alternatives (evidence only)

- **Concentration.** One engine, no fallback; a bad release is rolled back by redeploying our
  previous image (root CLAUDE.md). There is no SLA on PAYG or Pro (eval §10a item 16). A failed
  own key gets no backup model (replies §11.1).
- **Single point of contact.** Every answer comes from Ashutosh personally. His answers have been
  corrected several times (forward billing on 18, 19 and 21 Oct; the Gemini 2.5 deprecation
  against Google's page, replies §1, §7). Verify before money moves (hard rule 11).
- **Legal gates sit with them:** T-5 (DPA) blocks client calls; reg 4 is pending with Plivo.
- **Telephony underneath is Plivo** (replies §7); pulses and the 140-series minimum come from
  the carrier (§16.0, §23.0).
- **Alternatives.** The Pipecat engine is one checkout away at tag `pre-pipecat-removal` (D-763).
  Vobiz is Pipecat-only and testing-only until Vobiz consents in writing to resale (gate V-10,
  memory vobiz-resale-consent). Leaving ThinnestAI would give clients new numbers (eval §8).
  Numbers move only between ThinnestAI workspaces (D-737).
