import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmailVerificationPanel } from "@/components/authn/emailVerificationPanel";
import { Providers } from "@/app/providers";
import { clientAuthn } from "@/lib/authn/clientAuthn";
import { OTP_RESEND_COOLDOWN_MS } from "@/lib/authn/otp";

import { problem, stubApi } from "./harness";

const WRONG_CODE = problem(400, {
  type: "urn:calevate:auth/invalid_second_factor",
  title: "Wrong code",
  detail: "That code is not right.",
  code: "invalid_second_factor",
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("verifying an address by emailed code", () => {
  it("shows a failed resend instead of the refusal of the code it replaced", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    stubApi({
      "POST /v1/auth/client/otp/request": {},
      "POST /v1/auth/client/otp/verify": WRONG_CODE,
    });
    render(
      <Providers>
        <EmailVerificationPanel authn={clientAuthn} onVerified={() => {}} />
      </Providers>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Email me a code" }));
    const boxes = await screen.findAllByRole("textbox");
    await act(async () => {
      fireEvent.paste(boxes[0], { clipboardData: { getData: () => "123456" } });
    });
    const wrong = (await screen.findAllByRole("alert")).map((node) => node.textContent).join(" ");
    expect(wrong).not.toBe("");

    stubApi({
      "POST /v1/auth/client/otp/request": problem(503, {
        type: "urn:calevate:internal/unavailable",
        title: "Unavailable",
        detail: "Unavailable",
        kind: "internal",
      }),
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OTP_RESEND_COOLDOWN_MS + 1_000);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Send another code" }));
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const after = screen.queryAllByRole("alert").map((node) => node.textContent).join(" ");
    expect(after).not.toBe("");
    expect(after).not.toBe(wrong);
  });
});
