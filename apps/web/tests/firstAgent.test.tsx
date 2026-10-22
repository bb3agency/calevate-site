import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import FirstAgentPage from "@/app/c/[slug]/agents/first/page";
import { chooseDoor } from "@/app/c/[slug]/agents/first/FirstAgentScreen";
import type { Agent } from "@/lib/api/agents";
import {
  GREETING_MAX_CHARS,
  firstAgentOf,
  greetingFits,
  nextPiece,
  piecesOf,
  quickRepliesFor,
} from "@/lib/firstAgent";

import { OWNER_ME, agentRow } from "./fixtures/sharedReads";
import { renderClientPage } from "./harness";

/**
 * BUILD YOUR FIRST AGENT (D-854): two doors, Pip's chat beside a card that fills in from the
 * server's rows, progress that starts above zero, and the agent ringing the owner's phone.
 */

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replaced: [] as string[] }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/c/acme/agents/first",
  useSearchParams: () => nav.params,
  useRouter: () => ({
    push: vi.fn(),
    replace: (path: string) => nav.replaced.push(path),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

beforeEach(() => {
  nav.params = new URLSearchParams();
  nav.replaced = [];
});

const page = <FirstAgentPage params={Promise.resolve({ slug: "acme" })} />;

const PIP_ON = {
  status: "accepted",
  can_accept: true,
  can_withdraw: true,
  text: "Pip reads what you type.",
  text_sha256: "a".repeat(64),
  version: 1,
  accepted_at: "2026-10-22T05:00:00Z",
  withdrawn_at: null,
};

const TRIAL = {
  on_trial: true,
  status: "active",
  days_remaining: 7,
  ends_at: "2026-10-29T00:00:00Z",
  free_minutes: 15,
  minutes_used: "0",
  minutes_left: "15",
  calls_today: 0,
  daily_cap: 5,
  can_call: true,
  blocked_reason: null,
  max_call_seconds: 180,
  pledge_accepted: false,
};

const NO_FACTS = { facts: [], facts_state: "none", items: [], pinned_not_yet_on: [] };

const FIELDS: Agent["extraction_fields"] = [
  { key: "budget", label: "Budget", type: "text", required: false, reason: "", enum_values: null },
];

function building(over: Partial<Agent> = {}): Agent {
  return agentRow({
    id: "0192f3a4-0000-7000-8000-00000000a001",
    name: "Front desk",
    status: "draft",
    published: false,
    engine_voice_id: null,
    script_opening_line: "Namaskaram, Lakeview Properties. How can I help you today?",
    extraction_fields: FIELDS,
    ...over,
  });
}

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": OWNER_ME,
    "/v1/agents": [],
    "/v1/kb/knows": NO_FACTS,
    "/v1/copilot/consent": PIP_ON,
    "/v1/copilot/conversation?limit=50": { turns: [], has_more: false, consent: PIP_ON },
    "/v1/trial": TRIAL,
    "/v1/agents/engine-catalogue": { available: true, voices: [], models: [] },
    ...over,
  };
}

describe("the pieces, from the server's rows", () => {
  it("starts above zero, with only the account done", () => {
    const pieces = piecesOf({ agent: null, answers: [], calls: undefined });
    expect(pieces.filter((piece) => piece.done).map((piece) => piece.id)).toEqual(["account"]);
    expect(nextPiece(pieces)?.id).toBe("job");
  });

  it("counts a short greeting that ends on a question, in characters a person counts", () => {
    expect(greetingFits("Namaskaram! How can I help?")).toBe(true);
    expect(greetingFits("Namaskaram, how can I help.")).toBe(false);
    expect(greetingFits(`${"అ".repeat(GREETING_MAX_CHARS - 1)}?`)).toBe(true);
    expect(greetingFits(`${"a".repeat(GREETING_MAX_CHARS)}?`)).toBe(false);
  });

  it("follows the newest working agent unless the address names one", () => {
    const older = building({ id: "0192f3a4-0000-7000-8000-000000000001" });
    const newer = building({ id: "0192f3a4-0000-7000-8000-000000000009" });
    const gone = building({ id: "0192f3a4-0000-7000-8000-00000000000f", status: "archived" });
    expect(firstAgentOf([older, newer, gone], null)?.id).toBe(newer.id);
    expect(firstAgentOf([older, newer], older.id)?.id).toBe(older.id);
    expect(firstAgentOf([], null)).toBeNull();
  });

  it("offers one-tap answers for the piece Pip is on", () => {
    expect(quickRepliesFor("job")).toEqual(["Answer my calls", "Call my leads", "Both"]);
    expect(quickRepliesFor(null)).toEqual([]);
  });

  it("keeps the greeting ceiling the server's guide names", () => {
    const guide = readFileSync(resolve(__dirname, "../../api/copilot/screen_guides.py"), "utf8");
    expect(guide).toMatch(new RegExp(`FIRST_GREETING_MAX_CHARS: Final = ${GREETING_MAX_CHARS}\\b`));
  });

  it("opens Pip once an agent exists, and only the hand-built door when Pip cannot run", () => {
    expect(chooseDoor(null, false, false)).toBeNull();
    expect(chooseDoor(null, false, true)).toBe("pip");
    expect(chooseDoor("manual", false, true)).toBe("manual");
    expect(chooseDoor("pip", true, false)).toBe("manual");
    expect(chooseDoor(null, true, false)).toBeNull();
  });
});

describe("build your first agent", () => {
  it("offers Pip first and the manual door beside it, with the meter at one of nine", async () => {
    await renderClientPage(page, routes());
    expect(await screen.findByRole("button", { name: /Build it with Pip/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /I'll set it up myself/ })).toBeTruthy();
    expect(screen.getByText("Account created · 1 of 9 done")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Build it with Pip/ }));
    expect(nav.replaced.at(-1)).toContain("with=pip");
  });

  it("opens the chat with Pip's first question and the answers to it as one tap", async () => {
    nav.params = new URLSearchParams("with=pip");
    await renderClientPage(page, routes());
    expect(await screen.findByText(/First, what should it do/)).toBeTruthy();
    const replies = screen.getByRole("list", { name: "Quick answers" });
    expect(within(replies).getByRole("button", { name: "Answer my calls" })).toBeTruthy();
    // The card is there before anything is built, with the business's own example.
    expect(screen.getByRole("heading", { name: "Your agent" })).toBeTruthy();
  });

  it("sends a member who cannot turn Pip on to the hand-built door, with the reason", async () => {
    const locked = { ...PIP_ON, status: "required", can_accept: false, accepted_at: null };
    await renderClientPage(
      page,
      routes({
        "/v1/me": { ...OWNER_ME, role: "admin" },
        "/v1/copilot/consent": locked,
        "/v1/copilot/conversation?limit=50": { turns: [], has_more: false, consent: locked },
      }),
    );
    const pip = await screen.findByRole("button", { name: /Build it with Pip/ });
    expect((pip as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/off for this account until its owner turns it on/)).toBeTruthy();
  });

  it("refuses a member who may not build agents, in the console's own words", async () => {
    await renderClientPage(page, routes({ "/v1/me": { ...OWNER_ME, role: "staff", permissions: ["agents:read"] } }));
    expect(await screen.findByText(/cannot build an agent|build an agent/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Build it with Pip/ })).toBeNull();
  });

  it("resumes on the card from the server's rows, with the greeting counted", async () => {
    const agent = building();
    await renderClientPage(
      page,
      routes({
        "/v1/agents": [agent],
        [`/v1/calls?agent_id=${agent.id}&limit=1`]: [],
        "/v1/kb/knows": {
          ...NO_FACTS,
          facts: [
            {
              id: "f1",
              text: "No, Monday to Saturday.",
              question: "Open on Sundays?",
              pinned: true,
              origin: "taught",
              created_at: "2026-10-22T05:00:00Z",
            },
          ],
        },
      }),
    );
    expect(await screen.findByRole("heading", { name: "Front desk" })).toBeTruthy();
    expect(screen.getByText("Answers your calls")).toBeTruthy();
    expect(screen.getByText(/of 120 characters/)).toBeTruthy();
    expect(screen.getByText("Open on Sundays?")).toBeTruthy();
    expect(screen.getByText("2 more to go")).toBeTruthy();
    // account, job, name, greeting and notes are done; voice, questions, ready and call are not.
    expect(screen.getByText("5 of 9 done")).toBeTruthy();
  });

  it("gets a draft ready, then rings the number, from one press", async () => {
    const agent = building();
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/agents": [agent],
        [`/v1/calls?agent_id=${agent.id}&limit=1`]: [],
        [`POST /v1/agents/${agent.id}/prepare`]: { status: "draft", changed: true, numbers_released: 0 },
        "POST /v1/trial/calls": { status: "queued", call_handle: "h1", blocked_reason: null, blocked_rule: null },
      }),
    );
    const input = await screen.findByPlaceholderText("+91 98765 43210");
    fireEvent.change(input, { target: { value: "+91 98765 43210" } });
    fireEvent.click(screen.getByRole("button", { name: /Call me/ }));
    expect(await screen.findByText("Ringing your phone…")).toBeTruthy();
    const posts = calls.filter((call) => call.method === "POST").map((call) => call.path);
    expect(posts).toEqual([`/v1/agents/${agent.id}/prepare`, "/v1/trial/calls"]);
    await waitFor(() => expect(calls.some((call) => call.path === "/v1/trial" && call.method === "GET")).toBe(true));
  });

  it("shows the trial line's refusal in the server's words", async () => {
    const agent = building({ published: true, status: "draft" });
    await renderClientPage(
      page,
      routes({
        "/v1/agents": [agent],
        [`/v1/calls?agent_id=${agent.id}&limit=1`]: [],
        "/v1/trial": { ...TRIAL, can_call: false, blocked_reason: "You have used today's test calls." },
      }),
    );
    expect(await screen.findByText("You have used today's test calls.")).toBeTruthy();
    expect((screen.getByRole("button", { name: /Call me/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});
