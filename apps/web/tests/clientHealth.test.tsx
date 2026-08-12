import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ClientHealthPage from "@/app/admin/health/page";
import { CLIENT_HEALTH_PATH, type ClientHealth } from "@/lib/api/clientHealth";

import { problem, renderAdminPage } from "./harness";

/**
 * The client health board — the screen that decides which client gets looked at.
 *
 * Its whole value is that an operator can trust it enough to stop opening N dashboards,
 * so the failures worth pinning are the ones that make it UNTRUSTWORTHY rather than
 * merely ugly. Four of them, and three are failures of the screen SAYING SOMETHING IT
 * CANNOT KNOW:
 *
 * 1. **A trend must never be rendered on a basis that did not earn it.** `too_new` and
 *    `no_baseline` are "we are not entitled to say", not "0% change". A console that
 *    rendered them like a measured comparison would send an operator to accuse a
 *    four-day-old account of churning — the exact lie `after_hours_basis` exists to
 *    prevent, applied here to an accusation rather than a tile.
 * 2. **A failed read must not read as a healthy estate.** "Every client looks healthy" is
 *    a claim about the world; an expired token is not evidence for it.
 * 3. **Empty is the GOOD state and must say so.** A board rendering "no data" at its own
 *    success reads as a broken load.
 * 4. **A signal this build cannot name must keep its account on the board.** The set grows
 *    server-side whenever a gate does, and a row silently dropped for an unfamiliar rule
 *    is an account nobody looks at — worst, again, for the client who never complains.
 *
 * Hard rule 6 is asserted too: the payload carries accounts and machine rule names, and
 * this screen must not fetch anything identifying back to fill the gaps.
 */

function signal(over: Partial<ClientHealth["signals"][number]> = {}) {
  return {
    rule: "deliveries_failing",
    severity: "stop" as const,
    causes: [],
    count: 3,
    ...over,
  };
}

function row(over: Partial<ClientHealth> = {}): ClientHealth {
  return {
    tenant_id: "0192f0aa-7777-7000-8000-000000000001",
    name: "Sri Traders",
    slug: "sri-traders",
    plan_tier: "managed",
    status: "active",
    severity: "stop",
    signals: [signal()],
    calls_7d: 2,
    calls_prev_7d: 40,
    calls_basis: "measured",
    last_call_at: "2026-08-10T06:30:00Z",
    spend_used_inr: "900.5000",
    spend_cap_inr: "1000.0000",
    ...over,
  } as ClientHealth;
}

describe("the client health board", () => {
  it("refuses to render a trend for an account too new to have a previous week", async () => {
    const { container } = renderAdminPage(<ClientHealthPage />, {
      [CLIENT_HEALTH_PATH]: [row({ calls_basis: "too_new", calls_7d: 0, calls_prev_7d: 0 })],
    });

    await screen.findByText("Sri Traders");
    expect(container.textContent).toContain("Too new to compare");
    // The three ways a guess could get onto the screen, each excluded by name.
    expect(container.textContent).not.toContain("down ");
    expect(container.textContent).not.toContain("up ");
    expect(container.textContent).not.toContain("0 vs 0");
  });

  it("tells a thin baseline apart from a new account, because the next step differs", async () => {
    // A client doing four calls a week HAS traded. Telling an operator to wait for
    // history that has already arrived is a different mistake from calling it a collapse,
    // and the copy has to distinguish them.
    const { container } = renderAdminPage(<ClientHealthPage />, {
      [CLIENT_HEALTH_PATH]: [row({ calls_basis: "no_baseline", calls_7d: 1, calls_prev_7d: 3 })],
    });

    await screen.findByText("Sri Traders");
    expect(container.textContent).toContain("Too few calls last week");
    expect(container.textContent).not.toContain("Too new to compare");
    expect(container.textContent).not.toContain("down ");
  });

  it("renders the measured drop when, and only when, the server says it is measured", async () => {
    const { container } = renderAdminPage(<ClientHealthPage />, {
      [CLIENT_HEALTH_PATH]: [
        row({
          calls_basis: "measured",
          calls_7d: 2,
          calls_prev_7d: 40,
          signals: [signal({ rule: "calls_stopped", severity: "warn", count: 2, causes: [] })],
        }),
      ],
    });

    await screen.findByText("Sri Traders");
    expect(container.textContent).toContain("down 95%");
    expect(container.textContent).toContain("Calls stopped");
    expect(container.textContent).not.toContain("Too new to compare");
  });

  it("keeps an account flagged on a signal this build cannot name, and offers a real destination", async () => {
    const { container } = renderAdminPage(<ClientHealthPage />, {
      [CLIENT_HEALTH_PATH]: [
        row({ signals: [signal({ rule: "a_signal_added_after_this_build", count: null })] }),
      ],
    });

    await screen.findByText("Sri Traders");
    expect(container.textContent).toContain("a_signal_added_after_this_build");
    expect(container.textContent).toContain("This console does not know this signal");
    expect(screen.getByRole("link", { name: "Open the account" })).toBeDefined();
    expect(container.textContent).not.toContain("Every client looks healthy");
  });

  it("sends each cause of a blocked account to the desk that clears it", async () => {
    // The two R-11 gates are the hold queue's subject and `HOLD_RULES` owns both their
    // wording and their screens; the DLT registration is the account's. A board that sent
    // every cause to one place would bury the work, and one that re-worded the gates would
    // be a second vocabulary for a condition the client is already being refused on.
    const { container } = renderAdminPage(<ClientHealthPage />, {
      [CLIENT_HEALTH_PATH]: [
        row({
          signals: [
            signal({
              rule: "outbound_blocked",
              severity: "stop",
              count: null,
              causes: ["kyc_missing", "pe_registration_missing"],
            }),
          ],
        }),
      ],
    });

    await screen.findByText("Sri Traders");
    expect(container.textContent).toContain("Identity not filed");
    expect(container.textContent).toContain("No DLT Principal Entity registration");
    // The hold's remedy is the hold queue's OWN destination and wording (`HOLD_RULES`),
    // not a second copy invented here; the DLT registration lives on the account.
    expect(screen.getByRole("link", { name: "Identity (KYC)" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Open the account" })).toBeDefined();
  });

  it("refuses to call a failed read a healthy estate", async () => {
    const { container } = renderAdminPage(<ClientHealthPage />, {
      // A real refusal, the way the API issues one. A malformed 200 would exercise a
      // crash rather than the error branch.
      [CLIENT_HEALTH_PATH]: problem(401, {
        title: "Not authenticated",
        detail: "The admin token has expired.",
        status: 401,
      }),
    });

    await screen.findByText(/could not be read/);
    expect(container.textContent).toContain("we cannot say whether any client is in trouble");
    // The one sentence that must never appear on a failed load.
    expect(container.textContent).not.toContain("Every client looks healthy");
  });

  it("says every client is healthy, in words, when the board is empty", async () => {
    const { container } = renderAdminPage(<ClientHealthPage />, { [CLIENT_HEALTH_PATH]: [] });

    await screen.findByText("Every client looks healthy");
    expect(container.textContent).not.toContain("could not be read");
    // No headline count on an empty board — "0 accounts need attention" beside "every
    // client looks healthy" is the same fact twice.
    expect(container.textContent).not.toContain("need attention");
  });

  it("keeps the server's order and counts what is broken now", async () => {
    // The server ranks most-broken-first (`_triage_order`); the screen must not re-sort,
    // and the headline must be derived from the rows rather than assumed from the order.
    const { container } = renderAdminPage(<ClientHealthPage />, {
      [CLIENT_HEALTH_PATH]: [
        row({ tenant_id: "t-a", name: "Broken Co", severity: "stop" }),
        row({
          tenant_id: "t-b",
          name: "Wobbling Co",
          severity: "warn",
          signals: [signal({ rule: "knowledge_waiting", severity: "warn", count: 2 })],
        }),
      ],
    });

    await screen.findByText("Broken Co");
    expect(container.textContent).toContain("2 accounts need attention");
    expect(container.textContent).toContain("1 broken now");
    const text = container.textContent ?? "";
    expect(text.indexOf("Broken Co")).toBeLessThan(text.indexOf("Wobbling Co"));
  });

  it("reads only the board, and renders no phone number", async () => {
    // Hard rule 6 is a property of the payload — `admin/health.py` sends accounts and rule
    // names and drops the blockers' `reason` prose, which interpolates an operator's free
    // text. This screen must not fetch any of it back to fill the gap.
    const { container, calls } = renderAdminPage(<ClientHealthPage />, {
      [CLIENT_HEALTH_PATH]: [
        row({
          signals: [
            signal({
              rule: "outbound_blocked",
              causes: ["first_campaign_review_rejected"],
              count: null,
            }),
          ],
        }),
      ],
    });

    await screen.findByText("Sri Traders");
    // One request, to the board. A second one to a tenant's own screens would be this page
    // quietly widening what an ops list exposes.
    expect(calls.map((c) => c.path)).toEqual([CLIENT_HEALTH_PATH]);
    expect(container.textContent).toContain("First campaign refused");
    expect(container.textContent).not.toMatch(/\+?\d{10}/);
  });

  it("prints money as the string the server sent, never through Number()", async () => {
    // `UsagePanelOut` states the rule: a JSON float cannot hold a rupee exactly, and
    // `Number()` on INR is how ₹10,159.00 becomes ₹10,158.999999999998. The board carries
    // spend, so the board is bound by it — the percentage it shows is the SERVER's
    // integer, computed from Decimals, never divided in the browser.
    const { container } = renderAdminPage(<ClientHealthPage />, {
      [CLIENT_HEALTH_PATH]: [
        row({
          spend_used_inr: "10159.0000",
          spend_cap_inr: "10160.0000",
          signals: [signal({ rule: "spend_cap_near", severity: "warn", count: 99 })],
        }),
      ],
    });

    await screen.findByText("Sri Traders");
    expect(container.textContent).toContain("99% of the ceiling used");
    expect(container.textContent).not.toContain("10158.99");
  });
});
