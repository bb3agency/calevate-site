import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Actions } from "@/app/c/[slug]/agents/actions/Actions";
import {
  JOBS,
  addMinutesLocal,
  bookingParts,
  jobTitle,
  bookingTools,
  readBooking,
  readHours,
  uniqueName,
} from "@/app/c/[slug]/agents/actions/jobs";
import type { ActionTool, ActionsSettings, IntegrationCredential } from "@/lib/api/actions";
import { useClientSession } from "@/lib/api/session";
import { examplesFor } from "@/lib/verticalExamples";

import { OWNER_ME } from "./fixtures/sharedReads";
import { renderClientPage } from "./harness";

/**
 * THE GUIDED ACTIONS FLOW (REDESIGN-2): the owner picks a job and a few plain settings,
 * and the web layer derives the same `ToolIn` bodies the old form made them type.
 */

describe("the values the guided flow derives", () => {
  it("never reuses a name another action on the agent has", () => {
    expect(uniqueName("book_the_time", [])).toBe("book_the_time");
    expect(uniqueName("book_the_time", ["book_the_time", "book_the_time_2"])).toBe("book_the_time_3");
    // Changing an action keeps its own name.
    expect(uniqueName("book_the_time", ["book_the_time"], "book_the_time")).toBe("book_the_time");
  });

  it("builds the two calendar tools the server's CalendarConfig accepts", () => {
    const { check, book } = bookingTools(
      { credentialId: "cred-1", durationMin: 60, from: 9, to: 18, days: [1, 2, 3, 4, 5, 6], calendarId: "primary" },
      { check: "find_free_times", book: "book_the_time" },
    );
    // check needs a start AND an end parameter; book needs a start and a duration.
    expect(check.config).toMatchObject({ operation: "check", start_param: "start", end_param: "end", duration_min: 60 });
    expect(book.config).toMatchObject({ operation: "book", start_param: "start", duration_min: 60, summary_param: "summary" });
    expect(check.params?.map((p) => p.name)).toEqual(["start", "end"]);
    expect(book.params?.map((p) => p.name)).toEqual(["start", "summary"]);
    expect(check.credential_id).toBe("cred-1");
    // The hours and days are rules the server keeps, on BOTH tools…
    for (const tool of [check, book]) {
      expect(tool.config).toMatchObject({ opens: "09:00", closes: "18:00", open_days: [1, 2, 3, 4, 5, 6] });
    }
    // …and the same sentence is in what the agent is told, so it can say them.
    expect(readHours(book.description)).toEqual({ from: 9, to: 18 });
    expect(book.description).toContain("on Mon to Sat");
  });

  it("reads a booking job's settings back from its tools", () => {
    const { check, book } = bookingTools(
      { credentialId: "cred-1", durationMin: 30, from: 10, to: 13, days: [1, 2, 3, 4, 5, 6, 7], calendarId: "front-desk" },
      { check: "a", book: "b" },
    );
    const asTool = (body: typeof check, id: string): ActionTool => ({
      id,
      agent_id: "agent-1",
      enabled: true,
      kind: body.kind,
      provider: body.provider ?? null,
      name: body.name,
      description: body.description,
      trigger: body.trigger ?? "during_call",
      pre_call_message: body.pre_call_message ?? null,
      credential_id: body.credential_id ?? null,
      params: (body.params ?? []).map((p) => ({ ...p })),
      config: body.config,
    });
    const parts = bookingParts([asTool(check, "t1"), asTool(book, "t2")]);
    expect(readBooking(parts.check, parts.book)).toEqual({
      credentialId: "cred-1",
      durationMin: 30,
      from: 10,
      to: 13,
      days: [1, 2, 3, 4, 5, 6, 7],
      calendarId: "front-desk",
    });
    // Every day sends no day rule at all.
    expect(check.config.open_days).toBeNull();
  });

  it("reads hours from an action made before the server kept them", () => {
    const legacy = {
      id: "t1",
      agent_id: "agent-1",
      enabled: true,
      kind: "calendar",
      provider: "google",
      name: "book_the_time",
      description: "Use this to book. Only offer and book times between 10 am and 4 pm India time.",
      trigger: "during_call",
      pre_call_message: null,
      credential_id: null,
      params: [],
      config: { operation: "book", start_param: "start", duration_min: 30 },
    } satisfies ActionTool;
    expect(readBooking(undefined, legacy)).toMatchObject({ from: 10, to: 16, durationMin: 30 });
  });

  it("names the booking job in each trade's own word, and neutrally for anyone else", () => {
    const booking = JOBS.find((j) => j.id === "booking")!;
    expect(jobTitle(booking, examplesFor("clinic"))).toBe("Book appointments");
    expect(jobTitle(booking, examplesFor("real_estate"))).toBe("Book site visits");
    expect(jobTitle(booking, examplesFor("education"))).toBe("Book counselling sessions");
    expect(jobTitle(booking, examplesFor("insurance"))).toBe("Book meetings");
    for (const v of ["custom", undefined, "something-new"]) {
      expect(jobTitle(booking, examplesFor(v))).toBe("Take bookings");
    }
  });

  it("adds minutes to an India-time picker value without a time-zone shift", () => {
    expect(addMinutesLocal("2026-10-14T23:30", 60)).toBe("2026-10-15T00:30");
  });
});

const GOOGLE: IntegrationCredential = {
  id: "cred-gcal",
  kind: "google_calendar",
  label: "sri@example.in",
  last_four: "e.in",
  non_secret: null,
  version: 1,
  created_at: "2026-09-01T04:00:00Z",
  updated_at: "2026-09-01T04:00:00Z",
};

const EMPTY: ActionsSettings = { api_actions_enabled: false, calendar_available: true, tools: [] };

function Panel() {
  const session = useClientSession();
  return <Actions agentId="agent-1" session={session} />;
}

describe("turning on booking", () => {
  it("asks for a job first, then makes both calendar tools and switches actions on", async () => {
    const { calls } = await renderClientPage(<Panel />, {
      "/v1/me": OWNER_ME,
      "/v1/agents/agent-1/actions": EMPTY,
      "/v1/integrations/credentials": [GOOGLE],
      "/v1/integrations/connections/status": {
        google_calendar: true,
        google_sheets: false,
        zoho_crm: false,
        hubspot: false,
        sheets_share_with: null,
      },
      "POST /v1/agents/agent-1/actions": {},
      "PUT /v1/agents/agent-1/actions/enabled": { ...EMPTY, api_actions_enabled: true },
    });

    // No name field, no trigger select and no parameter rows on the way in.
    fireEvent.click(await screen.findByRole("button", { name: /take bookings/i }));
    expect(await screen.findByText("Google · sri@example.in")).toBeTruthy();
    expect(screen.queryByLabelText(/^Name/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Turn on booking" }));

    await waitFor(() =>
      expect(calls.some((c) => c.method === "PUT" && c.path.endsWith("/actions/enabled"))).toBe(true),
    );
    const posted = calls
      .filter((c) => c.method === "POST")
      .map((c) => JSON.parse(c.body ?? "{}") as { name: string; config: { operation: string } });
    expect(posted.map((b) => [b.name, b.config.operation])).toEqual([
      ["find_free_times", "check"],
      ["book_the_time", "book"],
    ]);
  });
});

function calendarTool(id: string, name: string, operation: "check" | "book"): ActionTool {
  return {
    id,
    agent_id: "agent-1",
    kind: "calendar",
    name,
    description: "Only offer and book times between 9 am and 6 pm India time on Mon to Sat.",
    trigger: "during_call",
    enabled: true,
    params: [],
    config: {
      operation,
      calendar_id: "primary",
      duration_min: 30,
      start_param: "start",
      end_param: "end",
      opens: "09:00",
      closes: "18:00",
      open_days: [1, 2, 3, 4, 5, 6],
    },
    credential_id: GOOGLE.id,
    pre_call_message: null,
    provider: "google",
  };
}

const WHATSAPP: ActionTool = {
  id: "tool-wa",
  agent_id: "agent-1",
  kind: "whatsapp",
  name: "send_whatsapp",
  description: "Send this message once the caller asks for it on WhatsApp.",
  trigger: "during_call",
  enabled: false,
  params: [],
  config: { template: "", language: "en" },
  credential_id: null,
  pre_call_message: null,
  provider: "aisensy",
};

const SET_UP: ActionsSettings = {
  api_actions_enabled: true,
  calendar_available: true,
  tools: [calendarTool("tool-check", "find_free_times", "check"), calendarTool("tool-book", "book_the_time", "book"), WHATSAPP],
};

function setUpRoutes() {
  return {
    "/v1/me": OWNER_ME,
    "/v1/agents/agent-1/actions": SET_UP,
    "/v1/integrations/credentials": [GOOGLE],
    "/v1/integrations/connections/status": {
      google_calendar: true,
      google_sheets: false,
      zoho_crm: false,
      hubspot: false,
      sheets_share_with: null,
    },
  };
}

describe("every action is a peer (founder, 10 Oct 2026)", () => {
  it("lists booking and every other set-up action as equal rows, with nothing expanded", async () => {
    await renderClientPage(<Panel />, setUpRoutes());

    const onAgent = (await screen.findByRole("heading", { name: "On this agent" })).closest("section")!;
    const rows = Array.from(onAgent.querySelectorAll("li"));
    expect(rows.map((li) => li.querySelector("p")?.textContent)).toEqual([
      "Take bookings",
      "Send a WhatsApp messageNot connected",
    ]);
    // Each row: its own switch and its own way in. Booking's settings are not on the overview.
    expect(screen.getByRole("switch", { name: "Take bookings" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Send a WhatsApp message" })).toBeTruthy();
    expect(screen.getByText("Google · sri@example.in · 9 am – 6 pm · Mon – Sat")).toBeTruthy();
    expect(screen.queryByText("Calendar")).toBeNull();
    expect(screen.queryByText("Try it")).toBeNull();
  });

  it("offers only what is not set up, in its own order rather than booking first", async () => {
    await renderClientPage(<Panel />, setUpRoutes());
    const chooser = await screen.findByRole("list", { name: "Things your agent can do" });
    const offered = Array.from(chooser.querySelectorAll("button .font-medium")).map((t) => t.textContent);
    expect(offered).toEqual([
      "Know who is calling",
      "Send a payment link",
      "Save callers to your CRM",
      "Write callers into a Google Sheet",
      "Use your own API",
    ]);
    expect(JOBS.map((j) => j.id)).toEqual([
      "caller_lookup",
      "booking",
      "whatsapp",
      "payment_link",
      "crm",
      "sheets",
      "custom_api",
    ]);
  });

  it("opens booking into its own view with its settings and a safe test, and comes back", async () => {
    await renderClientPage(<Panel />, setUpRoutes());
    fireEvent.click(await screen.findByRole("button", { name: "Manage Take bookings" }));

    expect(await screen.findByRole("heading", { name: "Take bookings" })).toBeTruthy();
    for (const label of ["Calendar", "Length", "Hours", "Days"]) expect(screen.getByText(label)).toBeTruthy();
    expect(screen.getByText("9 am – 6 pm")).toBeTruthy();
    expect(screen.getByText("Mon – Sat")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Check this time" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "← All actions" }));
    expect(await screen.findByRole("heading", { name: "On this agent" })).toBeTruthy();
  });

  it("opens WhatsApp into the same kind of view, saying what is wrong", async () => {
    await renderClientPage(<Panel />, { ...setUpRoutes(), "/v1/agents/agent-1/actions/tool-wa/log": [] });
    fireEvent.click(await screen.findByRole("button", { name: "Manage Send a WhatsApp message" }));

    expect(await screen.findByRole("heading", { name: "Send a WhatsApp message" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "← All actions" })).toBeTruthy();
    expect(screen.getByText(/Not connected\. Your agent cannot do this until it is fixed/)).toBeTruthy();
    expect(screen.getByText("Try it")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove send_whatsapp" })).toBeTruthy();
  });
});
