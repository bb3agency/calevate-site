import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CallerContinuity } from "@/app/c/[slug]/agents/panels/callerContinuity";
import { roomLabel } from "@/app/c/[slug]/agents/panels/openingLineFix";
import { OpeningNotices } from "@/app/c/[slug]/agents/panels/openingNotices";
import { OpeningEditor, type ScriptExamples } from "@/app/c/[slug]/agents/[agentId]/script/ScriptSections";
import { EMPTY_SCRIPT } from "@/lib/api/script";
import type { Agent } from "@/lib/api/agents";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { problem, renderClientPage, type ApiCall } from "./harness";

/*
 * D-846: what an agent says first is the notices switched on and then its opening line, and
 * only so many characters can be said there. The screen counts the line against the room
 * the server measured, and a notice switch refused for want of room offers the fix in place.
 */

const OWNER = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["agents:read", "org:read", "org:manage"],
  impersonating: false,
  organization: { id: "o1", name: "Raghava Organics", slug: "acme", status: "active" },
};

const LONG = "a".repeat(180);

function agent(over: Partial<Agent> = {}): Agent {
  return {
    id: "agent-1",
    name: "Raghava Organics receptionist",
    direction: "inbound",
    status: "live",
    archived_at: null,
    language_primary: "te-IN",
    reply_languages: ["te-IN"],
    disclosure_line: "Idi Raghava Organics AI assistant.",
    ai_disclosure_line: "Idi Raghava Organics AI assistant.",
    ai_disclosure_enabled: false,
    recording_notice_line: "Ee call record avutundi.",
    recording_notice_enabled: false,
    caller_memory_notice_line: "Oka chinna note gurtu pettukuntanu.",
    caller_memory_enabled: false,
    opening_line: "",
    script_opening_line: LONG,
    first_words: LONG,
    greeting_budget: {
      limit: 200,
      opening_chars: 180,
      opening_room: 200,
      opening_room_with_ai_disclosure: 165,
      opening_room_with_recording_notice: 175,
      opening_room_with_caller_memory: 141,
    },
    truthful_answer_rule: "The agent always answers honestly when a caller asks.",
    engine: "thinnest",
    published: true,
    inbound_number_count: 1,
    extraction_fields: [],
    extraction_schema_version: 0,
    llm_tier: null,
    llm_tier_effective: "standard",
    llm_tier_label: "Standard",
    llm_tier_source: "platform",
    llm_surcharged: false,
    ...over,
  };
}

const NO_ROOM = problem(422, {
  type: "https://calevate.tech/problems/opening_line_too_long_for_notice",
  title: "Shorten the opening line to switch this on",
  detail:
    "Remembering callers adds a sentence your agent says at the start of every call, before its opening line, telling callers it keeps a short note. With it, what the agent says first would be 239 characters, and at most 200 can be spoken there. Nothing was changed.",
  remediation: "Shorten the agent's opening line by at least 39 characters, then switch this on again.",
  kind: "business_rule",
  retryable: false,
});

describe("the opening line's room (D-846)", () => {
  it("counts what is left, and how far over, the way the server counts", () => {
    expect(roomLabel("  Namaskaram  ", 12)).toEqual({ label: "2 characters left", over: false });
    expect(roomLabel("a".repeat(13), 12)).toEqual({ label: "1 character too long", over: true });
    // A code point is one character, as the server's len() counts it.
    expect(roomLabel("🙂", 1).over).toBe(false);
  });

  it("shows the room under the opening line in the script, and marks it when it is over", () => {
    const eg = { outboundPurpose: "" } as ScriptExamples;
    const opening = (line: string) => (
      <OpeningEditor
        script={{ ...EMPTY_SCRIPT, opening_line: line }}
        set={() => {}}
        direction="inbound"
        room={20}
        standardVariables={[]}
        eg={eg}
      />
    );
    const { rerender } = render(opening("Namaskaram"));
    expect(screen.getByText("10 characters left")).toBeTruthy();
    const box = screen.getByRole("textbox", { name: /Opening line/ });
    expect(box.getAttribute("aria-invalid")).toBeNull();

    rerender(opening("a".repeat(25)));
    expect(screen.getByText("5 characters too long")).toBeTruthy();
    expect(box.getAttribute("aria-invalid")).toBe("true");
    // The meter is part of the box's description, so the count is read with it.
    const meter = screen.getByRole("meter", { name: "Opening line length" });
    expect(box.getAttribute("aria-describedby")).toContain(meter.parentElement?.id ?? "missing");
  });

  it("refused for want of room, the memory switch offers the line to shorten, saves it, and switches on", async () => {
    let tries = 0;
    const { calls } = await renderClientPage(<CallerContinuity agent={agent()} />, {
      "/v1/me": OWNER,
      "PATCH /v1/agents/agent-1/caller-memory": () =>
        tries++ === 0
          ? NO_ROOM
          : {
              agent_id: "agent-1",
              enabled: true,
              opening_line: "Oka chinna note gurtu pettukuntanu.",
              engine_synced: true,
              unchanged: false,
              attested_at: null,
              attested_by_name: null,
            },
      "PUT /v1/agents/agent-1/script/opening-line": { opening_line: "Namaskaram", version: 7 },
    });

    fireEvent.click(screen.getByRole("switch", { name: /Remember callers/ }));
    expect(await screen.findByText(/Remembering callers adds a sentence/)).toBeTruthy();
    const box = screen.getByLabelText("Opening line") as HTMLTextAreaElement;
    expect(box.value).toBe(LONG);
    expect(screen.getByText("39 characters too long")).toBeTruthy();
    const save = screen.getByRole("button", { name: "Save and switch on" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);

    fireEvent.change(box, { target: { value: "Namaskaram" } });
    expect(screen.getByText("131 characters left")).toBeTruthy();
    fireEvent.click(save);

    await waitFor(() => expect(tries).toBe(2));
    const put = calls.find((c: ApiCall) => c.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ opening_line: "Namaskaram" });
    const patches = calls.filter((c: ApiCall) => c.method === "PATCH");
    expect(patches.map((c) => JSON.parse(c.body ?? "{}").enabled)).toEqual([true, true]);
    expect(calls.indexOf(put!)).toBeLessThan(calls.indexOf(patches[1]));
  });

  it("offers Pip to shorten it, prefilled with the room and never sent", async () => {
    const asked: AssistantRequest[] = [];
    function Listener() {
      useAssistantRequests((request) => asked.push(request));
      return null;
    }
    render(<Listener />);
    const { calls } = await renderClientPage(<CallerContinuity agent={agent()} />, {
      "/v1/me": OWNER,
      "PATCH /v1/agents/agent-1/caller-memory": NO_ROOM,
    });
    fireEvent.click(screen.getByRole("switch", { name: /Remember callers/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Ask Pip to shorten it/ }));
    expect(asked.map((a) => a.prompt)).toEqual([
      "Shorten the opening line of Raghava Organics receptionist to at most 141 characters, in the same language, keeping what it says.",
    ]);
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("refused for want of room, a notice switch offers the room that notice needs and retries it", async () => {
    let tries = 0;
    const { calls } = await renderClientPage(<OpeningNotices agent={agent()} />, {
      "/v1/me": OWNER,
      "PATCH /v1/agents/agent-1/disclosure": () =>
        tries++ === 0
          ? NO_ROOM
          : {
              agent_id: "agent-1",
              ai_disclosure_enabled: true,
              recording_notice_enabled: false,
              opening_line: "Idi Raghava Organics AI assistant.",
              engine_synced: true,
              changed: ["ai_disclosure_enabled"],
            },
      "PUT /v1/agents/agent-1/script/opening-line": { opening_line: "Namaskaram", version: 7 },
    });

    const aiSwitch = screen.getByRole("switch", { name: /Say it is an AI assistant/ }) as HTMLInputElement;
    // Enabled once the screen has read who is looking (`org:manage`).
    await waitFor(() => expect(aiSwitch.disabled).toBe(false));
    fireEvent.click(aiSwitch);
    await screen.findByRole("button", { name: "Save and switch on" });
    // The AI notice's room, not the memory sentence's.
    expect(screen.getByText("15 characters too long")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Opening line"), { target: { value: "Namaskaram" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and switch on" }));
    await waitFor(() => expect(tries).toBe(2));
    const patches = calls.filter((c: ApiCall) => c.method === "PATCH");
    expect(patches.map((c) => JSON.parse(c.body ?? "{}"))).toEqual([
      { ai_disclosure_enabled: true },
      { ai_disclosure_enabled: true },
    ]);
  });
});
