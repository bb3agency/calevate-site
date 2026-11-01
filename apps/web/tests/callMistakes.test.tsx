import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import CallMistakesPage from "@/app/admin/ops/call-mistakes/page";
import { CallMistakes } from "@/components/improvement/CallMistakes";
import type { Me } from "@/lib/api/client";
import {
  PLATFORM_MISTAKES_PATH,
  agentMistakesPath,
  mistakeFixedPath,
  type AgentMistake,
  type PlatformMistake,
} from "@/lib/api/callMistakes";

import { problem, renderAdminPage, renderClientPage, type Routes } from "./harness";

/**
 * Mistakes on real calls (D-949). The client card must word each state as ours to fix and
 * never ask the owner to act; the admin board must post a note and show the API's refusal.
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "calls:read", "org:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

function mistake(over: Partial<AgentMistake> = {}): AgentMistake {
  return {
    kind: "said_again",
    label: "Said the same line again",
    instead: "With no clear reply, ask once in other words, then offer the next step.",
    calls: 3,
    calls_since_fix: 0,
    last_seen_at: "2026-10-25T10:00:00Z",
    last_call_id: "call-9",
    fixed_at: null,
    state: "fixing",
    ...over,
  };
}

async function renderCard(items: AgentMistake[]) {
  return await renderClientPage(<CallMistakes agentId="agent-1" />, {
    "/v1/me": OWNER,
    [agentMistakesPath("agent-1")]: { items, window_days: 30 },
  });
}

describe("the Training tab's mistakes on real calls", () => {
  it("says so in one line when there were none", async () => {
    await renderCard([]);
    expect(await screen.findByText("No mistakes found on real calls in the last 30 days.")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Mistakes on real calls" })).toBeNull();
  });

  it("words each state as ours to fix, with the count and the last call", async () => {
    await renderCard([
      mistake({ kind: "said_again", state: "back", calls_since_fix: 2, fixed_at: "2026-10-20T10:00:00Z" }),
      mistake({ kind: "asked_again", label: "Asked the same question again, word for word", calls: 1 }),
      mistake({
        kind: "opened_again",
        label: "Greeted the caller again in the middle of the call",
        state: "fixed",
        fixed_at: "2026-10-20T10:00:00Z",
        last_call_id: "call-3",
      }),
    ]);
    const list = await screen.findByRole("list", { name: "Mistakes on real calls" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]!.textContent).toContain("3 calls in 30 days");
    expect(rows[0]!.textContent).toContain("Came back after our fix — we're on it");
    expect(rows[1]!.textContent).toContain("1 call in 30 days");
    expect(rows[1]!.textContent).toContain("We're fixing this");
    expect(rows[2]!.textContent).toContain("Fixed — not seen since 20 Oct 2026");
    expect(within(rows[2]!).getByRole("link", { name: "Hear the last one" }).getAttribute("href")).toBe(
      "/c/acme/calls/call-3",
    );
    // Nothing on the card asks the owner to fix it or to contact anyone.
    expect(list.textContent).not.toMatch(/contact|you can fix|fix it yourself/i);
  });

  it("keeps what it should do behind a tap", async () => {
    await renderCard([mistake()]);
    const toggle = await screen.findByRole("button", { name: "What it should do" });
    const advice = screen.getByText(/ask once in other words/);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(advice.hidden).toBe(true);
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(advice.hidden).toBe(false);
  });

  it("says the list did not load rather than showing an empty one", async () => {
    await renderClientPage(<CallMistakes agentId="agent-1" />, {
      "/v1/me": OWNER,
      [agentMistakesPath("agent-1")]: problem(500, { title: "Something went wrong" }),
    });
    expect((await screen.findByRole("alert")).textContent).toContain("Something went wrong");
    expect(screen.queryByText(/No mistakes found/)).toBeNull();
  });
});

const OPERATOR: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-00000000ad09",
  role: "superadmin",
  permissions: ["org:read", "ops:manage"],
};

function row(over: Partial<PlatformMistake> = {}): PlatformMistake {
  return {
    kind: "said_again",
    label: "Said the same line again",
    calls_7d: 4,
    calls_30d: 9,
    accounts_30d: 3,
    calls_since_fix: 0,
    last_seen_at: "2026-10-25T10:00:00Z",
    fixed_at: null,
    fix_note: null,
    state: "fixing",
    ...over,
  };
}

function adminRoutes(over: Routes = {}): Routes {
  return {
    [ADMIN_ME_PATH]: OPERATOR,
    [PLATFORM_MISTAKES_PATH]: {
      window_days: 30,
      items: [
        row({ state: "back", calls_since_fix: 2, fixed_at: "2026-10-20T10:00:00Z", fix_note: "Rephrase rule added." }),
        row({ kind: "wrong_language", label: "Answered in a different language from the caller", calls_7d: 1 }),
      ],
    },
    ...over,
  };
}

describe("Ops > Call mistakes", () => {
  it("lists each kind with its counts, state and fix note", async () => {
    renderAdminPage(<CallMistakesPage />, adminRoutes());
    const table = await screen.findByRole("table", { name: "Call mistakes by kind" });
    const back = within(table)
      .getAllByRole("row")
      .find((r) => (r.textContent ?? "").includes("Said the same line again"));
    expect(back?.textContent).toContain("Back after the fix");
    expect(back?.textContent).toContain("Rephrase rule added.");
    const open = within(table)
      .getAllByRole("row")
      .find((r) => (r.textContent ?? "").includes("different language"));
    expect(open?.textContent).toContain("Not fixed yet");
  });

  it("refuses a blank note in words, then posts the note and reads the board again", async () => {
    const { calls } = renderAdminPage(
      <CallMistakesPage />,
      adminRoutes({ [`POST ${mistakeFixedPath("wrong_language")}`]: { kind: "wrong_language", fixed_at: "2026-11-01T10:00:00Z" } }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Mark fixed: Answered in a different language from the caller" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Mark fixed" }));
    expect(await within(dialog).findByText("Write what changed.")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    const reads = calls.filter((c) => c.path === PLATFORM_MISTAKES_PATH).length;
    fireEvent.change(within(dialog).getByLabelText("What changed"), { target: { value: "  Reply-language rule tightened.  " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Mark fixed" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const sent = calls.find((c) => c.method === "POST");
    expect(sent?.path).toBe(mistakeFixedPath("wrong_language"));
    expect(JSON.parse(sent!.body!)).toEqual({ note: "Reply-language rule tightened." });
    await waitFor(() => expect(calls.filter((c) => c.path === PLATFORM_MISTAKES_PATH).length).toBeGreaterThan(reads));
  });

  it("shows the API's refusal and keeps the dialog open", async () => {
    renderAdminPage(
      <CallMistakesPage />,
      adminRoutes({
        [`POST ${mistakeFixedPath("said_again")}`]: problem(400, {
          code: "mistake_fix_note_missing",
          title: "Say what was fixed",
          detail: "A fix needs a note saying what changed.",
        }),
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Mark fixed: Said the same line again" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("What changed"), { target: { value: "x" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Mark fixed" }));
    expect(await within(dialog).findByText(/A fix needs a note saying what changed/)).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("refuses an admin without ops:manage in words", async () => {
    renderAdminPage(
      <CallMistakesPage />,
      adminRoutes({ [ADMIN_ME_PATH]: { ...OPERATOR, permissions: ["org:read"] } }),
    );
    expect(await screen.findByText(/does not have permission to read and mark the call mistakes/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
