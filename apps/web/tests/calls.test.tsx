import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallsPage from "@/app/c/[slug]/calls/page";
import type { CallSummary, Me } from "@/lib/api/client";

import { browserOffline, csv, problem, renderClientPage, stubDownloads } from "./harness";

/**
 * The call log — the screen a client opens when they want to know what actually
 * happened, and the one that holds the most personal data per pixel.
 *
 * Ranked by what a wrong render costs:
 *
 * 1. A caller's number in a LINK TARGET. Since D-436 the number is printed in full —
 *    ringing back is the only action this screen leads to — but every row carries one,
 *    so an `href` that picked it up would be a hundred log entries at once. URLs reach
 *    access logs, referrers and browser history; that half of hard rule 6 is unmoved.
 * 2. An empty list that is actually a failed request. "No calls" and "we could not
 *    read your calls" are opposite facts — the first sends an owner to check their
 *    phone line, the second to check with us.
 * 3. A filter that cannot express what the system records. `calls.status` holds eight
 *    values; the chips used to offer four, so a client asking "which went to
 *    voicemail" had no way to ask.
 * 4. A status this build has never heard of rendering as a blank row. It fails VISIBLE
 *    — neutral medallion, and the status still printed, because an unknown status is
 *    exactly the one worth reading.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read"],
  impersonating: false,
  withheld_acts: [],
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
};

function call(over: Partial<CallSummary> = {}): CallSummary {
  return {
    id: "c1",
    agent_id: "a1",
    agent_name: "Reception",
    direction: "inbound",
    status: "completed",
    caller_e164: "+919876543210",
    started_at: "2026-08-13T04:30:00Z",
    duration_s: 92,
    outcome_tag: "call_back_booked",
    summary_state: "ready",
    test_call: false,
    sentiment: "positive",
    summary: "Caller asked for a Tuesday slot.",
    lead_id: null,
    ...over,
  };
}

const page = <CallsPage params={Promise.resolve({ slug: "acme" })} />;

function routes(calls: unknown, over: Record<string, unknown> = {}) {
  return { "/v1/me": ME, "/v1/calls?limit=100": calls, ...over };
}

describe("the call log", () => {
  it("renders the caller's number and keeps it out of every link target", async () => {
    const { container } = await renderClientPage(page, routes([call()]));

    // WAS `not.toContain("9876543210")`. D-436 reversed it: a call log nobody can ring
    // back from is a list of things that already happened and cannot be acted on.
    // Printed grouped for reading (`formatPhone`); the E.164 form stays the value.
    expect(await screen.findByText("+91 98765 43210")).toBeTruthy();
    // The half that did NOT change: an id is fine in a URL, a phone number is not,
    // because URLs reach logs, referrers and the browser's history.
    for (const link of Array.from(container.querySelectorAll("a"))) {
      expect(link.getAttribute("href") ?? "").not.toMatch(/\d{10}/);
    }
  });

  it("tells a failed request apart from an empty one", async () => {
    const { container } = await renderClientPage(
      page,
      routes(problem(503, { title: "Service unavailable" })),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // The empty state must NOT also render: "no calls yet" under an error is the
    // sentence that sends a client to check their phone line instead of ringing us.
    expect(container.textContent).not.toContain("No calls yet");
    expect(container.textContent).not.toContain("No calls match this filter");
  });

  it("says how many rows the filter matched, and only once it knows", async () => {
    const { container } = await renderClientPage(
      page,
      routes([call(), call({ id: "c2" })]),
    );
    // The instruction line that used to head the log ("Open a call to see …") is gone:
    // the rows are links and say so themselves. Wait on a row instead.
    await screen.findAllByText("+91 98765 43210");
    expect(container.textContent).toContain("2");
    expect(container.textContent).toContain("calls");
  });

  it("stops claiming a total once the page is full — 100 rows is our query, not their business", async () => {
    // A full page means the account may have any number of calls past it; "100 calls"
    // read forever on a busy account is the statement-about-our-query defect the leads
    // screen's docstring names (ux-audit CL1).
    const fullPage = Array.from({ length: 100 }, (_, i) =>
      call({ id: `c-${i}` }),
    );
    const { container } = await renderClientPage(page, routes(fullPage));
    await screen.findByText(/Showing the/);
    expect(container.textContent).toContain("Showing the");
    expect(container.textContent).toContain("most recent");
    expect(container.textContent).not.toContain("100 calls");
  });

  it("reaches yesterday — Show older calls appends the next offset page (CL2)", async () => {
    const fullPage = Array.from({ length: 100 }, (_, i) =>
      call({ id: `c-${i}` }),
    );
    const { container } = await renderClientPage(
      page,
      routes(fullPage, {
        "/v1/calls?limit=100&offset=100": [
          call({ id: "c-oldest", summary: "The oldest call in the log" }),
        ],
      }),
    );
    await screen.findByText(/Showing the/);
    fireEvent.click(screen.getByRole("button", { name: "Show older calls" }));
    await screen.findByText("The oldest call in the log");
    // Appended, and the short second page ends the log: the count is now the total.
    expect(container.textContent).toContain("101");
    expect(
      screen.queryByRole("button", { name: "Show older calls" }),
    ).toBeNull();
  });

  it("filters on one row: outcome chips with Needs you first, two dropdowns and the test-call switch", async () => {
    await renderClientPage(page, routes([call()]));
    await screen.findByText("+91 98765 43210");

    // The founder's outcome vocabulary (first-call review, decision 6), in the order an
    // owner works them. "Resolved" is gone.
    const chips = Array.from(
      screen.getByRole("group", { name: "Show calls by how they ended" }).querySelectorAll("button"),
    ).map((b) => b.textContent);
    expect(chips).toEqual(["Needs you", "Call back booked", "Answered", "Transferred", "Hung up early", "Missed"]);
    expect(screen.getByRole("combobox", { name: "When" })).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Which way" })).toBeTruthy();
    expect((screen.getByRole("checkbox", { name: "Include test calls" }) as HTMLInputElement).checked).toBe(true);
  });

  it("asks the server for the outcome the chip names", async () => {
    const { calls } = await renderClientPage(
      page,
      routes([call()], { "/v1/calls?outcome=missed&limit=100": [] }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Missed" }));
    await screen.findByText("No calls match this filter");

    // Server-side, not a client-side slice of a capped list — the difference decides
    // whether row 101 is findable at all.
    expect(calls.some((c) => c.path === "/v1/calls?outcome=missed&limit=100")).toBe(true);
  });

  it("leaves test calls out on the server when the switch is turned off", async () => {
    const { calls } = await renderClientPage(
      page,
      routes([call({ test_call: true })], { "/v1/calls?test_calls=false&limit=100": [] }),
    );
    expect(await screen.findByText("Test call")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: "Include test calls" }));
    await screen.findByText("No calls match this filter");
    expect(calls.some((c) => c.path === "/v1/calls?test_calls=false&limit=100")).toBe(true);
  });

  it("renders a status it has never seen rather than dropping the row", async () => {
    const { container } = await renderClientPage(
      page,
      // No assertion: `CallSummaryOut.status` is an open `string` on the wire, so
      // `as CallSummary["status"]` asserted `string` to `string` and bought nothing but a
      // place for the compiler to stop looking.
      routes([call({ status: "abandoned" })]),
    );

    await screen.findByText("+91 98765 43210");
    // Fails visible: the row is there and the unfamiliar word is printed, because a
    // status this build does not know is the one a reader most needs to see.
    // Sentence case since REDESIGN-2, like the outcome tag beside it.
    expect(container.textContent).toContain("Abandoned");
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
  it("does not report an empty call log over a read the browser never made", async () => {
    browserOffline();
    const { container } = await renderClientPage(page, routes([call()]));

    expect(container.textContent).not.toContain("No calls yet");
    expect(container.textContent).toContain("No reply reached this page");
  });
});

describe("exporting the call log (REDESIGN-2)", () => {
  it("downloads the same filtered log, for an owner who may read raw calls", async () => {
    stubDownloads();
    const owner: Me = { ...ME, permissions: ["calls:read", "calls:read_raw"] };
    const { calls } = await renderClientPage(page, {
      "/v1/me": owner,
      "/v1/calls?limit=100": [call()],
      "/v1/calls?direction=inbound&limit=100": [call()],
      "/v1/calls/export.csv?direction=inbound": csv("Started (India time),Direction\n"),
    });

    fireEvent.change(await screen.findByRole("combobox", { name: "Which way" }), {
      target: { value: "inbound" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Export CSV" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/v1/calls/export.csv?direction=inbound")).toBe(true),
    );
  });

  it("offers no export to someone the server would refuse", async () => {
    await renderClientPage(page, routes([call()]));
    await screen.findByText("+91 98765 43210");
    expect(screen.queryByRole("button", { name: "Export CSV" })).toBeNull();
  });
});

/**
 * WHAT ONE ROW SAYS (first-call review F-6): who (the lead's name, or the number), the
 * one-line headline written after the call and never the last thing said, how it ended
 * in words, how long and when. The warning tone is kept for the two things that ask the
 * owner to act: "Needs you" and a call back that is late.
 */
describe("a call row", () => {
  it("leads with the lead's name and the headline, never the last utterance", async () => {
    await renderClientPage(
      page,
      routes([
        call({
          lead_name: "Lakshmi",
          headline: "Asked for green chilli; wants a call back today",
          summary: "agent: ధన్యవాదాలు అండి, మళ్ళీ మాట్లాడతాము.",
        }),
      ]),
    );
    expect(await screen.findByRole("link", { name: "Lakshmi" })).toBeTruthy();
    expect(screen.getByText("Asked for green chilli; wants a call back today")).toBeTruthy();
    expect(document.body.textContent).not.toContain("agent: ధన్యవాదాలు");
  });

  it("says the summary is on its way for a fresh call rather than printing nothing", async () => {
    await renderClientPage(
      page,
      routes([call({ summary: null, headline: null, summary_state: "pending", outcome_tag: null })]),
    );
    expect(await screen.findByText("Summary on its way")).toBeTruthy();
  });

  it("uses the warning tone only for Needs you and an overdue call back", async () => {
    await renderClientPage(
      page,
      routes([
        call({ id: "c1", outcome_tag: "needs_you" }),
        call({ id: "c2", outcome_tag: "answered" }),
        call({
          id: "c3",
          outcome_tag: "call_back_booked",
          callback: { id: "cb", due_at: "2020-01-01T00:00:00Z", status: "scheduled" },
        }),
      ]),
    );
    await screen.findAllByText("+91 98765 43210");
    const needs = screen.getAllByText("Needs you").find((el) => el.tagName === "SPAN")!;
    expect(needs.className).toContain("text-warn");
    const answered = screen.getAllByText("Answered").find((el) => el.tagName === "SPAN")!;
    expect(answered.className).not.toContain("text-warn");
    const late = screen.getAllByText("Call back overdue")[0];
    expect(late.className).toContain("text-warn");
  });
});

/**
 * ONE AGENT'S CALLS, BY LINK. The agent page links its Calls entry to
 * `/c/{slug}/calls?agent_id=<id>`; the log asks the server for that agent only and says so
 * with a chip that clears it.
 */
describe("the agent filter from a link", () => {
  it("asks the server for that agent's calls and names the agent in a removable chip", async () => {
    window.history.replaceState(null, "", "/c/acme/calls?agent_id=a1");
    try {
      const { calls } = await renderClientPage(
        page,
        routes([call()], { "/v1/calls?agent_id=a1&limit=100": [call()] }),
      );
      const chip = await screen.findByRole("button", { name: "Agent: Reception" });
      expect(calls.some((c) => c.path === "/v1/calls?agent_id=a1&limit=100")).toBe(true);
      fireEvent.click(chip);
      await waitFor(() => expect(screen.queryByRole("button", { name: /^Agent:/ })).toBeNull());
      expect(calls.some((c) => c.path === "/v1/calls?limit=100")).toBe(true);
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });
});
