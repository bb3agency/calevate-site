import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  OpeningEditor,
  variablesNote,
  type ScriptExamples,
} from "@/app/c/[slug]/agents/[agentId]/script/ScriptSections";
import { EMPTY_SCRIPT } from "@/lib/api/script";

const EG = { outboundPurpose: "You enquired with us last week." } as ScriptExamples;
const STANDARD = [{ key: "lead_name", label: "Caller's name" }];

function opening(over: Partial<Parameters<typeof OpeningEditor>[0]> = {}) {
  const set = vi.fn();
  render(
    <OpeningEditor
      script={{ ...EMPTY_SCRIPT, opening_line: "Namaskaram andi.", variables: [{ key: "order_id", label: "Order id", example: "" }] }}
      set={set}
      direction="inbound"
      room={120}
      standardVariables={STANDARD}
      eg={EG}
      {...over}
    />,
  );
  return set;
}

describe("how the call opens, in the script editor", () => {
  it("says when a caller detail is filled, by who places the call", () => {
    expect(variablesNote("inbound")).toContain("only if they called before");
    expect(variablesNote("inbound")).not.toContain("from the lead");
    expect(variablesNote("outbound")).toContain("filled from the lead");
    expect(variablesNote("outbound")).not.toContain("called before");
    expect(variablesNote("both")).toContain("from the lead");
    expect(variablesNote("both")).toContain("called before");
  });

  it("offers the caller's name and the client's own fields, and inserts the field into the opening line", () => {
    const set = opening();
    const box = screen.getByRole("textbox", { name: /Opening line/ }) as HTMLTextAreaElement;
    box.setSelectionRange(box.value.length, box.value.length);
    fireEvent.click(screen.getByRole("button", { name: "Caller's name" }));
    expect(set).toHaveBeenCalledWith("opening_line", "Namaskaram andi.{{lead_name}}");
    expect(screen.getByRole("button", { name: "Order id" })).toBeTruthy();
  });

  it("keeps the line plain text: formatting typed or pasted is removed and said", () => {
    const set = opening();
    fireEvent.change(screen.getByRole("textbox", { name: /Opening line/ }), {
      target: { value: "**Namaskaram** andi 🙏" },
    });
    expect(set).toHaveBeenCalledWith("opening_line", "Namaskaram andi ");
    expect(screen.getByText(/Formatting was removed/)).toBeTruthy();
  });

  it("asks why it is calling only on an agent that places calls, within 300 characters", () => {
    opening({ direction: "inbound" });
    expect(screen.queryByRole("textbox", { name: /Why you are calling/ })).toBeNull();
  });

  it("shows why it is calling on an outbound agent, routed to its own field", () => {
    const set = opening({ direction: "outbound" });
    fireEvent.change(screen.getByRole("textbox", { name: /Why you are calling/ }), {
      target: { value: "Calling about your enquiry." },
    });
    expect(set).toHaveBeenCalledWith("outbound_purpose", "Calling about your enquiry.");
    expect(screen.getByText("300 characters left")).toBeTruthy();
  });

  it("previews the opening with each caller detail named where its value will be said", () => {
    opening({ script: { ...EMPTY_SCRIPT, opening_line: "Namaskaram {{lead_name}} garu." } });
    const preview = screen.getByRole("complementary", { name: "How it will sound" });
    expect(preview.textContent).toContain("Namaskaram Caller's name garu.");
  });
});
