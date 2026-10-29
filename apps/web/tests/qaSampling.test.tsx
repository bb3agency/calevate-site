import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, describe, expect, it } from "vitest";

import QaSampleReviewPage from "@/app/admin/qa-sampling/[sampleId]/page";
import QaSamplingPage from "@/app/admin/qa-sampling/page";
import {
  DEFAULT_FILTERS,
  nextWaitingPath,
  queuePath,
  type QaQueuePage,
  type QaSample,
} from "@/lib/api/qaSamples";

import { browserOffline, problem, stillLoading, stubApi } from "./harness";
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
  caller_e164: "+919876500021",
  started_at: "2026-08-05T06:30:00Z",
  duration_s: 154,
  outcome_tag: "resolved",
  sentiment: "positive",
  summary: "Caller booked a Tuesday slot.",
  lead_id: null,
  has_recording: false,
  disclosure_played: true,
  transcript: [
    {
      idx: 0,
      speaker: "agent",
      text: "Namaskaram, Sri Clinic.",
      lang: "te-IN",
      start_ms: 0,
      redacted: true,
    },
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

const QUEUE = queuePath(DEFAULT_FILTERS);
const NEXT = nextWaitingPath({ client: null, week: null });

const CLIENT = {
  tenant_id: "t1",
  tenant_name: "Sri Traders",
  tenant_slug: "sri-traders",
  waiting: 1,
  sampled: 2,
};

function page(items: QaSample[], over: Partial<QaQueuePage> = {}): QaQueuePage {
  return {
    items,
    total: items.length,
    offset: 0,
    limit: 50,
    waiting_total: items.filter((row) => row.verdict === null).length,
    clients: [CLIENT],
    weeks: ["2026-08-03"],
    ...over,
  };
}

describe("the QA sampling queue", () => {
  afterEach(() => window.history.replaceState(null, "", "/"));

  it("leads with the work and one button that starts it", async () => {
    const { container } = await renderAdminRoute(<QaSamplingPage />, { [QUEUE]: page([SAMPLE]) });
    await screen.findByText("1 call waiting for review");
    const start = screen.getByRole("link", { name: /Start reviewing/ });
    expect(start.getAttribute("href")).toBe("/admin/qa-sampling/s1");
    // The draw's evidence: what makes 5% a claim somebody can check.
    expect(container.textContent).toContain("Week of 3 Aug 2026");
    expect(container.textContent).toContain("Pick #1 of 2 from 40 calls");
  });

  it("puts each client's calls under its name, with that client's count", async () => {
    const other: QaSample = {
      ...SAMPLE,
      id: "s2",
      tenant_id: "t2",
      tenant_name: "Raghava Organics",
      tenant_slug: "raghava",
      agent_name: "Orders",
    };
    await renderAdminRoute(<QaSamplingPage />, {
      [QUEUE]: page([SAMPLE, other], {
        clients: [
          CLIENT,
          { ...CLIENT, tenant_id: "t2", tenant_name: "Raghava Organics", tenant_slug: "raghava", waiting: 2, sampled: 3 },
        ],
      }),
    });
    const heading = await screen.findByRole("heading", { name: "Raghava Organics" });
    expect(heading.parentElement?.textContent).toContain("2 of 3 to review, all weeks");
    const row = screen.getByRole("link", { name: /Raghava Organics, Orders/ });
    expect(row.getAttribute("href")).toBe("/admin/qa-sampling/s2");
    // The slug path is not printed on the row.
    expect(row.textContent).not.toContain("/c/raghava");
  });

  it("reads the filters from the URL and sends them to the server", async () => {
    window.history.replaceState(
      null,
      "",
      "/admin/qa-sampling?client=t1&status=reviewed&verdict=defect&week=2026-08-03",
    );
    const filtered = queuePath({
      ...DEFAULT_FILTERS,
      client: "t1",
      status: "reviewed",
      verdict: "defect",
      week: "2026-08-03",
    });
    const { calls } = await renderAdminRoute(<QaSamplingPage />, {
      [filtered]: page([{ ...SAMPLE, verdict: "defect", reviewed_at: "2026-08-11T05:00:00Z" }]),
      [nextWaitingPath({ client: "t1", week: "2026-08-03" })]: page([]),
    });
    await screen.findByText("Defect");
    expect(calls.map((call) => call.path)).toContain(filtered);
    expect(filtered).toContain("tenant_id=t1");
    expect(filtered).toContain("verdict=defect");
    // Nothing waiting under this client and week, so there is nothing to start.
    await waitFor(() =>
      expect(calls.map((call) => call.path)).toContain(nextWaitingPath({ client: "t1", week: "2026-08-03" })),
    );
    expect(screen.queryByRole("link", { name: /Start reviewing/ })).toBeNull();
  });

  it("pages on the server and says how many there are", async () => {
    await renderAdminRoute(<QaSamplingPage />, {
      [QUEUE]: page([SAMPLE], { total: 120, waiting_total: 120 }),
    });
    await screen.findByText(/of 120 calls/);
    expect(screen.getByRole("navigation", { name: "Queue pages" })).toBeTruthy();
  });

  it("marks the page it is leaving as loading while the next is fetched", async () => {
    await renderAdminRoute(<QaSamplingPage />, {
      [QUEUE]: page([SAMPLE], { total: 120, waiting_total: 120 }),
      [queuePath({ ...DEFAULT_FILTERS, page: 2 })]: stillLoading(),
      [NEXT]: page([SAMPLE]),
    });
    await screen.findByText(/of 120 calls/);
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() =>
      expect(screen.getByText(/of 120 calls/).closest("[aria-busy='true']")).not.toBeNull(),
    );
  });

  it("refuses rather than claiming everything has been reviewed", async () => {
    const { container } = await renderAdminRoute(<QaSamplingPage />, {
      [QUEUE]: problem(401, { title: "Unauthorized" }),
    });
    await screen.findByText("The sampling queue could not be read");
    expect(container.textContent).not.toContain("Every picked call has been reviewed");
  });

  it("says an empty queue is the GOOD state, and what happens next", async () => {
    const { container } = await renderAdminRoute(<QaSamplingPage />, { [QUEUE]: page([]) });
    await screen.findByText("Every picked call has been reviewed");
    expect(container.textContent).toContain("Monday at 07:20 IST");
    expect(container.textContent).not.toContain("could not be read");
  });

  it("says a filtered empty view is the filters, and offers to clear them", async () => {
    window.history.replaceState(null, "", "/admin/qa-sampling?client=t1");
    await renderAdminRoute(<QaSamplingPage />, {
      [queuePath({ ...DEFAULT_FILTERS, client: "t1" })]: page([], { waiting_total: 4 }),
    });
    await screen.findByText("No calls match these filters");
    expect(screen.getByRole("button", { name: "Clear the filters" })).toBeTruthy();
  });

  it("carries no phone number and no transcript on the list", async () => {
    const { container } = await renderAdminRoute(<QaSamplingPage />, { [QUEUE]: page([SAMPLE]) });
    await screen.findByText("1 call waiting for review");
    expect(container.textContent).not.toContain("+91");
    expect(container.textContent).not.toContain("Namaskaram");
  });

  it("finds a client by typing its name", async () => {
    await renderAdminRoute(<QaSamplingPage />, {
      [QUEUE]: page([SAMPLE], {
        clients: [CLIENT, { ...CLIENT, tenant_id: "t2", tenant_name: "Raghava Organics", tenant_slug: "raghava" }],
      }),
    });
    await screen.findByText("1 call waiting for review");
    const box = screen.getByRole("combobox", { name: "Client" });
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: "ragh" } });
    const options = within(screen.getByRole("listbox", { name: "Client" })).getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0]?.textContent).toContain("Raghava Organics");
  });

  it("does not report the sampling queue reviewed over a read the browser never made", async () => {
    browserOffline();
    const { container } = await renderAdminRoute(<QaSamplingPage />, { [QUEUE]: page([SAMPLE]) });
    expect(container.textContent).not.toContain("Every picked call has been reviewed");
    expect(container.textContent).toContain("The sampling queue could not be read");
  });
});

describe("reviewing a sampled call", () => {
  afterEach(() => window.history.replaceState(null, "", "/"));

  const NEXT_SAMPLE: QaSample = {
    ...SAMPLE,
    id: "s2",
    tenant_name: "Raghava Organics",
    agent_name: "Orders",
  };
  const open = (over: Record<string, unknown> = {}) =>
    renderAdminRoute(<QaSampleReviewPage params={routeParams({ sampleId: "s1" })} />, {
      "/v1/admin/qa-samples/s1": { sample: SAMPLE, call: CALL },
      ...over,
    });
  const record = async (verdict: RegExp) => {
    fireEvent.click(await screen.findByRole("radio", { name: verdict }));
    fireEvent.click(screen.getByRole("button", { name: "Record verdict" }));
  };

  it("renders the redacted transcript and says that is what it is", async () => {
    const { container } = await open();
    await screen.findByText("Namaskaram, Sri Clinic.");
    expect(container.textContent).toContain("[phone ••10]");
    expect(container.textContent).toContain("are hidden in this transcript");
    // Founder, 15 Oct 2026: no audit notices in the UI. The read is still audited server-side.
    expect(container.textContent).not.toMatch(/audit log|against your name/);
  });

  it("lists what to check before the reviewer reads", async () => {
    await open();
    const heading = await screen.findByRole("heading", { name: "What to check" });
    const text = heading.parentElement?.textContent ?? "";
    expect(text).toContain("say it is an AI");
    expect(text).toContain("wrong or made up");
    expect(text).toContain("anything personal left visible");
  });

  it("offers no way to see the unredacted text", async () => {
    const { container } = await open();
    await screen.findByText("Namaskaram, Sri Clinic.");
    // Hard rule 5 has ONE raw path in this product and it is not on this screen. Asserted
    // over the CONTROLS, not the prose: the notice says what is hidden.
    const controls = screen.queryAllByRole("button").map((node) => node.textContent ?? "");
    for (const control of controls) {
      expect(control).not.toMatch(/raw|unredacted|full text/i);
    }
    expect(container.querySelector('[href*="transcript/raw"]')).toBeNull();
  });

  it("shows why THIS call was picked, with the seed behind its info", async () => {
    await open();
    await screen.findByText(/Pick #1 of 2/);
    fireEvent.click(screen.getByRole("button", { name: /How this call was picked/ }));
    await screen.findByText("t1:2026-08-03");
  });

  it("offers the verdicts as a radio group and records nothing until asked", async () => {
    const { calls } = await open();
    const group = await screen.findByRole("radiogroup", { name: "What did this call show?" });
    expect(within(group).getAllByRole("radio")).toHaveLength(3);
    const button = screen.getByRole("button", { name: "Record verdict" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    fireEvent.click(within(group).getByRole("radio", { name: /Concern/ }));
    expect((within(group).getByRole("radio", { name: /Concern/ }) as HTMLInputElement).checked).toBe(true);
    expect(button.disabled).toBe(false);
    // A choice is not a verdict: nothing has been sent.
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("records a Clean verdict once and offers the next call", async () => {
    const { container, calls } = await open({
      "POST /v1/admin/qa-samples/s1/review": { ...SAMPLE, verdict: "clean", reviewed_at: "x" },
      [NEXT]: page([NEXT_SAMPLE]),
    });
    await record(/Clean/);

    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const posted = calls.find((call) => call.method === "POST");
    expect(posted?.path).toBe("/v1/admin/qa-samples/s1/review");
    expect(posted?.body).toContain("clean");

    const next = await screen.findByRole("link", { name: /Next call to review/ });
    expect(next.getAttribute("href")).toBe("/admin/qa-sampling/s2");
    expect(container.textContent).toContain("Recorded as Clean");
    // Write-once: the choices are gone, and a Clean call has nothing to follow up.
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByText("Follow it up")).toBeNull();
    // Recording does not re-read the call: that read is audited, and one opening is one row.
    expect(calls.filter((call) => call.path === "/v1/admin/qa-samples/s1")).toHaveLength(1);
  });

  it("says all caught up when nothing else is waiting", async () => {
    await open({
      "POST /v1/admin/qa-samples/s1/review": { ...SAMPLE, verdict: "clean", reviewed_at: "x" },
      [NEXT]: page([]),
    });
    await record(/Clean/);
    await screen.findByText("All caught up");
    expect(screen.getByRole("link", { name: "Back to the queue" }).getAttribute("href")).toBe(
      "/admin/qa-sampling",
    );
  });

  it("follows a Concern up through the client's own screens and Pip", async () => {
    await open({
      "POST /v1/admin/qa-samples/s1/review": { ...SAMPLE, verdict: "concern", reviewed_at: "x" },
      [NEXT]: page([NEXT_SAMPLE]),
    });
    await record(/Concern/);

    const setup = await screen.findByRole("link", { name: /Reception agent's set-up, as the client sees it/ });
    const setupUrl = new URL(setup.getAttribute("href") ?? "", "http://x");
    expect(setupUrl.pathname).toBe("/admin/view-as");
    expect(setupUrl.searchParams.get("slug")).toBe("sri-traders");
    expect(setupUrl.searchParams.get("path")).toBe("/agents/a1");

    const callLink = screen.getByRole("link", { name: /this call in the client's dashboard/ });
    expect(new URL(callLink.getAttribute("href") ?? "", "http://x").searchParams.get("path")).toBe(
      "/calls/c1",
    );

    const ask = screen.getByRole("button", { name: /Ask Pip about this call/ });
    // The prompt names the client and the agent, never the caller.
    expect(ask.getAttribute("title")).toContain("Sri Traders");
    expect(ask.getAttribute("title")).not.toContain("+91");
    expect(await screen.findByRole("link", { name: /Next call to review/ })).toBeTruthy();
  });

  it("keeps the next call inside the queue's client and week", async () => {
    window.history.replaceState(null, "", "/admin/qa-sampling/s1?client=t1&week=2026-08-03");
    const scoped = nextWaitingPath({ client: "t1", week: "2026-08-03" });
    const { calls } = await open({
      "POST /v1/admin/qa-samples/s1/review": { ...SAMPLE, verdict: "clean", reviewed_at: "x" },
      [scoped]: page([NEXT_SAMPLE]),
    });
    await record(/Clean/);
    const next = await screen.findByRole("link", { name: /Next call to review/ });
    expect(calls.map((call) => call.path)).toContain(scoped);
    expect(next.getAttribute("href")).toBe("/admin/qa-sampling/s2?client=t1&week=2026-08-03");
  });

  it("shows the refusal when somebody else reviewed it first", async () => {
    await open({
      "POST /v1/admin/qa-samples/s1/review": problem(409, {
        title: "Conflicting request",
        detail: "This call was already reviewed as 'defect'.",
      }),
    });
    await record(/Clean/);
    await screen.findByText(/already reviewed/);
    // The choices stay: the reviewer needs to see what happened, not a panel gone quiet.
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });

  it("refuses instead of rendering an empty review when the call cannot be read", async () => {
    const { container } = await renderAdminRoute(
      <QaSampleReviewPage params={routeParams({ sampleId: "s1" })} />,
      { "/v1/admin/qa-samples/s1": problem(503, { title: "Service unavailable" }) },
    );
    await screen.findByText(/could not be read, so it cannot be reviewed/);
    // No verdicts under a call nobody could read.
    expect(screen.queryByRole("radio")).toBeNull();
    expect(container.textContent).not.toContain("Namaskaram");
  });

  it("shows a recorded verdict as recorded, and does not offer a second one", async () => {
    await renderAdminRoute(<QaSampleReviewPage params={routeParams({ sampleId: "s1" })} />, {
      "/v1/admin/qa-samples/s1": { sample: { ...SAMPLE, verdict: "defect" }, call: CALL },
      [NEXT]: page([]),
    });
    await screen.findByText(/Recorded as/);
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.getByText("Follow it up")).toBeTruthy();
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
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
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
    await waitFor(() =>
      expect(calls.filter((c) => c.path === DETAIL_PATH).length).toBe(2),
    );
    second.unmount();
  });
});
