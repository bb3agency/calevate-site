import { describe, expect, it } from "vitest";

import { minutesLeftPhrase } from "@/lib/api/wallet";

/** Credit is shown as minutes first, from the server's own per-tier minutes (REDESIGN-2). */
describe("minutes left", () => {
  it("is one figure for one voice tier", () => {
    expect(minutesLeftPhrase({ minutes_left: [{ voice_tier: "clear", label: "Clear", minutes: 240 }] })).toBe(
      "About 240 minutes left",
    );
  });

  it("is a range when what a minute costs depends on the voice", () => {
    expect(
      minutesLeftPhrase({
        minutes_left: [
          { voice_tier: "clear", label: "Clear", minutes: 240 },
          { voice_tier: "studio", label: "Studio", minutes: 171 },
        ],
      }),
    ).toBe("About 171 to 240 minutes left");
  });

  it("never reads 'no rate quoted' as zero", () => {
    expect(minutesLeftPhrase({ minutes_left: null })).toBeNull();
    expect(minutesLeftPhrase({ minutes_left: [{ voice_tier: "clear", label: "Clear", minutes: 0 }] })).toBe(
      "No minutes left",
    );
  });
});
