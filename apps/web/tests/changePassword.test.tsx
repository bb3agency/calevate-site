import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ClientAccountPage from "@/app/(auth)/auth/account/page";
import AdminSessionPage from "@/app/(auth)/auth/admin/page";
import { revokedSentence } from "@/components/authn/changePasswordForm";
import { adminAuthn } from "@/lib/authn/adminAuthn";
import { clientAuthn } from "@/lib/authn/clientAuthn";
import { createRealmAuthn } from "@/lib/authn/realm";

import { problem, stubApi, type ApiCall, type Routes } from "./harness";

/**
 * "Change password" on both realms' account screens (`POST /password/change`).
 *
 * Driven through the real transport with `fetch` as the only seam, for the reason
 * `tests/harness.tsx` argues: everything under it — the realm instance, the rotation
 * barrier, the problem classification, the copy — is what is under test. The two realms
 * are exercised through their OWN pages and their own module-scoped instances, never
 * through a shared helper that would prove one and claim the other.
 */

const CURRENT = "the-one-i-have-today";
/** Comfortably past the client realm's 15-character floor, so both realms accept it. */
const NEXT = "seven league boots wander";

const AUTH = "That did not work";

/**
 * The client account page reads `/v1/me` for the account block at the top of it. None of
 * these tests is about that block, so it is answered here rather than in each table — an
 * unanswered route is a refusal arm rendering over the form under test.
 */
const ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage"],
  impersonating: false,
  organization: {
    id: "0192f0aa-0000-7000-8000-0000000000d1",
    name: "Sri Lakshmi Dental",
    slug: "sri-lakshmi-dental",
    status: "active",
  },
};

async function renderPage(ui: React.ReactElement, routes: Routes): Promise<ApiCall[]> {
  const calls = stubApi({ "/v1/me": ME, ...routes });
  await act(async () => {
    render(ui);
  });
  return calls;
}

/** Fill all three boxes and press the button. */
async function fillAndSubmit(next = NEXT): Promise<void> {
  fireEvent.change(await screen.findByLabelText("Current password"), {
    target: { value: CURRENT },
  });
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: next } });
  fireEvent.change(screen.getByLabelText("Type it again"), { target: { value: next } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
  });
}

/** The field's own message, read through the wiring `AuthField` gives a screen reader. */
function fieldMessage(label: string): string | null {
  const input = screen.getByLabelText(label);
  expect(input.getAttribute("aria-invalid")).toBe("true");
  const describedBy = (input.getAttribute("aria-describedby") ?? "").split(" ");
  for (const id of describedBy) {
    const node = document.getElementById(id);
    if (node?.getAttribute("role") === "alert") return node.textContent;
  }
  return null;
}

const CHANGED = (revoked: number) => ({ revoked });

beforeEach(() => {
  adminAuthn.reset();
  clientAuthn.reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("the client realm's account screen", () => {
  it("says every other session ends BEFORE anything is submitted", async () => {
    await renderPage(<ClientAccountPage />, {});
    // The person whose phone is about to be signed out has to be told while they can
    // still decide not to — a warning after the click is an explanation, not a choice.
    expect(await screen.findByText(/ends every other session on this account/)).toBeTruthy();
  });

  it("sends both passwords and says how many devices were signed out", async () => {
    const calls = await renderPage(<ClientAccountPage />, {
      "POST /v1/auth/client/password/change": CHANGED(2),
    });
    await fillAndSubmit();

    const change = calls.find((c) => c.path === "/v1/auth/client/password/change");
    expect(change?.method).toBe("POST");
    expect(JSON.parse(change?.body ?? "{}")).toEqual({
      current_password: CURRENT,
      new_password: NEXT,
    });
    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("We signed you out of 2 other devices.");
    expect(status.textContent).toContain("You are still signed in here");
  });

  it("puts a wrong current password under the current-password box", async () => {
    await renderPage(<ClientAccountPage />, {
      "POST /v1/auth/client/password/change": problem(401, {
        kind: "auth",
        type: "urn:calevate:auth/invalid_current_password",
        title: "That is not your current password",
        detail: "The current password you entered does not match the one on your account.",
      }),
    });
    await fillAndSubmit();

    await waitFor(() =>
      expect(fieldMessage("Current password")).toContain(
        "That is not the current password on this account",
      ),
    );
    // NOT also in the notice: one refusal in two places reads as two failures.
    expect(screen.queryByText(AUTH)).toBeNull();
  });

  it("puts an unchanged password under the new-password box", async () => {
    await renderPage(<ClientAccountPage />, {
      "POST /v1/auth/client/password/change": problem(422, {
        kind: "validation",
        type: "urn:calevate:auth/password_unchanged",
        title: "That is the password you already have",
        detail: "The new password is the same as your current one.",
      }),
    });
    await fillAndSubmit();

    await waitFor(() =>
      expect(fieldMessage("New password")).toContain("That is the password you already have"),
    );
    expect(screen.queryByText(AUTH)).toBeNull();
  });

  it("renders the blocklist's own reason, which depends on what was typed", async () => {
    await renderPage(<ClientAccountPage />, {
      "POST /v1/auth/client/password/change": problem(422, {
        kind: "validation",
        type: "urn:calevate:auth/password_unacceptable",
        title: "Choose a different password",
        detail: "That password is too easy to guess.",
        fields: [
          { field: "password", rule: "blocklist", message: "it is a run of keyboard keys" },
        ],
      }),
    });
    await fillAndSubmit();

    // NIST SP 800-63B-4 §3.1.1.2 requires the REASON to reach the person, and the reason
    // is composed from the string they typed — no fixed local sentence could name it.
    await waitFor(() =>
      expect(fieldMessage("New password")).toContain("it is a run of keyboard keys"),
    );
  });

  it("refuses a password below THIS realm's floor without asking the server", async () => {
    const calls = await renderPage(<ClientAccountPage />, {});
    // Fourteen characters: legal on the admin realm, one short on this one. The floor is
    // per realm (NIST SP 800-63B-4 §3.1.1.2, `authn/policy.MIN_CHARS_BY_REALM`), and a
    // form showing the wrong realm's number is the §5.7 defect 8 shape one level up.
    await fillAndSubmit("fourteen chars");
    expect(
      (screen.getByRole("button", { name: "Change password" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(calls.some((c) => c.path.endsWith("/password/change"))).toBe(false);
    expect(screen.getByText(/At least 15 characters/)).toBeTruthy();
  });

  it("says too many attempts in the notice, where a 429 belongs", async () => {
    await renderPage(<ClientAccountPage />, {
      "POST /v1/auth/client/password/change": problem(429, {
        kind: "auth",
        type: "urn:calevate:auth/too_many_attempts",
        title: "Too many attempts",
        detail: "Wait before trying again.",
      }),
    });
    await fillAndSubmit();

    // No field is at fault, so there is no field to hang it under.
    expect(await screen.findByText(AUTH)).toBeTruthy();
    expect(
      screen.getByText("Too many attempts. Wait a few minutes before trying again."),
    ).toBeTruthy();
  });

  it("keeps the button unusable until the repeat matches", async () => {
    await renderPage(<ClientAccountPage />, {});
    fireEvent.change(await screen.findByLabelText("Current password"), {
      target: { value: CURRENT },
    });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: NEXT } });
    fireEvent.change(screen.getByLabelText("Type it again"), { target: { value: `${NEXT}x` } });
    expect(
      (screen.getByRole("button", { name: "Change password" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText("These two do not match.")).toBeTruthy();
  });

  it("gives each password box its own reveal control", async () => {
    await renderPage(<ClientAccountPage />, {});
    // The founder's decision is that every password field can be revealed; the a11y
    // requirement is that a screen-reader user listing the buttons can tell them apart.
    for (const name of ["Show current password", "Show new password", "Show the repeated password"]) {
      const toggle = await screen.findByRole("button", { name });
      expect(toggle.getAttribute("aria-pressed")).toBe("false");
      fireEvent.click(toggle);
      expect(toggle.getAttribute("aria-pressed")).toBe("true");
    }
  });
});

describe("the admin realm's account screen", () => {
  it("sends the change to the ADMIN realm's route", async () => {
    const calls = await renderPage(<AdminSessionPage />, {
      "POST /v1/auth/admin/password/change": CHANGED(0),
    });
    await fillAndSubmit();

    expect(calls.some((c) => c.path === "/v1/auth/admin/password/change")).toBe(true);
    expect(calls.some((c) => c.path === "/v1/auth/client/password/change")).toBe(false);
    expect((await screen.findByRole("status")).textContent).toContain(
      "There were no other sessions to sign out.",
    );
  });

  it("routes a stale second factor through the step-up prompt and retries", async () => {
    let proved = false;
    const calls = await renderPage(<AdminSessionPage />, {
      "POST /v1/auth/admin/password/change": () =>
        proved
          ? CHANGED(3)
          : problem(403, {
              kind: "auth",
              type: "urn:calevate:auth/reauthentication_required",
              title: "Confirm it is still you",
              detail: "This action needs a recently proved second factor.",
            }),
      "POST /v1/auth/admin/step-up": {},
      "POST /v1/auth/admin/step-up/verify": () => {
        proved = true;
        return {
          realm: "admin",
          subject_id: "0192f0aa-0000-7000-8000-00000000000a",
          mfa_complete: true,
          email_verified: true,
        };
      },
    });
    await fillAndSubmit();

    // The refusal opens the ONE prompt this console has, rather than a dead end telling
    // an operator to run two curls (`authn/stepup.reauthentication_required`).
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/Changing your operator password/)).toBeTruthy();

    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Email me a code" }));
    });
    fireEvent.change(within(dialog).getByLabelText("Six-digit code"), {
      target: { value: "123456" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    });

    // Retried because the route checks freshness BEFORE it writes anything, which is the
    // property `lib/api/admin.ts::mint` retries on too.
    await waitFor(() =>
      expect(
        calls.filter((c) => c.path === "/v1/auth/admin/password/change"),
      ).toHaveLength(2),
    );
    expect((await screen.findByRole("status")).textContent).toContain(
      "We signed you out of 3 other devices.",
    );
  });
});

describe("the rotation barrier holds for a password change, exactly as for a refresh", () => {
  /**
   * `service.change_password` rotates the caller's session and then revokes every other
   * one INCLUDING the superseded row, so from the instant the response lands the old
   * cookie is retired — and `verify_session` reads a retired token as replay and revokes
   * the whole family (RFC 9700 §4.14.2). A request dispatched while the change is in
   * flight is carrying exactly that cookie.
   *
   * That failure is intermittent by construction — it depends on whether some background
   * query happened to be in the air — which is why it is asserted here rather than left
   * to be noticed. Same shape as the `session/refresh` case in `authnSession.test.ts`.
   */
  interface Pending {
    path: string;
    resolve: (body: unknown) => void;
  }

  function deferredFetch(): Pending[] {
    const pending: Pending[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        return new Promise<Response>((resolve, reject) => {
          const signal = init?.signal;
          if (signal) signal.addEventListener("abort", () => reject(signal.reason), { once: true });
          pending.push({
            path: url.replace(/^.*\/v1/, "/v1"),
            resolve: (body) =>
              resolve(
                new Response(JSON.stringify(body), {
                  status: 200,
                  headers: { "content-type": "application/json" },
                }),
              ),
          });
        });
      }),
    );
    return pending;
  }

  const SESSION = {
    realm: "admin",
    subject_id: "0192f0aa-0000-7000-8000-000000000001",
    mfa_complete: true,
    email_verified: true,
  };

  it("holds other calls until an in-flight password change has settled", async () => {
    const pending = deferredFetch();
    // A fresh instance, as `authnSession.test.ts` does: the module-scoped realms are
    // shared across the whole process and this case needs an isolated one.
    const authn = createRealmAuthn("admin");

    const changing = authn.changePassword({ currentPassword: "a", newPassword: "b" });
    expect(pending).toHaveLength(1);

    const read = authn.readSession();
    await Promise.resolve();
    expect(
      pending,
      "a request must not go out while a password change is retiring the cookie",
    ).toHaveLength(1);

    pending[0].resolve({ revoked: 4 });
    await expect(changing).resolves.toBe(4);
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[1].path).toBe("/v1/auth/admin/session");
    pending[1].resolve(SESSION);
    await expect(read).resolves.toEqual(SESSION);
  });

  it("still single-flights an ordinary refresh", async () => {
    // The barrier was widened to cover two routes; this is the negative control that the
    // refresh's own single-flight survived the widening.
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");
    const first = authn.rotateSession();
    const second = authn.rotateSession();
    expect(pending).toHaveLength(1);
    pending[0].resolve(SESSION);
    await expect(first).resolves.toEqual(SESSION);
    await expect(second).resolves.toEqual(SESSION);
  });
});

describe("the revocation count, said in words", () => {
  it("counts none, one and many", () => {
    expect(revokedSentence(0)).toBe("There were no other sessions to sign out.");
    expect(revokedSentence(1)).toBe("We signed you out of 1 other device.");
    expect(revokedSentence(5)).toBe("We signed you out of 5 other devices.");
  });
});
