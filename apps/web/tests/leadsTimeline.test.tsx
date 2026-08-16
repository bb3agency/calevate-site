import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LeadDetailPage from "@/app/c/[slug]/leads/[leadId]/page";
import type { Me } from "@/lib/api/client";
import type { Lead, LeadTimeline, LeadTimelineEvent, Member } from "@/lib/api/leads";

import { problem, renderClientPage } from "./harness";

/**
 * The lead's own screen, and the history nobody could read until M3.
 *
 * `lead_events` has been written since M1 by six producers across three deployables and
 * had exactly one reader: the aggregate behind the needs-attention badge. What this file
 * pins is the pair of distinctions the wave in BUILD-LOG §52 removed from nine screens
 * and that a NEW screen is the easiest place to reintroduce:
 *
 * - **An empty history and a failed one look different.** `?? []` on the timeline fetch
 *   would draw "Nothing has happened yet" over a 503, which tells an owner their AI
 *   never rang anybody. Both cases are tested, and the empty one asserts the failure
 *   copy is absent as well as the other way round.
 * - **The two requests do not answer for each other.** The lead and its timeline are
 *   separate reads and either can fail alone: a dead timeline must not blank the header,
 *   and a dead header must not imply the history is gone.
 *
 * Hard rule 6 has its own case: the API projects each event into prose server-side
 * rather than serializing `lead_events.payload`, and the phone planted below is in no
 * payload this screen receives — so if it renders, this screen put it there.
 */

const RAW_PHONE = "+919876543210";
const MASKED = "+9198••••3210";

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["leads:read", "leads:write", "calls:read"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const MEMBERS: Member[] = [
  { id: "u1", name: "Priya Nair", role: "owner" },
  { id: "u2", name: "Kiran Babu", role: "staff" },
];

const LEAD: Lead = {
  id: "lead-a",
  name: "Ramesh Kumar",
  phone_masked: MASKED,
  status: "hot",
  source: "inbound_call",
  data: {},
  schema_version: 1,
  call_count: 2,
  is_repeat_caller: true,
  last_call_id: "call-1",
  created_at: "2026-08-10T06:00:00Z",
  updated_at: "2026-08-13T04:30:00Z",
  assigned_to: "u2",
  assigned_to_name: "Kiran Babu",
};

function event(over: Partial<LeadTimelineEvent> = {}): LeadTimelineEvent {
  return {
    id: "ev-1",
    type: "status_change",
    occurred_at: "2026-08-13T04:30:00Z",
    actor_kind: "member",
    actor_name: "Priya Nair",
    title: "Moved to hot",
    detail: null,
    call_id: null,
    ...over,
  };
}

function timeline(items: LeadTimelineEvent[], over: Partial<LeadTimeline> = {}): LeadTimeline {
  return { items, total: items.length, limit: 50, offset: 0, ...over };
}

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    "/v1/members": MEMBERS,
    "/v1/leads/lead-a": LEAD,
    "/v1/leads/lead-a/timeline?limit=50": timeline([event()]),
    ...over,
  };
}

/** The route page reads `params` with React 19's `use()`, so it gets a promise. */
function page() {
  return <LeadDetailPage params={Promise.resolve({ slug: "acme", leadId: "lead-a" })} />;
}

describe("the history a client can finally read", () => {
  it("renders each event as the server's own prose, newest first", async () => {
    const { container } = await renderClientPage(
      page(),
      routes({
        "/v1/leads/lead-a/timeline?limit=50": timeline([
          event({ id: "ev-1", title: "Moved to hot" }),
          event({
            id: "ev-2",
            type: "notification",
            actor_kind: "system",
            actor_name: null,
            title: "Hot-lead alert not sent by WhatsApp",
            detail: "We could not deliver it after 3 attempt(s). (recipient_not_opted_in)",
          }),
          event({
            id: "ev-3",
            type: "note",
            actor_kind: "system",
            actor_name: null,
            title: "Call blocked",
            detail: "This person asked not to be called.",
          }),
        ]),
      }),
    );

    await screen.findByText("Moved to hot");
    expect(container.textContent).toContain("Hot-lead alert not sent by WhatsApp");
    expect(container.textContent).toContain("recipient_not_opted_in");
    expect(container.textContent).toContain("Call blocked");
    // A person's edit is attributed to them; the platform's is attributed to us. A
    // colleague's name on something nobody did is the failure this keeps out.
    expect(container.textContent).toContain("Priya Nair");
    expect(container.textContent).toContain("Calevate");
  });

  it("says how many entries there are and whether it is showing all of them", async () => {
    const { container } = await renderClientPage(
      page(),
      routes({
        "/v1/leads/lead-a/timeline?limit=50": timeline([event()], { total: 64 }),
      }),
    );
    await screen.findByText("Moved to hot");
    // `total` is the SET, `items` is the PAGE — the distinction §52 records four defects
    // for. A screen that printed `items.length` here would say "1 entry" of 64.
    expect(container.textContent).toContain("The 1 most recent of 64");
  });

  it("links an event that names a call, and never puts a number in the href", async () => {
    const { container } = await renderClientPage(
      page(),
      routes({
        "/v1/leads/lead-a/timeline?limit=50": timeline([
          event({ type: "call", title: "Call completed", call_id: "call-9" }),
        ]),
      }),
    );

    const link = (await screen.findByRole("link", { name: "Open the call" })) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/c/acme/calls/call-9");
    for (const anchor of Array.from(container.querySelectorAll("a"))) {
      expect(anchor.getAttribute("href") ?? "").not.toContain("9876543210");
    }
  });

  it("keeps an event whose type this build does not recognise", async () => {
    // A deploy sitting behind its own migration must not delete a client's history. The
    // style table is read through `lookup` with a visible fallback, exactly as the call
    // detail reads `speaker`.
    const { container } = await renderClientPage(
      page(),
      routes({
        "/v1/leads/lead-a/timeline?limit=50": timeline([
          event({ type: "merge", title: "Activity", actor_kind: "system", actor_name: null }),
        ]),
      }),
    );
    await screen.findByText("Activity");
    expect(container.textContent).toContain("Activity");
  });
});

describe("an empty history and a failed one are different sentences", () => {
  it("says nothing has happened only when the SERVER said so", async () => {
    const { container } = await renderClientPage(
      page(),
      routes({ "/v1/leads/lead-a/timeline?limit=50": timeline([]) }),
    );

    await screen.findByText("Nothing has happened yet");
    expect(container.textContent).toContain("0 entries");
    // The other half of the pair: the empty state must not carry the failure's words.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("refuses rather than drawing an empty history over a 503", async () => {
    /**
     * `?? []` here is the exact two characters §52 removed from nine screens. It would
     * tell an owner whose alerts have stopped that nothing ever happened to this lead.
     */
    const { container } = await renderClientPage(
      page(),
      routes({
        "/v1/leads/lead-a/timeline?limit=50": problem(503, {
          title: "Service unavailable",
          detail: "We could not read this lead's history.",
        }),
      }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).toContain("We could not read this lead's history.");
    expect(container.textContent).not.toContain("Nothing has happened yet");
    // And no count either: "0 entries" from a request that never landed is the same lie
    // in a smaller font.
    expect(container.textContent).not.toContain("0 entries");
  });

  it("keeps the lead header when only the timeline failed", async () => {
    const { container } = await renderClientPage(
      page(),
      routes({
        "/v1/leads/lead-a/timeline?limit=50": problem(503, { title: "Service unavailable" }),
      }),
    );

    await screen.findByRole("alert");
    // The lead itself read fine, so the header is real data and stays.
    expect(container.textContent).toContain("Ramesh Kumar");
    expect(container.textContent).toContain(MASKED);
    expect(container.textContent).not.toContain(RAW_PHONE);
  });

  it("keeps the history when only the lead failed", async () => {
    const { container } = await renderClientPage(
      page(),
      routes({
        "/v1/leads/lead-a": problem(503, { title: "Service unavailable" }),
      }),
    );

    await screen.findByText("Moved to hot");
    // …and does not describe a lead it could not read.
    expect(container.textContent).not.toContain("Ramesh Kumar");
  });

  it("answers a lead that is not there with the server's refusal, not an empty page", async () => {
    const { container } = await renderClientPage(
      page(),
      routes({
        "/v1/leads/lead-a": problem(404, {
          title: "Lead not found",
          detail: "No lead matches this request.",
        }),
        "/v1/leads/lead-a/timeline?limit=50": problem(404, {
          title: "Lead not found",
          detail: "No lead matches this request.",
        }),
      }),
    );

    await screen.findAllByRole("alert");
    expect(container.textContent).toContain("No lead matches this request.");
    expect(container.textContent).not.toContain("Nothing has happened yet");
  });
});

describe("the owner control on the lead's own screen", () => {
  it("is the same control the table uses, with the team from /v1/members", async () => {
    await renderClientPage(page(), routes());
    const select = (await screen.findByLabelText("Owner of Ramesh Kumar")) as HTMLSelectElement;
    expect(select.value).toBe("u2");
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual([
      "Unassigned",
      "Priya Nair",
      "Kiran Babu",
    ]);
  });

  it("is disabled WITH the reason for a role that may not assign", async () => {
    const staff = { ...ME, role: "staff", permissions: ["leads:read"] };
    const { container } = await renderClientPage(page(), routes({ "/v1/me": staff }));
    const select = (await screen.findByLabelText("Owner of Ramesh Kumar")) as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    expect(container.textContent).toContain("Only an account owner can change who owns a lead");
  });
});
