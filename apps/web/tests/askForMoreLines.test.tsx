import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AskForMoreLines } from "@/components/callLines/AskForMoreLines";
import type { CallLineRequest, MyCallLines } from "@/lib/api/callLines";
import { useClientRealm } from "@/lib/api/session";

import { problem, renderClientPage } from "./harness";

/**
 * "Need more? Ask us." on the client's Calls at once tile: a button that sends a request,
 * then the request's state where the button was, and no button for someone who may not ask.
 */

const OWNER = { user_id: "u1", tenant_id: "t1", role: "owner", permissions: ["org:read", "org:manage"], impersonating: false };
const STAFF = { ...OWNER, role: "staff", permissions: ["org:read"] };

function lines(over: Partial<MyCallLines> = {}): MyCallLines {
  return { call_lines: 2, in_progress: 0, on_trial: false, max_lines: 50, request: null, ...over };
}

function asked(over: Partial<CallLineRequest> = {}): CallLineRequest {
  return {
    id: "r1",
    status: "open",
    lines_at_request: 2,
    wanted_lines: 4,
    created_at: "2026-11-05T06:30:00Z",
    resolved_at: null,
    lines_granted: null,
    decline_reason: null,
    ...over,
  };
}

function Tile() {
  const { session } = useClientRealm();
  return <AskForMoreLines session={session} />;
}

describe("asking for more calls at once", () => {
  it("sends the number and note, then says it was asked", async () => {
    const { calls } = await renderClientPage(<Tile />, {
      "/v1/me": OWNER,
      "/v1/call-lines": lines(),
      "POST /v1/call-lines/requests": asked(),
    });
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Need more? Ask us." }));
    });
    const dialog = await screen.findByRole("dialog", { name: "Ask for more calls at once" });
    expect(dialog.textContent).toContain("You have 2 calls at once.");
    const box = screen.getByRole("spinbutton", { name: "How many at once" });
    fireEvent.change(box, { target: { value: "4" } });
    fireEvent.blur(box);
    fireEvent.change(screen.getByRole("textbox", { name: /Anything we should know/ }), {
      target: { value: "  Festival rush " },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "POST")?.body ?? "{}")).toEqual({
      wanted: 4,
      note: "Festival rush",
    });
    await screen.findByText(/Asked for 4 on .*We.ll let you know\./);
    expect(screen.queryByRole("button", { name: "Need more? Ask us." })).toBeNull();
  });

  it("shows an open request instead of a second button", async () => {
    await renderClientPage(<Tile />, { "/v1/me": OWNER, "/v1/call-lines": lines({ request: asked() }) });
    await screen.findByText(/Asked for 4 on/);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps the refusal inside the dialog", async () => {
    await renderClientPage(<Tile />, {
      "/v1/me": OWNER,
      "/v1/call-lines": lines(),
      "POST /v1/call-lines/requests": problem(409, {
        title: "We answered your last request today",
        detail: "You can ask again tomorrow.",
      }),
    });
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Need more? Ask us." }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
    });
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog.textContent).toContain("You can ask again tomorrow."));
  });

  it("disables the button with the reason for someone who may not ask", async () => {
    await renderClientPage(<Tile />, { "/v1/me": STAFF, "/v1/call-lines": lines() });
    const button = await screen.findByRole("button", { name: "Need more? Ask us." });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true));
    expect(button.getAttribute("aria-describedby")).toBeTruthy();
  });

  it("says what was decided and offers to ask again", async () => {
    await renderClientPage(<Tile />, {
      "/v1/me": OWNER,
      "/v1/call-lines": lines({
        call_lines: 4,
        request: asked({ status: "done", lines_granted: 4, resolved_at: "2026-11-05T08:00:00Z" }),
      }),
    });
    await screen.findByText("Raised to 4.");
    expect(screen.getByRole("button", { name: "Ask for more" })).toBeTruthy();
  });

  it("keeps the trial's sentence and offers no button", async () => {
    await renderClientPage(<Tile />, { "/v1/me": OWNER, "/v1/call-lines": lines({ call_lines: 1, on_trial: true }) });
    await screen.findByText("Trial: one line. More once you pay.");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
