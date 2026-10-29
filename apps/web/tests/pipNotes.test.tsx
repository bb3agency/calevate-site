import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PipNotes } from "@/components/copilot/PipNotes";
import { useClientRealm } from "@/lib/api/session";
import { launcherCount, type CopilotNote, type CopilotNotes } from "@/lib/copilot/notes";

import { problem, renderClientPage } from "./harness";

/**
 * D-936: what Pip noticed, at the top of its panel.
 *
 * - Each note is one line and one button; Pip's own notes can be put away, linked items
 *   (another screen's) cannot.
 * - `open` hands the route TEMPLATE to the dock, `ask` prefills and never sends.
 * - Opening the panel marks the notes seen once; pressing a note records it.
 * - Two notes show, the rest behind "Show N more".
 * - The launcher's count is Pip's own unseen notes only.
 */

function note(over: Partial<CopilotNote> = {}): CopilotNote {
  return {
    id: "0192f0aa-7777-7000-8000-000000000001",
    kind: "hot_lead_waiting",
    source: "pip",
    tone: "warning",
    line: "2 hot leads have waited over 4 hours for a call back.",
    button: { kind: "open", label: "Open leads", screen: "Leads", route: "/c/{slug}/leads", prompt: null },
    created_at: "2026-10-29T06:00:00Z",
    unread: true,
    dismissible: true,
    ...over,
  };
}

const WEEK = note({
  id: "0192f0aa-7777-7000-8000-000000000002",
  kind: "good_week",
  tone: "success",
  line: "Good week: 40 calls and 9 new leads, both up on the week before.",
  button: {
    kind: "ask",
    label: "See the week",
    screen: null,
    route: null,
    prompt: "How did this week go compared with last week?",
  },
  unread: false,
});

const LINKED = note({
  id: "linked:campaign_stalled",
  kind: "campaign_stalled",
  source: "linked",
  line: "1 campaign has stopped calling.",
  button: { kind: "open", label: "See why", screen: "Needs attention", route: "/c/{slug}/attention", prompt: null },
  unread: false,
  dismissible: false,
});

function Harnessed(props: { onOpen: (d: { route: string; screen: string; where: string }) => void; onAsk: (p: string) => void }) {
  const realm = useClientRealm();
  return <PipNotes session={realm.session} realm="client" onOpen={props.onOpen} onAsk={props.onAsk} />;
}

describe("Pip's notes", () => {
  it("shows each note as a line and a button, marks them seen once, and records a press", async () => {
    const onOpen = vi.fn();
    const onAsk = vi.fn();
    const feed: CopilotNotes = { notes: [note(), WEEK], unread: 1 };
    const { calls } = await renderClientPage(<Harnessed onOpen={onOpen} onAsk={onAsk} />, {
      "GET /v1/copilot/notes": feed,
      "POST /v1/copilot/notes/seen": { ok: true },
      [`POST /v1/copilot/notes/${note().id}/acted`]: { ok: true },
      [`POST /v1/copilot/notes/${WEEK.id}/acted`]: { ok: true },
    });

    expect(await screen.findByText(note().line)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open leads" }));
    expect(onOpen).toHaveBeenCalledWith({ route: "/c/{slug}/leads", screen: "Leads", where: "Leads" });
    fireEvent.click(screen.getByRole("button", { name: "See the week" }));
    expect(onAsk).toHaveBeenCalledWith("How did this week go compared with last week?");

    await waitFor(() =>
      expect(calls.filter((c) => c.method === "POST" && c.path === "/v1/copilot/notes/seen")).toHaveLength(1),
    );
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/acted"))).toBe(true),
    );
  });

  it("puts Pip's own note away and offers no dismiss on a linked item", async () => {
    let dismissed = false;
    const { calls } = await renderClientPage(<Harnessed onOpen={vi.fn()} onAsk={vi.fn()} />, {
      get "GET /v1/copilot/notes"() {
        return { notes: dismissed ? [LINKED] : [note({ unread: false }), LINKED], unread: 0 };
      },
      get [`POST /v1/copilot/notes/${note().id}/dismiss`]() {
        dismissed = true;
        return { ok: true };
      },
    });

    await screen.findByText(LINKED.line);
    expect(screen.queryByRole("button", { name: `Dismiss: ${LINKED.line}` })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: `Dismiss: ${note().line}` }));
    await waitFor(() => expect(screen.queryByText(note().line)).toBeNull());
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/dismiss"))).toBe(true);
    expect(calls.some((c) => c.path === "/v1/copilot/notes/seen")).toBe(false);
  });

  it("shows two notes and the rest behind Show more", async () => {
    await renderClientPage(<Harnessed onOpen={vi.fn()} onAsk={vi.fn()} />, {
      "GET /v1/copilot/notes": { notes: [note({ unread: false }), WEEK, LINKED], unread: 0 },
    });

    await screen.findByText(WEEK.line);
    expect(screen.queryByText(LINKED.line)).toBeNull();
    const more = screen.getByRole("button", { name: "Show 1 more" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(more);
    expect(screen.getByText(LINKED.line)).toBeTruthy();
  });

  it("renders nothing when Pip has noticed nothing", async () => {
    const { container } = await renderClientPage(<Harnessed onOpen={vi.fn()} onAsk={vi.fn()} />, {
      "GET /v1/copilot/notes": { notes: [], unread: 0 },
    });
    await waitFor(() => expect(container.querySelector("section")).toBeNull());
  });

  it("says so when the notes could not be read, rather than showing nothing", async () => {
    await renderClientPage(<Harnessed onOpen={vi.fn()} onAsk={vi.fn()} />, {
      "GET /v1/copilot/notes": problem(503, { title: "Unavailable", status: 503 }),
    });
    expect((await screen.findByRole("alert")).textContent).toContain("Could not check what");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("counts only Pip's own unseen notes on the launcher", () => {
    expect(launcherCount(undefined)).toBe(0);
    expect(launcherCount({ notes: [note(), LINKED], unread: 1 })).toBe(1);
  });
});
