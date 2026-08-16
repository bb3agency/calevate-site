import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallsPage from "@/app/c/[slug]/calls/page";
import type { CallSummary, Me } from "@/lib/api/client";

import { problem, renderClientPage } from "./harness";

/**
 * The call log — the screen a client opens when they want to know what actually
 * happened, and the one that holds the most personal data per pixel.
 *
 * Ranked by what a wrong render costs:
 *
 * 1. A caller's number printed in full. Every row carries one, so a mistake here is a
 *    mistake a hundred times over, on the screen most likely to be screenshotted into
 *    a WhatsApp group. `caller_masked` is the only form the API sends and the only one
 *    that may reach the DOM (hard rule 6).
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
    caller_masked: "+9198765•••10",
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
  it("never renders a caller's number unmasked", async () => {
    const { container } = await renderClientPage(page, routes([call()]));

    expect(await screen.findByText("+9198765•••10")).toBeTruthy();
    // The identifying digits, in any grouping — a partial leak is still a leak.
    expect(container.textContent).not.toContain("9876543210");
    // And nothing in a link target either: an id is fine in a URL, a phone number is
    // not, because URLs reach logs, referrers and the browser's history.
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
    await screen.findByText("Caller numbers are masked here; open a call to see its details.");
    expect(container.textContent).toContain("2");
    expect(container.textContent).toContain("calls");
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

    await screen.findByText("+9198765•••10");
    // Fails visible: the row is there and the unfamiliar word is printed, because a
    // status this build does not know is the one a reader most needs to see.
    expect(container.textContent).toContain("abandoned");
  });
});
