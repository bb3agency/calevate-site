import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallsPage from "@/app/c/[slug]/calls/page";
import type { CallSummary, Me } from "@/lib/api/client";

import { browserOffline, problem, renderClientPage } from "./harness";

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
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
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
    outcome_tag: "appointment_booked",
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
    expect(await screen.findByText("+919876543210")).toBeTruthy();
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
    const { container } = await renderClientPage(page, routes([call(), call({ id: "c2" })]));
    await screen.findByText("Open a call to see the transcript, recording and the details we captured.");
    expect(container.textContent).toContain("2");
    expect(container.textContent).toContain("calls");
  });

  it("stops claiming a total once the page is full — 100 rows is our query, not their business", async () => {
    // A full page means the account may have any number of calls past it; "100 calls"
    // read forever on a busy account is the statement-about-our-query defect the leads
    // screen's docstring names (ux-audit CL1).
    const fullPage = Array.from({ length: 100 }, (_, i) => call({ id: `c-${i}` }));
    const { container } = await renderClientPage(page, routes(fullPage));
    await screen.findByText(/Showing the/);
    expect(container.textContent).toContain("Showing the");
    expect(container.textContent).toContain("most recent");
    expect(container.textContent).not.toContain("100 calls");
  });

  it("can filter by every status the system records, not a subset of them", async () => {
    // The four the old chip row omitted. A client who cannot ASK for their voicemails
    // has no way to find them: the list is capped at 100 rows.
    for (const label of ["Busy", "Voicemail", "In progress", "No answer"]) {
      expect(screen.queryByRole("button", { name: label })).toBeNull();
    }

    await renderClientPage(page, routes([call()]));

    for (const label of ["All", "Completed", "No answer", "Busy", "Voicemail", "Failed", "In progress"]) {
      expect(screen.getByRole("button", { name: label }), `missing chip: ${label}`).toBeTruthy();
    }
  });

  it("asks the server for the status the chip names", async () => {
    const { calls } = await renderClientPage(
      page,
      routes([call()], { "/v1/calls?status=voicemail&limit=100": [] }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Voicemail" }));
    await screen.findByText("No calls match this filter");

    // Server-side, not a client-side slice of a capped list — the difference decides
    // whether row 101 is findable at all.
    expect(calls.some((c) => c.path === "/v1/calls?status=voicemail&limit=100")).toBe(true);
  });

  it("renders a status it has never seen rather than dropping the row", async () => {
    const { container } = await renderClientPage(
      page,
      // No assertion: `CallSummaryOut.status` is an open `string` on the wire, so
      // `as CallSummary["status"]` asserted `string` to `string` and bought nothing but a
      // place for the compiler to stop looking.
      routes([call({ status: "abandoned" })]),
    );

    await screen.findByText("+919876543210");
    // Fails visible: the row is there and the unfamiliar word is printed, because a
    // status this build does not know is the one a reader most needs to see.
    expect(container.textContent).toContain("abandoned");
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
    expect(container.textContent).toContain("We could not reach Calevate");
  });

});
