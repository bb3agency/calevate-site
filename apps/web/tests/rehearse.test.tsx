import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RehearseDock } from "@/app/c/[slug]/agents/[agentId]/script/RehearseDock";
import { fixInstruction } from "@/components/rehearse/rehearseModel";
import type { Me } from "@/lib/api/client";
import { useClientRealm } from "@/lib/api/session";

import { renderClientPage } from "./harness";

/**
 * Rehearse (W3.2) and What it is told (W3.15) on a campaign's Script tab. Each test names the
 * failure it guards: a tool shown as if it ran, a flagged reply with no way to fix it, a
 * conversation that loses its session, and a view that is not the server's text.
 */

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "leads:read", "leads:dispatch"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const SCRIPT = { schema_version: 2, opening_line: "Namaste.", stages: [] };

function Dock({ onFix }: { onFix?: (instruction: string) => void }) {
  const { session } = useClientRealm();
  return (
    <RehearseDock
      session={session}
      holder={{ kind: "campaign", id: "camp-1" }}
      script={SCRIPT}
      canWrite
      onFix={onFix}
    />
  );
}

const TWO_TOOLS = {
  session: "s-1",
  reply: "Open the Play Store and then search for Rytu Khata.",
  cut_short: false,
  runs: "saved",
  cost_note: "Nothing here calls anyone.",
  actions: [
    { said: "Would book a call-back for 5 PM on 3 Dec", ran: false },
    { said: "Looked up what you taught it", ran: true },
  ],
  flags: [{ kind: "several_actions", reason: "It gave two things to do in one turn.", in_script: true }],
};

describe("Rehearse", () => {
  it("shows every tool in the owner's words, marks what did not run, and offers the fix", async () => {
    const onFix = vi.fn();
    const { calls } = await renderClientPage(<Dock onFix={onFix} />, {
      "/v1/me": ME,
      "POST /v1/campaigns/camp-1/rehearse": TWO_TOOLS,
    });
    fireEvent.click(await screen.findByRole("button", { name: "Rehearse" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("What the caller says"), { target: { value: "Hello?" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));

    expect(await within(dialog).findByText(TWO_TOOLS.reply)).toBeTruthy();
    const did = within(dialog).getByRole("list", { name: "What it did" });
    const rows = within(did).getAllByRole("listitem");
    expect(rows[0]?.textContent).toContain("Would book a call-back for 5 PM on 3 Dec");
    expect(rows[0]?.textContent).toContain("not run");
    // A lookup reaches nobody, so it really ran and is not marked.
    expect(rows[1]?.textContent).not.toContain("not run");
    expect(within(dialog).getByText("It gave two things to do in one turn.")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Fix this in the script" }));
    expect(onFix).toHaveBeenCalledWith(
      fixInstruction(TWO_TOOLS.flags[0]!, "Hello?", TWO_TOOLS.reply),
    );
    const sent = JSON.parse(calls.find((c) => c.path === "/v1/campaigns/camp-1/rehearse")?.body ?? "{}");
    expect(sent).toEqual({ message: "Hello?", session: null });
  });

  it("keeps the conversation when closed and opened again, and goes on with its session", async () => {
    const { calls } = await renderClientPage(<Dock />, {
      "/v1/me": ME,
      "POST /v1/campaigns/camp-1/rehearse": { ...TWO_TOOLS, flags: [], actions: [] },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Rehearse" }));
    let dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("What the caller says"), { target: { value: "Hello?" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    expect(await within(dialog).findByText(TWO_TOOLS.reply)).toBeTruthy();
    // No fix offered where nothing was flagged.
    expect(within(dialog).queryByRole("button", { name: "Fix this in the script" })).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Rehearse" }));
    dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(TWO_TOOLS.reply)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("What the caller says"), { target: { value: "Price?" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/v1/campaigns/camp-1/rehearse")).toHaveLength(2));
    const second = JSON.parse(calls.filter((c) => c.path === "/v1/campaigns/camp-1/rehearse")[1]?.body ?? "{}");
    expect(second).toEqual({ message: "Price?", session: "s-1" });
  });

  it("shows what the agent is told as the server gives it", async () => {
    await renderClientPage(<Dock />, {
      "/v1/me": ME,
      "GET /v1/campaigns/camp-1/script/told": { told: "[GOAL]\nThe farmer books a soil test." },
    });
    fireEvent.click(await screen.findByRole("button", { name: "What it is told" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/The farmer books a soil test\./)).toBeTruthy();
  });
});

describe("fixInstruction", () => {
  it("quotes the caller and the reply and keeps under the ask's limit", () => {
    const flag = { kind: "several_actions", reason: "Two things at once.", in_script: true };
    const text = fixInstruction(flag, "Hi", "x".repeat(2000));
    expect(text.length).toBeLessThanOrEqual(1000);
    expect(text).toContain('the caller said "Hi"');
    expect(text).toContain("Two things at once.");
  });
});
