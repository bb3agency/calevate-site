import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ScriptPartsEditor } from "@/app/c/[slug]/agents/[agentId]/script/ScriptPartsEditor";
import { DEFAULT_LIMITS } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import { BLOCKER_COPY, blockerInPage } from "@/app/c/[slug]/campaigns/blockerCopy";
import { ScenarioFlow } from "@/app/c/[slug]/campaigns/ScenarioFlow";
import { ToastProvider } from "@/components/arc/toast";
import { SCRIPT_NEEDS_FIX_TEXT, ScriptNeedsFix } from "@/components/scriptChecks/ScriptNeedsFix";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";
import {
  SHOW_FINDING_EVENT,
  findingWarnings,
  fixLinesAsk,
  type ScriptChecks,
  type ScriptFinding,
} from "@/lib/api/scriptChecks";

import { expectNoA11yViolations } from "./a11y";
import { FIXTURE_CAMPAIGN_ID, workspaceFixture } from "./campaignFixtures";
import { renderClientPage } from "./harness";

/**
 * The saved script's checks (script rebuild §3.4) on the lines they are about, and the
 * refusal `script_needs_fix` in the owner's words with Pip's fix and "Show me". Lines are
 * English placeholders standing in for the call's language.
 */

const stage = (over: Partial<ConversationStage>): ConversationStage => ({
  id: "a",
  name: "A",
  mode: "guide",
  instruction: "Do A.",
  sounds_like: "",
  branches: [],
  otherwise: "",
  collect: [],
  procedure: [],
  position: null,
  step: 1,
  scripts: {},
  qa: [],
  coaching: [],
  ...over,
});

const SCRIPT: CallScript = {
  ...EMPTY_SCRIPT,
  schema_version: 2,
  opening_line: "Hello.",
  stages: [
    stage({ id: "intro", name: "Introduction", step: 1, scripts: { "te-IN": "Okay! Open the app and tell me when done." } }),
    stage({ id: "open", name: "Open the app", step: 2, instruction: "Ask them to open it." }),
  ],
};

const finding = (over: Partial<ScriptFinding>): ScriptFinding => ({
  check: "asks_to_say_done",
  path: "stages.0.scripts.te-IN",
  stage_id: "intro",
  message: "Step 1: asks them to say when it is done; give one action and stop.",
  detail: "asks them to say when it is done; give one action and stop.",
  line: "Okay! Open the app and tell me when done.",
  severity: "block",
  ...over,
});

const FINDINGS: ScriptFinding[] = [
  finding({}),
  finding({
    check: "textbook_words",
    path: "stages.1.instruction",
    stage_id: "open",
    message: "Step 2: uses a textbook word.",
    detail: "uses a textbook word.",
    line: "Ask them to open it.",
    severity: "warn",
  }),
];

describe("the checks' findings, adapted to the editors", () => {
  it("keys a finding by its step's id, keeps its line, and puts the rest behind Why?", () => {
    const [first, second] = findingWarnings(FINDINGS);
    expect(first).toEqual({
      path: "stages.intro.scripts.te-IN",
      message: "Asks them to say when it is done.",
      detail: "give one action and stop.",
      text: "Okay! Open the app and tell me when done.",
      severity: "block",
    });
    expect(second.path).toBe("stages.open.instruction");
    expect(second.detail).toBeNull();
  });

  it("asks Pip to fix only the lines that hold the script back", () => {
    const ask = fixLinesAsk(FINDINGS);
    expect(ask).toContain("Step 1: asks them to say when it is done");
    expect(ask).not.toContain("textbook");
  });

  it("names the refusal in one short line and fixes it on the page", () => {
    expect(BLOCKER_COPY.script_needs_fix.text).toBe(SCRIPT_NEEDS_FIX_TEXT);
    expect(blockerInPage("script_needs_fix")).toBe("fix-script");
  });
});

function Flow({ chosen }: { chosen: string }) {
  const [script, setScript] = useState(SCRIPT);
  return (
    <ToastProvider>
      <ScenarioFlow
        agent={null}
        direction="outbound"
        hear={{ allowed: true, reason: null, unknown: false }}
        script={script}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={["te-IN"]}
        selected={chosen}
        readOnly={false}
        wide
        warnings={findingWarnings(FINDINGS)}
        onSelect={() => {}}
        onChange={setScript}
      />
    </ToastProvider>
  );
}

describe("findings in the scenario editor", () => {
  it("shows a finding under its script line, and settles it once the line is rewritten", async () => {
    await renderClientPage(<Flow chosen="intro" />, {});
    const box = screen.getByRole("textbox", { name: "Script in Telugu" });
    const holder = box.parentElement as HTMLElement;
    expect(within(holder).getByText("Asks them to say when it is done.")).toBeTruthy();
    fireEvent.change(box, { target: { value: "Please open the app." } });
    expect(within(holder).queryByText("Asks them to say when it is done.")).toBeNull();
  });

  it("shows a finding on a step's description under that description", async () => {
    const r = await renderClientPage(<Flow chosen="open" />, {});
    const description = screen.getByRole("textbox", { name: "What the agent does" });
    expect(within(description.parentElement as HTMLElement).getByText("Uses a textbook word.")).toBeTruthy();
    await expectNoA11yViolations(r.container, "scenario editor with check findings");
  });
});

describe("findings while editing a saved script", () => {
  it("marks the step's row, and shows its finding when the step is opened", () => {
    render(<ScriptPartsEditor script={SCRIPT} warnings={findingWarnings(FINDINGS)} onSave={() => {}} onClose={() => {}} />);
    const step = screen.getByRole("button", { name: /^Open the app/ });
    expect(step.textContent).toContain("1 to check");
    fireEvent.click(step);
    expect(screen.getByText("Uses a textbook word.")).toBeTruthy();
  });

  it("opens the step Show me names", () => {
    render(
      <ScriptPartsEditor
        script={SCRIPT}
        warnings={findingWarnings(FINDINGS)}
        show={{ stageId: "open" }}
        onSave={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /^Open the app/ }).getAttribute("aria-expanded")).toBe("true");
  });
});

describe("the refusal, with Pip's fix and Show me", () => {
  const base = `/v1/campaigns/${FIXTURE_CAMPAIGN_ID}`;
  const checks: ScriptChecks = { findings: FINDINGS, blocks_live: true };

  it("asks Pip for those lines and goes to the first one", async () => {
    const shown = vi.fn();
    window.addEventListener(SHOW_FINDING_EVENT, (e) => shown((e as CustomEvent).detail));
    const r = await renderClientPage(
      <ScriptNeedsFix holder={{ kind: "campaign", id: FIXTURE_CAMPAIGN_ID }} canWrite />,
      {
        [`${base}/workspace`]: workspaceFixture({ script: SCRIPT }),
        [`${base}/script/checks`]: checks,
        [`POST ${base}/script/proposal`]: {
          id: "0192f0aa-6666-7000-8000-000000000001",
          status: "drafting",
          requested_at: "2026-11-26T04:00:00Z",
          base_script: null,
          script: null,
          note: null,
          disclosure: null,
          left_out: [],
          reason: null,
          fixes: null,
        },
      },
    );
    expect(screen.getByText(SCRIPT_NEEDS_FIX_TEXT)).toBeTruthy();
    const fix = await screen.findByRole("button", { name: "Let Pip fix it" });
    await waitFor(() => expect((fix as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(fix);
    await waitFor(() =>
      expect(r.calls.some((c) => c.method === "POST" && c.path === `${base}/script/proposal`)).toBe(true),
    );
    const body = JSON.parse(r.calls.find((c) => c.method === "POST")?.body ?? "{}") as { instruction?: string };
    expect(body.instruction).toContain("Step 1: asks them to say when it is done");
    fireEvent.click(screen.getByRole("button", { name: "Show me" }));
    expect(shown).toHaveBeenCalledWith({ stageId: "intro", path: "stages.0.scripts.te-IN" });
    await expectNoA11yViolations(r.container, "script needs fixing");
  });
});
