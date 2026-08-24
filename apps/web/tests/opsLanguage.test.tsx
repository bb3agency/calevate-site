import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import {
  KeyField,
  MonoValue,
  TermGloss,
  TimingBadge,
  TypeToConfirm,
  confirmMatches,
  dncSourceCopy,
  loadShedModeCopy,
  provenanceCopy,
  testOutcomeCopy,
  timingCopy,
  tmStatusCopy,
} from "@/app/admin/ops/opsLanguage";

/**
 * The plain-language layer is the one place the operations console decides how it speaks
 * to a non-technical operator, so its promises are worth pinning: that no internal enum
 * leaks through as a label, that an unknown value fails to a visible "not known" rather
 * than a blank or a crash (and cannot resolve a prototype member — the `StatusBadge`
 * bug), and that the key/confirm controls carry the accessibility and safety attributes
 * the whole rebuild was asked for.
 */
describe("ops plain-language maps", () => {
  it("translates every 'applies' timing to a human answer, none echoing the enum", () => {
    for (const applies of ["live", "needs_republish", "on_restart", "env_only", "unclassified"]) {
      const copy = timingCopy(applies);
      expect(copy.label).not.toContain("_");
      expect(copy.label).not.toBe(applies);
      expect(copy.help.length).toBeGreaterThan(0);
    }
    expect(timingCopy("live").label).toBe("Takes effect right away");
    expect(timingCopy("on_restart").label).toBe("Takes effect after a restart");
  });

  it("falls back visibly for an unrecognised timing rather than blank", () => {
    const copy = timingCopy("teleport");
    expect(copy.label).toBe("Timing not known");
    expect(copy.help).toContain("teleport");
  });

  it("does not resolve a prototype member as a real timing", () => {
    // `lookup` must treat "constructor" as missing, not return Object's constructor.
    expect(timingCopy("constructor").label).toBe("Timing not known");
  });

  it("names provenance in operator terms", () => {
    expect(provenanceCopy("db").label).toBe("Set here");
    expect(provenanceCopy("env").label).toBe("Set at deploy time");
    expect(provenanceCopy("default").label).toBe("Using the built-in default");
  });

  it("separates a rejected credential from an unreachable vendor", () => {
    expect(testOutcomeCopy("accepted").tone).toBe("ok");
    expect(testOutcomeCopy("rejected").tone).toBe("stop");
    expect(testOutcomeCopy("unreachable").tone).toBe("warn");
    expect(testOutcomeCopy("no_probe").tone).toBe("neutral");
  });

  it("does not show a green tick for an unverified acceptance", () => {
    // An 'accepted' the probe cannot fully confirm must read as indicative, not a pass.
    const copy = testOutcomeCopy("accepted", false);
    expect(copy.tone).not.toBe("ok");
    expect(copy.title).toBe("This key looks right");
  });

  it("maps load-shed modes onto status-page vocabulary", () => {
    expect(loadShedModeCopy("normal").label).toBe("Running normally");
    expect(loadShedModeCopy("maintenance").tone).toBe("stop");
    expect(loadShedModeCopy("nonsense").label).toContain("nonsense");
  });

  it("reads a TM registration status as a sentence", () => {
    expect(tmStatusCopy("active").label).toBe("Active");
    expect(tmStatusCopy("not_registered").label).toBe("Not registered");
  });

  it("names DNC sources without the enum", () => {
    expect(dncSourceCopy("regulator").label).not.toContain("_");
    expect(dncSourceCopy("platform_block").label).not.toContain("_");
  });

  it("matches a confirm word only on an exact equal", () => {
    expect(confirmMatches("STOP", "STOP")).toBe(true);
    expect(confirmMatches("stop", "STOP")).toBe(false);
    expect(confirmMatches(" STOP", "STOP")).toBe(false);
  });
});

describe("KeyField", () => {
  function Harness() {
    const [v, setV] = useState("");
    return <KeyField id="k" label="API key" value={v} onChange={setV} hint="Stored encrypted." />;
  }

  it("masks by default, is monospace, and refuses browser assistance on a secret", () => {
    render(<Harness />);
    const input = screen.getByLabelText("API key") as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(input.className).toContain("font-mono");
    expect(input.getAttribute("autocomplete")).toBe("off");
    // Assert the rendered attribute, not the `.spellcheck` IDL property — jsdom does not
    // reflect the latter, but the attribute is what a real browser reads.
    expect(input.getAttribute("spellcheck")).toBe("false");
  });

  it("reveals and re-hides the value on the toggle", () => {
    render(<Harness />);
    const input = screen.getByLabelText("API key") as HTMLInputElement;
    fireEvent.click(screen.getByRole("button", { name: "Show the key" }));
    expect(input.type).toBe("text");
    fireEvent.click(screen.getByRole("button", { name: "Hide the key" }));
    expect(input.type).toBe("password");
  });

  it("wires the hint to the field for a screen reader", () => {
    render(<Harness />);
    const input = screen.getByLabelText("API key");
    const described = input.getAttribute("aria-describedby");
    expect(described).toBeTruthy();
    expect(screen.getByText("Stored encrypted.").id).toBe(described);
  });
});

describe("TypeToConfirm", () => {
  function Harness() {
    const [v, setV] = useState("");
    return <TypeToConfirm id="c" word="STOP" value={v} onChange={setV} />;
  }

  it("labels the field with the exact word to type", () => {
    render(<Harness />);
    // The word appears both in the label and as the placeholder.
    expect(screen.getAllByText("STOP").length).toBeGreaterThan(0);
    const input = screen.getByLabelText(/Type/) as HTMLInputElement;
    expect(input.placeholder).toBe("STOP");
    expect(input.className).toContain("font-mono");
  });
});

describe("TermGloss", () => {
  it("keeps the term and exposes the gloss as its accessible name", () => {
    render(<TermGloss term="DLT">{"India's telecom message registry."}</TermGloss>);
    const el = screen.getByText("DLT");
    expect(el.getAttribute("aria-label")).toBe("DLT: India's telecom message registry.");
    expect(el.getAttribute("title")).toBe("India's telecom message registry.");
  });
});

describe("MonoValue and TimingBadge", () => {
  it("renders a fixed-width value", () => {
    render(<MonoValue>…4821</MonoValue>);
    expect(screen.getByText("…4821").className).toContain("font-mono");
  });

  it("renders the timing label as a badge", () => {
    render(<TimingBadge applies="live" />);
    expect(screen.getByText("Takes effect right away")).toBeTruthy();
  });
});
