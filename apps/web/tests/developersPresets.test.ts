import { describe, expect, it } from "vitest";

import {
  PRESETS,
  SCOPE_WORDS,
  parseAddresses,
  presetScopes,
} from "@/app/c/[slug]/integrations/developers/presets";

describe("API key presets (D-1047)", () => {
  it("never offer raw transcripts, and every permission has plain words", () => {
    for (const preset of PRESETS) {
      expect(preset.scopes).not.toContain("calls:read_raw");
      for (const scope of preset.scopes) expect(SCOPE_WORDS[scope]).toBeTruthy();
    }
  });

  it("read results changes nothing; place calls adds dialling", () => {
    expect(presetScopes("read")).not.toContain("leads:dispatch");
    expect(presetScopes("call")).toContain("leads:dispatch");
  });

  it("reads addresses separated by commas, spaces or lines", () => {
    expect(parseAddresses(" 203.0.113.7,198.51.100.0/24\n\n10.0.0.1 ")).toEqual([
      "203.0.113.7",
      "198.51.100.0/24",
      "10.0.0.1",
    ]);
  });
});
