import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StepUpPrompt } from "@/components/authn/stepUpPrompt";
import { WriteFailure } from "@/app/admin/writeFailure";
import { ApiProblem } from "@/lib/api/client";

import { renderAdminPage } from "./harness";

/**
 * PROVING A SECOND FACTOR HAD NO VISIBLE OUTCOME, AND NOBODY COULD SEE IT.
 *
 * `WriteFailure` renders the API's `reauthentication_required` refusal with a "Send me a
 * code" button, and on success it called `onRetry?.()` — an OPTIONAL prop that not one of
 * the seventeen call sites passed. So an operator pressed Install, was refused, typed the
 * emailed code, and watched the same red panel sit there unchanged; the only way forward
 * was to guess that pressing Install again would now work. That is what was reported from
 * the live console, and it is invisible from a diff because every individual piece worked.
 *
 * Two things are asserted, and the second is the one that stops the regression coming
 * back in a different shape:
 *
 *   1. proving the factor CHANGES THE SCREEN — a success panel, announced as a `status`
 *      rather than an `alert`, naming the button to press;
 *   2. it does NOT replay the write. That is deliberate and is written down in the
 *      component: step-up says who is at the keyboard, and a button that re-fired a
 *      platform halt off the back of an emailed code would turn an identity check into a
 *      confirmation. A test that only checked "something happened" would be satisfied by
 *      the version that re-sends, which is the dangerous one.
 *
 * The `actionLabel` prop is REQUIRED in the type, which is the compile-time half — the
 * eighteenth call site cannot repeat the original defect.
 */

const STEP_UP_PATH = "/v1/auth/admin/step-up";
const VERIFY_PATH = "/v1/auth/admin/step-up/verify";

/** The refusal exactly as `authn/stepup.py` sends it, as the console receives it. */
function reauthRefusal(): ApiProblem {
  return new ApiProblem(403, {
    type: "https://calevate.tech/problems/reauthentication_required",
    title: "Confirm it is still you",
    detail: "This action needs a second factor proved in the last 5 minutes.",
    kind: "permission",
  });
}

function mount(onRetryCalls: string[] = []) {
  return renderAdminPage(
    <>
      <StepUpPrompt />
      <WriteFailure
        error={reauthRefusal()}
        actionLabel="Install"
        onRetry={() => onRetryCalls.push("retried")}
      />
    </>,
    {
      [`POST ${STEP_UP_PATH}`]: {},
      [`POST ${VERIFY_PATH}`]: {
        realm: "admin",
        subject_id: "op-1",
        mfa_complete: true,
        email_verified: true,
      },
    },
  );
}

/** Drive the whole prompt: ask for the code, type it, confirm. */
async function proveTheFactor() {
  fireEvent.click(screen.getByRole("button", { name: /send me a code/i }));
  await screen.findByRole("alertdialog");
  fireEvent.click(screen.getByRole("button", { name: /email me a code/i }));
  const field = await screen.findByLabelText(/six-digit code/i);
  fireEvent.change(field, { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));
}

describe("proving a second factor acknowledges itself", () => {
  it("replaces the refusal with a confirmation that names the button to press", async () => {
    mount();

    // Before: the refusal, announced as an alert because it interrupts the operator.
    expect(screen.getByRole("alert").textContent).toContain("Nothing was changed");

    await proveTheFactor();

    const ok = await screen.findByRole("status");
    expect(ok.textContent).toContain("Confirmed");
    // The specific button, not "the button" — this screen has four.
    expect(ok.textContent).toContain("Install");
    // And the refusal is gone, so there is nothing left claiming the check still fails.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says plainly that nothing was applied, and does not re-send the write", async () => {
    const calls: string[] = [];
    const { calls: api } = mount(calls);

    await proveTheFactor();
    await screen.findByRole("status");

    expect(screen.getByRole("status").textContent).toContain("Nothing has been applied");
    // `onRetry` still fires for a caller that wants it — the component's contract is
    // unchanged — but no write left this screen on its own.
    expect(calls).toEqual(["retried"]);
    await waitFor(() => {
      const paths = api.map((call) => call.path);
      expect(paths.filter((p) => p !== STEP_UP_PATH && p !== VERIFY_PATH)).toEqual([]);
    });
  });

  it("leaves the refusal standing while the code is unproved, and offers no way to dodge it", async () => {
    mount();

    fireEvent.click(screen.getByRole("button", { name: /send me a code/i }));
    const dialog = await screen.findByRole("alertdialog");

    // D-473: the prompt has two exits, and neither is "dismiss". Escape is inert.
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("alertdialog")).toBeTruthy();

    // Still the refusal underneath: nothing was proved, and a screen that congratulated
    // the operator here would be lying about the state of their session.
    expect(screen.getByRole("alert").textContent).toContain("Nothing was changed");
    expect(screen.queryByRole("status")).toBeNull();
  });
});
