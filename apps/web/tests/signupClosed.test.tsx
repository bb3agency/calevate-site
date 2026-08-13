import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SignupPage from "@/app/signup/page";

import { stubApi } from "./harness";

/**
 * Signup on a deployment that does NOT open accounts online — which is every deployment
 * that has not deliberately switched the door on.
 *
 * `self_serve_signup_enabled` defaults OFF (R-11's kill switch, SURFACES §2c), and the
 * client mirror `SIGNUP_OPEN` reads unset as CLOSED for the same reason. So this file
 * sets no environment variable at all: the DEFAULT is the subject. It is separate from
 * `signup.test.tsx` because the constant is read at import time — see that file's note on
 * why `vi.resetModules()` is not the answer.
 *
 * What is asserted is an absence: on a closed deployment there must be no form. A form
 * that can only ever be refused walks a business through five fields to reach the same
 * sentence this panel opens with, and a disabled submit button is the same trap with a
 * greyer hat.
 */
describe("signup with the kill switch in its default position", () => {
  it("says it is closed before the form rather than after it", () => {
    stubApi({});
    render(<SignupPage />);

    expect(screen.getByText("Signing up online is closed")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Create workspace" })).toBeNull();
    expect(screen.queryByLabelText("Business name")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("makes no request, because the form that would make one is not mounted", () => {
    const calls = stubApi({});
    render(<SignupPage />);
    expect(calls).toEqual([]);
  });

  it("promises no turnaround it cannot keep", () => {
    stubApi({});
    const { container } = render(<SignupPage />);
    const text = container.textContent ?? "";
    // This panel used to end "usually the same day". Nothing in the product or in ops
    // measures account-setup turnaround, so it was a promise made by a screen with no
    // way to keep it — the strictest form of the honesty rule, on the one screen a
    // stranger reads.
    expect(text).not.toContain("same day");
    expect(text).not.toMatch(/within \d/i);
    expect(text).not.toMatch(/\d+\s*(hours|hrs|minutes)/i);
    // And it still says the thing that IS true: a human opens the account.
    expect(text).toContain("set up by hand with you");
  });
});
