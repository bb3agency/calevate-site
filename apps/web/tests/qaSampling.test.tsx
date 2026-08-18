import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it } from "vitest";

import QaSampleReviewPage from "@/app/admin/qa-sampling/[sampleId]/page";
import QaSamplingPage from "@/app/admin/qa-sampling/page";
import type { QaSample } from "@/lib/api/qaSamples";

import { browserOffline, problem, stubApi } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * The QA sampling queue and the review screen (SURFACES §1) — an internal control, so the
 * failures that matter are the ones that would let it look like a control while not being
 * one. Ranked by cost:
 *
 * 1. **A redacted transcript rendered as if it were the whole call, or a raw one
 *    rendered at all.** Hard rule 5: what a reviewer sees is `text_redacted`, and this
 *    screen must SAY so — a reviewer who thinks they are reading the full text will
 *    conclude the agent misheard a number that was in fact masked. There is no raw
 *    toggle here and this suite asserts its absence.
 * 2. **An empty queue rendered under a failed read.** "Everything has been reviewed" and
 *    "we could not read the queue" send a reviewer in opposite directions and only one is
 *    true (§52).
 * 3. **The draw's evidence missing from the screen.** Population, rank and target are
 *    what make "we sample 5%" checkable. A queue that shows only calls is a list somebody
 *    could have chosen by taste.
 * 4. **A verdict that looks recorded but was refused.** A second reviewer gets a 409, and
 *    the screen must show that sentence rather than falling quiet.
 */

const SAMPLE: QaSample = {
  id: "s1",
  tenant_id: "t1",
  tenant_name: "Sri Traders",
  tenant_slug: "sri-traders",
  call_id: "c1",
  agent_name: "Reception",
  week_start: "2026-08-03",
  population: 40,
  target: 2,
  selection_rank: 1,
  selection_seed: "t1:2026-08-03",
  selected_at: "2026-08-10T04:00:00Z",
  started_at: "2026-08-05T06:30:00Z",
  duration_s: 154,
  direction: "inbound",
  outcome_tag: "resolved",
  sentiment: "positive",
  disclosure_played: true,
  verdict: null,
  reviewed_at: null,
};

const CALL = {
  id: "c1",
  agent_id: "a1",
  agent_name: "Reception",
  direction: "inbound",
  status: "completed",
  caller_masked: "••••••21",
  started_at: "2026-08-05T06:30:00Z",
  duration_s: 154,
  outcome_tag: "resolved",
  sentiment: "positive",
  summary: "Caller booked a Tuesday slot.",
  lead_id: null,
  has_recording: false,
  disclosure_played: true,
  transcript: [
    { idx: 0, speaker: "agent", text: "Namaskaram, Sri Clinic.", lang: "te-IN", start_ms: 0, redacted: true },
    {
      idx: 1,
      speaker: "caller",
      text: "Call me on [phone ••10].",
      lang: "te-IN",
      start_ms: 2400,
      redacted: true,
    },
  ],
  extraction: {},
  extraction_valid: true,
};

describe("the QA sampling queue", () => {
  it("shows the draw's own evidence, not just the calls", async () => {
    const { container } = await renderAdminRoute(<QaSamplingPage />, {
      "/v1/admin/qa-samples?pending=true": [SAMPLE],
    });
    await screen.findByText("Sri Traders");
    // The frame and the rank: what makes 5% a claim somebody can check.
    expect(container.textContent).toContain("40 calls that week");
    expect(container.textContent).toContain("#1 of 2");
    expect(container.textContent).toContain("5% sampled");
    expect(container.textContent).toContain("2026-08-03");
  });

  it("refuses rather than claiming everything has been reviewed", async () => {
    const { container } = await renderAdminRoute(<QaSamplingPage />, {
      "/v1/admin/qa-samples?pending=true": problem(401, { title: "Unauthorized" }),
    });
    await screen.findByText("The sampling queue could not be read");
    expect(container.textContent).not.toContain("Every sampled call has been reviewed");
  });

  it("says an empty queue is the GOOD state", async () => {
    const { container } = await renderAdminRoute(<QaSamplingPage />, {
      "/v1/admin/qa-samples?pending=true": [],
    });
    await screen.findByText("Every sampled call has been reviewed");
    expect(container.textContent).not.toContain("could not be read");
  });

  it("carries no phone number and no transcript on the list", async () => {
    const { container } = await renderAdminRoute(<QaSamplingPage />, {
      "/v1/admin/qa-samples?pending=true": [SAMPLE],
    });
    await screen.findByText("Sri Traders");
    expect(container.textContent).not.toContain("+91");
    expect(container.textContent).not.toContain("Namaskaram");
  });
});

describe("reviewing a sampled call", () => {
  const routes = (over: Record<string, unknown> = {}) => ({
    "/v1/admin/qa-samples/s1": { sample: SAMPLE, call: CALL },
    ...over,
  });

  it("renders the redacted transcript and says that is what it is", async () => {
    const { container } = await renderAdminRoute(
      <QaSampleReviewPage params={routeParams({ sampleId: "s1" })} />,
      routes(),
    );
    await screen.findByText("Namaskaram, Sri Clinic.");
    expect(container.textContent).toContain("[phone ••10]");
    expect(container.textContent).toContain("are hidden in this transcript");
    // The reviewer is told the read is on the record BEFORE they read it.
    expect(container.textContent).toContain("recorded in the audit log");
  });

  it("offers no way to see the unredacted text", async () => {
    const { container } = await renderAdminRoute(
      <QaSampleReviewPage params={routeParams({ sampleId: "s1" })} />,
      routes(),
    );
    await screen.findByText("Namaskaram, Sri Clinic.");
    // Hard rule 5 has ONE raw path in this product and it is not on this screen. Asserted
    // rather than assumed, because a convenience toggle here is the likeliest way a
    // second one gets built.
    // Asserted over the CONTROLS, not the prose: the notice on this screen says the word
    // "unredacted" in order to promise there is no such view, and a text search would
    // match the promise itself.
    const controls = screen.queryAllByRole("button").map((node) => node.textContent ?? "");
    for (const control of controls) {
      expect(control).not.toMatch(/raw|unredacted|full text/i);
    }
    expect(container.querySelector('[href*="transcript/raw"]')).toBeNull();
  });

  it("shows why THIS call was drawn, including the seed", async () => {
    const { container } = await renderAdminRoute(
      <QaSampleReviewPage params={routeParams({ sampleId: "s1" })} />,
      routes(),
    );
    await screen.findByText(/Drawn #1 of 2/);
    expect(container.textContent).toContain("t1:2026-08-03");
  });

  it("records a verdict and then stops offering the buttons", async () => {
    const { container, calls } = await renderAdminRoute(
      <QaSampleReviewPage params={routeParams({ sampleId: "s1" })} />,
      routes({
        "POST /v1/admin/qa-samples/s1/review": { ...SAMPLE, verdict: "clean", reviewed_at: "x" },
        "/v1/admin/qa-samples?pending=true": [],
      }),
    );
    await screen.findByText("Clean");
    fireEvent.click(screen.getByRole("button", { name: /Clean/ }));

    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const posted = calls.find((call) => call.method === "POST");
    expect(posted?.path).toBe("/v1/admin/qa-samples/s1/review");
    expect(posted?.body).toContain("clean");
    // And the verdict, once recorded, is not offered again from this screen.
    await waitFor(() => expect(container.textContent).toContain("A verdict is written once"));
  });

  it("shows the refusal when somebody else reviewed it first", async () => {
    const { container } = await renderAdminRoute(
      <QaSampleReviewPage params={routeParams({ sampleId: "s1" })} />,
      routes({
        "POST /v1/admin/qa-samples/s1/review": problem(409, {
          title: "Conflicting request",
          detail: "This call was already reviewed as 'defect'.",
        }),
      }),
    );
    await screen.findByText("Clean");
    fireEvent.click(screen.getByRole("button", { name: /Clean/ }));
    await screen.findByText(/already reviewed/);
    // The buttons stay: the reviewer needs to see what happened, not a screen that went
    // quiet under their click.
    expect(container.textContent).toContain("Concern");
  });

  it("refuses instead of rendering an empty review when the call cannot be read", async () => {
    const { container } = await renderAdminRoute(
      <QaSampleReviewPage params={routeParams({ sampleId: "s1" })} />,
      { "/v1/admin/qa-samples/s1": problem(503, { title: "Service unavailable" }) },
    );
    await screen.findByText(/could not be read, so it cannot be reviewed/);
    // No verdict buttons under a call nobody could read: a verdict recorded against an
    // unread call is worse than no review at all.
    expect(screen.queryByRole("button", { name: /Defect/ })).toBeNull();
    expect(container.textContent).not.toContain("Namaskaram");
  });

  it("shows a recorded verdict as recorded, and does not offer a second one", async () => {
    const { container } = await renderAdminRoute(
      <QaSampleReviewPage params={routeParams({ sampleId: "s1" })} />,
      { "/v1/admin/qa-samples/s1": { sample: { ...SAMPLE, verdict: "defect" }, call: CALL } },
    );
    await screen.findByText(/Recorded as/);
    expect(container.textContent).toContain("A verdict is written once");
    expect(screen.queryByRole("button", { name: /Concern/ })).toBeNull();
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
  it("does not report the sampling queue reviewed over a read the browser never made", async () => {
    browserOffline();
    const { container } = await renderAdminRoute(<QaSamplingPage />, {
      "/v1/admin/qa-samples?pending=true": [SAMPLE],
    });

    expect(container.textContent).not.toContain("Every sampled call has been reviewed");
    expect(container.textContent).toContain("The sampling queue could not be read");
  });
});

/**
 * SEC-COMP §5: an admin read of a client's call is ALWAYS audited.
 *
 * `GET /v1/admin/qa-samples/{id}` writes an `audit_log` row in the same transaction as
 * the read (quality/sampling_routes.py::get_qa_sample) — the shape
 * `crm/routes.py::get_raw_transcript` uses, because this discloses one tenant's
 * conversation to somebody outside that tenant. The row is what makes "who looked at this
 * client's calls" answerable at all.
 *
 * The hook holds `staleTime: Infinity` so a poll cannot flood that trail, and until this
 * test the same setting also swallowed the deliberate SECOND OPEN: a reviewer who worked
 * two samples and came back to the first got the cached copy, so the trail recorded one
 * disclosure where there had been two. `refetchOnMount: "always"` is the setting that
 * separates the two cases — a navigation costs a row, a timer still costs none.
 *
 * Rendered through ONE `QueryClient` across two mounts, because a fresh client per render
 * is a fresh cache and the test would pass whatever the hook did.
 */
describe("re-opening a sampled call", () => {
  const DETAIL_PATH = "/v1/admin/qa-samples/s1";

  it("reads the server again, so the second look is audited too", async () => {
    const calls = stubApi({ [DETAIL_PATH]: { sample: SAMPLE, call: CALL } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const openIt = async () => {
      let result!: ReturnType<typeof render>;
      await act(async () => {
        result = render(
          <QueryClientProvider client={client}>
            <Suspense fallback={null}>
              <QaSampleReviewPage params={routeParams({ sampleId: "s1" })} />
            </Suspense>
          </QueryClientProvider>,
        );
      });
      return result;
    };

    const first = await openIt();
    await screen.findByText(/Sri Traders/);
    expect(calls.filter((c) => c.path === DETAIL_PATH).length).toBe(1);

    // Navigating away unmounts the screen; the cache outlives it, which is the whole
    // point of the cache and the whole danger here.
    first.unmount();

    const second = await openIt();
    await waitFor(() => expect(calls.filter((c) => c.path === DETAIL_PATH).length).toBe(2));
    second.unmount();
  });
});
