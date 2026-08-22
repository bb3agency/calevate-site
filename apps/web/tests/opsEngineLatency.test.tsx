import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import EngineLatencyPage from "@/app/admin/ops/engine-latency/page";
import {
  ENGINE_LATENCY_PATH,
  type EngineLatencyReport,
  type LatencyGroup,
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
 * 2. **`budget_breached` has THREE states.** True, false, and "the sample cannot support
 *    a median". The third must not render like the second: "within target" over a group
 *    nothing was measured against is the sentence that makes a latency problem invisible.
 * 3. **A failed read is not "the engine reported nothing".** §52 on a payload where the
 *    empty state is a claim about our own instrumentation — an operator who believes it
 *    goes looking for a broken adapter instead of for a broken API.
 * 4. **A refused session is told so, and is not shown an outage.** The read carries
 *    `ops:manage`, so a session without it can only collect a 403 — and a 403 rendered as
 *    a red failure box with a retry button is a permission working as designed dressed up
 *    as a platform fault, on the screen a runbook just sent that operator to.
 * 5. **The window the chips ask for is the window the API is asked for**, and the report
 *    states the window it answered for rather than the one the browser believes.
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

/** A group with enough turns to state a median, missing our target. */
function measured(over: Partial<LatencyGroup> = {}): LatencyGroup {
  return {
    engine: "bolna",
    region: "us",
    calls: 12,
    turns: 240,
    basis: "measured",
    llm_ttft_p50_ms: 412.5,
    llm_ttft_p95_ms: 980.2,
    llm_ttft_max_ms: 1633.04,
    turns_over_budget: 190,
    budget_breached: true,
    ...over,
  };
}

/**
 * A group the server REFUSED to summarise — three turns, so no median and no verdict.
 *
 * The optional fields are ABSENT rather than null, because that is what the API sends: a
 * Pydantic field with a `None` default is omitted, and a fixture that spelled them `null`
 * would test a wire this server does not produce.
 */
function tooFew(over: Partial<LatencyGroup> = {}): LatencyGroup {
  return {
    engine: "bolna",
    region: null,
    calls: 1,
    turns: 3,
    basis: "insufficient_samples",
    llm_ttft_max_ms: 288.1,
    turns_over_budget: 0,
    ...over,
  };
}

function report(over: Partial<EngineLatencyReport> = {}): EngineLatencyReport {
  return {
    window_days: 7,
    llm_ttft_budget_ms: 350,
    complete: true,
    groups: [measured()],
    ...over,
  };
}

function routes(over: Routes = {}): Routes {
  return { [ADMIN_ME_PATH]: SUPERADMIN, [WINDOW_PATH(7)]: report(), ...over };
}

/** The data row for one region, as its cells. */
async function rowFor(region: string): Promise<string[]> {
  await screen.findByRole("table");
  const row = within(screen.getByRole("table"))
    .getAllByRole("row")
    .find((candidate) => (candidate.textContent ?? "").includes(region));
  expect(row).toBeDefined();
  return within(row as HTMLElement)
    .getAllByRole("cell")
    .map((cell) => cell.textContent ?? "");
}

describe("the engine latency report", () => {
  it("prints the server's own percentiles and its budget verdict", async () => {
    const { container } = renderAdminPage(<EngineLatencyPage />, routes());

    const cells = await rowFor("United States");
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
    // The region CODE stays beside the country: it is what the vendor stamps and what an
    // operator greps their own logs for.
    expect(cells.join(" ")).toContain("us");
    // The target itself comes off the payload, never from a constant in this bundle.
    expect(container.textContent).toContain("350 ms");
  });

  it("never invents a percentile the server withheld, and never calls it within target", async () => {
    renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(7)]: report({ groups: [tooFew()] }) }),
    );

    const cells = await rowFor("Region not reported");
    // The median and the p95 are em dashes, NOT zeros. A zero here would be the fastest
    // number on the screen sitting exactly where "not enough turns to say" belongs.
    expect(cells.filter((cell) => cell === "—")).toHaveLength(2);
    expect(cells).not.toContain("0 ms");
    // The maximum IS printed at any sample size: an observation, not an estimate.
    expect(cells).toContain("288 ms");
    // The third state of `budget_breached`, said as itself.
    expect(cells.join(" ")).toContain("not enough turns");
    expect(cells.join(" ")).not.toContain("within target");
    // The reason is beside the row, and it names NO threshold: `P50_MIN_TURNS` is a
    // constant in `engine_latency.py` that never reaches the wire, so a figure typed into
    // this console would be a second copy of it going stale in silence.
    expect(cells.join(" ")).toContain("Too few timed turns");
    expect(cells.join(" ")).not.toMatch(/fewer than (five|5)/i);
  });

  it("says when the report describes only part of the window", async () => {
    const { container } = renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(7)]: report({ complete: false }) }),
    );

    await screen.findByRole("table");
    expect(container.textContent).toContain("This describes a subset of the window");
  });

  it("asks the API for the window the chips ask for", async () => {
    const { calls } = renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(30)]: report({ window_days: 30, groups: [] }) }),
    );

    await screen.findByRole("table");
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
    // "No timed turns in this window" is a claim about our own instrumentation, and a 503
    // is not evidence for it. Neither is a skeleton left on screen forever.
    expect(container.textContent).not.toContain("No timed turns in this window");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("shows a skeleton while the report is in flight and no figure at all", async () => {
    const { container } = renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(7)]: stillLoading() }),
    );

    await screen.findByText("Loading the engine's latency report");
    expect(container.textContent).not.toContain("No timed turns in this window");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("reports an empty window only when the server actually sent one", async () => {
    const { container } = renderAdminPage(
      <EngineLatencyPage />,
      routes({ [WINDOW_PATH(7)]: report({ groups: [] }) }),
    );

    await waitFor(() => expect(container.textContent).toContain("No timed turns in this window"));
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
          detail: "This action requires the ops:manage permission.",
        }),
      }),
    );

    await waitFor(() =>
      expect(container.textContent).toContain("does not have the ops:manage permission"),
    );
    // No red failure box, and therefore no retry button whose only outcome is another 403.
    expect(container.textContent).not.toContain("Forbidden");
    expect(screen.queryByRole("button", { name: /Try again/i })).toBeNull();
    // And no window picker over a report that is not there, no table, and above all no
    // claim about what the engine measured.
    expect(screen.queryByRole("group", { name: "Choose a window" })).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.textContent).not.toContain("No timed turns in this window");
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
      expect(container.textContent).toContain("does not have the ops:manage permission"),
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
