import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH } from "@/app/admin/access";
import AdminLayout from "@/app/admin/layout";
import { HOLDS_PATH } from "@/lib/api/holds";

import { problem, stubApi, type Routes } from "./harness";

/**
 * What an operator without a second factor SEES — never what stops them.
 *
 * The stopping happens in `apps/api/core/auth.py::verify_token`, which refuses every
 * admin-realm token whose Clerk session never completed a second factor (TRD §2,
 * SEC-COMP §5); `tests/admin_mfa_test.py` is where that property lives, and it is the
 * one that would fail if the control were removed. Nothing in this file makes anything
 * safe, and it is written so that it cannot be mistaken for the control: the API's
 * refusal is what it renders, and it renders the console untouched when there is none.
 *
 * The defect it removes is real all the same. Without it the refusal reaches an operator
 * as `403 mfa_required` on `/v1/admin/me`, on the hold queue, and on every panel of
 * whichever screen they opened — a shell full of red boxes, none of which says the one
 * thing they need to do. The console holds cross-client data and the platform switches,
 * so "you are locked out and here is why" has to be one page, not twelve.
 */

const OPERATOR = { role: "superadmin", permissions: ["ops:manage", "admin:tenants"] };

const MFA_REFUSAL = problem(403, {
  type: "https://calevate.tech/problems/mfa_required",
  title: "Two-step verification required",
  detail: "The operator console requires two-step verification.",
  kind: "permission",
  remediation: "Set up two-step verification on your Calevate operator account.",
});

function renderShell(routes: Routes) {
  stubApi(routes);
  return render(
    <AdminLayout>
      <p>console body</p>
    </AdminLayout>,
  );
}

describe("the operator console under an MFA refusal", () => {
  it("replaces the whole console with the API's own sentence and remedy", async () => {
    const { container } = renderShell({ [ADMIN_ME_PATH]: MFA_REFUSAL, [HOLDS_PATH]: [] });

    expect(await screen.findByText(/Two-step verification required/)).toBeTruthy();
    // The REMEDIATION, not just the refusal: a wall that does not say what to do next is
    // the state this component exists to replace.
    expect(container.textContent).toContain("Set up two-step verification");

    // REPLACES rather than sits above. If the shell rendered underneath, every panel on
    // it would answer its own 403 and the page would be a list of failures.
    expect(container.textContent).not.toContain("console body");
    expect(container.textContent).not.toContain("Cross-client · every action is audited");
  });

  it("says the same for a misconfigured Clerk application, which is a different fault", async () => {
    /**
     * `mfa_claim_missing` is the admin Clerk application issuing a session token with no
     * `fva` claim — an OPERATOR's misconfiguration, not the signed-in person's. The API
     * gives it its own code and its own remediation precisely so the two are not
     * conflated; the console must therefore print what the API said rather than a
     * hard-coded "enrol a second factor" that would send someone to fix the wrong thing.
     */
    const { container } = renderShell({
      [ADMIN_ME_PATH]: problem(403, {
        type: "https://calevate.tech/problems/mfa_claim_missing",
        detail: "This session does not say whether a second factor was verified.",
        kind: "permission",
        remediation: "The admin Clerk application must issue the default session token claims.",
      }),
      [HOLDS_PATH]: [],
    });

    expect(await screen.findByText(/default session token claims/)).toBeTruthy();
    expect(container.textContent).not.toContain("console body");
  });
});

describe("every other state of the console", () => {
  it("renders untouched when the identity read succeeds", async () => {
    const { container } = renderShell({ [ADMIN_ME_PATH]: OPERATOR, [HOLDS_PATH]: [] });

    // The ROLE, which only renders once `/v1/admin/me` has answered — so this waits for
    // the query to settle rather than catching the shell in its loading state, where a
    // gate that blanks on every error would still look correct.
    expect(await screen.findByText(/superadmin · signed in across every client/)).toBeTruthy();
    expect(container.textContent).not.toContain("Two-step verification required");
  });

  it("renders untouched when the identity read fails for ANY other reason", async () => {
    /**
     * The gate keys on the CODE, never on the status or the kind. A 403 for a missing
     * permission, a 502 while Clerk is down, a dropped connection — none of those are
     * "you have no second factor", and a console that blamed MFA for an outage would
     * send an operator to enrol a factor they already have while the platform is on
     * fire. `/v1/ops` is on `ALWAYS_ALLOWED_PREFIXES` so the ops screen survives a load
     * shed; a shell that blanked on any failed identity read would undo that in the
     * browser, which is the more expensive direction of the two.
     */
    const { container } = renderShell({
      [ADMIN_ME_PATH]: problem(403, {
        type: "https://calevate.tech/problems/forbidden",
        title: "Forbidden",
        detail: "This account has no admin access.",
        kind: "permission",
      }),
      [HOLDS_PATH]: [],
    });
    // Same status and the same `kind` as the MFA refusal, settling on the same tick —
    // so if the gate keyed on either of those instead of on the code, this would blank.
    await act(async () => {});
    await act(async () => {});

    expect(container.textContent).toContain("console body");
    expect(container.textContent).not.toContain("Two-step verification required");
  });
});
