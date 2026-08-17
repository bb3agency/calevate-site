import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH } from "@/app/admin/access";
import AdminLayout from "@/app/admin/layout";
import { HOLDS_PATH } from "@/lib/api/holds";

import { problem, stubApi, type Routes } from "./harness";

/**
 * What an operator without a second factor SEES — never what stops them.
 *
 * The stopping happens in `apps/api/core/auth.py::_require_second_factor`, which refuses
 * every admin-realm session whose `mfa_verified_at` is NULL (TRD §2, SEC-COMP §5);
 * `tests/admin_mfa_test.py` is where that property lives, and it is the one that would
 * fail if the control were removed. Nothing in this file makes anything
 * safe, and it is written so that it cannot be mistaken for the control: the API's
 * refusal is what it renders, and it renders the console untouched when there is none.
 *
 * The defect it removes is real all the same. Without it the refusal reaches an operator
 * as `401 second_factor_required` on `/v1/admin/me`, on the hold queue, and on every panel of
 * whichever screen they opened — a shell full of red boxes, none of which says the one
 * thing they need to do. The console holds cross-client data and the platform switches,
 * so "you are locked out and here is why" has to be one page, not twelve.
 */

const OPERATOR = { role: "superadmin", permissions: ["ops:manage", "admin:tenants"] };

// `401 auth`, not `403 permission` (D-177): a session that owes its emailed code is
// half-AUTHENTICATED rather than half-authorised, and the difference is what tells an
// operator to finish signing in instead of asking somebody for a role.
const MFA_REFUSAL = problem(401, {
  type: "https://calevate.tech/problems/second_factor_required",
  title: "Two-step verification required",
  detail: "The operator console requires two-step verification.",
  kind: "auth",
  remediation: "Enter the code emailed to your operator address to finish signing in.",
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
    expect(container.textContent).toContain("Enter the code emailed to your operator address");

    // REPLACES rather than sits above. If the shell rendered underneath, every panel on
    // it would answer its own 403 and the page would be a list of failures.
    expect(container.textContent).not.toContain("console body");
    expect(container.textContent).not.toContain("Cross-client · every action is audited");
  });

  it("prints the API's own remediation rather than a sentence of its own", async () => {
    /**
     * THE SECOND CODE IS GONE AND THIS IS WHAT THE TEST FOR IT BECAME (D-177).
     *
     * It used to drive `mfa_claim_missing` — the admin Clerk application issuing a session
     * token with no `fva` claim, an OPERATOR's misconfiguration rather than the signed-in
     * person's, which had its own code so the two were never conflated. A NULL column
     * cannot be ambiguous, so there is one code now.
     *
     * What has to survive that collapse is the reason the pair existed: this panel renders
     * the API's sentence, not one of its own. A hard-coded "enrol a second factor" would
     * be right today and wrong the moment the server's remediation changes, and it is the
     * server that knows why a session was refused.
     */
    const { container } = renderShell({
      [ADMIN_ME_PATH]: problem(401, {
        type: "https://calevate.tech/problems/second_factor_required",
        detail: "This session has not completed two-factor authentication.",
        kind: "auth",
        remediation: "Check the inbox for the address this operator account was created with.",
      }),
      [HOLDS_PATH]: [],
    });

    expect(await screen.findByText(/the address this operator account was created with/)).toBeTruthy();
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
     * permission, a 502 from the database, a dropped connection — none of those are
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
