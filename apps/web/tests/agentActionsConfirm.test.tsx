import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Credentials } from "@/app/c/[slug]/agents/actions/Credentials";
import { ToolRow } from "@/app/c/[slug]/agents/actions/ToolRow";
import type { ActionTool, IntegrationCredential } from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";

import { renderClientPage } from "./harness";
import { relPosix } from "./repoPaths";
import { blankComments } from "./sourceScan";

/**
 * DELETING AN ACTION OR A SAVED SECRET ASKS IN THE PRODUCT'S OWN DIALOG.
 *
 * Both of these rows used to gate their `DELETE` on `window.confirm`, which is the second
 * confirmation mechanism in a console that argues at length for exactly one
 * (`components/confirmDialog.tsx`, and `lib/copilot/unsaved.ts` which rejects
 * `window.confirm` by name). The reason it is a DEFECT and not a style choice is the
 * failure mode: a native dialog is suppressible — Chrome drops it for a tab the user has
 * not interacted with, and mobile browsers drop it more readily still — and a suppressed
 * `confirm()` returns `false`. The delete then silently does not happen, on a click the
 * person believes they completed. A dialog we render cannot be suppressed by the browser,
 * and it can carry the consequence sentence a native box has no room for.
 *
 * These assertions are written so they fail on the old code: nothing here stubs
 * `window.confirm`, so under `confirm()` jsdom's own implementation answers `false`
 * (jsdom does not implement it) and the DELETE is never sent — which is exactly the
 * Android behaviour, reproduced for free.
 */

const SESSION: Session = { orgSlug: "acme" };

const CREDENTIAL: IntegrationCredential = {
  id: "cred-1",
  label: "Clinic WhatsApp",
  kind: "aisensy",
  last_four: "8241",
  non_secret: null,
  version: 1,
  created_at: "2026-09-01T04:00:00Z",
  updated_at: "2026-09-01T04:00:00Z",
};

const TOOL: ActionTool = {
  id: "tool-1",
  agent_id: "agent-1",
  name: "send_reminder",
  kind: "whatsapp",
  provider: "aisensy",
  trigger: "after_call",
  description: "Sends the appointment reminder.",
  enabled: true,
  params: [],
  config: {},
  credential_id: "cred-1",
  pre_call_message: null,
};

describe("removing a saved credential", () => {
  it("asks in ConfirmDialog and only then sends the DELETE", async () => {
    const { calls } = await renderClientPage(
      <Credentials session={SESSION} />,
      {
        "/v1/integrations/credentials": [CREDENTIAL],
        "DELETE /v1/integrations/credentials/cred-1": {},
      },
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Delete Clinic WhatsApp" }),
    );

    // The dialog, not the browser's: it is in the accessibility tree and it names the row.
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Clinic WhatsApp");
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Delete it" }));
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === "DELETE" &&
            c.path === "/v1/integrations/credentials/cred-1",
        ),
      ).toBe(true),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("sends nothing when the person backs out", async () => {
    const { calls } = await renderClientPage(
      <Credentials session={SESSION} />,
      {
        "/v1/integrations/credentials": [CREDENTIAL],
      },
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Delete Clinic WhatsApp" }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  });
});

describe("removing a configured action", () => {
  it("asks in ConfirmDialog and only then sends the DELETE", async () => {
    const { calls } = await renderClientPage(
      <ToolRow tool={TOOL} agentId="agent-1" session={SESSION} />,
      { "DELETE /v1/agents/agent-1/actions/tool-1": {} },
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Remove send_reminder" }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("send_reminder");
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Remove it" }));
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === "DELETE" &&
            c.path === "/v1/agents/agent-1/actions/tool-1",
        ),
      ).toBe(true),
    );
  });
});

/**
 * AND THE CLASS, NOT JUST THESE TWO ROWS.
 *
 * Fixing two files leaves the third writable, and the two above were written by people who
 * had simply not met `ConfirmDialog`. The same technique the rest of this suite uses for a
 * rule with no runtime seam (`surfaceStatesGuard`, `responsive`, `contrast`,
 * `plainLanguageGuard`) applies here: read the source and refuse the spelling.
 *
 * All three of the browser's modal functions, not only `confirm`: `alert` is a refusal
 * nobody can style, translate or place in the reading order, and `prompt` is a form field
 * with none of this console's validation. Comments are blanked first — `lib/copilot/
 * unsaved.ts` and `components/confirmDialog.tsx` both NAME `window.confirm` in the
 * argument for not using it, and a guard that flagged those would be reporting its own
 * documentation (`tests/sourceScan.ts`).
 */
describe("the browser's own dialogs", () => {
  const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
  const BROWSER_DIALOG =
    /(?<![.\w])(?:window\s*\.\s*)?(?:confirm|alert|prompt)\s*\(/;

  function files(dir: string): string[] {
    const found: string[] = [];
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) found.push(...files(path));
      else if (path.endsWith(".ts") || path.endsWith(".tsx")) found.push(path);
    }
    return found;
  }

  it("are not used anywhere — this console asks in its own", () => {
    const sources = files(SRC);
    expect(sources.length).toBeGreaterThan(100);
    const offenders: string[] = [];
    for (const path of sources) {
      blankComments(readFileSync(path, "utf8").split("\n")).forEach(
        (line, index) => {
          if (BROWSER_DIALOG.test(line)) {
            offenders.push(
              `${relPosix(resolve(SRC, ".."), path)}:${index + 1} — ${line.trim()}`,
            );
          }
        },
      );
    }
    expect(offenders).toEqual([]);
  });
});
