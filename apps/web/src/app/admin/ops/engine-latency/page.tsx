"use client";

import { useState } from "react";
import { Gauge, Timer, TriangleAlert } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { MonoValue } from "@/app/admin/ops/opsLanguage";
import {
  Card,
  EmptyState,
  FilterChip,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  ScrollRegion,
  Skeleton,
  StatTile,
  formatCount,
} from "@/components/ui";
import {
  BASIS_COPY,
  BUDGET_GAP_BODY,
  BUDGET_GAP_TITLE,
  DEFAULT_WINDOW_DAYS,
  INHERITED_WAIT_NOTE,
  LEG_COPY,
  UNVERIFIED_UNIT_NOTE,
  WINDOW_CHOICES,
  budgetVerdict,
  formatMs,
  regionLabel,
  useEngineLatency,
  type BudgetVerdict,
  type EngineLatencyReport,
  type LatencyBudget,
  type LatencyGroup,
  type LegSummary,
} from "@/lib/api/engineLatency";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

/**
 * WHAT THE VOICE ENGINE'S OWN PIPELINE COST, BY REGION — the console half of
 * `GET /v1/ops/engine-latency` (OPERATIONS §2 gate 4).
 *
 * ## Why this screen exists
 *
 * The endpoint shipped with no path in the console, so the two documents that need it
 * pointed at a curl: OPERATIONS §2 gate 4 ("place the calls, read `GET
 * /v1/ops/engine-latency` grouped by `region`") and `runbooks/alarm-index.md`, whose entry
 * for `engine_llm_ttft_degraded` opens *"Read `GET /v1/ops/engine-latency` first"*. That is
 * an operator hand-assembling a request against production, mid-incident, from the
 * document people follow when they are least careful — the exact argument
 * `app/admin/ops/page.tsx` makes for why the load-shed switch, the outbox replay and the
 * audit-chain verification are controls rather than curls.
 *
 * ## It is a REPORT, not a dashboard, and three things follow
 *
 * 1. **Nothing here is derived — including the budget and the verdict on it.** Every
 *    percentile, every count, every verdict and every target is the server's own field.
 *    TRD §4 declares five stages and a crossing inside a voice-to-voice p50, and the
 *    composed totals (`turn_ms`, `pipeline_ms`, `voice_to_voice_floor_ms`, the headroom)
 *    arrive already summed, so this bundle never adds two targets together.
 *    `engine_latency.py` withholds a p95 below 20 timed turns and a p50 below 5 and
 *    publishes `basis` so the withholding is a fact rather than a gap.
 * 1b. **THE SHORTFALL IS STATED, NOT LEFT IN A TEST.** Since the founder set voice-to-voice
 *    at 500ms (27 Aug 2026) the declared stages no longer fit inside it — `budget.composes`
 *    is false and the headroom is negative. A guard test failing in CI is invisible to the
 *    person reading this console mid-incident, so the gap is a banner above the budget, in
 *    the server's own three numbers.
 * 2. **`budget_breached` has THREE states and is rendered as three, PER LEG.** True is
 *    "the typical reply missed our target for this stage", false is "it did not", and
 *    `null`/absent is "the sample cannot support a median" — which must never render like
 *    the second. This screen showed ONE verdict, the language model's, beside a tile
 *    reading "Target for the first reply: 350 ms" as though that were the whole budget: it
 *    is one of four legs inside a 1.1s target, and a reply that spent 900ms in the
 *    transcriber was painted as comfortably within it.
 * 3. **§52 without exception.** Loading is a skeleton, a failed read is a refusal, and
 *    neither is "no turns were measured". "The engine reported nothing" is a claim about
 *    our own instrumentation — the sentence an operator would act on by going to look for
 *    a broken adapter — and a 500 is not evidence for it.
 *
 * ## What it deliberately does not say
 *
 * **Not voice-to-voice latency.** Both ends of that interval are on the PSTN leg this
 * stack is not in (D-25/D-33), which is why `calls.latency` was dropped and stays dropped.
 * These are the engine's numbers about the engine's own pipeline. The stopwatch that says
 * whether they resemble what a caller HEARS is gate 4's, and a human types it in. The two
 * voice-to-voice targets ARE shown — among the budget, labelled as targets nothing here
 * measures — because a reader who cannot see what the four stages were cut from has no way
 * to tell whether meeting them would be enough.
 *
 * **Not the lookup leg, and not the wait before the reply starts.** TRD §4 budgets a
 * knowledge-base retrieval at 100ms and an endpointing wait at 100ms, and the budget panel
 * shows both — but neither has a row in any group. The engine measures no retrieval stage
 * (the in-call RAG endpoint is ours and uninstrumented) and reports no endpointing figure
 * at all: that wait is inside its `time_to_first_audio` total and outside the transcriber
 * timing it publishes. A row of em dashes would read as "fast", and on the endpointing
 * stage that would be the opposite of the truth — the shipped setting waits 650ms there.
 *
 * **Not gate 4's verdict.** The gate is answered by comparing two rows that both carry a
 * median, and the rule that counts them (`EngineLatencyReport.regions_measured`) is a
 * Python `@property` — not a wire field, and nothing reads it. Restating it in this bundle
 * would be a second spelling of a rule that already exists; the table shows each group's
 * own `basis` and the reader compares two rows.
 *
 * ## Permission
 *
 * `ops:manage`, which only `superadmin` holds (`core/rbac.py`), asked of `GET
 * /v1/admin/me` rather than derived from this screen's own 403 — so an `operator` sent
 * here by the runbook is told why in a sentence instead of being handed a refusal that
 * reads like an outage.
 *
 * Unlike `/admin/ops/dnc`, the answer gates the READ and not only a control: this screen
 * is one GET, so a session the server refuses has nothing left to look at, and firing the
 * request anyway would paint the permission as a red failure box with a retry button whose
 * only outcome is another 403. It is still a PREVIEW and never the enforcement — the API
 * refuses on its own, the `ProblemNotice` below stays as the backstop for every other way
 * a read can fail, and the withholding happens only on a definite refusal (see the hook
 * call for why `!refused` rather than `allowed`).
 *
 * No `<h1>`: the shell derives the title from the nav list it also renders the sidebar
 * from (`app/admin/layout.tsx`).
 */
export default function EngineLatencyPage() {
  const [days, setDays] = useState(DEFAULT_WINDOW_DAYS);
  /**
   * The READ carries `ops:manage` here, unlike `/admin/ops/dnc` where only the writes do
   * — this whole screen is one GET, so a session the server refuses has nothing left to
   * look at. That is why the answer gates the query rather than only a control.
   *
   * `!access.refused` and NOT `access.allowed`, and the difference is `access.ts`'s two
   * booleans doing the job they exist for. `refused` is the server having ANSWERED "you
   * may not"; `allowed` is false while the identity read is merely in flight or has
   * itself failed. Gating on `allowed` would make a slow or dead `/v1/admin/me` lock an
   * operator out of an incident read the API would have served — the failure the module
   * spells out as "navigation fails open, the API is the enforcement". So the report is
   * fetched on the unknown and withheld only on a refusal.
   */
  const access = useAdminAccess("ops:manage", "read the engine's latency report");
  const report = useEngineLatency(days, !access.refused);

  /*
   * THE LATENCY REPORT, DECLARED TO THE SCREEN ASSISTANT.
   *
   * Aggregate over every call the engine ran, grouped by REGION and not by client, so
   * there is no cross-tenant question to answer: no group here belongs to a tenant and no
   * row can be traced to one. The whole payload is milliseconds and turn counts.
   *
   * The window IS writable — it is the screen's only control, it is a choice from four
   * fixed values, and "show me the last 30 days instead" is what an operator says out loud
   * while reading this. `WINDOW_CHOICES` is the option list, so a fill that names anything
   * else is refused server-side against the declared options rather than setting a window
   * the endpoint would reject.
   *
   * The per-leg breach counts go, because they are the answer to the question
   * `runbooks/alarm-index.md` sends people here with ("read this first" on
   * `engine_llm_ttft_degraded`). Whether the unit was VERIFIED goes with them — an
   * unverified figure that reaches a model as a bare number becomes a fact somebody
   * repeats, which is hard rule 11's whole subject.
   */
  const data = report.data;
  useCopilotSurface({
    route: "/admin/ops/engine-latency",
    title: "Engine latency",
    realm: "admin",
    fields: [
      {
        id: "latency-window-days",
        label: "Window (days)",
        type: "select",
        value: String(days),
        options: WINDOW_CHOICES.map((choice) => ({
          value: String(choice),
          label: `Last ${windowLabel(choice)}`,
        })),
      },
    ],
    facts: access.refused
      ? [
          {
            key: "report",
            label: "The latency report",
            value: "withheld — this admin account may not read it",
          },
        ]
      : data
        ? [
            { key: "window_days", label: "Window shown (days)", value: String(data.window_days) },
            {
              key: "complete",
              label: "Did every measured turn fit the window",
              value: data.complete ? "yes" : "no, the report is truncated",
            },
            {
              key: "groups",
              label: "Regions the engine ran calls in",
              value:
                data.groups.map((group) => regionLabel(group.region)).join(", ") ||
                "no calls measured in this window",
            },
            {
              key: "calls",
              label: "Calls measured",
              value: String(data.groups.reduce((total, group) => total + group.calls, 0)),
            },
            {
              key: "turns",
              label: "Turns measured",
              value: String(data.groups.reduce((total, group) => total + group.turns, 0)),
            },
            {
              key: "breaches",
              label: "Legs over budget, by region",
              value:
                data.groups
                  .flatMap((group) =>
                    group.legs
                      .filter((leg) => leg.budget_breached === true)
                      .map(
                        (leg) =>
                          `${regionLabel(group.region)} ${leg.leg}: ${leg.turns_over_budget} of ${leg.turns} turns over ${leg.budget_ms}ms`,
                      ),
                  )
                  .join("; ") || "none",
            },
            {
              key: "unverified_units",
              label: "Legs whose unit is NOT verified against the vendor's own docs",
              value:
                [
                  ...new Set(
                    data.groups.flatMap((group) =>
                      group.legs.filter((leg) => !leg.unit_verified).map((leg) => leg.leg),
                    ),
                  ),
                ]
                  .sort()
                  .join(", ") || "none — every leg's unit is verified",
            },
          ]
        : [
            {
              key: "report",
              label: "The latency report",
              value: report.error ? "could not be read" : "still loading",
            },
          ],
    apply: (items) => {
      const window = items.find((item) => item.field_id === "latency-window-days");
      if (window === undefined) return;
      const chosen = Number(asText(window.value));
      // Only one of the four the chips offer. A window the endpoint would refuse is worse
      // than no change: the screen would sit on a red box the operator did not ask for.
      if (WINDOW_CHOICES.includes(chosen)) setDays(chosen);
    },
  });

  return (
    <div className="space-y-4 pb-12">
      <p className="text-sm text-ink-muted">
        How long each stage of a reply takes — hearing the caller, thinking of an answer,
        starting to speak — measured on every reply and grouped by the region the engine ran
        the call in. These are the engine&rsquo;s own figures about its own pipeline. They
        are not what a caller actually hears on the phone from end to end, which is a
        stopwatch measurement nobody can take from here.
      </p>

      {access.refused ? (
        /* The refusal INSTEAD of the report, never beside it. A disabled window picker
           over a red "we could not read this" box describes an outage, and this is a
           permission working exactly as designed — the distinction `admin/ops/dnc` draws
           for a control, applied to a screen whose entire subject is one refused read. */
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label="Choose a window"
          >
            {WINDOW_CHOICES.map((choice) => (
              <FilterChip
                key={choice}
                label={`Last ${windowLabel(choice)}`}
                active={choice === days}
                onClick={() => setDays(choice)}
              />
            ))}
          </div>

          {report.error != null && (
            <ProblemNotice error={report.error} onRetry={() => void report.refetch()} />
          )}

          {/* §52. `!report.data` covers all three ways to have no answer — in flight,
              failed, and the paused query a console tab open across a dropped connection
              produces (`lib/api/client.ts` calls that the normal case). Only the first
              gets a skeleton; the other two are answered by the refusal above. */}
          {!report.data ? (
            report.error ? null : (
              <Card>
                <Skeleton rows={6} label="Loading the engine's latency report" />
              </Card>
            )
          ) : (
            <Report report={report.data} />
          )}
        </>
      )}
    </div>
  );
}

/**
 * "7 days", and "1 day" rather than "1 days".
 *
 * One spelling for the chips and for the header tile, so the control an operator clicked
 * and the figure they are reading name the same period in the same words.
 */
function windowLabel(days: number): string {
  return `${formatCount(days)} ${days === 1 ? "day" : "days"}`;
}

/**
 * The report, given one that ARRIVED.
 *
 * Takes the payload rather than the query envelope for the reason every board in this
 * console does: each sentence below is a claim about what the engine measured, and a
 * component that cannot see `undefined` cannot accidentally make one out of it.
 */
function Report({ report }: { report: EngineLatencyReport }) {
  // THE NUMBER THE OPERATOR ARRIVED FOR (ux-audit F-15): the alarm runbook sends them
  // here to learn whether anything is over target, and it used to live only in the ninth
  // column of a nine-column table. This COUNTS the server's own per-leg verdicts
  // (`budgetVerdict`, three-state) — it derives no percentile, so the screen's
  // no-derivation doctrine holds. A row with any `over` leg is over; a row with an
  // `unknown` leg and no `over` one is unknown, counted separately so "we could not
  // tell" never reads as "fine" — the exact rule the verdict cell below applies.
  const verdicts = report.groups.map((group) => group.legs.map(budgetVerdict));
  const rowsOver = verdicts.filter((v) => v.includes("over")).length;
  const rowsUnknown = verdicts.filter(
    (v) => !v.includes("over") && v.includes("unknown"),
  ).length;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Over target"
          value={`${formatCount(rowsOver)} of ${formatCount(report.groups.length)}`}
          tone={rowsOver > 0 ? "strong" : undefined}
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          hint={
            rowsUnknown > 0
              ? `Rows with any stage over its goal, by the server's own verdicts. ${formatCount(rowsUnknown)} more row(s) could not be judged — that is not the same as fine.`
              : "Rows with any stage over its goal, by the server's own verdicts."
          }
        />
        {/* The WHOLE reply, not one stage of it. This tile read "Target for the first
            reply: 350 ms" — the language model's leg — which is the defect this screen's
            second version exists for. `budget.turn_ms` is the server's sum of the three
            stages it actually measures; the panel below opens the sum up. */}
        <StatTile
          label="Target for a whole reply"
          value={formatMs(report.budget.turn_ms)}
          icon={<Gauge aria-hidden className="h-5 w-5" />}
          hint="Our goal for the three stages the engine measures, added together. It's a target we set, not a measurement — this report is the first thing that can show whether we're meeting it."
        />
        <StatTile
          label="Rows in this window"
          /* NOT "rows measured": a row with three replies is IN the window and is
             precisely the one the server declined to summarise, so counting it under that
             word would state a measurement that was refused one column to the right. */
          value={formatCount(report.groups.length)}
          icon={<Timer aria-hidden className="h-5 w-5" />}
          hint="One row for each engine and region we saw in this window. Each stage of each row is judged on its own typical time."
        />
        {/* The window the SERVER answered for, not the one the chips asked for: the route
            clamps `days` to its own bounds, and a header quoting the request would describe
            a period the figures beside it are not about. */}
        <StatTile label="Window" value={windowLabel(report.window_days)} />
      </div>

      {/* THE GAP, WHERE AN OPERATOR WILL ACTUALLY SEE IT. `composes` is the server's
          verdict and the two figures beside it are the server's numbers: this block states
          a shortfall, it never works one out. Rendered ABOVE the budget panel because it
          changes how every target below it should be read — they are goals that, added up,
          exceed the goal they were cut from. */}
      {report.budget.composes === false && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title={BUDGET_GAP_TITLE}
        >
          <p className="mt-1">{BUDGET_GAP_BODY}</p>
          <dl className="mt-3 grid gap-3 sm:grid-cols-3">
            <BudgetItem
              label="What a caller should wait"
              value={report.budget.voice_to_voice_p50_ms}
              note="The end-to-end goal, from the caller finishing their sentence to hearing the reply begin."
            />
            <BudgetItem
              label="What the stages add up to, at best"
              value={report.budget.voice_to_voice_floor_ms}
              note="Every stage at the fastest figure its supplier publishes, plus the trip to the engine's servers and back."
            />
            {/* A SIGN FLIP, NOT A CALCULATION. `voice_to_voice_headroom_p50_ms` is the
                server's field and is negative when the stages overrun; "short by 100 ms"
                is the same fact an operator can act on, where "-100 ms left over" reads
                as a rendering bug. No target is derived here — the magnitude is the
                server's number and the label carries the sign. */}
            <BudgetItem
              label="Short by"
              value={-report.budget.voice_to_voice_headroom_p50_ms}
              note="How much longer the stages take than the end-to-end goal allows. Nothing on this page can close it."
            />
          </dl>
        </NoticeBox>
      )}

      <BudgetPanel budget={report.budget} />

      {/* The server says when it stopped counting. A subset described as a distribution is
          the defect `ExecutionListing.complete` exists for, and it is worse here than
          elsewhere: the rows it dropped are the busiest tenant's, which is the tenant whose
          latency an operator is most likely to be asked about. */}
      {!report.complete && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="These figures cover only part of the window"
        >
          <p className="mt-1">
            One or more accounts had so much traffic in this window that we only measured
            part of it, so the figures below are worked out from some of its calls rather
            than all of them. Narrow the window to get a complete answer.
          </p>
        </NoticeBox>
      )}

      {report.groups.length === 0 ? (
        <Card title="How long a reply takes, by engine and region">
          <EmptyState
            title="No timed replies in this window"
            hint="The engine records these on every call, so an empty window means either that no calls finished in this period, or that the calls that did finish came back with no timings. Widen the window before assuming the second."
          />
        </Card>
      ) : (
        report.groups.map((group) => (
          <GroupCard key={`${group.engine}:${group.region ?? ""}`} group={group} />
        ))
      )}
    </div>
  );
}

/**
 * THE WHOLE BUDGET, AS TRD §4 DECLARES IT — every target, and what they add up to.
 *
 * The panel exists because this screen used to print one of these six numbers and call it
 * the target. Every figure below is read straight off `report.budget`, including the two
 * composed totals and the headroom: those are `computed_field`s on the server, so no
 * addition happens in this bundle. A budget computed in a browser is a budget that quietly
 * becomes whatever the last build believed — the doctrine `lib/api/aiQuota.ts` states for
 * the one figure where the same mistake costs money.
 *
 * A `<dl>` rather than a table: these are labelled values, not a distribution, and the
 * tables on this screen are reserved for things that were measured.
 */
function BudgetPanel({ budget }: { budget: LatencyBudget }) {
  return (
    <Card title="What we are aiming for">
      <p className="text-xs text-ink-muted">
        Every figure here is a goal we set, not something we have measured. The three stages
        the engine times are shown against their own goals in the rows below; the rest is
        here so the parts can be read against the whole.
      </p>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {/* THE STAGE THIS PANEL USED TO HAVE NO LINE FOR. The caller stops speaking and
            something has to decide that they have — before any of the stages below start.
            It is first because it happens first, and it has no row in the tables: the
            engine reports no figure for it. */}
        <BudgetItem
          label="Noticing the caller stopped"
          value={budget.endpointing_ms}
          note="How long we wait, after the caller stops making a sound, before deciding they have finished their sentence. Nothing measures this stage, and the setting we actually run is far higher — see below."
        />
        <BudgetItem label={LEG_COPY.stt.label} value={budget.stt_ms} note={LEG_COPY.stt.gloss} />
        <BudgetItem
          label={LEG_COPY.llm_ttft.label}
          value={budget.llm_ttft_ms}
          note={LEG_COPY.llm_ttft.gloss}
        />
        <BudgetItem
          label={LEG_COPY.tts_ttfa.label}
          value={budget.tts_ttfa_ms}
          note={LEG_COPY.tts_ttfa.gloss}
        />
        {/* The one sub-budget with no distribution anywhere on this screen. It is shown
            with the reason attached rather than left out of the panel, because it is part
            of what the caller waits for and dropping it would make the sum below look
            unexplained. */}
        <BudgetItem
          label="Looking something up"
          value={budget.retrieval_ms}
          /* NOT "nothing measures it YET" — nothing PERFORMS it. In-call retrieval is T0
             and nothing else (`docs/TRD.md:948`): approved facts are compiled into the
             prompt at publish time, the engine's built-in KB is off
             (`apps/api/engine/bolna.py:2484`) and no tool does a mid-reply lookup. The
             engine's budget is still shown, because the sum below is cut from it. */
          note="The engine's own budget for a mid-reply lookup. Our agents never do one — the approved facts are already in the prompt — so there is nothing to measure and no row below."
        />
        <BudgetItem
          label={LEG_COPY.turn.label}
          value={budget.turn_ms}
          note="The three stages the engine measures, added together."
        />
        <BudgetItem
          label="A reply that needed a lookup"
          value={budget.pipeline_ms}
          note="All four stages together — everything we have set a goal for."
        />
        <BudgetItem
          label="What the caller should hear, typically"
          value={budget.voice_to_voice_p50_ms}
          note="From the caller finishing their sentence to hearing the reply begin, for a typical reply. Nobody can measure this from here — it takes a stopwatch on a real call."
        />
        <BudgetItem
          label="What the caller should hear, at worst"
          value={budget.voice_to_voice_p95_ms}
          note="The same measurement for the slowest 1 reply in 20. Also a stopwatch measurement, and one that needs far more calls than a pilot places."
        />
        <BudgetItem
          label="Getting to the engine and back"
          value={budget.india_us_transit_floor_ms}
          note="The engine runs our calls on servers in the United States and our callers are in India. This is the shortest round trip the supplier publishes for that, and it is on every reply."
        />
        <BudgetItem
          label="Everything, at best"
          value={budget.voice_to_voice_floor_ms}
          note="All the stages plus the trip, each at the fastest figure its supplier publishes. Compare it with the end-to-end goal above."
        />
        <BudgetItem
          label="Left over for everything else"
          value={budget.voice_to_voice_headroom_p50_ms}
          note="What the typical-reply goal leaves once every stage and the trip are spent: the caller's own connection, their carrier, and the gaps between the stages nobody times. A negative figure means there is nothing left."
        />
        {/* WHAT WE ACTUALLY RUN, beside what we allow. It is not part of any total on this
            panel — it is a setting, not a goal — and it is the one number here an operator
            can change without changing a supplier. */}
        <BudgetItem
          label="What we actually wait today"
          value={budget.inherited_turn_detection_ms}
          note={INHERITED_WAIT_NOTE}
        />
      </dl>
    </Card>
  );
}

/** One labelled target. The value is formatted, never computed. */
function BudgetItem({ label, value, note }: { label: string; value: number; note: string }) {
  return (
    <div>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium tabular-nums">{formatMs(value)}</dd>
      <dd className="mt-0.5 text-[11px] text-ink-faint">{note}</dd>
    </div>
  );
}

/**
 * How each verdict reads, and how it is painted.
 *
 * Keyed by the union `budgetVerdict` returns, so a fourth state added there fails `tsc`
 * here rather than rendering a blank cell. The unknown arm is deliberately NOT muted into
 * invisibility: "we could not tell" is the answer an operator has to act on by placing
 * more calls, and a cell that looked empty would read as "nothing wrong".
 */
const VERDICT_COPY: Record<BudgetVerdict, { label: string; className: string }> = {
  over: {
    label: "over target",
    className: "font-semibold text-rose-600 dark:text-rose-400",
  },
  within: {
    label: "within target",
    className: "font-medium text-brand-strong dark:text-brand-bright",
  },
  unknown: {
    label: "not enough replies",
    className: "text-ink-muted",
  },
};

/**
 * One column header: a plain label, and an optional one-line gloss beneath it.
 *
 * A component rather than repeated `<th>` markup so the metric jargon is translated in
 * exactly one shape — the operator reading this screen is not an engineer, so "typical
 * reply" and "slowest typical reply (95th percentile)" carry a sentence saying what the
 * number actually means, right under the column it labels.
 */
function HeadCell({ label, gloss }: { label: string; gloss?: string }) {
  return (
    <th scope="col" className="py-1 pr-3 align-top font-medium">
      {label}
      {gloss && (
        <span className="mt-0.5 block text-[11px] font-normal text-ink-faint">{gloss}</span>
      )}
    </th>
  );
}

/**
 * ONE (engine, region) PAIR, EVERY STAGE OF IT — a card per group, a row per stage.
 *
 * A single fleet-wide table with one row per group carried one distribution and therefore
 * one verdict, which is exactly how a reply that spent its whole budget in the transcriber
 * was reported as fine. Four rows per group is more markup and the only shape in which the
 * composed reply can sit beneath the stages it is the sum of.
 */
function GroupCard({ group }: { group: LatencyGroup }) {
  const heading = `${group.engine} — ${regionLabel(group.region)}`;
  return (
    <Card title={heading} bodyClassName="p-2">
      <p className="px-2 text-xs text-ink-muted">
        {formatCount(group.calls)} {group.calls === 1 ? "call" : "calls"},{" "}
        {formatCount(group.turns)} timed {group.turns === 1 ? "reply" : "replies"}. Each stage
        below counts only the replies that reported it, so the counts differ by row.
      </p>
      <ScrollRegion label={`How long a reply takes: ${heading}`}>
        <table className="w-full text-left text-xs">
          <thead className="text-ink-muted">
            <tr>
              <HeadCell label="Stage" />
              <HeadCell label="Target" gloss="Our goal for this stage" />
              <HeadCell label="Replies" gloss="Replies that reported this stage" />
              <HeadCell label="Typical" gloss="Half of replies were at least this fast" />
              {/* "p95" kept as the plain-English label an operator can act on, with the
                  technical term in parentheses and a one-line gloss beneath it. */}
              <HeadCell
                label="Slowest typical (95th percentile)"
                gloss="95 out of 100 replies were at least this fast"
              />
              <HeadCell label="Worst" gloss="The single slowest reply" />
              <HeadCell label="Over target" gloss="Replies slower than the target" />
              <HeadCell label="Verdict" gloss="The typical reply vs the target" />
            </tr>
          </thead>
          <tbody>
            {group.legs.map((leg) => (
              <LegRow key={leg.leg} leg={leg} />
            ))}
          </tbody>
        </table>
      </ScrollRegion>
      {/* The sample-size rule in words, with NO threshold in it. The two minimums are
          constants in `apps/api/ops/engine_latency.py` and are not on the wire, so a
          figure typed here would be a copy that goes stale silently — see
          `lib/api/engineLatency.ts::BASIS_COPY`. What a reader needs is which cells are
          a refusal and which are a number, and that does not depend on the value. */}
      <p className="mt-3 px-2 text-xs text-ink-muted">
        We don&rsquo;t show a typical or slowest-typical time until we&rsquo;ve timed enough
        replies to trust it, so a blank cell means we don&rsquo;t have enough replies yet —
        it is never zero. The worst single reply is shown no matter how few replies there
        are, because it is one real measurement rather than an estimate.
      </p>
    </Card>
  );
}

/**
 * One stage of a reply, judged against its OWN target.
 *
 * `leg.budget_ms` comes off the wire per row rather than from one number at the top of the
 * screen, which is the whole correction: the three stages have different goals and the
 * composed reply has a fourth, and a single figure at the top could only ever be one of
 * them.
 */
function LegRow({ leg }: { leg: LegSummary }) {
  const verdict = VERDICT_COPY[budgetVerdict(leg)];
  /**
   * `basis` comes off the wire, so it is read through `lookup` and not indexed
   * (`lib/lookup.ts`). TWO absences collapse to the same rendering — nothing — and both
   * are correct: `undefined` is a basis this build has no words for (a server that grew a
   * third one, where inventing a sentence is how a screen starts describing a state it has
   * never seen), and `null` is the table saying this state needs no sentence.
   */
  const basis = lookup(BASIS_COPY, leg.basis);
  const copy = lookup(LEG_COPY, leg.leg);

  return (
    <tr className="border-t border-line align-top">
      <td className="py-1.5 pr-3">
        {/* A leg this build has no words for prints its wire name rather than an empty
            cell — the same fallback direction `regionLabel` takes for a region code the
            vendor invented after this bundle was built. */}
        {copy?.label ?? <MonoValue>{leg.leg}</MonoValue>}
        {copy && (
          <span className="mt-0.5 block text-[11px] text-ink-faint">{copy.gloss}</span>
        )}
        {basis != null && (
          <span className="mt-0.5 block text-[11px] text-ink-faint">{basis}</span>
        )}
        {/* The doubt is the SERVER's field, not this screen's opinion: a verdict computed
            from a number whose unit nobody has confirmed is not a verdict, and the row that
            prints it says so rather than leaving the caveat in a module docstring. */}
        {!leg.unit_verified && (
          <span className="mt-0.5 block text-[11px] text-amber-700 dark:text-amber-400">
            {UNVERIFIED_UNIT_NOTE}
          </span>
        )}
      </td>
      <td className="py-1.5 pr-3 tabular-nums">{formatMs(leg.budget_ms)}</td>
      <td className="py-1.5 pr-3 tabular-nums">{formatCount(leg.turns)}</td>
      <td className="py-1.5 pr-3 tabular-nums">{formatMs(leg.p50_ms)}</td>
      <td className="py-1.5 pr-3 tabular-nums">{formatMs(leg.p95_ms)}</td>
      <td className="py-1.5 pr-3 tabular-nums">{formatMs(leg.max_ms)}</td>
      <td className="py-1.5 pr-3 tabular-nums">
        {formatCount(leg.turns_over_budget)}
        {leg.turns > 0 && <span className="text-ink-faint"> of {formatCount(leg.turns)}</span>}
      </td>
      <td className={`py-1.5 pr-3 ${verdict.className}`}>{verdict.label}</td>
    </tr>
  );
}
