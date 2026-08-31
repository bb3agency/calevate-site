import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import EngineLatencyPage from "@/app/admin/ops/engine-latency/page";
import {
  ENGINE_LATENCY_PATH,
  type EngineLatencyReport,
  type LatencyBudget,
  type LatencyGroup,
  type LatencyLeg,
  type LegSummary,
} from "@/lib/api/engineLatency";

import { problem, renderAdminPage, stillLoading, type Routes } from "./harness";

/**
 * The engine-latency report — the console half of `GET /v1/ops/engine-latency`.
 *
 * The endpoint landed with no path in the console, so OPERATIONS §2 gate 4 and
 * `runbooks/alarm-index.md::engine_llm_ttft_degraded` both told an operator to
 * hand-assemble a curl against production, mid-incident. What this screen must get right
 * is therefore not layout — it is the set of claims it is allowed to make about a
 * measurement, ranked here by what each failure costs:
 *
 * 1. **A withheld percentile must never render as a number.** `engine_latency.py` refuses
 *    a p50 below five timed turns and a p95 below twenty, and says so in `basis`. A
 *    console that filled either in — from the maximum, or from a zero — would hand an
 *    operator a percentile computed from three turns and let them close gate 4 on it.
 * 2. **`budget_breached` has THREE states, and there is one per STAGE.** True, false, and
 *    "the sample cannot support a median". The third must not render like the second:
 *    "within target" over a leg nothing was measured against is the sentence that makes a
 *    latency problem invisible. And the stages are judged separately on purpose — a reply
 *    that spends 120ms in the model and 900ms in the transcriber is within target on the
 *    language leg and over budget as a reply, which is the defect this screen's second
 *    version exists for.
 * 3. **A failed read is not "the engine reported nothing".** §52 on a payload where the
 *    empty state is a claim about our own instrumentation — an operator who believes it
 *    goes looking for a broken adapter instead of for a broken API.
 * 4. **A refused session is told so, and is not shown an outage.** The read carries
 *    `ops:manage`, so a session without it can only collect a 403 — and a 403 rendered as
 *    a red failure box with a retry button is a permission working as designed dressed up
 *    as a platform fault, on the screen a runbook just sent that operator to.
 * 5. **The window the chips ask for is the window the API is asked for**, and the report
 *    states the window it answered for rather than the one the browser believes.
 * 6. **No target is computed in the browser.** Every figure in the budget panel is a wire
 *    field, including the composed totals. The fixtures below therefore carry budget
 *    numbers that are deliberately NOT the ones TRD §4 declares and are deliberately not
 *    self-consistent: a fixture that agreed with the server's own constants could not tell
 *    a payload-sourced figure apart from a hardcoded one.
 */

const SUPERADMIN: AdminMe = {
  user_id: "0192f0aa-7777-7000-8000-0000000000e1",
  realm: "admin",
  role: "superadmin",
  permissions: ["ops:manage", "admin:tenants"],
};

/** An admin who may run the console but may not read platform state. */
const OPERATOR: AdminMe = {
  user_id: "0192f0aa-7777-7000-8000-0000000000e2",
  realm: "admin",
  role: "operator",
  permissions: ["admin:tenants", "org:read"],
};

const WINDOW_PATH = (days: number) => `${ENGINE_LATENCY_PATH}?days=${days}`;

/**
 * A BUDGET THAT IS NOT THE REAL ONE, ON PURPOSE.
 *
 * Not one of these numbers is what TRD §4 declares, and `turn_ms` is deliberately not the
 * sum of the three legs above it. Both choices are the same assertion: the screen prints
 * what the server sent. A fixture carrying the real budget and a consistent total would
 * pass identically against a bundle that had hardcoded the spec or added the legs up
 * itself, which are precisely the two failures this surface must not have.
 *
 * `composes: true` here for the same reason it is FALSE in the product: the verdict is the
 * server's, so the screen must be shown obeying both answers. The false case has its own
 * test below, on its own fixture.
 */
const BUDGET: LatencyBudget = {
  endpointing_ms: 101,
  stt_ms: 311,
  llm_ttft_ms: 371,
  tts_ttfa_ms: 331,
  retrieval_ms: 111,
  india_us_transit_floor_ms: 101,
  inherited_turn_detection_ms: 651,
  voice_to_voice_p50_ms: 1171,
  voice_to_voice_p95_ms: 1871,
  turn_ms: 941,
  pipeline_ms: 1051,
  voice_to_voice_floor_ms: 1151,
  voice_to_voice_headroom_p50_ms: 121,
  composes: true,
};

/** One stage's summary. Enough turns to state a median, missing its target. */
function leg(over: Partial<LegSummary> & { leg: LatencyLeg }): LegSummary {
  return {
    budget_ms: BUDGET.llm_ttft_ms,
    turns: 240,
    basis: "measured",
    p50_ms: 412.5,
    p95_ms: 980.2,
    max_ms: 1633.04,
    turns_over_budget: 190,
    budget_breached: true,
    unit_verified: true,
    ...over,
  };
}

/**
 * A stage the server REFUSED to summarise — three turns, so no median and no verdict.
 *
 * The optional fields are ABSENT rather than null, because that is what the API sends: a
 * Pydantic field with a `None` default is omitted, and a fixture that spelled them `null`
 * would test a wire this server does not produce.
 */
function tooFewLeg(over: Partial<LegSummary> & { leg: LatencyLeg }): LegSummary {
  return {
    budget_ms: BUDGET.llm_ttft_ms,
    turns: 3,
    basis: "insufficient_samples",
    max_ms: 288.1,
    turns_over_budget: 0,
    unit_verified: true,
    ...over,
  };
}

/** A group with a measured summary for every stage. */
function measured(over: Partial<LatencyGroup> = {}): LatencyGroup {
  return {
    engine: "bolna",
    region: "us",
    calls: 12,
    turns: 240,
    legs: [
      leg({ leg: "stt", budget_ms: BUDGET.stt_ms, unit_verified: false }),
      leg({ leg: "llm_ttft" }),
      leg({ leg: "tts_ttfa", budget_ms: BUDGET.tts_ttfa_ms }),
      leg({ leg: "turn", budget_ms: BUDGET.turn_ms, unit_verified: false }),
    ],
    ...over,
  };
}

/** A group the server could summarise on no stage at all. */
function tooFew(over: Partial<LatencyGroup> = {}): LatencyGroup {
  return {
    engine: "bolna",
    region: null,
    calls: 1,
    turns: 3,
    legs: [
      tooFewLeg({ leg: "stt", budget_ms: BUDGET.stt_ms, unit_verified: false }),
      tooFewLeg({ leg: "llm_ttft" }),
      tooFewLeg({ leg: "tts_ttfa", budget_ms: BUDGET.tts_ttfa_ms }),
      tooFewLeg({ leg: "turn", budget_ms: BUDGET.turn_ms, unit_verified: false }),
    ],
    ...over,
  };
}

function report(over: Partial<EngineLatencyReport> = {}): EngineLatencyReport {
  return {
    window_days: 7,
    budget: BUDGET,
    complete: true,
    groups: [measured()],
    ...over,
  };
}

function routes(over: Routes = {}): Routes {
  return { [ADMIN_ME_PATH]: SUPERADMIN, [WINDOW_PATH(7)]: report(), ...over };
}

/**
 * One STAGE's row, as its cells — from the single group the default fixtures render.
 *
 * A card and a table per (engine, region) pair rather than one fleet-wide table, because a
 * group now carries four distributions and four verdicts. The tests that care about two
 * groups reach for `getAllByRole("table")` themselves.
 */
async function rowFor(stage: string): Promise<string[]> {
  const tables = await screen.findAllByRole("table");
  const row = within(tables[0])
    .getAllByRole("row")
    .find((candidate) => (candidate.textContent ?? "").includes(stage));
  expect(row).toBeDefined();
  return within(row as HTMLElement)
    .getAllByRole("cell")
    .map((cell) => cell.textContent ?? "");
}

describe("the engine latency report", () => {
  it("foregrounds how many rows are over target, counting verdicts and never deriving one (F-15)", async () => {
    // Default `measured()` has breached legs; the second group has no verdict at all.
    const { container } = renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(7)]: report({ groups: [measured(), tooFew()] }) }),
    );
    await screen.findAllByText("Over target");
    // The alarm's question, answered above the table: one of two rows is over, and the
    // unjudgeable row is named separately so "could not tell" never reads as "fine".
    expect(container.textContent).toContain("1 of 2");
    expect(container.textContent).toContain("1 more row(s) could not be judged");
  });

  it("prints the server's own percentiles and its budget verdict", async () => {
    const { container } = renderAdminPage(<EngineLatencyPage />, routes());

    const cells = await rowFor("Thinking of a reply");
    // Rounded to whole milliseconds — these are float8 timings, not money, and the
    // sub-millisecond digits the engine reports are noise a reader cannot act on.
    expect(cells).toContain("413 ms");
    expect(cells).toContain("980 ms");
    expect(cells).toContain("1,633 ms");
    // The verdict is the SERVER's `budget_breached` and is about the median turn. It is
    // not recomputed here from p50 against the budget: that would be a second spelling of
    // a rule `engine_latency.py` already owns, and the two would disagree the day the
    // rule moved off the median.
    expect(cells.join(" ")).toContain("over target");
    // The stage carries ITS OWN target, in its own row.
    expect(cells).toContain("371 ms");
    // The region CODE stays beside the country: it is what the vendor stamps and what an
    // operator greps their own logs for.
    expect(container.textContent).toContain("United States (us)");
  });

  it("judges every stage against its own target, and the whole reply against the sum", async () => {
    /*
     * THE DEFECT THIS SCREEN'S SECOND VERSION EXISTS FOR, rendered.
     *
     * The language leg is comfortably inside its target and the transcriber leg is not, so
     * the composed reply is over budget. A screen carrying one verdict — the model's — put
     * "within target" on that row and an operator had nothing to read that disagreed.
     */
    const split = measured({
      legs: [
        leg({
          leg: "stt",
          budget_ms: BUDGET.stt_ms,
          unit_verified: false,
          p50_ms: 900,
          budget_breached: true,
        }),
        leg({ leg: "llm_ttft", p50_ms: 120, budget_breached: false, turns_over_budget: 0 }),
        leg({
          leg: "tts_ttfa",
          budget_ms: BUDGET.tts_ttfa_ms,
          p50_ms: 250,
          budget_breached: false,
          turns_over_budget: 0,
        }),
        leg({
          leg: "turn",
          budget_ms: BUDGET.turn_ms,
          unit_verified: false,
          p50_ms: 1270,
          budget_breached: true,
        }),
      ],
    });
    renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(7)]: report({ groups: [split] }) }),
    );

    expect((await rowFor("Thinking of a reply")).join(" ")).toContain("within target");
    expect((await rowFor("Hearing the caller")).join(" ")).toContain("over target");
    const whole = await rowFor("The whole reply");
    expect(whole.join(" ")).toContain("over target");
    // And it is judged against the COMPOSED target, which is a different number from any
    // single stage's — and comes off the wire already summed.
    expect(whole).toContain("941 ms");
  });

  it("shows the whole budget and never adds two targets together", async () => {
    const { container } = renderAdminPage(<EngineLatencyPage />, routes());
    await screen.findAllByRole("table");

    // Every figure TRD §4 declares, as the SERVER sent it. None of these is the number the
    // spec states, so a bundle that had hardcoded the spec would fail here.
    for (const target of ["311 ms", "371 ms", "331 ms", "111 ms", "1,171 ms", "1,871 ms"]) {
      expect(container.textContent).toContain(target);
    }
    // The composed totals and the headroom are the server's arithmetic. The fixture's
    // `turn_ms` is deliberately NOT 311 + 371 + 331, so a browser that summed the legs
    // itself would print 1,013 ms here and fail.
    expect(container.textContent).toContain("941 ms");
    expect(container.textContent).not.toContain("1,013 ms");
    expect(container.textContent).toContain("1,051 ms");
    expect(container.textContent).toContain("121 ms");
    // The two stages the budget carries and the engine does not measure are BOTH shown,
    // and the new one is the wait before the reply starts — the stage TRD §4 had no line
    // for until 27 Aug 2026.
    expect(container.textContent).toContain("101 ms");
    expect(container.textContent).toContain("Noticing the caller stopped");
    expect(container.textContent).toContain("Getting to the engine and back");
    // What we actually wait today, beside what we allow. A setting, not a goal, and it is
    // in no total on the panel.
    expect(container.textContent).toContain("651 ms");
    expect(container.textContent).toContain("What we actually wait today");
    // The retrieval target is shown, and is explicitly NOT given a measured row.
    expect(container.textContent).toContain("Looking something up");
    const stages = within((await screen.findAllByRole("table"))[0])
      .getAllByRole("row")
      .map((row) => row.textContent ?? "");
    expect(stages.some((row) => row.includes("Looking something up"))).toBe(false);
  });

  it("states the shortfall when the stage goals do not fit inside the end-to-end goal", async () => {
    /*
     * THE FOUNDER'S 500ms, AND THE HONEST ANSWER TO IT. `composes` is the server's verdict
     * and the three figures beside it are the server's fields: the screen states a
     * shortfall it did not work out. This is the case that matters in production — the
     * declared stages floor at 600ms against a 500ms target — and a guard test failing in
     * CI is invisible to the operator this console is for.
     */
    const short: LatencyBudget = {
      ...BUDGET,
      voice_to_voice_p50_ms: 501,
      voice_to_voice_floor_ms: 601,
      voice_to_voice_headroom_p50_ms: -100,
      composes: false,
    };
    const { container } = renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(7)]: report({ budget: short }) }),
    );
    await screen.findAllByRole("table");

    expect(container.textContent).toContain("do not fit inside");
    expect(container.textContent).toContain("501 ms");
    expect(container.textContent).toContain("601 ms");
    // The magnitude of the server's negative headroom, under a label that carries the
    // sign. "-100 ms left over" reads as a rendering bug; "short by 100 ms" is the fact.
    expect(container.textContent).toContain("Short by");
    expect(container.textContent).toContain("100 ms");
  });

  it("says nothing about a shortfall when the server says the budget fits", async () => {
    /* The verdict is the SERVER's in both directions: a banner that appeared regardless
       would be this screen holding an opinion about a target, which is the one thing the
       whole surface refuses to do. The default fixture carries `composes: true`. */
    const { container } = renderAdminPage(<EngineLatencyPage />, routes());
    await screen.findAllByRole("table");

    expect(container.textContent).not.toContain("do not fit inside");
    expect(container.textContent).not.toContain("Short by");
  });

  it("says when the unit of a stage's measurement is not confirmed", async () => {
    /*
     * `unit_verified` is the server's field, false on the transcriber leg: the vendor's
     * field table calls `audio_to_text_latency` milliseconds while their own example
     * carries 20.12. The doubt has to reach the operator reading the verdict, not stop at
     * a module docstring.
     */
    renderAdminPage(<EngineLatencyPage />, routes());

    expect((await rowFor("Hearing the caller")).join(" ")).toContain("have not confirmed what unit");
    expect((await rowFor("The whole reply")).join(" ")).toContain("have not confirmed what unit");
    expect((await rowFor("Thinking of a reply")).join(" ")).not.toContain(
      "have not confirmed what unit",
    );
  });

  it("never invents a percentile the server withheld, and never calls it within target", async () => {
    renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(7)]: report({ groups: [tooFew()] }) }),
    );

    const cells = await rowFor("Thinking of a reply");
    // The median and the p95 are em dashes, NOT zeros. A zero here would be the fastest
    // number on the screen sitting exactly where "not enough turns to say" belongs.
    expect(cells.filter((cell) => cell === "—")).toHaveLength(2);
    expect(cells).not.toContain("0 ms");
    // The maximum IS printed at any sample size: an observation, not an estimate.
    expect(cells).toContain("288 ms");
    // The third state of `budget_breached`, said as itself in plain words.
    expect(cells.join(" ")).toContain("not enough replies");
    expect(cells.join(" ")).not.toContain("within target");
    // The reason is beside the row, and it names NO threshold: `P50_MIN_TURNS` is a
    // constant in `engine_latency.py` that never reaches the wire, so a figure typed into
    // this console would be a second copy of it going stale in silence.
    expect(cells.join(" ")).toContain("Too few timed replies");
    expect(cells.join(" ")).not.toMatch(/fewer than (five|5)/i);
    // And the group still names the region it could not summarise — an unattributable
    // measurement is itself a finding.
    expect(screen.getByText(/Region not reported/)).toBeTruthy();
  });

  it("says when the report describes only part of the window", async () => {
    const { container } = renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(7)]: report({ complete: false }) }),
    );

    await screen.findAllByRole("table");
    expect(container.textContent).toContain("These figures cover only part of the window");
  });

  it("asks the API for the window the chips ask for", async () => {
    const { calls } = renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(30)]: report({ window_days: 30, groups: [] }) }),
    );

    await screen.findAllByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Last 30 days" }));

    await waitFor(() => {
      expect(calls.some((call) => call.path === WINDOW_PATH(30))).toBe(true);
    });
    // And the window on screen is the one the SERVER answered for, so a request that was
    // clamped or served from another window cannot be described as the one that was asked
    // for.
    await waitFor(() => expect(screen.getByText("30 days")).toBeTruthy());
  });

  it("does not report an empty window over a read that failed", async () => {
    const { container } = renderAdminPage(
      <EngineLatencyPage />,
      routes({
        [WINDOW_PATH(7)]: problem(503, {
          type: "urn:calevate:ops/unavailable",
          title: "Service unavailable",
          detail: "The report could not be assembled.",
        }),
      }),
    );

    await waitFor(() => expect(container.textContent).toContain("could not be assembled"));
    // "No timed replies in this window" is a claim about our own instrumentation, and a 503
    // is not evidence for it. Neither is a skeleton left on screen forever.
    expect(container.textContent).not.toContain("No timed replies in this window");
    expect(screen.queryAllByRole("table")).toHaveLength(0);
  });

  it("shows a skeleton while the report is in flight and no figure at all", async () => {
    const { container } = renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(7)]: stillLoading() }),
    );

    await screen.findByText("Loading the engine's latency report");
    expect(container.textContent).not.toContain("No timed replies in this window");
    expect(screen.queryAllByRole("table")).toHaveLength(0);
  });

  it("reports an empty window only when the server actually sent one", async () => {
    const { container } = renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(7)]: report({ groups: [] }) }),
    );

    await waitFor(() => expect(container.textContent).toContain("No timed replies in this window"));
  });

  it("withholds the report from a session the server would refuse, and never paints it as an outage", async () => {
    const { container } = renderAdminPage(
      <EngineLatencyPage />,
      // The route ANSWERS 403, which is what the server does. The claim below is that the
      // screen says the permission rather than the failure — an operator sent here by
      // `runbooks/alarm-index.md` must not conclude the platform is down.
      routes({
        [ADMIN_ME_PATH]: OPERATOR,
        [WINDOW_PATH(7)]: problem(403, {
          type: "urn:calevate:auth/forbidden",
          title: "Forbidden",
          detail: "You do not have permission to do this.",
        }),
      }),
    );

    await waitFor(() =>
      expect(container.textContent).toContain("does not have permission to"),
    );
    // No red failure box, and therefore no retry button whose only outcome is another 403.
    expect(container.textContent).not.toContain("Forbidden");
    expect(screen.queryByRole("button", { name: /Try again/i })).toBeNull();
    // And no window picker over a report that is not there, no table, and above all no
    // claim about what the engine measured.
    expect(screen.queryByRole("group", { name: "Choose a window" })).toBeNull();
    expect(screen.queryAllByRole("table")).toHaveLength(0);
    expect(container.textContent).not.toContain("No timed replies in this window");
  });

  /**
   * The gate is `!refused`, so the ONE request a cold render issues before the identity
   * answer lands is expected — and it is the last one.
   *
   * Spelled as a count rather than as "no request at all", because that stronger claim is
   * false and the reason it is false is the design: `access.ts` requires navigation to
   * fail OPEN on the unknown, so the report is fetched while `/v1/admin/me` is in flight
   * and withheld only once the server has actually said no. In the console the shell has
   * usually resolved that identity before a page mounts (`admin/layout.tsx` reads it for
   * the sidebar, same query key), so the common case really is zero — but a test that
   * asserted zero would be pinning a cache-warming accident rather than the rule.
   */
  it("stops asking once the refusal has landed", async () => {
    const { container, calls } = renderAdminPage(
      <EngineLatencyPage />,
      routes({
        [ADMIN_ME_PATH]: OPERATOR,
        [WINDOW_PATH(7)]: problem(403, { title: "Forbidden" }),
      }),
    );

    await waitFor(() =>
      expect(container.textContent).toContain("does not have permission to"),
    );
    const reads = calls.filter((call) => call.path.startsWith(ENGINE_LATENCY_PATH)).length;
    expect(reads).toBeLessThanOrEqual(1);
    // Nothing re-arms it: no retry control is on screen, and the disabled query does not
    // refetch. A settle is given so a queued refetch would have had its chance to fire.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(calls.filter((call) => call.path.startsWith(ENGINE_LATENCY_PATH)).length).toBe(reads);
  });

  it("still asks while the identity read is unknown — navigation fails open", async () => {
    // `/v1/admin/me` never answers. `allowed` is false throughout and `refused` never
    // becomes true, and the difference is the whole reason `access.ts` carries two
    // booleans: an identity read that is merely slow must not lock an operator out of an
    // incident read the API would have served.
    const { calls } = renderAdminPage(
      <EngineLatencyPage />,
      routes({ [ADMIN_ME_PATH]: stillLoading() }),
    );

    await waitFor(() => expect(calls.some((call) => call.path === WINDOW_PATH(7))).toBe(true));
  });
});

/*
 * NO AXE SWEEP HERE. `tests/a11y.test.tsx` registers this screen with exactly the fixture
 * a duplicate would have used — one measured group and one withheld — and the coverage
 * guard in that file reads `src/app` off disk, so the screen cannot fall out of the sweep
 * silently. A second scan spelled here would be the same check in two places, which is the
 * shape this repo treats as a defect even when both pass.
 */
