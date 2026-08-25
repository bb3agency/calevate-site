# Calevate — Master Blueprint (Document Set)

Version 1.0 · July 2026 · Product brand of BuiltByThree · calevate.tech
Status: **decision-complete**. Remaining unknowns are enumerated (BRD §10 assumptions)
and are all closed by two non-code actions: the Engine Verification Session
(OPERATIONS.md §2) and Milestone-0 admin tasks (entity → DLT).

## Reading order

1. **BRD.md** — what we're building and why: vision, market, personas, pricing/revenue
   model, GTM for a cold start, KPIs, risk register, assumptions log.
2. **TRD.md** — how: architecture (4 deployables), locked stack, voice stack + latency
   budget, VoiceEngine adapter contract, RAG tiers, schema-driven extraction, metering,
   cost model with phase-2/3 triggers.
3. **DATA-MODEL.md** — full Postgres schema with RLS pattern, extraction-schema JSON
   shape, append-only ledgers, compliance tables.
4. **BACKEND-PATTERNS.md** — the CONSTRUCTION MANUAL for every Python service (read
   with TRD + DATA-MODEL before writing backend code): module anatomy, locked
   bootstrap order, RFC-9457 error ladder, the reliability triad (idempotency/outbox/
   inbox), CAS concurrency doctrine, health/readiness, audit hash chain, alert
   taxonomy, testing structure.
5. **SECURITY-COMPLIANCE.md** — TRAI/DLT/DPDP obligations mapped to features; call-level
   and campaign gates; threat model; compliance calendar.
   - **legal/LEGAL-OPS-PLAYBOOK.md** (the legal SOURCE OF TRUTH, read with it) — the
     founder's decision-complete scenario (24 Aug 2026): **India-only B2B, no foreign
     clients**, sole proprietor, **Model B** numbers (client owns the connection, Calevate is
     Telemarketer), **no GST at launch**, inbound-without-TM but **outbound gated on TM-ID +
     Active PE–TM chain + correct number series**. It DECIDES the entity/geography/number
     questions the audits left open, and its freeze parks all foreign-client work. Wins over
     stale assumptions elsewhere. Background: `legal/phone-number-research.md`,
     `legal/comet-legal-research.md` (the latter's US/FEMA/export material is parked).
   - **LEGAL-SURFACE.md** (the obligation audit, read with it) — every legal obligation
     mapped to the code that creates it, and the findings where we fall short. Read the
     playbook for the DECISION, LEGAL-SURFACE for the code map.
   - **PLATFORM-CONFIG.md** (read with it) — the `admin.calevate.tech/ops` console:
     where core config lives, where SECRETS live (envelope encryption in Postgres, KEK
     in the environment and nowhere else), the six bootstrap keys that may never move
     out of `.env`, and the security trade the console makes explicit. D-95.
   - **AUTH-MIGRATION.md** (read with it) — D-165: the first-party auth module that
     replaced Clerk. Its §1 capability inventory was the ACCEPTANCE CRITERIA and is now
     the record of what each vendor capability became; §3 is the realm boundary built out
     of our own materials; §5 is the cutover that ran; §11 is what is still NOT built.
     **`apps/api/authn/` is the only authenticator this product has** (D-170 mounted it,
     D-177 deleted the vendor beside it). Two sentences here said the opposite for two
     slices after they stopped being true — "still the live authenticator", "mounted on no
     router" — which is the class of drift §11 now keeps a struck list for.
6. **FLOWS.md** — onboarding wizard, invitations/auth, inbound call lifecycle, instant
   lead callback, bulk campaigns, post-call pipeline, KB updates, billing, offboarding.
7. **OPERATIONS.md** — engine verification checklist (do this first), per-client
   regression/eval harness, observability, SLOs, runbooks, pre-launch checklist.
8. **ROADMAP.md** — milestones with gates (client #1 before platform polish), decision
   log from D-01 onwards (§6; entries are appended, so the tail is not in numeric order and
   the highest number is not a count — read
   the whole table, and note the ⚠SUPERSEDED/AMENDED markers on the early ones),
   deferred list.
9. **SURFACES.md** — the three product surfaces: admin-panel and client-CRM feature
   inventories (seed the build-time design discussions) + the decided integration
   doctrine (webhook intake pipeline, real-time UI transport, engine API usage rules).
9a. **WEBHOOKS.md** — the client-developer integration contract in both directions
    (events we sign and send, signature verification and delivery rules; lead ingest,
    field mapping, consent and the dry-run tester), written against the shipping code —
    the concrete form of SURFACES §2b/§3's integration doctrine.
10. **DEPLOYMENT.md** — VPS deployment + CI/CD blueprint (adapted from the
    raghava-organics production playbook): topology, self-hosted-runner CD, nginx/TLS/
    Cloudflare, secrets tiers, backups/DR, go-live order, lessons-not-to-relearn.
    The mechanism it describes now exists — `Dockerfile`, `compose.prod.yml`,
    `scripts/vps-deploy.sh`, `infra/nginx/`, `.github/workflows/deploy.yml` — and
    **has been run against nothing**: §4d is the hand-first checklist with pass
    conditions, and CD stays disabled until its last item.
11. **ENGINEERING-PRACTICES.md** — executable governance: the guardrail pack
    (fitness functions enforcing the Hard Rules in CI), git workflow (trunk-based +
    Conventional Commits + pre-commit hooks), dev-loop conventions, release
    discipline trajectory.

Method & evidence:
11a. **RESEARCH-DISCIPLINE.md** — how vendor/competitor claims are handled: verify
    first-party, mark verified vs inferred, compare like with like, never rank on
    headline per-minute rates. Includes the eight mistakes already made and corrected,
    and the vendor due-diligence bar. **Read before any vendor evaluation.**
11b. **evidence/** — committed research artifacts: `bolna-pilot-scorecard.md` (the 13
    gates that close the remaining cost unknowns), `outpero-teardown-aug2026.md`
    (conclusions from the authenticated competitor teardown) and
    `outpero-research-log.md` (the raw working notes behind it, including which
    findings were later retracted). **And, since 20 Aug 2026, `bolna-*.md` — ten lane
    reports over the vendor's ENTIRE hosted documentation set**, mirrored read-only at
    `bolna-findings/mirror/` (335 pages, per-page SHA-256 manifest; the host itself is
    still egress-blocked here, so the fetch happened elsewhere and cannot be refreshed
    from this tree). Every vendor sentence in the blueprint is now expected to cite a page
    and a line in that mirror — evidence class **VERIFIED-VENDOR-DOCS**. The decisions
    they produced are ROADMAP §6 D-414…D-424 and OPERATIONS §2 gates 9v, 21–27.

Engineering companions:
12. **CLAUDE.md** — operating manual for Claude Code in the repo (hard rules, commands,
    conventions; the full manual now lives in the root CLAUDE.md). **AGENTS.md** — same
    for all other coding agents (open standard).
13. **DEV-SETUP.md** — local environment, bootstrap, env vars, Makefile targets.
14. **PROMPT-GUIDE.md** — how client agent system prompts are structured, versioned,
    regression-gated, and red-teamed (prompts are product code).

## The two gates that are still unrun (Milestone 0)

Both were once framed as preceding *any* code; they no longer do — M1 backend and web
slices have shipped against the `fake` engine adapter (`ENGINE=fake`, the default), which
is exactly what the adapter contract exists to make possible. They remain hard blockers on
specific things, and neither has been run:

1. **Engine Verification Session — the Bolna pilot (D-31)** — one afternoon on paid
   Bolna credits (OPERATIONS.md §2). Confirms webhooks/API/latency/Telugu quality/
   commercials incl. the unpublished BYOK platform fee.
   **Blocks:** flipping `ENGINE=bolna` in production, the cost model's remaining
   unknowns, and Gate G0. Evidence artifact `evidence/bolna-pilot-scorecard.md` is still
   an empty template — the honest status marker.
2. **Entity decision → DLT PE registration** — legal prerequisite for all outbound
   calling (SECURITY-COMPLIANCE.md §3; Risk R-01). **Blocks:** every outbound path
   (campaigns, "call this lead", instant callback) going live on real numbers — the code
   is built and the compliance gate enforces it. Inbound-only launch is the fallback, and
   D-38 makes inbound the headline capability anyway.

## One-line summary of the locked stack

Bolna (engine, adapter-isolated — D-31) + **Sarvam for SPEECH** (D-36's Saaras STT ·
Bulbul v3 TTS default, v2 as the value tier — unchanged) + **Azure OpenAI in East US 2
for LANGUAGE, on BOTH LLM surfaces** — **D-410 supersedes D-400/D-404 on the in-call leg
and D-127 on the dashboard leg; Gemini and Vertex are out of this product. D-449 moved the
REGION off South India: the declared posture is `us-azure-openai`, and the client-facing
India warranty is withdrawn, not narrowed.** One region (`AZURE_LOCATION`, `eastus2`), one
default (`AZURE_OPENAI_DEFAULT_MODEL`, `gpt-4o-mini` — unchanged by D-449, and TRD §10 is
unrepriced), one allow-list (`AZURE_OPENAI_MODELS`) and one builder
(`azure_openai_base_url()`); `gpt-4.1-mini` is a live config switch rather than a second
shipped default. The engine
authenticates with a **static API key** on the OpenAI-compatible v1 surface, so D-404's
rotation cron, its alarm, its runbook and D-408's dead man are all deleted — they existed
because a regional Vertex endpoint took no static key. **BRD R-04's 16 Oct 2026 Gemini
retirement dies with this**, and no vendor deadline is currently running against the
product. **The residency claim is narrower than it was and this line will not pretend
otherwise, and since D-449 it is not an India claim at all**: `<resource>.openai.azure.com`
names no region, so the build proves only that one constant spells the region and that no
endpoint is constructible outside the builder — that the resource really is in East US 2,
and that its deployment is Regional Standard rather than Azure's worldwide-by-default
Global, are attested by a human (OPERATIONS §2 gates 20 and 20c, which survive D-449
re-aimed rather than retiring). Speech stays Sarvam and Indian; the caller's words reach a
US model as they are spoken. The third surface is decided the OTHER way and permanently:
`GEMINI_EXTRACTION_DEFAULT is False`, so the
first post-call extraction stays on Sarvam because it reads the raw transcript, and D-410
does not move it. **D-04/D-20's Gemini-primary stack is superseded** · Vobiz/Exotel telephony · FastAPI + Next.js/TS ·
Postgres 16 + RLS (pgvector is a D-28 contingency) · Redis/ARQ · first-party auth, two
realms (D-165/D-170/D-177 — Clerk is deleted) ·
a general-purpose VPS (D-25 moved hosting off DigitalOcean; nothing is provisioned yet).
**This line used to say "with an India-resident data plane" and that was a claim the code
cannot make**: `docs/DEPLOYMENT.md` says India co-location is NOT required for this stack,
which is the stack holding every transcript, and F-1 is open precisely because the region
is undecided. It was scrubbed from the landing page and left here, where it seeded the
same sentence in BRD §sales. Nothing may re-assert it until a host is chosen and named · Sentry/OTel (LLM tracing is a named gap, D-49) · setup-fee + retainer + overage pricing, plus the
D-34 self-serve prepaid tier · all-in target ≈ **₹3.3–3.8/min**, ₹1.9–2.6/min at phase 2
(floor **₹2.9** on Bulbul v2 + Sarvam LLM, UNCHANGED — that combination's LLM leg
is free; TRD §10.1's ladder cell said ₹1.89 from this repository's first commit until
20 Aug 2026 and has been corrected TO this number, with the arithmetic shown there. Read
"verified" off it: the MODEL rates are first-party, the ₹1.50 platform fee inside it is
still pilot gate 12). **Both bands were re-derived at D-410 and both moved, because D-36 struck them
against a ₹0.00 LLM leg and the leg is no longer free.** They carry the shipped default,
`gpt-4o-mini` at ₹0.16/min on a five-minute call (TRD §10.1): D-36's ₹3.1–3.6 + ₹0.16 =
3.26–3.76, and phase 2 is that less the ₹1.50 platform fee plus ₹0.15–0.30 compute. **TRD
§10 owns that derivation and this line quotes it** — the two used to subtract independently
and disagreed by 0.1–0.2 at both ends.
D-400 would have added ₹0.36 and nobody updated this line at the time, so what D-410
actually delivers here is **₹0.20/min back** — the line is now ₹0.16 above D-36 rather than
₹0.36 above it. Flipping `azure_openai_model` to `gpt-4.1-mini` costs 2.67x that leg and
puts the target at ≈ ₹3.5–4.0.
