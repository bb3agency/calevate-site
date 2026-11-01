import { describe, expect, it } from "vitest";

import { formatClock as playerClock } from "@/components/callAudioPlayer";
import { formatClock, formatDuration } from "@/components/ui";

describe("formatDuration", () => {
  it("reads minutes and seconds under an hour", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(137)).toBe("2:17");
    expect(formatDuration(3599)).toBe("59:59");
  });

  it("rolls over to hours instead of counting minutes past 59", () => {
    expect(formatDuration(3600)).toBe("1:00:00");
    expect(formatDuration(7252)).toBe("2:00:52");
  });

  it("says the length is unknown rather than zero", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(undefined)).toBe("—");
  });

  it("is the same clock the recording player shows", () => {
    expect(playerClock).toBe(formatClock);
    expect(formatDuration(3730)).toBe(formatClock(3730));
  });
});
