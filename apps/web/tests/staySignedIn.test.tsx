import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminSessionPage from "@/app/(auth)/auth/admin/page";
import {
  AdminIdleTimeoutModal,
  idleDurationLabel,
  idleWarningAfterMs,
} from "@/components/authn/adminIdleTimeoutModal";
import { sessionLifetime } from "@/components/authn/staySignedInRow";

import { problem, stubApi, type Routes } from "./harness";

/**
 * "Stay signed in" (D-766): the switch on the operator's own account page, and the idle
 * warning counting down from the SERVER's bound for this session rather than a copy of 30.
 */

const OFF = {
  realm: "admin",
  subject_id: "0192f0aa-0000-7000-8000-00000000000a",
  mfa_complete: true,
  email_verified: true,
  idle_timeout_seconds: 30 * 60,
  stay_signed_in: false,
};
const ON = { ...OFF, idle_timeout_seconds: 12 * 60 * 60, stay_signed_in: true };

const ADMIN_ME = {
  realm: "admin",
  user_id: "00000000-0000-7000-8000-0000000000ad",
  role: "superadmin",
  permissions: ["org:read"],
  email: "ops@calevate.example",
};

const SWITCH_PATH = "/v1/auth/admin/stay-signed-in";
const LABEL = /Stay signed in on this device for up to 14 days/;

afterEach(() => {
  vi.useRealTimers();
});

async function renderPage(routes: Routes) {
  const calls = stubApi({ "/v1/admin/me": ADMIN_ME, ...routes });
  await act(async () => {
    render(<AdminSessionPage />);
  });
  return calls;
}

describe("the idle warning follows the server's bound", () => {
  const advance = async (ms: number) => {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  };

  it("warns at 25 minutes on an ordinary operator session", async () => {
    vi.useFakeTimers();
    stubApi({});
    const view = render(<AdminIdleTimeoutModal session={OFF} />);
    await advance(25 * 60 * 1000 + 10);
    expect(view.container.textContent).toContain("Still there?");
    expect(view.container.textContent).toContain("after 30 minutes");
  });

  it("does not warn at 25 minutes when the server allows twelve hours", async () => {
    vi.useFakeTimers();
    stubApi({});
    const view = render(<AdminIdleTimeoutModal session={ON} />);
    await advance(25 * 60 * 1000 + 10);
    expect(view.container.textContent).not.toContain("Still there?");
    await advance(idleWarningAfterMs(ON.idle_timeout_seconds) - 25 * 60 * 1000);
    expect(view.container.textContent).toContain("Still there?");
    expect(view.container.textContent).toContain("after 12 hours");
  });

  it("names the bound in words", () => {
    expect(idleDurationLabel(30 * 60)).toBe("30 minutes");
    expect(idleDurationLabel(12 * 60 * 60)).toBe("12 hours");
    expect(idleDurationLabel(60 * 60)).toBe("1 hour");
    expect(idleDurationLabel(60)).toBe("1 minute");
  });
});

describe("the switch on the operator's own account page", () => {
  it("is off by default and says what the session's bounds are", async () => {
    await renderPage({ "GET /v1/auth/admin/session": OFF });
    const toggle = await screen.findByRole("switch", { name: LABEL });
    expect((toggle as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText(/less secure on a shared device/i)).toBeTruthy();
    expect(screen.getByText(sessionLifetime(OFF))).toBeTruthy();
  });

  it("switches on through the server and adopts its answer", async () => {
    const calls = await renderPage({
      "GET /v1/auth/admin/session": OFF,
      [`POST ${SWITCH_PATH}`]: ON,
    });
    const toggle = await screen.findByRole("switch", { name: LABEL });
    await act(async () => {
      fireEvent.click(toggle);
    });

    const sent = calls.filter((c) => c.path === SWITCH_PATH);
    expect(sent).toHaveLength(1);
    expect(JSON.parse(sent[0].body ?? "{}")).toEqual({ stay_signed_in: true });
    await waitFor(() =>
      expect((screen.getByRole("switch", { name: LABEL }) as HTMLInputElement).checked).toBe(
        true,
      ),
    );
    expect(screen.getByText(sessionLifetime(ON))).toBeTruthy();
  });

  it("asks for a code when the second factor is stale, then retries", async () => {
    let proved = false;
    const calls = await renderPage({
      "GET /v1/auth/admin/session": OFF,
      [`POST ${SWITCH_PATH}`]: () =>
        proved
          ? ON
          : problem(403, {
              kind: "auth",
              type: "urn:calevate:auth/reauthentication_required",
              title: "Confirm it is still you",
              detail: "This action needs a recently proved second factor.",
            }),
      "POST /v1/auth/admin/step-up": {},
      "POST /v1/auth/admin/step-up/verify": () => {
        proved = true;
        return OFF;
      },
    });
    await act(async () => {
      fireEvent.click(await screen.findByRole("switch", { name: LABEL }));
    });

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/Keeping you signed in on this device/)).toBeTruthy();
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Email me a code" }));
    });
    fireEvent.change(within(dialog).getByLabelText("Six-digit code"), {
      target: { value: "123456" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    });

    await waitFor(() => expect(calls.filter((c) => c.path === SWITCH_PATH)).toHaveLength(2));
    await waitFor(() =>
      expect((screen.getByRole("switch", { name: LABEL }) as HTMLInputElement).checked).toBe(
        true,
      ),
    );
  });

  it("switches off without a code", async () => {
    const calls = await renderPage({
      "GET /v1/auth/admin/session": ON,
      [`POST ${SWITCH_PATH}`]: OFF,
    });
    const toggle = await screen.findByRole("switch", { name: LABEL });
    expect((toggle as HTMLInputElement).checked).toBe(true);
    await act(async () => {
      fireEvent.click(toggle);
    });
    const sent = calls.filter((c) => c.path === SWITCH_PATH);
    expect(JSON.parse(sent[0].body ?? "{}")).toEqual({ stay_signed_in: false });
    await waitFor(() =>
      expect((screen.getByRole("switch", { name: LABEL }) as HTMLInputElement).checked).toBe(
        false,
      ),
    );
  });

  it("shows the refusal when the change fails", async () => {
    await renderPage({
      "GET /v1/auth/admin/session": OFF,
      [`POST ${SWITCH_PATH}`]: problem(503, {
        type: "urn:calevate:internal/unavailable",
        title: "Unavailable",
        detail: "Unavailable",
        kind: "internal",
      }),
    });
    await act(async () => {
      fireEvent.click(await screen.findByRole("switch", { name: LABEL }));
    });
    expect((screen.getByRole("switch", { name: LABEL }) as HTMLInputElement).checked).toBe(false);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
