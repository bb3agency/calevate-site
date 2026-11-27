import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScenarioFlow } from "@/app/c/[slug]/campaigns/ScenarioFlow";
import { DEFAULT_LIMITS } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import type { WriteAccess } from "@/lib/api/hooks";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";

import { renderClientPage } from "./harness";

/** Dragging a scenario's dot onto another scenario makes it a next scenario (the canvas). */

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
  stages: [stage({ id: "a", name: "First", step: 1 }), stage({ id: "b", name: "Second", step: 2 })],
};

describe("drag to link", () => {
  it("links the dragged scenario to the one it is dropped on", async () => {
    const hear: WriteAccess = { allowed: true, reason: null, unknown: false };
    const onChange = vi.fn();
    await renderClientPage(
      <ScenarioFlow
        agent={null}
        direction="outbound"
        hear={hear}
        script={SCRIPT}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={["te-IN"]}
        selected={null}
        readOnly={false}
        wide
        onSelect={() => {}}
        onChange={onChange}
      />,
      {},
    );
    const target = (await screen.findByRole("button", { name: /Reply 2\.1: Second/ })).parentElement as HTMLElement;
    const dot = document.querySelectorAll<HTMLElement>("[data-link-from]")[0]!;
    dot.setPointerCapture = () => {};
    const x = Number.parseFloat(target.style.left) + 20;
    const y = Number.parseFloat(target.style.top) + 20;
    fireEvent.pointerDown(dot, { button: 0, pointerId: 1, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(dot, { pointerId: 1, clientX: x, clientY: y });
    fireEvent.pointerUp(dot, { pointerId: 1, clientX: x, clientY: y });
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0]?.[0] as CallScript | undefined;
    const first = next?.stages?.find((s) => s.id === "a");
    expect(first?.branches?.map((b) => b.target)).toEqual(["b"]);
  });

  it("counts a drop just outside a card's edge, where its arrowhead is", async () => {
    const hear: WriteAccess = { allowed: true, reason: null, unknown: false };
    const onChange = vi.fn();
    await renderClientPage(
      <ScenarioFlow
        agent={null}
        direction="outbound"
        hear={hear}
        script={SCRIPT}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={["te-IN"]}
        selected={null}
        readOnly={false}
        wide
        onSelect={() => {}}
        onChange={onChange}
      />,
      {},
    );
    const target = (await screen.findByRole("button", { name: /Reply 2\.1: Second/ })).parentElement as HTMLElement;
    const dot = document.querySelectorAll<HTMLElement>("[data-link-from]")[0]!;
    dot.setPointerCapture = () => {};
    const x = Number.parseFloat(target.style.left) - 8;
    const y = Number.parseFloat(target.style.top) + 40;
    fireEvent.pointerDown(dot, { button: 0, pointerId: 1, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(dot, { pointerId: 1, clientX: x, clientY: y });
    fireEvent.pointerUp(dot, { pointerId: 1, clientX: x, clientY: y });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("says why when a drop links nothing", async () => {
    const hear: WriteAccess = { allowed: true, reason: null, unknown: false };
    const linked: CallScript = {
      ...SCRIPT,
      stages: [stage({ id: "a", name: "First", step: 1, branches: [{ when: "Second", target: "b" }] }), SCRIPT.stages[1] as ConversationStage],
    };
    await renderClientPage(
      <ScenarioFlow
        agent={null}
        direction="outbound"
        hear={hear}
        script={linked}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={["te-IN"]}
        selected={null}
        readOnly={false}
        wide
        onSelect={() => {}}
        onChange={() => {}}
      />,
      {},
    );
    const target = (await screen.findByRole("button", { name: /Reply 2\.1: Second/ })).parentElement as HTMLElement;
    const dot = document.querySelectorAll<HTMLElement>("[data-link-from]")[0]!;
    dot.setPointerCapture = () => {};
    const x = Number.parseFloat(target.style.left) + 20;
    const y = Number.parseFloat(target.style.top) + 20;
    fireEvent.pointerDown(dot, { button: 0, pointerId: 1, clientX: 10, clientY: 10 });
    fireEvent.pointerUp(dot, { pointerId: 1, clientX: x, clientY: y });
    expect(await screen.findByText("It already goes there.")).toBeTruthy();
  });
});

describe("Pick where it goes next, with no drag", () => {
  const hear: WriteAccess = { allowed: true, reason: null, unknown: false };
  const flow = (over: { selected: string | null; onSelect?: (id: string | null) => void; onChange?: () => void }) => (
    <ScenarioFlow
      agent={null}
      direction="outbound"
      hear={hear}
      script={SCRIPT}
      limits={DEFAULT_LIMITS}
      issues={[]}
      languages={["te-IN"]}
      readOnly={false}
      wide
      onSelect={over.onSelect ?? (() => {})}
      onChange={over.onChange ?? (() => {})}
      selected={over.selected}
    />
  );

  it("is offered from the box's own menu and chooses that box", async () => {
    const onSelect = vi.fn();
    await renderClientPage(flow({ selected: null, onSelect }), {});
    fireEvent.click(await screen.findByRole("button", { name: "More for reply 1.1" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Pick where it goes next" }));
    expect(onSelect).toHaveBeenCalledWith("a");
  });

  it("links two replies by a tick in What can happen next", async () => {
    const onChange = vi.fn();
    await renderClientPage(flow({ selected: "a", onChange }), {});
    const list = await screen.findByRole("group", { name: "What can happen next" });
    fireEvent.click(within(list).getByRole("checkbox", { name: /2\.1 Second/ }));
    const next = onChange.mock.calls.at(-1)?.[0] as CallScript | undefined;
    expect(next?.stages?.find((s) => s.id === "a")?.branches?.map((b) => b.target)).toEqual(["b"]);
  });
});

describe("script boxes by language", () => {
  const view = (languages: string[], scripts: Record<string, string> = {}) =>
    renderClientPage(
      <ScenarioFlow
        agent={null}
        direction="outbound"
        hear={{ allowed: true, reason: null, unknown: false }}
        script={{ ...SCRIPT, stages: [stage({ id: "a", name: "First", step: 1, scripts }), SCRIPT.stages[1] as ConversationStage] }}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={languages}
        selected="a"
        readOnly={false}
        wide
        onSelect={() => {}}
        onChange={() => {}}
      />,
      {},
    );

  it("shows one Telugu box and no switch for a campaign that speaks only Telugu", async () => {
    await view(["te-IN"]);
    expect(await screen.findByText("Script in Telugu")).toBeTruthy();
    expect(screen.queryByText(/Script in English/)).toBeNull();
    expect(screen.queryByRole("radiogroup", { name: "Script language" })).toBeNull();
  });

  it("offers English when the campaign speaks it", async () => {
    await view(["te-IN", "en-IN"]);
    const switcher = await screen.findByRole("radiogroup", { name: "Script language" });
    expect(within(switcher).getByRole("radio", { name: /English/ })).toBeTruthy();
  });

  it("keeps an English line already written reachable", async () => {
    await view(["te-IN"], { "en-IN": "Hello." });
    const switcher = await screen.findByRole("radiogroup", { name: "Script language" });
    fireEvent.click(within(switcher).getByRole("radio", { name: /English/ }));
    expect((await screen.findByLabelText(/Script in English/)) as HTMLTextAreaElement).toHaveProperty("value", "Hello.");
  });

  it("holds every language of a many-language campaign in one box", async () => {
    const many = ["te-IN", "hi-IN", "ta-IN", "kn-IN", "ml-IN", "mr-IN", "en-IN"];
    await view(many, { "te-IN": "Telugu line." });
    const switcher = await screen.findByRole("radiogroup", { name: "Script language" });
    expect(within(switcher).getAllByRole("radio")).toHaveLength(many.length);
    expect(screen.getAllByRole("textbox", { name: /^Script in / })).toHaveLength(1);
    expect(screen.getByText("A dot marks a language with no line yet.")).toBeTruthy();
    fireEvent.click(within(switcher).getByRole("radio", { name: /Hindi/ }));
    expect(await screen.findByLabelText("Script in Hindi")).toBeTruthy();
    expect(screen.queryByLabelText("Script in Telugu")).toBeNull();
  });

  it("writes a line into the language that is open", async () => {
    const onChange = vi.fn();
    await renderClientPage(
      <ScenarioFlow
        agent={null}
        direction="outbound"
        hear={{ allowed: true, reason: null, unknown: false }}
        script={SCRIPT}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={["te-IN", "hi-IN"]}
        selected="a"
        readOnly={false}
        wide
        onSelect={() => {}}
        onChange={onChange}
      />,
      {},
    );
    const switcher = await screen.findByRole("radiogroup", { name: "Script language" });
    fireEvent.click(within(switcher).getByRole("radio", { name: /Hindi/ }));
    fireEvent.change(await screen.findByLabelText("Script in Hindi"), { target: { value: "Line." } });
    const next = onChange.mock.calls.at(-1)?.[0] as CallScript | undefined;
    expect(next?.stages?.find((s) => s.id === "a")?.scripts).toEqual({ "hi-IN": "Line." });
  });
});
