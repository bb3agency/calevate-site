import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PipNotes } from "@/app/c/[slug]/PipNotes";
import { useClientRealm } from "@/lib/api/session";
import type { CopilotNote, CopilotNotes } from "@/lib/copilot/notes";

import { problem, renderClientPage } from "./harness";

/**
 * D-936: what Pip noticed, with the dashboard's notices (founder, 9 Nov 2026: Pip's panel
 * opens on one question, so its notes moved here).
 *
 * - Each note is one line and one button, and can be put away.
 * - Linked items (the attention queue's and the healer's, said in Pip's voice) are not shown:
 *   the dashboard already says them.
 * - `open` hands the route TEMPLATE on, `ask` hands the words on and never sends.
 * - Showing the notes marks them seen once; pressing a note records it.
 * - Two notes show, the rest behind "Show N more".
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

const RUNWAY = note({
  id: "0192f0aa-7777-7000-8000-000000000003",
  kind: "credit_runway",
  line: "Your credit may run out in 4 days.",
  button: { kind: "open", label: "Add credit", screen: "Credits & billing", route: "/c/{slug}/billing", prompt: null },
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
  return <PipNotes session={realm.session} onOpen={props.onOpen} onAsk={props.onAsk} />;
}

describe("Pip's notes on the dashboard", () => {
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

  it("puts a note away, and leaves out the items this screen already shows", async () => {
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

    await screen.findByText(note().line);
    expect(screen.queryByText(LINKED.line)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: `Dismiss: ${note().line}` }));
    await waitFor(() => expect(screen.queryByText(note().line)).toBeNull());
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/dismiss"))).toBe(true);
    expect(calls.some((c) => c.path === "/v1/copilot/notes/seen")).toBe(false);
  });

  it("shows two notes and the rest behind Show more", async () => {
    await renderClientPage(<Harnessed onOpen={vi.fn()} onAsk={vi.fn()} />, {
      "GET /v1/copilot/notes": { notes: [note({ unread: false }), WEEK, RUNWAY, LINKED], unread: 0 },
    });

    await screen.findByText(WEEK.line);
    expect(screen.queryByText(RUNWAY.line)).toBeNull();
    const more = screen.getByRole("button", { name: "Show 1 more" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(more);
    expect(screen.getByText(RUNWAY.line)).toBeTruthy();
    expect(screen.queryByText(LINKED.line)).toBeNull();
  });

  it("renders nothing when Pip has noticed nothing of its own", async () => {
    const { container } = await renderClientPage(<Harnessed onOpen={vi.fn()} onAsk={vi.fn()} />, {
      "GET /v1/copilot/notes": { notes: [LINKED], unread: 0 },
    });
    await waitFor(() => expect(container.querySelector("section")).toBeNull());
  });

  it("says so when the notes could not be read, rather than showing nothing", async () => {
    await renderClientPage(<Harnessed onOpen={vi.fn()} onAsk={vi.fn()} />, {
      "GET /v1/copilot/notes": problem(503, { title: "Unavailable", status: 503 }),
    });
    expect(await screen.findByText(/Could not check what/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});
