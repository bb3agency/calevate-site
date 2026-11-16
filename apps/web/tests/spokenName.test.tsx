import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OpeningEditor, withoutNameFor } from "@/app/c/[slug]/agents/[agentId]/script/ScriptSections";
import { fillSpokenLine } from "@/components/arc/spoken-text";
import { EMPTY_SCRIPT } from "@/lib/api/script";

type NameCase = { text: string; values: Record<string, string | null>; spoken: string };

const CASES: NameCase[] = JSON.parse(
  readFileSync(resolve(__dirname, "../../../tests/fixtures/spoken_name_cases.json"), "utf8"),
).cases;

describe("a line said on a call with no name (U-4)", () => {
  it.each(CASES.map((c) => [c.text, c] as const))("fills %s as the dial does", (_text, c) => {
    expect(fillSpokenLine(c.text, c.values)).toBe(c.spoken);
  });

  it("shows the title said alone on a call it answers, where only the field is left out", () => {
    const { placed, answered } = withoutNameFor([{ key: "lead_name", label: "Caller's name", sample: "Caller's name" }]);
    expect(placed("Hello {{lead_name}} sir, how can I help?")).toBe("Hello, how can I help?");
    expect(answered("Hello {{lead_name}} sir, how can I help?")).toBe("Hello sir, how can I help?");
  });

  it("previews an outbound opening with and without the name", () => {
    render(
      <OpeningEditor
        script={{ ...EMPTY_SCRIPT, opening_line: "Hello {{lead_name}} sir, Asha from Acme. Can we talk now?" }}
        set={() => undefined}
        direction="outbound"
        standardVariables={[{ key: "lead_name", label: "Caller's name" }]}
        eg={{ outboundPurpose: "Calling about your order." } as never}
      />,
    );
    expect(screen.getByText("Hello Caller's name sir, Asha from Acme. Can we talk now?")).toBeTruthy();
    expect(screen.getByText("With no name:")).toBeTruthy();
    expect(screen.getByText("Hello, Asha from Acme. Can we talk now?")).toBeTruthy();
  });

  it("shows nothing extra for an opening that does not use the name", () => {
    render(
      <OpeningEditor
        script={{ ...EMPTY_SCRIPT, opening_line: "Hello, Asha from Acme. Can we talk now?" }}
        set={() => undefined}
        direction="outbound"
        standardVariables={[{ key: "lead_name", label: "Caller's name" }]}
        eg={{ outboundPurpose: "Calling about your order." } as never}
      />,
    );
    expect(screen.queryByText("With no name:")).toBeNull();
  });
});
