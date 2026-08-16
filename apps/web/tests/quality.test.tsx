import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import QualityPage from "@/app/c/[slug]/quality/page";
import { renderMeasurement, type QaReport } from "@/lib/api/quality";

import { problem, renderClientPage } from "./harness";

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
});
