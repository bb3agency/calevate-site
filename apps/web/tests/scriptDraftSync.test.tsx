import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import AgentScriptPage from "@/app/c/[slug]/agents/[agentId]/script/page";
import { reconcileDraft, saveState } from "@/app/c/[slug]/agents/[agentId]/script/scriptDraft";
import { liveScriptText } from "@/app/c/[slug]/agents/[agentId]/sections/scriptSection";
import type { Me } from "@/lib/api/client";
import { EMPTY_SCRIPT, type CallScript, type ScriptOut } from "@/lib/api/script";

import { problem, renderClientPage } from "./harness";
import { agentRow, settledPending } from "./fixtures/sharedReads";

/**
 * The builder autosaves a draft and follows the stored copy underneath it.
 *
 * It once took its copy ONCE, at mount, and saved that old text over a newer version. Now
 * the working copy follows every read, the autosave carries the `saved_at` it started from,
 * and a refusal (`script_changed_elsewhere`) keeps the owner's edits and offers both ways
 * out. Nothing reaches callers before "Put it live".
 */

const OWNER: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["agents:read", "org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Raghava Organics", slug: "acme", status: "active" },
};

const OLD = "Namaste!";
const NEW = "Namaste garu! Nenu Raghava Organics nundi call chestunnanu.";
const SAVED_AT = "2026-10-10T12:00:00.000001+00:00";

function out(opening: string, version: number | null, draft: { opening: string; at: string } | null = null): ScriptOut {
  return {
    script: { ...EMPTY_SCRIPT, opening_line: opening },
    draft: draft ? { script: { ...EMPTY_SCRIPT, opening_line: draft.opening }, saved_at: draft.at } : null,
    stored_schema_version: version === null ? null : 2,
    context: null,
    version,
    is_freeform: false,
    has_pending: false,
    standard_variables: [],
  };
}

const NO_TESTS = { available: false, unavailable_reason: "Not yet.", cost_note: "", latest: null };
const PREVIEW = { compiled: "", instructions_chars: 2000, instructions_limit: 8000, native_steps: 0 };
const page = <AgentScriptPage params={Promise.resolve({ slug: "acme", agentId: "agent-1" })} />;

function opening(): HTMLTextAreaElement {
  return screen.getByLabelText("Opening line") as HTMLTextAreaElement;
}

function client(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

const routes = (script: unknown, extra: Record<string, unknown> = {}) => ({
  "/v1/me": OWNER,
  "/v1/agents/agent-1": agentRow(),
  "/v1/agents/agent-1/script": script,
  "/v1/agents/agent-1/script/tests": NO_TESTS,
  "POST /v1/agents/agent-1/script/preview": PREVIEW,
  "/v1/agents/agent-1/script/proposed-rules": [],
  "/v1/agents/agent-1/pending": settledPending(),
  ...extra,
});

describe("the builder follows the stored draft", () => {
  it("opens the autosaved draft rather than the live script", async () => {
    await renderClientPage(page, routes(out(OLD, 3, { opening: NEW, at: SAVED_AT })));
    await waitFor(() => expect(opening().value).toBe(NEW));
    expect(await screen.findByRole("button", { name: "Put it live" })).toBeTruthy();
  });

  it("shows a newer draft that arrives while nothing is unsaved", async () => {
    let current = out(OLD, 3);
    const qc = client();
    await renderClientPage(page, routes(() => current), "acme", qc);
    await waitFor(() => expect(opening().value).toBe(OLD));
    expect(screen.queryByRole("button", { name: "Put it live" })).toBeNull();

    current = out(OLD, 3, { opening: NEW, at: SAVED_AT });
    await act(async () => {
      await qc.invalidateQueries();
    });
    await waitFor(() => expect(opening().value).toBe(NEW));
  });

  it("keeps unsaved edits when somebody else's draft arrives, and loads it on request", async () => {
    let current = out(OLD, 3);
    const qc = client();
    await renderClientPage(page, routes(() => current), "acme", qc);
    await waitFor(() => expect(opening().value).toBe(OLD));
    fireEvent.change(opening(), { target: { value: "My own edit" } });

    current = out(OLD, 3, { opening: NEW, at: SAVED_AT });
    await act(async () => {
      await qc.invalidateQueries();
    });
    expect(await screen.findByText("This draft was changed somewhere else")).toBeTruthy();
    expect(opening().value).toBe("My own edit");
    fireEvent.click(screen.getByRole("button", { name: "Load the newer draft" }));
    await waitFor(() => expect(opening().value).toBe(NEW));
  });
});

describe("the autosave", () => {
  it("saves a moment after typing stops, against the draft it started from", async () => {
    const { calls } = await renderClientPage(
      page,
      routes(out(OLD, 3, { opening: OLD, at: SAVED_AT }), {
        "PUT /v1/agents/agent-1/script/draft": { saved_at: "2026-10-10T12:05:00+00:00" },
      }),
    );
    await waitFor(() => expect(opening().value).toBe(OLD));
    fireEvent.change(opening(), { target: { value: NEW } });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true), { timeout: 4000 });
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.path).toBe("/v1/agents/agent-1/script/draft");
    const body = JSON.parse(put?.body ?? "{}");
    expect(body.base_saved_at).toBe(SAVED_AT);
    expect(body.script.opening_line).toBe(NEW);
    expect(await screen.findByText(/Draft saved/)).toBeTruthy();
    expect(opening().value).toBe(NEW);
  });

  it("on a refusal keeps the edits, says so, and Keep mine saves without the check", async () => {
    let refuse = true;
    const { calls } = await renderClientPage(
      page,
      routes(out(OLD, 3), {
        "PUT /v1/agents/agent-1/script/draft": () => {
          if (refuse) {
            refuse = false;
            return problem(409, {
              type: "urn:calevate:agents/script_changed_elsewhere",
              title: "We could not complete that",
              detail: "This draft was changed somewhere else after you opened it.",
            });
          }
          return { saved_at: "2026-10-10T12:06:00+00:00" };
        },
      }),
    );
    await waitFor(() => expect(opening().value).toBe(OLD));
    fireEvent.change(opening(), { target: { value: "mine" } });
    expect(await screen.findByText("This draft was changed somewhere else", {}, { timeout: 4000 })).toBeTruthy();
    expect(opening().value).toBe("mine");
    const first = JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}");
    expect(first).toHaveProperty("base_saved_at", null);

    fireEvent.click(screen.getByRole("button", { name: "Keep mine" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2));
    const second = JSON.parse(calls.filter((c) => c.method === "PUT")[1].body ?? "{}");
    expect(second).not.toHaveProperty("base_saved_at");
    await waitFor(() => expect(screen.queryByText("This draft was changed somewhere else")).toBeNull());
  });

  it("holds a draft the server would refuse and says what to finish", async () => {
    const { calls } = await renderClientPage(page, routes(out(OLD, 3)));
    await waitFor(() => expect(opening().value).toBe(OLD));
    // Writes wait for `/v1/me` (they fail closed), so the button appears once it answers.
    fireEvent.click(await screen.findByRole("button", { name: "Add a section" }));
    // A new section has a name and no instruction yet: the server would refuse it.
    expect(await screen.findByText(/Not saved yet: one part needs finishing/)).toBeTruthy();
    await new Promise((r) => setTimeout(r, 1500));
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });
});

describe("Put it live", () => {
  it("publishes the draft with a note and the version it was looking at", async () => {
    const { calls } = await renderClientPage(
      page,
      routes(out(OLD, 3, { opening: NEW, at: SAVED_AT }), {
        "POST /v1/agents/agent-1/script/publish": { version: 4, live: true },
      }),
    );
    const open = await screen.findByRole("button", { name: "Put it live" });
    await waitFor(() => expect(open.matches(":disabled")).toBe(false));
    fireEvent.click(open);
    const dialog = await screen.findByRole("dialog", { name: "Put these changes live?" });
    expect((screen.getByLabelText("What changed") as HTMLInputElement).value).toBe("Changed opening line");
    fireEvent.click(dialog.querySelectorAll("button")[1]);
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/publish"))).toBe(true));
    const body = JSON.parse(calls.find((c) => c.path.endsWith("/publish"))?.body ?? "{}");
    expect(body).toMatchObject({ summary: "Changed opening line", expected_version: 3 });
    expect(body.script.opening_line).toBe(NEW);
    expect(await screen.findByText("It is live")).toBeTruthy();
  });

  it("names the voice tier callers will hear it in", async () => {
    await renderClientPage(page, routes(out(OLD, 3, { opening: NEW, at: SAVED_AT })));
    const open = await screen.findByRole("button", { name: "Put it live" });
    await waitFor(() => expect(open.matches(":disabled")).toBe(false));
    fireEvent.click(open);
    expect(await screen.findByText("Voice: Clear voice · ₹2.50 / min")).toBeTruthy();
  });
});

describe("the list reorders the one model", () => {
  const two: CallScript = {
    ...EMPTY_SCRIPT,
    stages: [
      { id: "greet", name: "Greet", mode: "guide", instruction: "Say hello", sounds_like: "", branches: [], otherwise: "", collect: [], position: null },
      { id: "need", name: "Find the need", mode: "guide", instruction: "Ask", sounds_like: "", branches: [], otherwise: "", collect: [], position: null },
    ],
  };

  it("moves a section with the visible buttons and the handle's arrow keys, and announces it", async () => {
    await renderClientPage(page, routes({ ...out(OLD, 3), script: two }));
    const list = await screen.findByRole("list", { name: "Sections of the call, in order" });
    const names = () => Array.from(list.querySelectorAll(":scope > li")).map((li) => li.textContent ?? "");
    expect(names()[0]).toContain("Greet");
    fireEvent.click(await screen.findByRole("button", { name: "Move Find the need earlier" }));
    await waitFor(() => expect(names()[0]).toContain("Find the need"));
    expect(screen.getByText("Find the need moved to number 1 of 2.")).toBeTruthy();
    fireEvent.keyDown(screen.getByRole("button", { name: /^Move Find the need, number 1/ }), { key: "ArrowDown" });
    await waitFor(() => expect(names()[0]).toContain("Greet"));
  });
});

describe("reconcileDraft", () => {
  const base = { script: { ...EMPTY_SCRIPT, opening_line: OLD }, stamp: "v:3", savedAt: null };
  const next = { script: { ...EMPTY_SCRIPT, opening_line: NEW }, stamp: `d:${SAVED_AT}`, savedAt: SAVED_AT };

  it("adopts a new read over a clean editor", () => {
    expect(reconcileDraft(base.script, base, next, null)).toEqual({ kind: "adopt" });
  });

  it("keeps unsaved edits against somebody else's copy", () => {
    const edited = { ...base.script, opening_line: "mine" };
    expect(reconcileDraft(edited, base, next, null)).toEqual({ kind: "conflict" });
  });

  it("does nothing when the same content arrives in a different key order", () => {
    const { raw_override, ...rest } = base.script;
    expect(reconcileDraft(base.script, base, { ...base, script: { raw_override, ...rest } }, null)).toEqual({ kind: "unchanged" });
  });

  it("treats its own save as its own, even before the stamp is known", () => {
    const sent = { ...EMPTY_SCRIPT, opening_line: NEW };
    expect(reconcileDraft(sent, base, next, { script: sent, stamp: null, savedAt: null })).toEqual({ kind: "adopt" });
    const typedOn = { ...sent, opening_line: `${NEW} more` };
    expect(reconcileDraft(typedOn, base, next, { script: sent, stamp: next.stamp, savedAt: SAVED_AT })).toEqual({ kind: "rebase" });
  });
});

describe("the save line", () => {
  const plain = { dirty: false, saving: false, canWrite: true, conflict: false, failed: false, issueCount: 0, savedAt: null };
  it("reads plainly in every state", () => {
    expect(saveState(plain)).toEqual({ kind: "clean", savedAt: null });
    expect(saveState({ ...plain, dirty: true })).toEqual({ kind: "waiting" });
    expect(saveState({ ...plain, dirty: true, issueCount: 2 })).toEqual({ kind: "held", reason: "Not saved yet: 2 parts need finishing." });
    expect(saveState({ ...plain, dirty: true, conflict: true })).toEqual({ kind: "conflict" });
    expect(saveState({ ...plain, canWrite: false })).toEqual({ kind: "read-only" });
  });
});

describe("the agent page says whether callers hear the script, without version numbers", () => {
  it("reads plainly", () => {
    expect(liveScriptText({ published: false }, out(OLD, null))).toBe("Not put live yet");
    expect(liveScriptText({ published: true }, out(OLD, 4))).toBe("Live");
    expect(liveScriptText({ published: true }, out(OLD, 4, { opening: NEW, at: SAVED_AT }))).toBe("Live, with changes waiting");
    expect(liveScriptText({ published: false }, out(OLD, 4))).toBe("Ready · agent is off");
  });
});
