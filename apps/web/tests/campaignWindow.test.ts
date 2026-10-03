import { describe, expect, it } from "vitest";

import { PLATFORM_WINDOW, windowRefusal } from "@/app/c/[slug]/campaigns/NewCampaignFlow";

/**
 * The "When should we call?" step refuses a narrowed calling window the server would refuse
 * at create (`campaigns/service.py::_validated_window`), so the client fixes it on the step
 * that set it instead of seeing a 422 on "Create campaign".
 */
describe("the campaign calling window", () => {
  it("accepts a window inside the platform hours, including the hours themselves", () => {
    expect(windowRefusal("10:00", "18:00")).toBeNull();
    expect(windowRefusal(PLATFORM_WINDOW.start, PLATFORM_WINDOW.end)).toBeNull();
  });

  it("refuses a window that ends before, or when, it starts", () => {
    expect(windowRefusal("18:00", "10:00")).toMatch(/start before it ends/);
    expect(windowRefusal("12:00", "12:00")).toMatch(/start before it ends/);
  });

  it("refuses a window that starts before 09:00 or ends after 21:00 IST", () => {
    expect(windowRefusal("08:30", "12:00")).toMatch(/between 9am and 9pm IST/);
    expect(windowRefusal("12:00", "21:30")).toMatch(/between 9am and 9pm IST/);
  });
});
