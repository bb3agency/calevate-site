import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import GlobalDncPage from "@/app/admin/ops/dnc/page";
import { OPS_DNC_GLOBAL_PATH, type GlobalDncEntry } from "@/lib/api/opsDnc";

import { problem, renderAdminPage, type Routes } from "./harness";

/**
 * Step-up re-authentication, from the operator's side of the glass (D-340).
 *
 * `apps/api/core/stepup.py` refuses any confirmed admin write whose session has not proved
 * a second factor in the last five minutes, and its `remediation` names two curl calls.
 * Nothing in the console rendered anything but that string, so the response to
 * "confirm it is still you" was a screen telling an operator mid-incident to go and write
 * HTTP by hand — while `lib/authn/problems.ts` already held the sentence that says the
 * session is fine and a code is what clears it, unread by any surface outside sign-in.
 *
 * Every assertion below is at the NETWORK SEAM, not on the component's internals: the two
 * endpoints, in order, with the operator's keystrokes between them. That is what makes
 * these fail against the old rendering rather than restate the new one.
 */

const SUPERADMIN: AdminMe = {
  user_id: "admin-1",
  realm: "admin",
  role: "superadmin",
  permissions: ["ops:manage", "admin:tenants"],
};

const LIST_PATH = `${OPS_DNC_GLOBAL_PATH}?limit=500`;
const STEP_UP_PATH = "/v1/auth/admin/step-up";
const VERIFY_PATH = "/v1/auth/admin/step-up/verify";

function entry(over: Partial<GlobalDncEntry> = {}): GlobalDncEntry {
  return {
    id: "0192f0aa-7777-7000-8000-000000000001",
    phone_masked: "+9198••••3210",
    scope: "global",
    source: "regulator",
    added_at: "2026-08-12T09:00:00Z",
    removable: false,
    ...over,
  };
}

/** The refusal `authn/stepup.reauthentication_required` actually sends, field for field. */
function staleFactor() {
  return problem(403, {
    type: "https://calevate.tech/problems/reauthentication_required",
    title: "Confirm it is still you",
    detail: "This action needs a second factor proved in the last 5 minutes.",
    status: 403,
    kind: "permission",
    retryable: false,
    remediation:
      "POST /v1/auth/admin/step-up to have a code emailed, POST the code to " +
      "/v1/auth/admin/step-up/verify, then repeat this request with " +
      "X-Confirm-Action: suppress_number_platform_wide",
  });
}

function routes(over: Routes = {}): Routes {
  return { [ADMIN_ME_PATH]: SUPERADMIN, [LIST_PATH]: [entry()], ...over };
}

/** Fill the suppression form and press the button, which is four keystrokes every test needs. */
async function attemptSuppression() {
  const button = await screen.findByRole("button", { name: /Suppress/ });
  fireEvent.change(screen.getByPlaceholderText(/9876543210/), {
    target: { value: "9876543210" },
  });
  fireEvent.change(screen.getByPlaceholderText(/TRAI escalation/), {
    target: { value: "TRAI escalation TR-4471" },
  });
  fireEvent.change(screen.getByPlaceholderText("SUPPRESS"), { target: { value: "SUPPRESS" } });
  // The control is fail-closed until `/v1/admin/me` answers; drawing a conclusion from a
  // button that was disabled for that reason would make every assertion below vacuous.
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(button);
  return button;
}

describe("a confirmed admin write refused for a stale second factor", () => {
  it("offers the two calls as controls instead of printing the curl", async () => {
    const { calls, container } = renderAdminPage(
      <GlobalDncPage />,
      routes({
        [`POST ${OPS_DNC_GLOBAL_PATH}`]: staleFactor(),
        [`POST ${STEP_UP_PATH}`]: {},
        [`POST ${VERIFY_PATH}`]: {
          realm: "admin",
          subject_id: "0192f0aa-0000-7000-8000-00000000000a",
          mfa_complete: true,
          email_verified: true,
        },
      }),
    );

    await attemptSuppression();

    // The sentence the console chose, not the server's `detail`. Its FIRST job is to stop
    // this being read as a logout and the action being abandoned.
    expect(await screen.findByText(/Your session is fine/)).toBeTruthy();
    // And the curl the server sent for a log reader is NOT what a screen with a button
    // shows. This is the assertion that fails against the old `ProblemNotice` rendering.
    expect(container.textContent).not.toContain("POST /v1/auth/admin/step-up");

    // Nothing is asked for until the operator asks — an emailed code is a side effect.
    expect(calls.filter((c) => c.path === STEP_UP_PATH)).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Email me a code" }));
    await waitFor(() => expect(calls.filter((c) => c.path === STEP_UP_PATH)).toHaveLength(1));

    // The code field appears only once the mail has actually left: a field nobody can
    // satisfy is worse than the button that failed to produce one.
    const field = await screen.findByLabelText(/Code from your email/);
    fireEvent.change(field, { target: { value: "482913" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(calls.filter((c) => c.path === VERIFY_PATH)).toHaveLength(1));
    const verify = calls.find((c) => c.path === VERIFY_PATH);
    expect(JSON.parse(verify?.body ?? "{}")).toEqual({ code: "482913" });
    // No bearer and no tenant header on `/v1/auth/**` — the cookie is the credential
    // (lib/authn/transport.ts), and a step-up is platform-level.
    expect(verify?.headers["Authorization"]).toBeUndefined();
    expect(verify?.headers["X-Org-Slug"]).toBeUndefined();

    // "Nothing was changed" is not decoration: `StepUp.require` refuses before the work
    // and the transaction rolls back, so an operator must not go and check.
    expect(await screen.findByText(/Nothing was changed by the refused attempt/)).toBeTruthy();
    // And with no `onRetry` wired for this write, the console says who presses next —
    // it does not re-send an irreversible action on the operator's behalf.
    expect(screen.getByText(/Press the control again to send the action/)).toBeTruthy();
  });

  it("keeps the operator in front of the code field when the code is wrong", async () => {
    const { calls } = renderAdminPage(
      <GlobalDncPage />,
      routes({
        [`POST ${OPS_DNC_GLOBAL_PATH}`]: staleFactor(),
        [`POST ${STEP_UP_PATH}`]: {},
        [`POST ${VERIFY_PATH}`]: problem(401, {
          type: "https://calevate.tech/problems/invalid_second_factor",
          title: "That code did not work",
          detail: "The code was not accepted.",
          status: 401,
          kind: "auth",
          retryable: false,
          remediation: "Check the most recent email, or ask for a new code.",
        }),
      }),
    );

    await attemptSuppression();
    fireEvent.click(await screen.findByRole("button", { name: "Email me a code" }));
    fireEvent.change(await screen.findByLabelText(/Code from your email/), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(calls.filter((c) => c.path === VERIFY_PATH)).toHaveLength(1));
    // The API's own sentence, which already names the remedy beside the field.
    expect(await screen.findByText(/Check the most recent email/)).toBeTruthy();
    // STILL in the code step. `invalid_second_factor` is a typo, not a dead session
    // (`isSessionGone` excludes it on purpose) — dropping back to "Email me a code" would
    // retire the code they are holding and lose the one they are looking at.
    expect(screen.getByRole("button", { name: "Confirm" })).toBeTruthy();
    // And the reason they are here has not been replaced by the reason the keystroke
    // failed: two failures, two remedies, both on screen.
    expect(screen.getByText(/Your session is fine/)).toBeTruthy();
  });

  it("does not strand the operator in a code step when the mail never left", async () => {
    const { calls } = renderAdminPage(
      <GlobalDncPage />,
      routes({
        [`POST ${OPS_DNC_GLOBAL_PATH}`]: staleFactor(),
        [`POST ${STEP_UP_PATH}`]: problem(503, {
          title: "Service unavailable",
          detail: "We could not send the code.",
          status: 503,
          kind: "dependency",
          retryable: true,
        }),
      }),
    );

    await attemptSuppression();
    fireEvent.click(await screen.findByRole("button", { name: "Email me a code" }));

    await waitFor(() => expect(calls.filter((c) => c.path === STEP_UP_PATH)).toHaveLength(1));
    expect(await screen.findByText("We could not send the code.")).toBeTruthy();
    // No code field: the request that produces the code failed, so a field expecting one
    // would be a control that can never be satisfied.
    expect(screen.queryByLabelText(/Code from your email/)).toBeNull();
    expect(screen.getByRole("button", { name: "Email me a code" })).toBeTruthy();
  });

  it("leaves the version-skew panel to the refusal that actually means a skew", async () => {
    // `step_up_required` and `reauthentication_required` are two halves of one control
    // (intent versus presence) and have opposite remedies. Routing both to one panel
    // would tell an operator to reload for a build skew that is not there — or would
    // offer a code for a header mismatch no code can fix.
    renderAdminPage(
      <GlobalDncPage />,
      routes({
        [`POST ${OPS_DNC_GLOBAL_PATH}`]: problem(403, {
          type: "https://calevate.tech/problems/step_up_required",
          title: "Confirmation required",
          detail: "This action needs an explicit confirmation.",
          status: 403,
          kind: "permission",
          retryable: false,
          remediation: "Repeat the request with the header X-Confirm-Action: …",
        }),
      }),
    );

    await attemptSuppression();

    expect(
      await screen.findByText(/this console's confirmation is not the one the API expects/),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Email me a code" })).toBeNull();
  });
});
