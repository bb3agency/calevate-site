import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  FxRatePanel,
  fxHeadline,
  fxReason,
} from "@/app/admin/ops/FxRatePanel";
import { fxSourceCopy } from "@/app/admin/ops/opsLanguage";
import { OPS_FX_RATE_PATH, type FxRate } from "@/lib/api/opsFxRate";

import { problem, stubApi, type Routes } from "./harness";

/**
 * The exchange-rate panel — the screen that answers "what rate is the platform billing
 * off right now, why that one, and is the pull still running?".
 *
 * What each failure would cost, worst first:
 *
 * 1. **A degraded state that reads as a healthy one.** A stale publication, a manual
 *    override, a feed that has never run, and a read this console could not perform are
 *    different facts with different next steps, and none of them may look like a fresh
 *    published rate.
 * 2. **The browser inventing a figure.** Every rate here is the server's decimal string,
 *    printed verbatim. A rate through `Number()` is a binary double, and this is the
 *    multiplier under every client's invoice (hard rule 7).
 * 3. **The browser inventing an AGE.** `last_checked_label` is the server's phrase. A
 *    missing check must render as "not recorded yet" — never as "recently".
 */

const LIVE: FxRate = {
  base_currency: "USD",
  quote_currency: "INR",
  effective_rate: "88.427500",
  basis: "published",
  state: "live",
  manual_rate: "88.00",
  manual_override: false,
  published_rate: "88.427500",
  published_as_of: "2026-08-27",
  published_source: "fbil:refrates",
  observed_at: "2026-08-27T04:05:00Z",
  last_checked_at: "2026-08-27T09:30:00Z",
  last_checked_label: "3 minutes ago",
  max_age_days: 5,
  history: [],
};

/** Every source is behind: the LAST published rate stays in force, labelled stale. */
const STALE: FxRate = {
  ...LIVE,
  basis: "stale_published",
  state: "stale",
  published_as_of: "2026-08-01",
};

const OVERRIDE: FxRate = {
  ...LIVE,
  basis: "manual_override",
  manual_override: true,
  effective_rate: "88.00",
};

/** Rung 1 is behind, a lower published rung is serving — the state D-589/D-609 exist for. */
const DEGRADED: FxRate = {
  ...LIVE,
  effective_rate: "95.390000",
  published_rate: "95.390000",
  published_as_of: "2026-09-11",
  published_source: "frankfurter:default",
};

const NEVER: FxRate = {
  ...LIVE,
  basis: "manual_no_quote",
  state: "never_pulled",
  effective_rate: "88.00",
  published_rate: null,
  published_as_of: null,
  published_source: null,
  observed_at: null,
  last_checked_at: null,
  last_checked_label: null,
};

function renderPanel(routes: Routes) {
  const calls = stubApi(routes);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={client}>
      <FxRatePanel />
    </QueryClientProvider>,
  );
  return Object.assign(result, { calls, client });
}

describe("the exchange rate panel", () => {
  it("prints the server's rate string verbatim and never a computed one", async () => {
    renderPanel({ [OPS_FX_RATE_PATH]: LIVE });
    await waitFor(() =>
      expect(screen.queryAllByText("88.427500").length).toBeGreaterThan(0),
    );
    // Not "88.43", not "88.4275", not "₹88.43" — the digits the server sent. A browser
    // that reformatted this would be a second place the multiplier can be wrong.
    expect(screen.queryAllByText("88.43")).toHaveLength(0);
    expect(
      screen.queryAllByText(/converting at the published rate/i).length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryAllByText(/Published rate for 2026-08-27, in force now/)
        .length,
    ).toBeGreaterThan(0);
    // The manual rate is shown, and said to be unused.
    expect(screen.queryAllByText(/\(not in use\)/).length).toBeGreaterThan(0);
  });

  it("shows when the pull last checked, apart from the publication date", async () => {
    // The founder's report: "fetched 5 hours ago" on a healthy poller, because a daily
    // publication is stored once. The check time and the publication date are two facts.
    renderPanel({ [OPS_FX_RATE_PATH]: LIVE });
    await waitFor(() =>
      expect(screen.queryAllByText("Last checked").length).toBeGreaterThan(0),
    );
    expect(screen.queryAllByText(/\(3 minutes ago\)/).length).toBeGreaterThan(0);
    expect(screen.queryAllByText("Published for").length).toBeGreaterThan(0);
  });

  it("says the last published rate is still in force, and stale, when every source is behind", async () => {
    renderPanel({ [OPS_FX_RATE_PATH]: STALE });
    await waitFor(() =>
      expect(screen.queryAllByText(/out of date/i).length).toBeGreaterThan(0),
    );
    expect(
      screen.queryAllByText(/Last published rate, for 2026-08-01\. Stale/)
        .length,
    ).toBeGreaterThan(0);
    // The ceiling the SERVER sent, so the screen cannot disagree with the metering path.
    expect(screen.queryAllByText(/more than 5 days/).length).toBeGreaterThan(0);
    // The published rate is still the one in force, not the manual one.
    expect(screen.queryAllByText(/\(not in use\)/).length).toBeGreaterThan(0);
  });

  it("names the manual override when it is on", async () => {
    renderPanel({ [OPS_FX_RATE_PATH]: OVERRIDE });
    await waitFor(() =>
      expect(
        screen.queryAllByText(/converting at your manual rate/i).length,
      ).toBeGreaterThan(0),
    );
    expect(fxReason(OVERRIDE)).toMatch(/override is on/);
    expect(screen.queryAllByText(/\(in use\)/).length).toBeGreaterThan(0);
  });

  it("tells 'nothing published yet' apart from 'we could not read it'", async () => {
    const { unmount } = renderPanel({ [OPS_FX_RATE_PATH]: NEVER });
    await waitFor(() =>
      expect(
        screen.queryAllByText(/No rate has been published yet/i).length,
      ).toBeGreaterThan(0),
    );
    expect(screen.queryAllByText("none yet").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("not recorded yet").length).toBeGreaterThan(0);
    unmount();

    renderPanel({
      [OPS_FX_RATE_PATH]: problem(503, { title: "Dependency unavailable" }),
    });
    await waitFor(() =>
      expect(
        screen.queryAllByText(/could not read the exchange rate/i).length,
      ).toBeGreaterThan(0),
    );
    // The two must not be confusable: a failed read must NOT claim the pull never ran.
    expect(
      screen.queryAllByText(/No rate has been published yet/i),
    ).toHaveLength(0);
  });

  it("chooses every sentence from the server's basis", () => {
    expect(fxHeadline(LIVE).tone).toBe("ok");
    for (const rate of [STALE, OVERRIDE, NEVER]) {
      expect(fxHeadline(rate).tone).toBe("warn");
    }
    expect(fxHeadline(LIVE).body).not.toMatch(/recently|just now/);
  });

  it("never renders a rate the server did not send", async () => {
    renderPanel({ [OPS_FX_RATE_PATH]: NEVER });
    await waitFor(() =>
      expect(
        screen.queryAllByText(/No rate has been published yet/i).length,
      ).toBeGreaterThan(0),
    );
    // The manual rate IS a real number and is shown; the published one is absent and
    // stays absent — a panel that filled it in would report a pull that never happened.
    expect(screen.queryAllByText("88.00").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("88.427500")).toHaveLength(0);
  });

  it("names WHICH source each pull came from, in words and verbatim", async () => {
    // The pull walks a ladder, so "Recent publications" is a list of DIFFERENT sources, not one
    // source over time. A row without its source cannot answer the only question this
    // list is for: which rung priced the minutes written while it was in force.
    renderPanel({
      [OPS_FX_RATE_PATH]: {
        ...DEGRADED,
        history: [
          {
            rate: "95.390000",
            as_of: "2026-09-11",
            source: "frankfurter:default",
            source_url: "https://api.frankfurter.dev/v2/rate/USD/INR",
            observed_at: "2026-09-11T04:05:00Z",
          },
          {
            rate: "94.491400",
            as_of: "2026-09-04",
            source: "fbil:refrates",
            source_url: "https://www.fbil.org.in/wasdm/refrates/fetchfiltered?x=1",
            observed_at: "2026-09-11T04:05:00Z",
          },
        ],
      },
    });
    await waitFor(() =>
      expect(screen.queryAllByText("94.491400").length).toBeGreaterThan(0),
    );
    // The operator's words...
    expect(screen.queryAllByText("FBIL, direct").length).toBeGreaterThan(0);
    expect(
      screen.queryAllByText("Frankfurter's own rate").length,
    ).toBeGreaterThan(0);
    // ...AND the string the ledger row carries, which is what they reconcile against.
    expect(screen.queryAllByText("fbil:refrates").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("frankfurter:default").length).toBeGreaterThan(
      0,
    );
  });

  it("prints an unrecognised source raw rather than inventing a name for it", () => {
    // A rung added to the ladder after this bundle was built. The fail direction is
    // SILENCE, not a wrong sentence: the gloss collapses to the string itself, which is
    // exactly what the panel showed before the copy table existed.
    const unknown = fxSourceCopy("rbi:reference");
    expect(unknown.label).toBe("rbi:reference");
    expect(unknown.help).toBe("");
    // And a source this build DOES know is never printed as its own key.
    expect(fxSourceCopy("fbil:refrates").label).toBe("FBIL, direct");
    expect(fxSourceCopy("configured:usd_inr_rate").label).toBe(
      "Your manual rate",
    );
  });
});
