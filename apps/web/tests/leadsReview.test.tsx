import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import LeadsPage from "@/app/c/[slug]/leads/page";
import type { Me } from "@/lib/api/client";
import type { Lead, LeadList } from "@/lib/api/leads";
import { calledTimes, leadNextStep, sourceLabel, stageSetBy } from "@/lib/leadLabels";

import { renderClientPage } from "./harness";
import { LEAD_FIELDS_CORE_ONLY } from "./fixtures/sharedReads";

/**
 * THE LEADS PAGE AS A WORK QUEUE (first-call review F-7): one toolbar, the stage chips and
 * a closed "More filters"; five columns to start — who, what they want, what is next, the
 * last call and the stage; plain words for the source; "Called 3 times" rather than a
 * "repeat" badge; whether the stage was set by a person or after a call; and on a phone a
 * two-line list rather than a table that scrolls sideways.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["leads:read", "leads:write"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Raghava Organics", slug: "acme", status: "active" },
};

const USUAL_COLUMNS: LeadList["columns"] = [
  { key: "name", label: "Name", kind: "fixed", type: "text" },
  { key: "need", label: "What they want", kind: "extraction", type: "text" },
  { key: "next_step", label: "Next step", kind: "fixed", type: "text" },
  { key: "last_call", label: "Last call", kind: "fixed", type: "text" },
  { key: "status", label: "Status", kind: "fixed", type: "enum" },
];

function lead(over: Partial<Lead> = {}): Lead {
  return {
    id: "lead-a",
    name: null,
    phone_e164: "+919876543210",
    status: "interested",
    source: "test_call",
    status_set_by: "system",
    data: { need: "Two kilos of green chilli" },
    schema_version: 1,
    call_count: 3,
    is_repeat_caller: true,
    last_call_id: "call-1",
    last_call_headline: "Asked for green chilli; wants a call back",
    last_call_outcome: "call_back_booked",
    next_callback_at: "2026-10-10T12:33:00Z",
    next_step: "Call back with today's price.",
    created_at: "2026-10-10T06:00:00Z",
    updated_at: "2026-10-10T12:30:00Z",
    assigned_to: null,
    assigned_to_name: null,
    ...over,
  };
}

function leadList(items: Lead[]): LeadList {
  return {
    items,
    columns: USUAL_COLUMNS,
    available_columns: [...USUAL_COLUMNS, { key: "quantity", label: "Quantity", kind: "extraction", type: "text" }],
    dropped_column_keys: [],
    total: items.length,
    limit: 100,
    offset: 0,
    status_counts_matching_search: { new: 0, contacted: 0, interested: 1, hot: 0, won: 0, lost: 0 },
    semantic_truncated: false,
  };
}

function routes(items: Lead[]) {
  return {
    "/v1/me": ME,
    "/v1/agents": [],
    "/v1/members": [],
    "POST /v1/leads/search": leadList(items),
    "/v1/leads/facets": { facets: [], omitted_field_count: 0 },
    "/v1/leads/views": { items: [] },
    "/v1/lead-fields": LEAD_FIELDS_CORE_ONLY,
  };
}

/** Make the phone media query match, as a 375px screen would. */
function asPhone() {
  const original = window.matchMedia;
  window.matchMedia = ((query: string) =>
    ({
      matches: query.includes("max-width: 767px") || query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList) as typeof window.matchMedia;
  return () => {
    window.matchMedia = original;
  };
}

let restore: (() => void) | null = null;
afterEach(() => {
  restore?.();
  restore = null;
});

describe("the words for a lead", () => {
  it("names every source in plain words, and an unknown one as it came", () => {
    expect(
      ["inbound_call", "outbound_call", "test_call", "campaign", "webhook", "manual"].map(sourceLabel),
    ).toEqual(["Incoming call", "Outgoing call", "Test call", "Campaign", "Website form", "Import"]);
    expect(sourceLabel("whatsapp_chat")).toBe("whatsapp chat");
  });

  it("says how often a lead called instead of a repeat badge, and says nothing for one call", () => {
    expect(calledTimes(3)).toBe("Called 3 times");
    expect(calledTimes(1)).toBeNull();
  });

  it("tells a stage a person chose from one the rules set after a call", () => {
    expect(stageSetBy("person")).toBe("Set by your team");
    expect(stageSetBy("system")).toBe("Set after a call");
  });

  it("puts the soonest call back before the suggested next step", () => {
    expect(leadNextStep(lead())).toMatch(/^Call back /);
    expect(leadNextStep(lead({ next_callback_at: null }))).toBe("Call back with today's price.");
    expect(leadNextStep(lead({ next_callback_at: null, next_step: null }))).toBeNull();
  });
});

describe("the leads table", () => {
  it("asks for the usual five columns and the business's own key for what they want", async () => {
    const { calls } = await renderClientPage(<LeadsPage />, routes([lead()]));
    await screen.findAllByRole("columnheader");
    const search = calls.find((c) => c.path === "/v1/leads/search");
    expect(JSON.parse(search?.body ?? "{}").columns).toBe("name,need,next_step,last_call,status");
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Select", "Name", "What they want", "Next step", "Last call", "Status", "More"]);
  });

  it("reads a row: the number for a nameless lead, called N times, the last call linked, who set the stage", async () => {
    await renderClientPage(<LeadsPage />, routes([lead()]));
    const row = (await screen.findByRole("link", { name: "+91 98765 43210" })).closest("tr")!;
    const cells = within(row);
    expect(cells.getByText("Called 3 times")).toBeTruthy();
    expect(cells.getByText("Two kilos of green chilli")).toBeTruthy();
    expect(cells.getByText(/^Call back /)).toBeTruthy();
    const last = cells.getByRole("link", { name: "Asked for green chilli; wants a call back" });
    expect(last.getAttribute("href")).toContain("/calls/call-1");
    expect(cells.getByText("Set after a call")).toBeTruthy();
    expect(row.textContent).not.toContain("repeat");
    expect(row.textContent).not.toContain("No name");
  });

  it("keeps everything used now and then behind one closed 'More filters'", async () => {
    await renderClientPage(<LeadsPage />, routes([lead()]));
    const more = await screen.findByText("More filters");
    expect(more.closest("details")?.hasAttribute("open")).toBe(false);
    expect(within(more.closest("details")!).getByRole("button", { name: "Assigned to me" })).toBeTruthy();
  });
});

describe("the leads table on a phone", () => {
  it("stays a table, with the Name column pinned while the rest scrolls sideways", async () => {
    restore = asPhone();
    const { container } = await renderClientPage(<LeadsPage />, routes([lead({ name: "Lakshmi" })]));
    const name = await screen.findByRole("link", { name: "Lakshmi" });
    expect(container.querySelector("table")).not.toBeNull();
    expect(name.closest("td")?.className).toContain("sticky");
    // The scroller is the table's own named region, not the page.
    expect(name.closest("[role=region]")?.getAttribute("aria-label")).toBe("Leads");
  });
});
