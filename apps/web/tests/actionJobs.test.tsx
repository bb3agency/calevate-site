import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Actions } from "@/app/c/[slug]/agents/actions/Actions";
import {
  addMinutesLocal,
  bookingParts,
  bookingTools,
  readBooking,
  readHours,
  uniqueName,
} from "@/app/c/[slug]/agents/actions/jobs";
import type { ActionTool, ActionsSettings, IntegrationCredential } from "@/lib/api/actions";
import { useClientSession } from "@/lib/api/session";

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
      { credentialId: "cred-1", durationMin: 60, from: 9, to: 18, calendarId: "primary" },
      { check: "find_free_times", book: "book_the_time" },
    );
    // check needs a start AND an end parameter; book needs a start and a duration.
    expect(check.config).toMatchObject({ operation: "check", start_param: "start", end_param: "end", duration_min: 60 });
    expect(book.config).toMatchObject({ operation: "book", start_param: "start", duration_min: 60, summary_param: "summary" });
    expect(check.params?.map((p) => p.name)).toEqual(["start", "end"]);
    expect(book.params?.map((p) => p.name)).toEqual(["start", "summary"]);
    expect(check.credential_id).toBe("cred-1");
    // The hours travel in what the agent is told, and read back out.
    expect(readHours(book.description)).toEqual({ from: 9, to: 18 });
  });

  it("reads a booking job's settings back from its tools", () => {
    const { check, book } = bookingTools(
      { credentialId: "cred-1", durationMin: 30, from: 10, to: 13, calendarId: "front-desk" },
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
      calendarId: "front-desk",
    });
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
    fireEvent.click(await screen.findByRole("button", { name: /book appointments/i }));
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
