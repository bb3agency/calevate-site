import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import CallMistakesPage from "@/app/admin/ops/call-mistakes/page";
import { CallMistakes } from "@/components/improvement/CallMistakes";
import type { Me } from "@/lib/api/client";
import {
  FLEET_FIXES_PATH,
  PLATFORM_MISTAKES_PATH,
  agentMistakesPath,
  mistakeFixedPath,
  mistakeUndoPath,
  type AgentMistake,
  type FleetFix,
  type PlatformMistake,
} from "@/lib/api/callMistakes";

import { problem, renderAdminPage, renderClientPage, stillLoading, type Routes } from "./harness";

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
    clean_calls: 0,
    clean_calls_needed: 5,
    can_undo: false,
    found_in_script: false,
    ...over,
  };
}

async function renderCard(items: AgentMistake[], extra: Routes = {}) {
  return await renderClientPage(<CallMistakes agentId="agent-1" />, {
    "/v1/me": OWNER,
    [agentMistakesPath("agent-1")]: { items, window_days: 30 },
    ...extra,
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
    expect(rows[0]!.textContent).toContain("Seen again after our fix on 20 Oct 2026 · our team has been told");
    expect(rows[1]!.textContent).toContain("1 call in 30 days");
    expect(rows[1]!.textContent).toContain("Not fixed yet · our team has been told");
    expect(rows[2]!.textContent).toContain("Fixed on 20 Oct 2026 · not seen since");
    expect(within(rows[2]!).getByRole("link", { name: "Hear the last one" }).getAttribute("href")).toBe(
      "/c/acme/calls/call-3",
    );
    // Nothing on the card asks the owner to fix it or to contact anyone.
    expect(list.textContent).not.toMatch(/contact|you can fix|fix it yourself/i);
  });

  it("words each script fix as what is true of the agent (D-985)", async () => {
    await renderCard([
      mistake({ kind: "a", label: "A", state: "script_rolled_back" }),
      mistake({ kind: "b", label: "B", state: "with_team" }),
      mistake({ kind: "c", label: "C", state: "script_fixing" }),
      mistake({ kind: "d", label: "D", state: "script_live", fixed_at: "2026-11-12T10:00:00Z", can_undo: true }),
      mistake({ kind: "e", label: "E", state: "script_undone" }),
      mistake({ kind: "f", label: "F", state: "script_fixed", clean_calls: 6, fixed_at: "2026-11-12T10:00:00Z" }),
    ]);
    const rows = within(await screen.findByRole("list", { name: "Mistakes on real calls" })).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Came back · we put your script back"),
      expect.stringContaining("Our team is fixing this"),
      expect.stringContaining("Fixing it in your script"),
      expect.stringContaining("Fixed in your script on 12 Nov 2026 · watching the next calls"),
      expect.stringContaining("You put your old script back"),
      expect.stringContaining("Fixed in your script · not seen in 6 calls"),
    ]);
    // Undo is offered only where the server says the fix can be undone.
    expect(within(rows[3]!).getByRole("button", { name: "Undo our fix: D" })).toBeTruthy();
    for (const row of [rows[0]!, rows[1]!, rows[2]!, rows[4]!, rows[5]!]) {
      expect(within(row).queryByRole("button", { name: /Undo/ })).toBeNull();
    }
  });

  it("says where a fix came from when no call showed the mistake (D-989)", async () => {
    await renderCard([
      mistake({
        state: "script_live",
        calls: 0,
        last_seen_at: null,
        last_call_id: null,
        found_in_script: true,
        fixed_at: "2026-11-13T10:00:00Z",
        can_undo: true,
      }),
    ]);
    const row = within(await screen.findByRole("list", { name: "Mistakes on real calls" })).getByRole("listitem");
    expect(row.textContent).toContain("Found in your script before any call");
    expect(row.textContent).not.toContain("0 calls");
    expect(within(row).queryByRole("link", { name: "Hear the last one" })).toBeNull();
    expect(within(row).getByRole("button", { name: "Undo our fix: Said the same line again" })).toBeTruthy();
  });

  it("undoes our fix and reads the list again", async () => {
    const { calls } = await renderCard(
      [mistake({ state: "script_live", fixed_at: "2026-11-12T10:00:00Z", can_undo: true })],
      { [`POST ${mistakeUndoPath("agent-1", "said_again")}`]: { kind: "said_again", version: 7 } },
    );
    const reads = () => calls.filter((c) => c.path === agentMistakesPath("agent-1")).length;
    const before = reads();
    fireEvent.click(await screen.findByRole("button", { name: "Undo our fix: Said the same line again" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.path).toBe(mistakeUndoPath("agent-1", "said_again"));
    await waitFor(() => expect(reads()).toBeGreaterThan(before));
  });

  it("shows why an undo was refused", async () => {
    await renderCard([mistake({ state: "script_fixed", can_undo: true })], {
      [`POST ${mistakeUndoPath("agent-1", "said_again")}`]: problem(409, {
        code: "mistake_fix_script_changed",
        title: "Your script changed after this fix, so it cannot be undone on its own.",
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Undo our fix: Said the same line again" }));
    expect((await screen.findByRole("alert")).textContent).toContain("cannot be undone on its own");
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
    fixed_by: null,
    state: "fixing",
    rule: 'HOW TO SPEAK: "Never re-ask what they said or repeat a sentence"',
    last_call_id: "call-9",
    last_client_slug: "rytu",
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
        row({
          kind: "wrong_language",
          label: "Answered in a different language from the caller",
          calls_7d: 1,
          rule: "",
          last_call_id: null,
          last_client_slug: null,
        }),
      ],
    },
    [FLEET_FIXES_PATH]: { window_days: 30, items: [] },
    ...over,
  };
}

function fleetFix(over: Partial<FleetFix> = {}): FleetFix {
  return {
    id: "fix-1",
    client_slug: "rytu",
    agent_id: "agent-1",
    agent_name: "Varsha",
    kind: "opened_again",
    label: "Greeted the caller again in the middle of the call",
    state: "live",
    ended_because: null,
    attempts: 1,
    version_before: 4,
    version_after: 5,
    live_at: "2026-11-12T10:00:00Z",
    settled_at: null,
    created_at: "2026-11-12T09:50:00Z",
    found_by: "call",
    ...over,
  };
}

describe("Ops > Call mistakes", () => {
  it("lists every agent's script fixes with where each stands (D-985)", async () => {
    renderAdminPage(
      <CallMistakesPage />,
      adminRoutes({
        [FLEET_FIXES_PATH]: {
          window_days: 30,
          items: [
            fleetFix(),
            fleetFix({
              id: "fix-2",
              agent_name: "Asha",
              state: "rolled_back",
              ended_because: "worse",
              attempts: 2,
              found_by: "script_check",
            }),
          ],
        },
      }),
    );
    const table = await screen.findByRole("table", { name: "Script fixes by agent" });
    const rows = within(table).getAllByRole("row");
    const live = rows.find((r) => (r.textContent ?? "").includes("Varsha"));
    expect(live?.textContent).toContain("Live, watching calls");
    expect(live?.textContent).toContain("v4 → v5");
    const back = rows.find((r) => (r.textContent ?? "").includes("Asha"));
    expect(back?.textContent).toContain("Put back");
    expect(back?.textContent).toContain("other mistakes rose");
    // What opened each fix (D-989).
    expect(live?.textContent).toContain("Seen on a call");
    expect(back?.textContent).toContain("Found in the script before any call");
  });

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
    expect(open?.textContent).toContain("No platform rule traced yet");
  });

  it("names where the fix goes and opens the latest call as that client", async () => {
    renderAdminPage(<CallMistakesPage />, adminRoutes());
    const table = await screen.findByRole("table", { name: "Call mistakes by kind" });
    expect(table.textContent).toContain('Fix in: HOW TO SPEAK: "Never re-ask what they said or repeat a sentence"');
    const link = within(table).getByRole("link", { name: "Open the latest call: Said the same line again" });
    expect(link.getAttribute("href")).toBe("/admin/view-as?slug=rytu&path=%2Fcalls%2Fcall-9");
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

  it("sends one note however often Enter is pressed while it is out", async () => {
    const { calls } = renderAdminPage(
      <CallMistakesPage />,
      adminRoutes({ [`POST ${mistakeFixedPath("said_again")}`]: stillLoading() }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Mark fixed: Said the same line again" }));
    const dialog = screen.getByRole("dialog");
    const note = within(dialog).getByLabelText("What changed");
    fireEvent.change(note, { target: { value: "Rephrase rule added." } });
    // The form has no submit button inside it, so Enter submits it directly.
    fireEvent.submit(note.closest("form")!);
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Mark fixed" }).getAttribute("aria-busy")).toBe("true"),
    );
    fireEvent.submit(note.closest("form")!);
    fireEvent.click(within(dialog).getByRole("button", { name: "Mark fixed" }));
    await new Promise((settle) => setTimeout(settle, 50));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
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
