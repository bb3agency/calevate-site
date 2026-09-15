import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FxRatePanel, fxHeadline } from "@/app/admin/ops/FxRatePanel";
import { fxSourceCopy } from "@/app/admin/ops/opsLanguage";
import { OPS_FX_RATE_PATH, type FxRate } from "@/lib/api/opsFxRate";

import { problem, stubApi, type Routes } from "./harness";

/**
 * The exchange-rate panel — the screen that answers "is the platform billing off a
 * published rate right now, or off the typed fallback?".
 *
 * What each failure would cost, worst first:
 *
 * 1. **A degraded state that reads as a healthy one.** A stale feed, a feed that has never
 *    run, and a read this console could not perform are THREE different facts with three
 *    different next steps, and the one thing none of them may look like is a working rate.
 * 2. **The browser inventing a figure.** Every rate here is the server's decimal string,
 *    printed verbatim. A rate through `Number()` is a binary double, and this is the
 *    multiplier under every client's invoice (hard rule 7).
 * 3. **The browser inventing an AGE.** `age_label` is the server's phrase. A missing one
 *    must render as nothing at all — never as "recently", and never as a `0` that reads
 *    as "just now".
 */

const LIVE: FxRate = {
  base_currency: "USD",
  quote_currency: "INR",
  effective_rate: "88.427500",
  state: "live",
  using_fallback: false,
  fallback_rate: "88.00",
  published_rate: "88.427500",
  published_as_of: "2026-08-27",
  published_source: "fbil:refrates",
  observed_at: "2026-08-27T04:05:00Z",
  age_label: "3 minutes ago",
  max_age_days: 5,
  history: [],
};

const STALE: FxRate = {
  ...LIVE,
  state: "stale",
  using_fallback: true,
  effective_rate: "88.00",
  published_as_of: "2026-08-01",
  age_label: "26 days ago",
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
  state: "never_pulled",
  using_fallback: true,
  effective_rate: "88.00",
  published_rate: null,
  published_as_of: null,
  published_source: null,
  observed_at: null,
  age_label: null,
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
  });

  it("says the fallback is in force when the published rate has aged out", async () => {
    renderPanel({ [OPS_FX_RATE_PATH]: STALE });
    await waitFor(() =>
      expect(screen.queryAllByText(/too old to use/i).length).toBeGreaterThan(
        0,
      ),
    );
    expect(
      screen.queryAllByText(/fallback you set, not a published rate/i).length,
    ).toBeGreaterThan(0);
    // The headline names the ceiling the SERVER sent, so the screen cannot disagree with
    // the constant the metering path applies.
    expect(screen.queryAllByText(/5-day limit/).length).toBeGreaterThan(0);
  });

  it("tells 'nothing pulled yet' apart from 'we could not read it'", async () => {
    const { unmount } = renderPanel({ [OPS_FX_RATE_PATH]: NEVER });
    await waitFor(() =>
      expect(
        screen.queryAllByText(/No rate has been pulled yet/i).length,
      ).toBeGreaterThan(0),
    );
    expect(screen.queryAllByText("none yet").length).toBeGreaterThan(0);
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
    expect(screen.queryAllByText(/No rate has been pulled yet/i)).toHaveLength(
      0,
    );
  });

  it("renders no age at all rather than inventing one", () => {
    // The pure headline, so the assertion is about the sentence and not about a render.
    const noAge = fxHeadline({ ...LIVE, age_label: null });
    expect(noAge.body).not.toMatch(/fetched/);
    expect(noAge.body).not.toMatch(/recently|just now|\b0\b/);
    expect(fxHeadline(LIVE).body).toMatch(/fetched 3 minutes ago/);
  });

  it("never renders a rate the server did not send", async () => {
    renderPanel({ [OPS_FX_RATE_PATH]: NEVER });
    await waitFor(() =>
      expect(
        screen.queryAllByText(/No rate has been pulled yet/i).length,
      ).toBeGreaterThan(0),
    );
    // The fallback IS a real number and is shown; the published one is absent and stays
    // absent — a panel that filled it in with the fallback would report a pull that never
    // happened.
    expect(screen.queryAllByText("88.00").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("88.427500")).toHaveLength(0);
  });

  it("names WHICH source each pull came from, in words and verbatim", async () => {
    // The pull walks a ladder, so "Recent pulls" is a list of DIFFERENT sources, not one
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
      "The fallback you set",
    );
  });
});
