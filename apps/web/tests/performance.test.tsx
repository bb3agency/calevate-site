import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PerformancePage from "@/app/c/[slug]/performance/page";
import type { Me } from "@/lib/api/client";
import type { Performance } from "@/lib/api/performance";

import { problem, renderClientPage } from "./harness";

/**
 * The performance report — the screen an owner uses to decide whether the agent is worth
 * paying for. Every number on it is an argument, so a wrong one is not a cosmetic defect.
 *
 * Ranked by what a wrong render costs:
 *
 * 1. **A null rate rendered as 0%.** `connect_rate_pct` is null — never 0 — when there
 *    were no calls to measure, and the server goes out of its way to keep the two apart
 *    (`PerformanceOut`, crm/performance.py). "0% answered" tells a client who has not
 *    launched yet that their agent is failing; it is the one wrong number on this screen
 *    that would make someone cancel.
 * 2. **A 0% rendered as "no data".** The same distinction from the other side, and the
 *    reason a `?? "—"` is not good enough: calls that happened and never connected are
 *    the bad news this report exists to deliver.
 * 3. **Figures under a failed request.** A refusal, never a zero and never a blank —
 *    the previous screen answered a failed refetch with `return null`, i.e. nothing at
 *    all.
 * 4. **A silent hour dropped from the histogram.** The API guarantees 24 buckets for
 *    this reason; a chart missing 3am reads as data loss to the only person who would
 *    notice.
 * 5. **A caption naming a period the numbers are not for.** The chips say what was
 *    asked; every sentence says what the server measured.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read", "leads:read"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", plan_tier: "managed" },
} as unknown as Me;

/** 24 IST buckets, as the API always sends them — silent hours are 0, not absent. */
const HOURS = [0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 5, 3, 1, 0, 0, 4, 6, 9, 12, 7, 2, 0, 0, 0];

function performance(over: Partial<Performance> = {}): Performance {
  return {
    days: 30,
    funnel: { calls: 51, connected: 39, qualified: 14 },
    connect_rate_pct: 76,
    qualify_rate_pct: 36,
    inbound: 30,
    outbound: 21,
    avg_duration_s: 154,
    outcomes: { appointment_booked: 14, no_answer: 8, enquiry: 29 },
    busiest_hours_ist: HOURS,
    ...over,
  } as unknown as Performance;
}

/** Nothing has happened yet — the state most likely to be rendered as failure. */
const NOTHING_YET = performance({
  funnel: { calls: 0, connected: 0, qualified: 0 },
  connect_rate_pct: null,
  qualify_rate_pct: null,
  inbound: 0,
  outbound: 0,
  avg_duration_s: null,
  outcomes: {},
  busiest_hours_ist: Array.from({ length: 24 }, () => 0),
});

const page = <PerformancePage />;

function routes(over: Record<string, unknown> = {}) {
  return { "/v1/me": ME, "/v1/performance?days=30": performance(), ...over };
}

describe("the performance report", () => {
  it("says there is nothing to measure rather than reporting 0%", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/performance?days=30": NOTHING_YET }),
    );

    await screen.findByText("Calls answered");
    // THE assertion. A brand-new client has made no calls; "0% answered" would be a
    // verdict on an agent that has never rung, and it is the number that gets us
    // cancelled in week one.
    expect(container.textContent, "a null rate must never render as a percentage").not.toContain(
      "0%",
    );
    expect(container.textContent).toContain("No calls yet — nothing to measure");
    expect(container.textContent).toContain("No answered calls yet — nothing to measure");
    // And the tile itself carries the em dash, not a fabricated figure.
    expect(container.textContent).not.toContain("undefined");
    expect(container.textContent).not.toContain("null%");
  });

  it("reports a real 0% as 0%, because that is bad news the owner has to see", async () => {
    // Twelve calls, none of which reached a conversation. This is the opposite fact from
    // the test above and the screen must not collapse the two.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/performance?days=30": performance({
          funnel: { calls: 12, connected: 0, qualified: 0 },
          connect_rate_pct: 0,
          // The denominator for the second rate is `connected`, so it is genuinely null
          // here even though calls happened — both states on one screen at once.
          qualify_rate_pct: null,
        }),
      }),
    );

    await screen.findByText("Calls answered");
    expect(container.textContent).toContain("0%");
    expect(container.textContent).toContain("0 of 12 reached a real conversation");
    // The "nothing to measure" copy belongs to the OTHER state; printing it here would
    // hide a failing agent behind a shrug.
    expect(container.textContent).not.toContain("No calls yet — nothing to measure");
    expect(container.textContent).toContain("No answered calls yet — nothing to measure");
  });

  it("shows a refusal instead of figures when the request fails", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/performance?days=30": problem(503, {
          title: "Service unavailable",
          detail: "We could not read your call history.",
        }),
      }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // Not a percentage, not a funnel, not an empty state that reads like a verdict on
    // the business rather than on the request.
    expect(container.textContent).not.toContain("%");
    expect(container.textContent).not.toContain("No calls in this period");
    expect(container.textContent).not.toContain("Nothing to show yet");
    expect(container.textContent).not.toContain("Calls answered");
  });

  it("draws all 24 IST hours, silent ones included and labelled with their zero", async () => {
    const { container } = await renderClientPage(page, routes());
    await screen.findByText("Busiest hours (IST)");

    const bars = Array.from(container.querySelectorAll("[title]")).filter((el) =>
      /\b\d+ calls?$/.test(el.getAttribute("title") ?? ""),
    );
    expect(bars, "one bar per IST hour, always 24").toHaveLength(24);

    // A silent hour is a FACT about that hour: it keeps its column and prints its 0.
    // Dropping it would slide every later bar an hour earlier and misdate the whole day.
    const dead = screen.getByTitle("3 am: 0 calls");
    expect(dead.textContent).toContain("0");
    // And the busiest hour prints its own number, so the picture is checkable without
    // hovering anything (the dashboard's chart doctrine).
    expect(screen.getByTitle("6 pm: 12 calls").textContent).toContain("12");
    expect(screen.getByTitle("12 midnight: 0 calls")).toBeTruthy();
  });

  it("names the period the SERVER measured, not the one the chip asked for", async () => {
    // The chips default to 30 days; the server answers with 7. That mismatch is real —
    // it is what a switch in flight looks like — and a caption reading "last 30 days"
    // over 7 days of numbers is a lie the reader has no way to catch.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/performance?days=30": performance({ days: 7 }) }),
    );

    await screen.findByText("How your phone agent did over the last 7 days.");
    expect(container.textContent).not.toContain("over the last 30 days");
  });

  it("explains a missing permission instead of answering with an error", async () => {
    // `GET /v1/performance` requires `calls:read`. A session without it used to reach a
    // red 403 alert, which reads like an outage rather than like a permission.
    const { container } = await renderClientPage(
      page,
      // No `/v1/performance` route at all: the screen must not send the request, and the
      // harness throws if it does.
      { "/v1/me": { ...ME, permissions: ["leads:read"] } },
    );

    await screen.findByText(/permission to read call records/);
    expect(screen.queryByRole("alert"), "a permission is not a fault").toBeNull();
    expect(container.textContent).not.toContain("Calls answered");
    expect(container.textContent).not.toContain("%");
  });

  it("counts the calls the histogram cannot show rather than letting them go missing", async () => {
    // The buckets count calls that HAVE a start time; the funnel counts every call made.
    // A dial that never reached the network is in one and not the other, and an owner who
    // adds up the bars and comes up short has no way to know which number to distrust.
    const started = HOURS.reduce((sum, n) => sum + n, 0);
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/performance?days=30": performance({
          funnel: { calls: started + 4, connected: 39, qualified: 14 },
        }),
      }),
    );
    await screen.findByText("Busiest hours (IST)");
    expect(container.textContent).toContain(
      `${started} of ${started + 4} calls in this period have a start time`,
    );
  });

  it("says nothing about a shortfall when there is none", async () => {
    // The default fixture's buckets add up to the funnel exactly. Printing "51 of 51"
    // would invite a reader to look for a discrepancy that is not there.
    const { container } = await renderClientPage(page, routes());
    await screen.findByText("Busiest hours (IST)");

    expect(HOURS.reduce((sum, n) => sum + n, 0)).toBe(51);
    expect(container.textContent).not.toContain("calls in this period have a start time");
  });
});
