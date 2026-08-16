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
   - **PLATFORM-CONFIG.md** (read with it) — the `admin.calevate.tech/ops` console:
     where core config lives, where SECRETS live (envelope encryption in Postgres, KEK
     in the environment and nowhere else), the six bootstrap keys that may never move
     out of `.env`, and the security trade the console makes explicit. D-95.
6. **FLOWS.md** — onboarding wizard, invitations/auth, inbound call lifecycle, instant
   lead callback, bulk campaigns, post-call pipeline, KB updates, billing, offboarding.
7. **OPERATIONS.md** — engine verification checklist (do this first), per-client
   regression/eval harness, observability, SLOs, runbooks, pre-launch checklist.
8. **ROADMAP.md** — milestones with gates (client #1 before platform polish), decision
   log D-01…D-39 (§6; entries are appended, so the tail is not in numeric order — read
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
    findings were later retracted).

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

Bolna (engine, adapter-isolated — D-31) + the **D-36 canonical all-Sarvam BYOK stack**
(Saaras STT · Sarvam 105B LLM, free + sovereign · Bulbul v3 TTS default, v2 as the value
tier) — **Gemini 3.x Flash-Lite runs the user-triggered dashboard AI on Vertex AI
`asia-south1` (D-127), with `GEMINI_MODEL_CONFIRMED_IN_REGION is False` because nobody has
verified Mumbai serves that identifier (D-142, OPERATIONS §2 gate 14);
`GEMINI_EXTRACTION_DEFAULT is False`, so the first post-call
extraction stays on Sarvam. D-04/D-20's Gemini-primary stack is superseded** · Vobiz/Exotel telephony · FastAPI + Next.js/TS ·
Postgres 16 + RLS (pgvector is a D-28 contingency) · Redis/ARQ · Clerk (two realms) ·
a Hetzner-class VPS with an India-resident data plane (D-25 moved hosting off
DigitalOcean; nothing is provisioned yet) · Sentry/OTel (LLM tracing is a named gap, D-49) · setup-fee + retainer + overage pricing, plus the
D-34 self-serve prepaid tier · all-in target ≈ ₹3.1–3.6/min (D-36; verified floor ₹2.9 on
Bulbul v2 + Sarvam LLM), ₹1.7–2.3/min at phase 2.
