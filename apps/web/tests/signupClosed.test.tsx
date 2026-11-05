import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SignupPage from "@/app/signup/page";
import { CLIENT_SIGN_IN_PATH } from "@/lib/authn/clientAuthn";
import { resolvePlaceholders } from "@/lib/legal/placeholders";

import { problem, stubApi } from "./harness";

/**
 * Signup on a deployment that does NOT open accounts online (D-703).
 *
 * Whether signing up is open is the server's live answer (`GET /v1/auth/client/sign-in-
 * options`, the `self_serve_signup_enabled` console switch, OFF by default), so this file
 * answers it "closed" and asserts the absence: no account form, no workspace form, and no
 * request beyond reading the switch. A form that can only ever be refused is a trap.
 */
const CLOSED = { "GET /v1/auth/client/sign-in-options": { google: false, self_serve_signup: false } };

async function mount(): Promise<void> {
  await act(async () => {
    render(<SignupPage />);
  });
}

describe("signup with the kill switch off", () => {
  it("says it is closed before any form", async () => {
    stubApi(CLOSED);
    await mount();
    expect(await screen.findByText("Signing up online is closed")).toBeTruthy();
    expect(screen.queryByLabelText("Business name")).toBeNull();
    expect(screen.queryByLabelText("Work email")).toBeNull();
  });

  it("asks only whether signing up is open, and nothing else", async () => {
    const calls = stubApi(CLOSED);
    await mount();
    await screen.findByText("Signing up online is closed");
    expect(calls.every((call) => !call.url.includes("/v1/auth/signup"))).toBe(true);
  });

  it("gives a way to reach a person when no contact address is configured", async () => {
    expect(process.env.NEXT_PUBLIC_SIGNUP_CONTACT_EMAIL ?? "").toBe("");
    stubApi(CLOSED);
    await mount();
    await screen.findByText("Signing up online is closed");
    const mail = resolvePlaceholders("{{SUPPORT_EMAIL}}");
    const link = screen.getByRole("link", { name: mail });
    expect(link.getAttribute("href")).toBe(`mailto:${mail}`);
  });

  it("sends someone who already has an account to sign in, not to a path to type", async () => {
    // E2E audit OB-21.
    stubApi(CLOSED);
    await mount();
    await screen.findByText("Signing up online is closed");
    expect(screen.getByRole("link", { name: "Sign in" }).getAttribute("href")).toBe(CLIENT_SIGN_IN_PATH);
    expect(document.body.textContent).not.toContain("/c/your-slug");
    expect(document.body.textContent).not.toContain("Nothing here places a call");
  });

  it("does not call signup closed when it could not read the switch", async () => {
    stubApi({
      "GET /v1/auth/client/sign-in-options": problem(503, { title: "Service unavailable" }),
    });
    await mount();
    expect(await screen.findByText("We could not open signup")).toBeTruthy();
    expect(screen.queryByText("Signing up online is closed")).toBeNull();
  });

  it("promises no turnaround it cannot keep", async () => {
    stubApi(CLOSED);
    await mount();
    await screen.findByText("Signing up online is closed");
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("same day");
    expect(text).not.toMatch(/within \d/i);
    expect(text).not.toMatch(/\d+\s*(hours|hrs|minutes)/i);
    expect(text).toContain("set up by hand with you");
  });
});
