import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import QualityPage from "@/app/c/[slug]/quality/page";
import { renderMeasurement, type QaReport } from "@/lib/api/quality";

import { browserOffline, problem, renderClientPage } from "./harness";

/**
 * The monthly quality report, in-app (SURFACES §2, D-15) — the screen a client checks our
 * central claim on. Ranked by what a wrong render costs:
 *
 * 1. **A clean run invented for an account that never had one.** No stored report means
 *    no run, and "no defects across 0 scenarios" is the most reassuring lie the product
 *    could tell. The empty state must say NOT RUN, and the number zero must not appear as
 *    a defect count.
 * 2. **Figures under a failed request.** A refusal, never a zero and never the empty
 *    state: a client told their agent has never been tested because a token expired has
 *    been misinformed about the exact thing this screen exists to prove (§52).
 * 3. **A percentage the numbers do not support.** `basis: "too_few"` means the count is
 *    honest and the percentage is not, and the screen prints what the API's own
 *    `Measurement.rendered` would print — the emailed report and this screen must not
 *    differ by a point.
 * 4. **The defect count buried under a pass rate.** The pass rate measures our offline
 *    stand-in extractor; the defect count measures the promise. The headline is the
 *    second one.
 */

const ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["agents:read", "calls:read"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

function report(over: Partial<QaReport> = {}): QaReport {
  return {
    version: 1,
    client: "acme",
    vertical: "clinic",
    as_of: "2026-07-31",
    model: "offline-heuristic",
    scenarios_total: 58,
    defects: 0,
    red_team: 11,
    everything_captured: { passed: 44, total: 58, basis: "measured" },
    field_left_blank: { passed: 14, total: 58, basis: "measured" },
    trend: "no_baseline",
    scenario_classes: [
      {
        scenario: 1,
        label: "A normal call, start to finish",
        meaning: "the caller's details reach your leads list correctly",
        count: 13,
      },
    ],
    known_limits: [{ label: "Budget (lakhs)", scenarios: 4 }],
    ...over,
  };
}

describe("the client's quality report", () => {
  it("says NOT RUN — never a clean run — when no report is stored", async () => {
    const { container } = await renderClientPage(<QualityPage />, {
      "/v1/me": ME,
      "/v1/quality/reports": [],
    });
    await screen.findByText("No quality report yet");
    expect(container.textContent).not.toContain("No defects found");
    expect(container.textContent).not.toContain("0 scenarios");
  });

  it("refuses rather than reporting nothing when the read fails", async () => {
    const { container } = await renderClientPage(<QualityPage />, {
      "/v1/me": ME,
      "/v1/quality/reports": problem(503, { title: "Service unavailable" }),
    });
    await screen.findByText("Your quality reports could not be loaded");
    // The distinction the whole branch exists for: a failure is not an absence.
    expect(container.textContent).not.toContain("No quality report yet");
    expect(container.textContent).not.toContain("No defects found");
  });

  it("leads with the defect count and prints the report's own figures", async () => {
    const { container } = await renderClientPage(<QualityPage />, {
      "/v1/me": ME,
      "/v1/quality/reports": [report()],
    });
    await screen.findByText("No defects found across 58 scenarios");
    expect(container.textContent).toContain(renderMeasurement(report().everything_captured));
    expect(container.textContent).toContain("Budget (lakhs)");
    expect(container.textContent).toContain("11 of those scenarios are adversarial");
  });

  it("names the defects when there are any, instead of softening them", async () => {
    const { container } = await renderClientPage(<QualityPage />, {
      "/v1/me": ME,
      "/v1/quality/reports": [report({ defects: 3 })],
    });
    await screen.findByText("3 of 58 scenarios found a defect");
    expect(container.textContent).toContain("reissued");
  });

  it("prints the count and NOT a percentage when the basis does not earn one", async () => {
    const scarce = report({
      scenarios_total: 3,
      everything_captured: { passed: 2, total: 3, basis: "too_few" },
      field_left_blank: { passed: 1, total: 3, basis: "too_few" },
    });
    const { container } = await renderClientPage(<QualityPage />, {
      "/v1/me": ME,
      "/v1/quality/reports": [scarce],
    });
    await screen.findByText(/Too few scenarios/);
    expect(container.textContent).toContain("2 of 3");
    expect(container.textContent).not.toContain("67%");
    expect(container.textContent).toContain("Too few scenarios");
  });

  it("claims no trend from a single month", async () => {
    await renderClientPage(<QualityPage />, {
      "/v1/me": ME,
      "/v1/quality/reports": [report()],
    });
    await screen.findByText(/No previous report to compare against/);
  });

  it("offers earlier months and shows the one that was picked", async () => {
    await renderClientPage(<QualityPage />, {
      "/v1/me": ME,
      "/v1/quality/reports": [report(), report({ as_of: "2026-06-30", defects: 2 })],
    });
    // Newest first by default — the server's order, kept.
    await screen.findByText("No defects found across 58 scenarios");
    expect(screen.getByRole("group", { name: "Choose a month" })).toBeTruthy();
  });

  /**
   * THE MONTH LABEL, IN A BROWSER THAT IS NOT IN INDIA.
   *
   * `monthLabel` built a `Date` from the API's `YYYY-MM-DD` and formatted it in the
   * browser's zone. `new Date("2026-09-01")` is midnight UTC, which is 31 August in every
   * zone west of it — so an operator or a client on a laptop still set to a US timezone
   * read "August 2026" over September's report, on the one document this product sends a
   * client every month to prove the agent was tested.
   *
   * The timezone is moved for real rather than mocked: Node re-reads `process.env.TZ` on
   * assignment, so this is the same code path a browser in New York takes. `as_of` is the
   * FIRST of a month because that is the value that separates the two implementations —
   * a month-end date happens to survive the bug, which is why the suite did not catch it.
   */
  it("names the month the report is for, in a browser outside India", async () => {
    const original = process.env.TZ;
    process.env.TZ = "America/New_York";
    try {
      // TWO reports, because the month picker only renders when there is a choice —
      // and the picker is where `monthLabel` is read.
      const { container } = await renderClientPage(<QualityPage />, {
        "/v1/me": ME,
        "/v1/quality/reports": [
          report({ as_of: "2026-09-01" }),
          report({ as_of: "2026-08-01", defects: 2 }),
        ],
      });
      await screen.findByText("No defects found across 58 scenarios");
      expect(screen.getByRole("button", { name: "September 2026" })).toBeTruthy();
      // The report's own line names the same month, in words rather than as a wire
      // format — and the same UTC-anchored day, not the one the browser's zone lands on.
      expect(container.textContent).toContain("For the month ending 1 September 2026");
      expect(container.textContent).not.toContain("2026-09-01");
    } finally {
      if (original === undefined) delete process.env.TZ;
      else process.env.TZ = original;
    }
  });

  /**
   * THE PAUSED QUERY — the state that is neither loading nor failed.
   *
   * TanStack does not start a fetch it believes cannot succeed: with the default
   * `networkMode: "online"` it parks the query (`fetchStatus: "paused"`), so
   * `isLoading` — which is `isPending && isFetching` — is FALSE, `error` is null and
   * `data` is undefined. A two-armed ladder therefore walks past both arms into its data
   * branch with nothing in it. `browserOffline()` flips the library's own switch rather
   * than mocking anything, so this is the branch a dropped connection actually produces.
   */
  it("does not claim an untested agent over a read the browser never made", async () => {
    browserOffline();
    const { container } = await renderClientPage(<QualityPage />, {
      "/v1/me": ME,
      "/v1/quality/reports": [report()],
    });

    // The strongest claim on this screen is that we test the agent. Its ABSENCE is the
    // second strongest, and it must never be made from a request that was never sent.
    expect(container.textContent).not.toContain("No quality report yet");
    expect(container.textContent).toContain("Your quality reports could not be loaded");
  });

});
