import { describe, expect, it } from "vitest";

import {
  PLATFORM_WINDOW,
  minutesOf,
  windowRefusal,
  windowWords,
} from "@/app/c/[slug]/campaigns/callingWindow";

/**
 * The "When should we call?" step refuses a narrowed calling window the server would refuse
 * at create (`campaigns/service.py::validated_window`), so the client fixes it on the step
 * that set it instead of seeing a 422 on "Create campaign".
 */
describe("the campaign calling window", () => {
  it("accepts a window inside the platform hours, including the hours themselves", () => {
    expect(windowRefusal("10:00", "18:00")).toBeNull();
    expect(windowRefusal(PLATFORM_WINDOW.start, PLATFORM_WINDOW.end)).toBeNull();
  });

  it("refuses a window that ends before, or when, it starts", () => {
    expect(windowRefusal("18:00", "10:00")).toMatch(/start before they end/);
    expect(windowRefusal("12:00", "12:00")).toMatch(/start before they end/);
  });

  it("refuses a window that starts before 09:00 or ends after 21:00 IST", () => {
    expect(windowRefusal("08:30", "12:00")).toMatch(/between 9am and 9pm IST/);
    expect(windowRefusal("12:00", "21:30")).toMatch(/between 9am and 9pm IST/);
  });

  it("says the window in words read from the one constant", () => {
    expect(windowWords()).toBe("9am to 9pm");
    expect(windowWords(" and ")).toBe("9am and 9pm");
    expect(windowWords("–")).toBe("9am–9pm");
    expect(minutesOf(PLATFORM_WINDOW.end)).toBe(21 * 60);
  });
});
