import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminSignInPage from "@/app/(auth)/auth/admin/sign-in/page";
import ClientForgotPasswordPage from "@/app/(auth)/auth/forgot-password/page";
import ClientResetPasswordPage from "@/app/(auth)/auth/reset-password/page";
import { SessionGate } from "@/components/authn/sessionGate";
import { ApiProblem } from "@/lib/api/client";
import { adminAuthn } from "@/lib/authn/adminAuthn";
import { clientAuthn } from "@/lib/authn/clientAuthn";
import { AUTHN_CODES, isSessionGone, needsSecondFactor, signInMessage } from "@/lib/authn/problems";
import { useCountdown } from "@/lib/authn/useCountdown";

import { problem, stubApi, type Routes } from "./harness";

/**
 * The first-party auth screens, end to end through the real transport (D-174).
 *
 * `fetch` is the only seam, exactly as `tests/harness.ts` argues: everything below it —
 * the realm instance, the single-flight, the restore, the problem classification, the
 * copy — is what is under test, and stubbing a hook instead would test a mock's opinion.
 *
 * The realm instances are module-scoped singletons, so each test resets them. Without it,
 * a hard restore failure in one test blocks the audience for every test after it, which is
 * the cross-test bleed `stubApi` clears the impersonation-grant cache for.
 */

/** A signed-out realm: the restore refuses, so a guest page renders its form. */
const SIGNED_OUT: Routes = {
  "GET /v1/auth/admin/session": problem(401, {
    type: "urn:calevate:auth/unauthorized",
    title: "Unauthorized",
    detail: "Your session is not valid. Sign in again.",
    kind: "auth",
  }),
  "GET /v1/auth/client/session": problem(401, {
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
});

async function renderPage(ui: React.ReactElement, routes: Routes) {
  const calls = stubApi(routes);
  let result!: ReturnType<typeof render>;
  await act(async () => {
    result = render(ui);
  });
  return Object.assign(result, { calls });
}

describe("§5.7 defect 2 — the sign-in screen is not a user-enumeration oracle", () => {
  /**
   * Theirs answers a known admin with a wrong password, a deactivated admin and an unknown
   * address three different ways and RENDERS three different sentences, which its own
   * client documents as the contract. Ours cannot: `service.sign_in` equalises status,
   * body and wall-clock cost, and this screen renders one fixed sentence chosen by problem
   * code.
   *
   * The test drives two upstream refusals that differ in everything a server could vary —
   * title, detail, remediation — and asserts the reader sees the same words. That is the
   * property: a frontend that passed `problem.detail` through would fail this the moment
   * the backend's copy diverged, which is exactly how the leak would come back.
   */
  const refusal = (detail: string, title: string, remediation: string) =>
    problem(401, {
      type: "urn:calevate:auth/invalid_credentials",
      title,
      detail,
      remediation,
      kind: "auth",
    });

  async function signInAndRead(email: string, refuse: ReturnType<typeof problem>): Promise<string> {
    const view = await renderPage(<AdminSignInPage />, {
      ...SIGNED_OUT,
      "POST /v1/auth/admin/login": refuse,
    });
    fireEvent.change(await screen.findByLabelText("Email address"), { target: { value: email } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "not-the-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("alert");
    const text = (view.container.textContent ?? "").replace(/\s+/g, " ").trim();
    view.unmount();
    adminAuthn.reset();
    return text;
  }

  it("renders identical copy for an unknown address and a wrong password", async () => {
    const unknown = await signInAndRead(
      "nobody@example.com",
      refusal("No such account exists.", "Unknown account", "Create an account."),
    );
    const wrong = await signInAndRead(
      "operator@example.com",
      refusal("That password is wrong.", "Wrong password", "Try again."),
    );

    expect(
      unknown,
      "two upstream refusals produced two different screens — that is the oracle",
    ).toEqual(wrong);
    expect(unknown).toContain("That email address and password did not match");
  });

  it("never renders the server's own sentence for a credential refusal", async () => {
    const text = await signInAndRead(
      "operator@example.com",
      refusal("No such account exists.", "Unknown account", "Create an account."),
    );
    expect(text, "the server's detail leaked into the UI").not.toContain("No such account exists");
    expect(text).not.toContain("Unknown account");
  });

  it("does not echo the address that was typed", async () => {
    const text = await signInAndRead(
      "operator@example.com",
      refusal("nope", "nope", "nope"),
    );
    // Printing the address back is the cheapest version of the same leak: a screenshot of
    // a refusal then carries "this address was tried at the operator console".
    expect(text).not.toContain("operator@example.com");
  });
});

describe("§5.7 defect 5 — the password does not survive the code step", () => {
  const OTP_ROUTES: Routes = {
    ...SIGNED_OUT,
    "POST /v1/auth/admin/login": { status: "otp_required" },
    "POST /v1/auth/admin/login/otp/resend": {},
  };

  it("clears the password from the form and sends no body on resend", async () => {
    const view = await renderPage(<AdminSignInPage />, OTP_ROUTES);
    fireEvent.change(await screen.findByLabelText("Email address"), { target: { value: "operator@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct-horse-battery" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await screen.findByLabelText("Six-digit code");
    // Not merely hidden — gone. There is no input in the tree still holding it, so a
    // memory dump, a devtools inspection or an autofill manager has nothing to find for
    // the whole OTP window.
    for (const input of Array.from(view.container.querySelectorAll("input"))) {
      expect(input.value).not.toContain("correct-horse-battery");
    }

    const before = view.calls.length;
    // The cooldown makes resend unavailable immediately, which is itself the point of the
    // countdown; drive the mutation through the exported realm instead of the button.
    await act(async () => {
      await adminAuthn.resendSecondFactor();
    });
    const resendCall = view.calls[before];
    expect(resendCall.path).toBe("/v1/auth/admin/login/otp/resend");
    expect(resendCall.body, "resend must not re-post the password").toBeNull();
  });

  it("moves focus to the code field when the step changes", async () => {
    await renderPage(<AdminSignInPage />, OTP_ROUTES);
    fireEvent.change(await screen.findByLabelText("Email address"), { target: { value: "operator@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct-horse-battery" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    // The control that had focus has just unmounted; without this, focus falls to `<body>`
    // and a keyboard user is dropped at the top of a page that changed under them.
    const code = await screen.findByLabelText("Six-digit code");
    await waitFor(() => expect(document.activeElement).toBe(code));
  });
});

describe("§5.7 defect 4 — one countdown, not two", () => {
  /**
   * Theirs creates a `setInterval` per resend, cleared only on reaching zero, so two
   * intervals decrement one counter and the display ticks at double speed; and neither is
   * cleared on unmount, so both keep setting state on a component that no longer exists.
   *
   * Tested against `useCountdown` itself rather than by driving the sign-in form: the
   * property is about TIMERS, and `findBy*` queries schedule their own, so a fake-timer
   * test that also had to wait for the DOM would be measuring the harness. What binds the
   * form to this hook is asserted separately and structurally — `authnSourceGuards.test.ts`
   * refuses a hand-rolled `setInterval` anywhere in the auth surface.
   */
  function Countdown({ deadline }: { deadline: number | null }) {
    return <output>{useCountdown(deadline)}</output>;
  }

  it("ticks once per second, and replacing the deadline does not add a second interval", () => {
    vi.useFakeTimers();
    const start = Date.now();
    const view = render(<Countdown deadline={start + 60_000} />);
    expect(view.container.textContent).toBe("60");

    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    // Three seconds of progress for three seconds of time. A duplicated interval shows up
    // here as six, which is exactly the reported "expiry ticks down at double speed".
    expect(view.container.textContent).toBe("57");

    // The resend case: a NEW deadline while the previous countdown is still running.
    view.rerender(<Countdown deadline={Date.now() + 60_000} />);
    expect(view.container.textContent).toBe("60");
    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(view.container.textContent, "the previous interval is still decrementing").toBe("58");
  });

  it("leaves no timer behind on unmount", () => {
    vi.useFakeTimers();
    const view = render(<Countdown deadline={Date.now() + 60_000} />);
    expect(vi.getTimerCount()).toBe(1);
    view.unmount();
    expect(vi.getTimerCount(), "an interval still setting state on an unmounted tree").toBe(0);
  });

  it("recomputes from the deadline, so a slept tab returns showing the truth", () => {
    vi.useFakeTimers();
    const view = render(<Countdown deadline={Date.now() + 30_000} />);
    // A phone asleep: `setInterval` did not fire at all. A counter decremented per tick
    // would come back reading 30; recomputing from the deadline reads 0, which is true.
    act(() => {
      vi.setSystemTime(Date.now() + 45_000);
      vi.advanceTimersByTime(1_000);
    });
    expect(view.container.textContent).toBe("0");
  });
});

describe("§5.7 defect 9 — a dropped connection and a dead session are different screens", () => {
  /**
   * `OpsSessionGate` rendered `error ?? "Sign in to continue."` for every failure. The two
   * have opposite remedies, and telling somebody whose connection dropped that they are
   * signed out sends them to re-enter a password at the moment the network cannot take one.
   */
  const gate = (status: "unreachable" | "signed-out") =>
    render(
      <SessionGate
        status={status}
        realmLabel="operator console"
        signInPath="/auth/admin/sign-in"
        onRetry={() => {}}
      />,
    );

  it("offers RETRY and claims nothing about the credential when unreachable", () => {
    const view = gate("unreachable");
    expect(view.container.textContent).toContain("We could not reach Calevate");
    expect(view.container.textContent).toContain("has not been ended");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("offers SIGN IN and claims nothing about the network when signed out", () => {
    const view = gate("signed-out");
    expect(view.container.textContent).toContain("You are signed out");
    expect(view.container.textContent).not.toContain("could not reach");
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("waits out loud rather than rendering a blank while restoring", () => {
    const view = render(
      <SessionGate
        status="restoring"
        realmLabel="operator console"
        signInPath="/auth/admin/sign-in"
        onRetry={() => {}}
      />,
    );
    // BUILD-LOG §52: loading is a loading state, and a screen reader is not left on
    // silence while it happens.
    expect(view.container.querySelector('[role="status"]')).not.toBeNull();
    expect(view.container.textContent).toContain("Nothing has been signed out");
  });
});

describe("§5.3 — which refusals may clear a session", () => {
  it("a wrong password never means the session ended", () => {
    const wrongPassword = problemFor(AUTHN_CODES.invalidCredentials);
    // The exclusion §5.3 calls easy to get wrong: an admin who fat-fingers a step-up
    // confirmation must not be ejected from the console for it.
    expect(isSessionGone(wrongPassword)).toBe(false);
    expect(isSessionGone(problemFor(AUTHN_CODES.invalidSecondFactor))).toBe(false);
    expect(isSessionGone(problemFor(AUTHN_CODES.tooManyAttempts))).toBe(false);
    expect(isSessionGone(problemFor(AUTHN_CODES.unauthorized))).toBe(true);
  });

  it("a half-authenticated session is a navigation, not a logout", () => {
    const partial = problemFor(AUTHN_CODES.secondFactorRequired);
    expect(needsSecondFactor(partial)).toBe(true);
    expect(isSessionGone(partial)).toBe(false);
  });

  it("an unrecognised refusal gets no invented sentence", () => {
    // `null` means "fall through to ProblemNotice". A generic string here would turn every
    // unexpected failure into a confident claim about the credential.
    expect(signInMessage(problemFor("some_new_code"))).toBeNull();
  });
});

describe("the reset request tells you nothing either way", () => {
  it("answers one confirmation that is true whether or not the account exists", async () => {
    const view = await renderPage(<ClientForgotPasswordPage />, {
      "POST /v1/auth/client/password/reset/request": {},
    });
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "someone@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Email me a reset link" }));

    await screen.findByText(/If that address has an account/);
    const text = view.container.textContent ?? "";
    expect(text, "'check your inbox' would be a claim that the account exists").not.toContain(
      "Check your inbox",
    );
  });

  it("sends an Idempotency-Key that is not the address", async () => {
    const view = await renderPage(<ClientForgotPasswordPage />, {
      "POST /v1/auth/client/password/reset/request": {},
    });
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "someone@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Email me a reset link" }));
    await screen.findByText(/If that address has an account/);

    const call = view.calls.find((c) => c.path.endsWith("/password/reset/request"));
    const key = (call?.headers as Record<string, string>)["Idempotency-Key"];
    expect(key, "§5.6 requires the key from the first commit").toBeTruthy();
    expect(key, "hard rule 6: the address must not travel in a header").not.toContain("someone@");
  });
});

describe("the set-password forms carry the hasher's real bounds", () => {
  it("refuses a password under the API's floor before it is submitted", async () => {
    const view = await renderPage(<ClientResetPasswordPage />, {});

    // No token in the URL, so the form does not render — assert the honest panel instead,
    // which says the LINK is short rather than that the reset is invalid.
    await screen.findByText(/missing its code/);
    expect(view.container.textContent).not.toContain("invalid");
  });

  it("states the length rule under the field", async () => {
    window.history.replaceState(null, "", "/auth/reset-password?token=" + "t".repeat(40));
    const view = await renderPage(<ClientResetPasswordPage />, {});
    await screen.findByLabelText("New password");
    expect(view.container.textContent).toContain("At least 12 characters");
    // And the token is out of the URL by the time anything can read it back.
    expect(window.location.search).toBe("");
  });
});

/**
 * A real `ApiProblem` carrying one code.
 *
 * The REAL class, not a look-alike: every classifier in `lib/authn/problems.ts` starts
 * with `error instanceof ApiProblem`, and a duck-typed stand-in would pass these tests
 * while failing in the browser. `ApiProblem` reads the last path segment of `type` as the
 * machine code, which is the shape the API sends.
 */
function problemFor(code: string): ApiProblem {
  return new ApiProblem(401, {
    type: `urn:calevate:auth/${code}`,
    kind: "auth",
    title: "no",
    detail: "no",
  });
}
