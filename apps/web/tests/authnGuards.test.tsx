import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminIdleTimeoutModal, ADMIN_IDLE_LOGOUT_MS, ADMIN_IDLE_WARNING_MS } from "@/components/authn/adminIdleTimeoutModal";
import { adminAuthn } from "@/lib/authn/adminAuthn";
import { ADMIN_WATCHDOG_MS, AdminSessionGate, AdminSessionProvider } from "@/lib/authn/adminSession";
import { RESTORE_DEADLINE_MS } from "@/lib/authn/realm";
import { useRealmSession } from "@/lib/authn/useRealmSession";

import { problem, stubApi, stillLoading, type Routes } from "./harness";

/**
 * The guard/gate/provider quartet, the generation counter, and the idle modal (D-174).
 *
 * §5.4 and §5.5 of `docs/evidence/raghava-platform-teardown.md`.
 */

const ADMIN_SESSION = {
  realm: "admin",
  subject_id: "0192f0aa-0000-7000-8000-000000000001",
  mfa_complete: true,
  email_verified: true,
};

const unauthorized = () =>
  problem(401, {
    type: "urn:calevate:auth/unauthorized",
    title: "Unauthorized",
    detail: "Your session is not valid.",
    kind: "auth",
  });

beforeEach(() => {
  adminAuthn.reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

async function renderGuarded(routes: Routes) {
  const calls = stubApi(routes);
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <AdminSessionProvider>
        <AdminSessionGate>
          <p>the operator console</p>
        </AdminSessionGate>
      </AdminSessionProvider>,
    );
  });
  return Object.assign(view, { calls });
}

describe("§5.5 — the gate is fail-closed", () => {
  it("renders the console only for a live, fully authenticated session", async () => {
    const view = await renderGuarded({ "GET /v1/auth/admin/session": ADMIN_SESSION });
    expect(await screen.findByText("the operator console")).toBeTruthy();
    expect(view.container.textContent).not.toContain("You are signed out");
  });

  it("shows the signed-out screen and NOT the console on a hard refusal", async () => {
    const view = await renderGuarded({ "GET /v1/auth/admin/session": unauthorized() });
    await screen.findByText("You are signed out");
    expect(view.container.textContent).not.toContain("the operator console");
  });

  it("shows the second-factor screen for a half-authenticated session", async () => {
    const view = await renderGuarded({
      "GET /v1/auth/admin/session": problem(401, {
        type: "urn:calevate:auth/second_factor_required",
        title: "Two-factor authentication required",
        detail: "This session has not completed two-factor authentication.",
        kind: "auth",
      }),
    });
    await screen.findByText(/still needs its emailed code/);
    // Alive and one door short: neither the console (every call refused) nor the
    // signed-out screen (a session that is one code away from working, thrown out).
    expect(view.container.textContent).not.toContain("the operator console");
    expect(view.container.textContent).not.toContain("You are signed out");
  });

  it("waits rather than flashing the console while restoring", async () => {
    const view = await renderGuarded({ "GET /v1/auth/admin/session": stillLoading() });
    expect(view.container.textContent).toContain("Checking your operator console session");
    expect(view.container.textContent).not.toContain("the operator console");
  });
});

describe("§5.4 — the generation counter", () => {
  /**
   * A restore that started before a sign-in must not resolve after it and overwrite the
   * fresh session with its stale answer. The answer that matters is `signed_out`: without
   * the counter it logs out a user who has, at that instant, just successfully logged in.
   */
  function Probe() {
    const { status, adopt } = useRealmSession(adminAuthn, "session");
    return (
      <>
        <output>{status}</output>
        <button type="button" onClick={() => adopt(ADMIN_SESSION)}>
          adopt
        </button>
      </>
    );
  }

  it("drops a restore that resolves after the realm generation moved", async () => {
    let settle!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => (settle = resolve))),
    );

    const view = render(<Probe />);
    await waitFor(() => expect(view.container.querySelector("output")?.textContent).toBe("restoring"));

    // A fresh sign-in lands while the restore is still in flight. `signIn` and the second
    // factor both call `reset()`, which is what bumps the generation.
    act(() => {
      adminAuthn.reset();
      fireEvent.click(screen.getByRole("button", { name: "adopt" }));
    });
    expect(view.container.querySelector("output")?.textContent).toBe("ready");

    // ...and only now does the old restore answer, with the worst possible answer.
    await act(async () => {
      settle(
        new Response(JSON.stringify({ type: "urn:calevate:auth/unauthorized", kind: "auth" }), {
          status: 401,
          headers: { "content-type": "application/problem+json" },
        }),
      );
      await Promise.resolve();
    });

    expect(
      view.container.querySelector("output")?.textContent,
      "a stale restore cleared a session that had already been established",
    ).toBe("ready");
  });
});

describe("§5.5 — the watchdog only ever redirects, and only after the deadline", () => {
  it("is scheduled after the restore deadline, so it cannot pre-empt a slow success", () => {
    // Theirs fires at 12s against a 15s deadline, so a slow-but-working 13-second restore
    // is redirected away — which contradicts the same file's rule that a timeout is soft.
    // Ours can only catch a gate that is still "restoring" after the machinery that was
    // supposed to resolve it did not.
    expect(ADMIN_WATCHDOG_MS).toBeGreaterThan(RESTORE_DEADLINE_MS);
  });

  it("is cleared as soon as the restore resolves", async () => {
    vi.useFakeTimers();
    const calls = stubApi({ "GET /v1/auth/admin/session": ADMIN_SESSION });
    expect(calls).toHaveLength(0);

    await act(async () => {
      render(
        <AdminSessionProvider>
          <AdminSessionGate>
            <p>the operator console</p>
          </AdminSessionGate>
        </AdminSessionProvider>,
      );
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // Nothing left that could navigate a console which has already resolved.
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("§5.6 — the idle modal re-checks the SERVER'S answer before extending", () => {
  /**
   * §5.7 defect 7 is a client that decides authorization from an unverified JWT claim. We
   * hold no token, so the equivalent check is the server's own `SessionOut`, freshly
   * re-read from the subject row — which means a deactivated operator pressing "stay
   * signed in" is signed out by it rather than extended.
   */
  const warn = async (): Promise<void> => {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ADMIN_IDLE_WARNING_MS + 10);
    });
  };

  it("warns before the server's own idle bound, and lands exactly on it", () => {
    // 25 + 5 = 30 minutes = `REALM_TIMEOUTS["admin"].idle`. The equality is the
    // justification: the polling console keeps sliding the server's window, so this is
    // what makes the 30 minutes mean what it says.
    expect(ADMIN_IDLE_WARNING_MS + ADMIN_IDLE_LOGOUT_MS).toBe(30 * 60 * 1000);
  });

  it("extends when the refreshed session is still a complete admin session", async () => {
    vi.useFakeTimers();
    const calls = stubApi({ "POST /v1/auth/admin/session/refresh": ADMIN_SESSION });
    const view = render(<AdminIdleTimeoutModal enabled />);

    await warn();
    expect(view.container.textContent).toContain("Still there?");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Stay signed in" }));
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(calls.some((c) => c.path.endsWith("/session/refresh"))).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(view.container.textContent).not.toContain("Still there?");
  });

  it("signs out when the refreshed session is no longer a complete admin session", async () => {
    vi.useFakeTimers();
    const calls = stubApi({
      "POST /v1/auth/admin/session/refresh": { ...ADMIN_SESSION, mfa_complete: false },
      "POST /v1/auth/admin/logout": { revoked: 1 },
    });
    render(<AdminIdleTimeoutModal enabled />);

    await warn();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Stay signed in" }));
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(calls.some((c) => c.path.endsWith("/logout"))).toBe(true);
  });

  it("does NOT sign out when the extension request simply failed", async () => {
    vi.useFakeTimers();
    const calls = stubApi({
      "POST /v1/auth/admin/session/refresh": problem(503, {
        type: "urn:calevate:internal/unavailable",
        title: "Unavailable",
        detail: "Unavailable",
        kind: "internal",
      }),
      "POST /v1/auth/admin/logout": { revoked: 1 },
    });
    const view = render(<AdminIdleTimeoutModal enabled />);

    await warn();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Stay signed in" }));
      await vi.advanceTimersByTimeAsync(0);
    });

    // §5.7 defect 9 with teeth: ending a live admin session because one request did not
    // land is the same conflation, applied to something a person loses work over.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(view.container.textContent).toContain("could not extend");
    expect(calls.some((c) => c.path.endsWith("/logout"))).toBe(false);
    expect(view.container.textContent, "the countdown must keep running").toContain("Still there?");
  });

  it("runs no timers at all when there is no session to protect", () => {
    vi.useFakeTimers();
    stubApi({});
    render(<AdminIdleTimeoutModal enabled={false} />);
    expect(vi.getTimerCount()).toBe(0);
  });
});
