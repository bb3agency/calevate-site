import { describe, expect, it } from "vitest";

import { weekOnWeek } from "@/lib/weekOnWeek";

describe("weekOnWeek", () => {
  it("says more, fewer or the same, and nothing over two empty weeks", () => {
    expect(weekOnWeek(29, 17)).toBe("12 more than the week before");
    expect(weekOnWeek(3, 5)).toBe("2 fewer than the week before");
    expect(weekOnWeek(4, 4)).toBe("same as the week before");
    expect(weekOnWeek(0, 0)).toBeNull();
  });
});
