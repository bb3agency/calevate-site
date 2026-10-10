import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import AgentScriptPage from "@/app/c/[slug]/agents/[agentId]/script/page";
import { reconcileDraft } from "@/app/c/[slug]/agents/[agentId]/script/scriptDraft";
import { liveVersionText } from "@/app/c/[slug]/agents/[agentId]/sections/scriptSection";
import type { Me } from "@/lib/api/client";
import { EMPTY_SCRIPT, type CallScript, type ScriptOut } from "@/lib/api/script";

import { problem, renderClientPage } from "./harness";
import { agentRow } from "./fixtures/sharedReads";

/**
 * The script builder and the agent page must show the same saved script.
 *
 * The founder saw the agent page's summary read one opening line while the builder showed
 * another under a "v4 saved" badge. The builder took its copy of the script ONCE, when it
 * mounted, and never followed the read underneath it: a newer version arriving (a second
 * tab, a knowledge recompile, a rollback, a cached read replaced by a fresh one) left the
 * old text on screen, and Save then wrote that old text over the newer version.
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
const NEW = "Namaste {{lead_name}} garu! Nenu Raghava Organics nundi call chestunnanu.";

function out(opening: string, version: number | null, extra: Partial<CallScript> = {}): ScriptOut {
  return {
    script: { ...EMPTY_SCRIPT, opening_line: opening, ...extra },
    version,
    is_freeform: false,
    has_pending: false,
    standard_variables: [],
  };
}

const page = <AgentScriptPage params={Promise.resolve({ slug: "acme", agentId: "agent-1" })} />;

function opening(): HTMLTextAreaElement {
  return screen.getByLabelText("Opening line") as HTMLTextAreaElement;
}

function client(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

describe("the builder follows the saved script", () => {
  it("shows a newer saved version that arrives while nothing is unsaved", async () => {
    let current = out(OLD, 3);
    const qc = client();
    await renderClientPage(
      page,
      {
        "/v1/me": OWNER,
        "/v1/agents/agent-1": agentRow(),
        "/v1/agents/agent-1/script": () => current,
      },
      "acme",
      qc,
    );
    await waitFor(() => expect(opening().value).toBe(OLD));
    expect(screen.getByText("v3 saved")).toBeTruthy();

    current = out(NEW, 4);
    await act(async () => {
      await qc.invalidateQueries();
    });

    await waitFor(() => expect(opening().value).toBe(NEW));
    expect(screen.getByText("v4 saved")).toBeTruthy();
  });

  it("keeps unsaved edits when the saved version moves, says so, and loads it on request", async () => {
    let current = out(OLD, 3);
    const qc = client();
    await renderClientPage(
      page,
      {
        "/v1/me": OWNER,
        "/v1/agents/agent-1": agentRow(),
        "/v1/agents/agent-1/script": () => current,
      },
      "acme",
      qc,
    );
    await waitFor(() => expect(opening().value).toBe(OLD));
    fireEvent.change(opening(), { target: { value: "My own edit" } });

    current = out(NEW, 4);
    await act(async () => {
      await qc.invalidateQueries();
    });

    expect(await screen.findByText("This script was changed somewhere else")).toBeTruthy();
    expect(opening().value).toBe("My own edit");
    fireEvent.click(screen.getByRole("button", { name: "Load version 4" }));
    await waitFor(() => expect(opening().value).toBe(NEW));
    expect(screen.getByText("v4 saved")).toBeTruthy();
  });

  it("saves against the version it started from, and shows what the server stored", async () => {
    let current = out(OLD, 3);
    const { calls } = await renderClientPage(page, {
      "/v1/me": OWNER,
      "/v1/agents/agent-1": agentRow(),
      "/v1/agents/agent-1/script": () => current,
      "PUT /v1/agents/agent-1/script": () => {
        // The server splits end-call rules one per line; the builder must show that copy.
        current = out(NEW, 4, { end_call_extra_rules: ["one", "two"] });
        return { version: 4, staged: false };
      },
    });
    await waitFor(() => expect(opening().value).toBe(OLD));
    fireEvent.change(opening(), { target: { value: NEW } });
    fireEvent.click(screen.getByRole("button", { name: "Save script" }));

    await waitFor(() => expect(screen.getByText("v4 saved")).toBeTruthy());
    const put = calls.find((call) => call.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}").expected_version).toBe(3);
    expect(opening().value).toBe(NEW);
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });

  it("shows the server's refusal when the script moved before the save", async () => {
    await renderClientPage(page, {
      "/v1/me": OWNER,
      "/v1/agents/agent-1": agentRow(),
      "/v1/agents/agent-1/script": out(OLD, 3),
      "PUT /v1/agents/agent-1/script": problem(409, {
        code: "script_changed_elsewhere",
        title: "We could not complete that",
        detail: "This script was changed somewhere else after you opened it.",
      }),
    });
    await waitFor(() => expect(opening().value).toBe(OLD));
    fireEvent.change(opening(), { target: { value: "edit" } });
    fireEvent.click(screen.getByRole("button", { name: "Save script" }));
    expect(
      await screen.findByText("This script was changed somewhere else after you opened it."),
    ).toBeTruthy();
    expect(screen.getByText("Unsaved changes")).toBeTruthy();
  });
});

describe("reconcileDraft", () => {
  const base = { script: { ...EMPTY_SCRIPT, opening_line: OLD }, version: 3 };
  const next = { script: { ...EMPTY_SCRIPT, opening_line: NEW }, version: 4 };

  it("adopts a new read over a clean editor", () => {
    expect(reconcileDraft(base.script, base, next, null)).toEqual({ kind: "adopt" });
  });

  it("keeps unsaved edits against somebody else's version", () => {
    const edited = { ...base.script, opening_line: "mine" };
    expect(reconcileDraft(edited, base, next, null)).toEqual({ kind: "conflict", version: 4 });
  });

  it("does nothing when the same content arrives in a different key order", () => {
    const { raw_override, ...rest } = base.script;
    const reordered = { version: 3, script: { raw_override, ...rest } };
    expect(reconcileDraft(base.script, base, reordered, null)).toEqual({ kind: "unchanged" });
  });

  it("treats its own save as its own, even before the version is known", () => {
    const sent = { ...EMPTY_SCRIPT, opening_line: NEW };
    expect(reconcileDraft(sent, base, next, { script: sent, version: null })).toEqual({
      kind: "adopt",
    });
    expect(reconcileDraft(sent, base, next, { script: sent, version: 4 })).toEqual({
      kind: "adopt",
    });
    const typedOn = { ...sent, opening_line: `${NEW} more` };
    expect(reconcileDraft(typedOn, base, next, { script: sent, version: 4 })).toEqual({
      kind: "rebase",
    });
  });
});

describe("the agent page's live version row", () => {
  it("reads plainly", () => {
    expect(liveVersionText({ published: false }, 4, undefined)).toBe("Not switched on yet");
    expect(liveVersionText({ published: true }, 4, undefined)).toBe("Version 4");
    expect(liveVersionText({ published: true }, null, undefined)).toBe("None yet");
    expect(liveVersionText({ published: true }, 5, { live_version: 4 })).toBe("Version 4");
  });
});
