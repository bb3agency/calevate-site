# Calevate — Master Blueprint (Document Set)

Version 1.0 · July 2026 · Product brand of BuiltByThree · calevate.tech
Status: **decision-complete**. Remaining unknowns are enumerated (BRD §10 assumptions,
OPERATIONS §2 gates); what still blocks a client going live is listed at the end of this
file.

## Reading order

1. **BRD.md** — what we're building and why: vision, market, personas, pricing/revenue
   model, GTM for a cold start, KPIs, risk register, assumptions log.
2. **TRD.md** — how: architecture (5 deployables), locked stack, voice stack + latency
   budget, VoiceEngine adapter contract, RAG tiers, schema-driven extraction, metering,
   cost model with phase-2/3 triggers.
   - **PIPECAT-MIGRATION.md** (read with it) — the construction manual for the engine we
     run: the owned Pipecat loop (`apps/voice-worker`, D-592), its adapter, the language
     path, the cost model after the engine change, and §6, the step list whose step 6 is
     the first real call on Vobiz.
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
9b. **UX-DOCTRINE.md** — the CONSTRUCTION MANUAL for `apps/web`, the front-end twin of
    BACKEND-PATTERNS (read before building or restructuring any screen): the one-primary-
    job hierarchy rule and when a `Card` is the wrong container, the frequency × consequence
    disclosure test, task-oriented IA, action hierarchy, the per-file size budget, the
    shared-primitive contract, the WCAG-referenced accessibility floor (including which
    compliance controls may never be disclosed), and what "maximum control, minimum
    complexity" does and does not license. Reference implementation: `/c/[slug]/agents`.
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
    they produced are ROADMAP §6 D-414…D-424 and OPERATIONS §2 gates 9v, 21–27. Bolna was
    deleted by D-639, so those reports are now the record of a withdrawn engine. **The
    carrier's equivalent is `vobiz-api-contract.md` and `vobiz-integration-plan.md`**, over
    the hash-pinned Vobiz mirror at `vobiz-findings/mirror/` (D-662; OPERATIONS §2 gate 55
    and the V-series). Neither mirror is ever edited.
11c. **`runbooks/`** — incident and first-time procedures; `alarm-index.md` maps every
    alarm code to its runbook, and `first-deploy.md` and `vobiz-first-live-call.md` are the
    two checklists that turn the build into a running service. `thinnest-first-live-call.md`
    is the first-call checklist for a deployment switched to `ENGINE=thinnest` (D-678), and
    `thinnest-studio-voices.md` turns Studio on per client and moves production off the old
    developer-workspace switch (D-717).

Engineering companions:
12. **CLAUDE.md** — operating manual for Claude Code in the repo (hard rules, commands,
    conventions; the full manual now lives in the root CLAUDE.md). **AGENTS.md** — same
    for all other coding agents (open standard).
13. **DEV-SETUP.md** — local environment, bootstrap, env vars, Makefile targets.
14. **PROMPT-GUIDE.md** — how client agent system prompts are structured, versioned,
    regression-gated, and red-teamed (prompts are product code).

## What still blocks a client going live

Backend and web slices have shipped against the `fake` engine adapter (`ENGINE=fake`, the
default in `calevate_shared.config`), which is what the adapter contract exists to make
possible. Four things outside the code still stand between that and a client's first call:

1. **The first real call (BLOCKER-1).** No call has yet been placed on this product. The
   owned runtime (D-592) is the engine and Vobiz is the carrier (D-662); the checklist for
   the first inbound and outbound call is `runbooks/vobiz-first-live-call.md`, and its
   results close PIPECAT-MIGRATION §6 step 6 and the OPERATIONS §2 V-series gates. The
   Bolna pilot that used to sit here will not run: D-639 deleted the adapter, and the gates
   phrased against Bolna are withdrawn, not failed (OPERATIONS §2 preamble).
2. **Vobiz's written consent to carry clients' traffic** (OPERATIONS §2 gate V-10). Until
   then the founder's own Vobiz account carries the founder's own test calls only, and
   `number_resale_authorization` stays unset (gate 47), which refuses every client number
   purchase.
3. **DLT registration** — Calevate's telemarketer registration and each client's Principal
   Entity chain, the legal prerequisite for every outbound path (SECURITY-COMPLIANCE §3;
   Risk R-01). The compliance gate enforces it on every dial; inbound does not need it, and
   D-38 makes inbound the headline capability.
4. **The first deploy.** The host is a Hostinger India VPS (D-180). `docs/DEPLOYMENT.md`
   and `runbooks/first-deploy.md` describe it, the Pipecat Cloud worker and the deploy
   path; `infra/README.md` §5 lists what a human must do before any of it is real.

## One-line summary of the stack

Our own Pipecat conversation loop (`apps/voice-worker`, on Pipecat Cloud `ap-south`, D-592;
`ENGINE` accepts `fake`, `cartesia` and `pipecat`, and Bolna was deleted by D-639) · Vobiz
telephony behind a carrier switch (`CARRIER`, default `vobiz`, Plivo the fallback, D-662),
Vobiz recording the call and our copy kept 90 days (D-668/D-670) · Sarvam Saaras for
speech-to-text and the first extraction pass, which reads the raw transcript · text-to-speech
chosen per agent: Cartesia Sonic 3.5 on the Studio rung, Gnani Timbre v2.5 on the Clear rung,
not sellable until an operator attests its price (D-547/D-618/D-629) · language models on the
`multi-provider-byok` posture — Azure OpenAI in East US 2, OpenAI direct and Google — with
`gemini-2.5-flash-lite` the platform default and `agents/llm_models.offerable_models()` what a
client may pick (D-410/D-449/D-456) · FastAPI + Next.js/TS · Postgres 16 + RLS + pgvector
(`kb_chunks`, D-502 — an extension, not a deployable) · Redis/ARQ · first-party auth in two
realms (D-165/D-170/D-177) · a Hostinger India VPS (D-25/D-180) · Sentry/OTel
(LLM tracing is a named gap, D-49) · setup-fee + retainer + overage pricing plus the D-34
prepaid self-serve tier. The per-minute cost model is TRD §10 and PIPECAT-MIGRATION §10;
quote it from there rather than from a summary.

Two claims this product does NOT make, because the code cannot back them: an India-resident
data plane (the host is in India, but the R2 buckets are `apac`, the voice and model vendors
process outside India, and DEPLOYMENT §0 says so; LEGAL-SURFACE F-1), and India residency for
the language leg (D-449 withdrew it; the Azure region is attested in the portal, OPERATIONS
§2 gates 20/20c). Speech is Sarvam, an
Indian company whose privacy policy permits processing outside India and whose ToS s.17.5
permits training on inputs absent a signed order form (VENDOR-PUBLISHED, read by the founder
27 Aug 2026 and relayed; `/legal/subprocessors` §3.4 discloses it).
