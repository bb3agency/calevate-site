import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminSignInPage from "@/app/(auth)/auth/admin/sign-in/page";
import { OtpInput, sanitizeOtp } from "@/components/interior/otp-input";
import { ApiProblem } from "@/lib/api/client";
import { adminAuthn, adminSignedInDestination } from "@/lib/authn/adminAuthn";
import { clientAuthn, clientSignedInDestination } from "@/lib/authn/clientAuthn";
import { safeNextPath, withNext } from "@/lib/authn/nextPath";
import { OTP_LENGTH, OTP_RESEND_COOLDOWN_MS } from "@/lib/authn/otp";
import { AUTHN_CODES, signInMessage } from "@/lib/authn/problems";

import { problem, stubApi, type Routes } from "./harness";

/**
 * The emailed-code step: the OTP field's own behaviour, the sign-in form that drives it,
 * the error mapping for every code the server can refuse it with, and `?next=`.
 */

const SIGNED_OUT: Routes = {
  "GET /v1/auth/admin/session": problem(401, {
    type: "urn:calevate:auth/unauthorized",
    title: "Unauthorized",
    detail: "Your session is not valid. Sign in again.",
    kind: "auth",
  }),
};

beforeEach(() => {
  adminAuthn.reset();
  clientAuthn.reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

// ─────────────────────────────── the field ───────────────────────────────

function Harness({
  onComplete = () => {},
  readOnly = false,
}: {
  onComplete?: (value: string) => void;
  readOnly?: boolean;
}) {
  const [value, setValue] = useState("");
  return (
    <OtpInput
      label="Six-digit code"
      value={value}
      onChange={setValue}
      onComplete={onComplete}
      readOnly={readOnly}
    />
  );
}

const field = () => screen.getByLabelText("Six-digit code") as HTMLInputElement;

function paste(el: HTMLElement, text: string) {
  fireEvent.paste(el, { clipboardData: { getData: () => text } });
}

describe("the one-time-code field", () => {
  it("is ONE labelled input the platform can autofill, with a numeric keypad", () => {
    const view = render(<Harness />);
    const input = field();
    expect(input.getAttribute("autocomplete")).toBe("one-time-code");
    expect(input.getAttribute("inputmode")).toBe("numeric");
    expect(input.getAttribute("name")).toBe("one-time-code");
    // The boxes are drawing only: a screen reader meets one field, not six.
    expect(view.container.querySelectorAll("input")).toHaveLength(1);
    expect(view.container.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it("keeps digits only and never more than the code's length", () => {
    expect(sanitizeOtp("12a3 4-5678", 6)).toBe("123456");
    render(<Harness />);
    fireEvent.change(field(), { target: { value: "1a" } });
    expect(field().value).toBe("1");
    fireEvent.change(field(), { target: { value: "12" } });
    expect(field().value).toBe("12");
  });

  it("steps back on Backspace (the input loses its last digit)", () => {
    render(<Harness />);
    fireEvent.change(field(), { target: { value: "123" } });
    fireEvent.change(field(), { target: { value: "12" } });
    expect(field().value).toBe("12");
  });

  it("takes a pasted code whole, even out of a sentence, and completes once", () => {
    const onComplete = vi.fn();
    render(<Harness onComplete={onComplete} />);
    fireEvent.change(field(), { target: { value: "9" } });
    paste(field(), "Your Calevate code is 123 456.");
    // A full paste REPLACES what was typed rather than appending after it.
    expect(field().value).toBe("123456");
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledWith("123456");
  });

  it("appends a partial paste after what is already there", () => {
    render(<Harness />);
    fireEvent.change(field(), { target: { value: "12" } });
    paste(field(), "34");
    expect(field().value).toBe("1234");
  });

  it("completes once per full code, not once per event", () => {
    const onComplete = vi.fn();
    render(<Harness onComplete={onComplete} />);
    fireEvent.change(field(), { target: { value: "123456" } });
    // The same value again (an autofill landing after a paste) is not a new code.
    fireEvent.change(field(), { target: { value: "123456" } });
    paste(field(), "123456");
    expect(onComplete).toHaveBeenCalledTimes(1);
    fireEvent.change(field(), { target: { value: "12345" } });
    fireEvent.change(field(), { target: { value: "123457" } });
    expect(onComplete).toHaveBeenCalledTimes(2);
  });

  it("takes no paste while a check is in flight", () => {
    render(<Harness readOnly />);
    paste(field(), "123456");
    expect(field().value).toBe("");
    expect(field().readOnly).toBe(true);
  });
});

// ─────────────────────────────── the sign-in step ───────────────────────────────

const OTP_PATH = "POST /v1/auth/admin/login/otp";
const RESEND_PATH = "POST /v1/auth/admin/login/otp/resend";

async function reachCodeStep(routes: Routes) {
  const calls = stubApi({
    ...SIGNED_OUT,
    "POST /v1/auth/admin/login": { status: "otp_required" },
    ...routes,
  });
  await act(async () => {
    render(<AdminSignInPage />);
  });
  fireEvent.change(await screen.findByLabelText("Email address"), {
    target: { value: "operator@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "correct-horse-battery" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByLabelText("Six-digit code");
  return calls;
}

const refusal = (status: number, code: string, headers: Record<string, string> = {}) =>
  problem(
    status,
    { type: `urn:calevate:auth/${code}`, title: "Refused", detail: "Refused.", kind: "auth" },
    headers,
  );

const codeCalls = (calls: { method: string; path: string }[], path: string) =>
  calls.filter((c) => `${c.method} ${c.path}` === path);

describe("the sign-in code step", () => {
  it("submits by itself on the last digit, exactly once", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, search: "" });
    const calls = await reachCodeStep({
      [OTP_PATH]: { realm: "admin", subject_id: "s", email_verified: true },
    });
    // A paste, the platform's autofill and an Enter, all landing together.
    paste(field(), "123456");
    fireEvent.change(field(), { target: { value: "123456" } });
    fireEvent.submit(field().closest("form")!);

    await waitFor(() => expect(assign).toHaveBeenCalled());
    expect(codeCalls(calls, OTP_PATH)).toHaveLength(1);
  });

  it("clears a wrong code, marks the field and keeps focus in it", async () => {
    await reachCodeStep({ [OTP_PATH]: refusal(401, AUTHN_CODES.invalidSecondFactor) });
    const input = field();
    input.focus();
    fireEvent.change(input, { target: { value: "000000" } });

    expect((await screen.findByRole("alert")).textContent).toContain("That code did not match");
    expect(field().value).toBe("");
    expect(field().getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(field());
  });

  it("says an expired code has expired, and sends the person to a new one", async () => {
    await reachCodeStep({ [OTP_PATH]: refusal(401, AUTHN_CODES.codeExpired) });
    fireEvent.change(field(), { target: { value: "123456" } });
    expect((await screen.findByRole("alert")).textContent).toContain("That code has expired");
  });

  it("states the wait the server gave for too many attempts", async () => {
    await reachCodeStep({
      [OTP_PATH]: refusal(429, AUTHN_CODES.tooManyAttempts, { "Retry-After": "540" }),
    });
    fireEvent.change(field(), { target: { value: "123456" } });
    expect((await screen.findByRole("alert")).textContent).toContain("Try again in 9 minutes");
  });

  it("starts the resend countdown at the server's cooldown", async () => {
    await reachCodeStep({});
    const resend = screen.getByRole("button", { name: /Send a new code in/ });
    expect((resend as HTMLButtonElement).disabled).toBe(true);
    expect(resend.textContent).toContain(`${OTP_RESEND_COOLDOWN_MS / 1000}s`);
  });

  it("restarts the countdown from Retry-After when the server refuses a resend", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await reachCodeStep({
      [RESEND_PATH]: refusal(429, AUTHN_CODES.resendTooSoon, { "Retry-After": "42" }),
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OTP_RESEND_COOLDOWN_MS + 1_000);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Send a new code" }));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect((await screen.findByRole("alert")).textContent).toContain("We sent a code moments ago");
    const resend = screen.getByRole("button", { name: /Send a new code in/ });
    expect(resend.textContent).toMatch(/4[12]s/);
    expect((resend as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("the refusal copy for codes", () => {
  const p = (status: number, code: string, retryAfter?: number) =>
    new ApiProblem(status, { type: `urn:calevate:auth/${code}`, title: "t", detail: "d" }, retryAfter);

  it.each([
    [401, AUTHN_CODES.invalidSecondFactor, "That code did not match"],
    [401, AUTHN_CODES.invalidCode, "That code did not match"],
    [401, AUTHN_CODES.codeExpired, "That code has expired"],
    [429, AUTHN_CODES.resendTooSoon, "We sent a code moments ago"],
    [429, AUTHN_CODES.tooManyAttempts, "Too many attempts"],
  ])("%i %s reads as a sentence a person can act on", (status, code, expected) => {
    expect(signInMessage(p(status, code))).toContain(expected);
  });

  it("rounds a short wait up to a minute rather than saying zero", () => {
    expect(signInMessage(p(429, AUTHN_CODES.tooManyAttempts, 20))).toBe(
      "Too many attempts. Try again in a minute.",
    );
  });
});

// ─────────────────────────────── ?next= ───────────────────────────────

describe("where signing in returns a person to", () => {
  it.each([
    ["/c/acme/leads?status=hot#top", "/c", "/c/acme/leads?status=hot#top"],
    ["/c", "/c", "/c"],
    ["/admin/tenants/42", "/admin", "/admin/tenants/42"],
  ])("accepts %s inside %s", (raw, prefix, expected) => {
    expect(safeNextPath(raw, prefix)).toBe(expected);
  });

  it.each([
    "https://evil.example/c",
    "//evil.example/c",
    "/\\evil.example/c",
    "\\\\evil.example",
    "javascript:alert(1)",
    "/admin",
    "/cx/elsewhere",
    "/c/../admin",
    "/c/\u0000",
    "/c/a\nb",
    "",
    `/c/${"a".repeat(3000)}`,
  ])("refuses %j for the client console", (raw) => {
    expect(safeNextPath(raw, "/c")).toBeNull();
  });

  it("refuses the client console for the operator realm", () => {
    expect(safeNextPath("/c/acme", "/admin")).toBeNull();
  });

  it("carries the page a gate sent away from, and nothing for the front door", () => {
    expect(withNext("/auth/sign-in", "/c/acme/calls?x=1")).toBe(
      "/auth/sign-in?next=%2Fc%2Facme%2Fcalls%3Fx%3D1",
    );
    expect(withNext("/auth/sign-in", "/")).toBe("/auth/sign-in");
    expect(withNext("/auth/sign-in", "/auth/sign-in?next=x")).toBe("/auth/sign-in");
  });

  it("lands each realm on its own `next`, or on its own console", () => {
    window.history.replaceState(null, "", "/auth/sign-in?next=%2Fc%2Facme%2Fcalls");
    expect(clientSignedInDestination()).toBe("/c/acme/calls");
    expect(adminSignedInDestination()).toBe("/admin");

    window.history.replaceState(null, "", "/auth/admin/sign-in?next=https%3A%2F%2Fevil.example");
    expect(adminSignedInDestination()).toBe("/admin");
    expect(clientSignedInDestination()).toBe("/c");
  });
});

// ─────────────────────────────── pinned to the server ───────────────────────────────

describe("the code's shape is the server's", () => {
  const api = (file: string) =>
    readFileSync(join(process.cwd(), "..", "..", "apps", "api", "authn", file), "utf8");

  it("OTP_LENGTH is the server's OTP_DIGITS", () => {
    const found = /^OTP_DIGITS: Final = (\d+)/m.exec(api("codes.py"));
    expect(found, "OTP_DIGITS not found in apps/api/authn/codes.py").not.toBeNull();
    expect(OTP_LENGTH).toBe(Number(found![1]));
  });

  it("the resend countdown is the server's cooldown", () => {
    const found = /^OTP_RESEND_COOLDOWN: Final = timedelta\(seconds=(\d+)\)/m.exec(api("otp.py"));
    expect(found, "OTP_RESEND_COOLDOWN not found in apps/api/authn/otp.py").not.toBeNull();
    expect(OTP_RESEND_COOLDOWN_MS).toBe(Number(found![1]) * 1000);
  });
});
