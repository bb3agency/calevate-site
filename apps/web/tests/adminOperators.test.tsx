import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import AdminLayout from "@/app/admin/layout";
import OperatorsPage from "@/app/admin/operators/page";
import {
  OPERATORS_PATH,
  addOperatorConfirmation,
  operatorLabel,
  operatorRevocationConfirmation,
  operatorRoleConfirmation,
  operatorSetupLinkConfirmation,
  selfAdministrationBlock,
  tierChangeTarget,
  type Operator,
} from "@/lib/api/adminOperators";
import { HOLDS_PATH } from "@/lib/api/holds";

import { browserOffline, problem, renderAdminPage, stillLoading, type Routes } from "./harness";

/**
 * The operator allowlist — who may sign in to the admin console, and in which tier.
 *
 * This is the screen that makes the two admin tiers usable, and it is also the screen
 * whose defects are the most expensive in the product, because every one of them is an
 * error about WHO CAN REACH EVERY CLIENT'S DATA. Ranked worst first, which is the order
 * the cases below run in:
 *
 * 1. **A normal admin must never be shown a control that will 403.** Every route here is
 *    `admin:operators`, which only `superadmin` holds (`core/rbac.py`) — and unlike most
 *    screens the READ carries it too, so a normal admin cannot even see the list. The
 *    screen is therefore WITHHELD with the reason and asks the API nothing; a list with
 *    dead buttons would be a screen whose every request is a refusal.
 * 2. **The founder must not be able to lock themselves out.** The API refuses a role
 *    change or a revocation aimed at the actor's own account
 *    (`operator_self_administration`), and that refusal is what holds the "there is
 *    always a live super admin" invariant up — `authn/operators.py` argues it as a
 *    consequence of three facts rather than as a count. The screen must make the same
 *    thing visibly impossible and say why, so the person who owns the platform meets a
 *    sentence rather than a 403 on the one request that would end their own access.
 * 3. **A consequential act must not be reachable by muscle memory.** The typed
 *    confirmation is the API's OWN `X-Confirm-Action` string, so it is bound to the ROLE
 *    when an account is created and to the SUBJECT for the other three: a phrase typed
 *    for Asha cannot lift Ravi, and a phrase typed to add an admin cannot add a second
 *    super admin.
 * 4. **§52, on a list whose empty state is a security claim.** "Nobody else has an admin
 *    account", printed over a failed read, invites a founder to add an administrator they
 *    already have and answers "who else can reach this" with a reassurance nobody checked.
 * 5. **No credential, token or setup link may appear on screen.** The API has no field to
 *    put one in (D-190: a token the inviter can see is an account squat), and the create
 *    response is rendered as a confirmation that a link was MAILED, never as the link.
 */

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const ROUTES_PY = resolve(REPO_ROOT, "apps/api/admin/operator_routes.py");
const RBAC_PY = resolve(REPO_ROOT, "apps/api/core/rbac.py");
const OPERATORS_PY = resolve(REPO_ROOT, "apps/api/authn/operators.py");

const FOUNDER_ID = "0192f0aa-7777-7000-8000-0000000000a1";
const ASHA_ID = "0192f0aa-7777-7000-8000-0000000000a2";
const RAVI_ID = "0192f0aa-7777-7000-8000-0000000000a3";

function me(over: Partial<AdminMe> = {}): AdminMe {
  return {
    realm: "admin",
    user_id: FOUNDER_ID,
    role: "superadmin",
    permissions: ["org:read", "admin:tenants", "admin:operators"],
    ...over,
  };
}

const SUPERADMIN = me();
/** The narrow tier: everything `ROLE_PERMISSIONS["operator"]` holds, and nothing more. */
const NORMAL_ADMIN = me({
  user_id: ASHA_ID,
  role: "operator",
  permissions: ["org:read", "admin:tenants", "admin:impersonate"],
});

function operator(over: Partial<Operator> = {}): Operator {
  return {
    id: ASHA_ID,
    email: "asha@calevate.tech",
    name: "Asha Rao",
    role: "operator",
    created_at: "2026-08-14T09:15:00Z",
    activated: true,
    ...over,
  };
}

const FOUNDER: Operator = operator({
  id: FOUNDER_ID,
  email: "founder@calevate.tech",
  name: "Sri J",
  role: "superadmin",
  created_at: "2026-07-01T04:30:00Z",
});

function routes(list: unknown, identity: unknown = SUPERADMIN, extra: Routes = {}): Routes {
  return { [ADMIN_ME_PATH]: identity, [OPERATORS_PATH]: list, ...extra };
}

/** The list as the server sends it: the signed-in founder plus one normal admin. */
function listOf(...operators: Operator[]): { operators: Operator[] } {
  return { operators };
}

/** Fill a labelled box on the screen. */
function type(label: RegExp | string, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

// ─────────────────────────────────────────────────────────────────────────────────────
// 1. The tier boundary
// ─────────────────────────────────────────────────────────────────────────────────────

describe("what a normal admin is shown", () => {
  it("withholds the whole screen, with the reason, and asks the API nothing", async () => {
    const { container, calls } = renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER), NORMAL_ADMIN),
    );

    await screen.findByText(/does not have the admin:operators permission/);
    expect(container.textContent).toContain("Your admin account cannot see this");
    // The permission name is the useful half of the refusal: it is what they have to ask
    // a super admin for.
    expect(container.textContent).toContain("Ask a superadmin");
    // NOT A DIRECTORY. Nothing about who holds an account leaks through the refusal —
    // no name, no address, no count.
    expect(container.textContent).not.toContain("founder@calevate.tech");
    expect(container.textContent).not.toContain("Sri J");
    // And the read that can only 403 is never sent. A request whose sole outcome is a
    // refusal is a log line, not a preview.
    expect(calls.some((call) => call.path === OPERATORS_PATH)).toBe(false);
  });

  it("offers no control at all — not a disabled one", async () => {
    renderAdminPage(<OperatorsPage />, routes(listOf(FOUNDER), NORMAL_ADMIN));

    await screen.findByText(/does not have the admin:operators permission/);
    expect(screen.queryAllByRole("button")).toEqual([]);
    expect(screen.queryAllByRole("textbox")).toEqual([]);
  });

  it("waits for the identity read before mounting anything, so nothing flashes", () => {
    const { container, calls } = renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER), stillLoading()),
    );

    // A skeleton, not the list and not the refusal: the honest statement while the answer
    // is in flight is "we are finding out whether you may see this".
    expect(container.textContent).toContain("Checking whether you may manage admin accounts");
    expect(calls.some((call) => call.path === OPERATORS_PATH)).toBe(false);
  });

  /**
   * THE REGRESSION THIS SCREEN SHIPPED WITH FOR ONE AFTERNOON, pinned because it is
   * invisible from a diff and catastrophic in production.
   *
   * The screen mounts its body only once the identity read has answered. Written as
   * `me.isLoading`, that boolean goes false → TRUE → false around every retry of a
   * FAILED read: query-core's `fetchState` puts a query back into `pending` whenever a
   * fetch starts with `data === undefined`. So the body unmounted on each attempt — and
   * because the body observed the same query, its remount is what triggered the next
   * attempt (`retryOnMount`). Measured: ~45 requests to `/v1/admin/me` in 300ms, on the
   * one screen an operator opens when authentication is already misbehaving, from a
   * browser that would keep going as long as the tab was open.
   *
   * Two changes closed it and this test drives both: the predicate is sticky
   * (`identityAnswerPending`) and the identity is read ONCE, at the top, and passed down.
   */
  it("does not spin the identity read when it fails", async () => {
    const { container, calls } = renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER), problem(503, { title: "identity unavailable" })),
    );

    // The screen falls through to its own body — the API is the enforcement, and a
    // console that hid the allowlist because an unrelated read was slow would be worse
    // than one that meets the server's own answer.
    await screen.findByText("Sri J");
    expect(container.textContent).toContain("We could not check what you may do here");

    // Settle anything still in flight, then count. A handful is a mount and a retry; a
    // spin is unbounded, and the bound is what this assertion is for.
    await new Promise((resolve) => setTimeout(resolve, 250));
    const identityReads = calls.filter((call) => call.path === ADMIN_ME_PATH).length;
    expect(identityReads, `${identityReads} reads of ${ADMIN_ME_PATH}`).toBeLessThan(4);
  });

  it("closes the controls when the console could not ask who you are", async () => {
    // The fourth state `AdminAccess` has no sentence for: no data, no error, and not
    // loading — a query query-core has PAUSED because the browser is offline. A control
    // fails closed, and "we have no answer" is not "you may".
    browserOffline();
    const { container } = renderAdminPage(<OperatorsPage />, routes(listOf(FOUNDER)));

    await waitFor(() =>
      expect(container.textContent).toContain("has not been able to establish what you may do"),
    );
    expect(
      (screen.getByLabelText(/Email address of the admin to add/) as HTMLInputElement).disabled,
    ).toBe(true);
  });

  it("renders a 403 on the list as a refusal rather than as an outage", async () => {
    // The one window the permission gate cannot cover: `adminAccess` fails OPEN when the
    // identity read itself failed, so the screen mounts, asks, and is refused. The
    // refusal must not arrive wearing the outage sentence and a Retry that cannot work.
    const { container } = renderAdminPage(
      <OperatorsPage />,
      routes(
        problem(403, {
          title: "Forbidden",
          detail: "This account does not have the admin:operators permission.",
        }),
        problem(503, { title: "identity unavailable" }),
      ),
    );

    await screen.findByText("Your admin account cannot see this");
    // The API's own sentence, verbatim: an authorization refusal is the server's to word.
    expect(container.textContent).toContain(
      "This account does not have the admin:operators permission.",
    );
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
  });
});

describe("the nav entry that reaches this screen", () => {
  /**
   * The seam, closed at the shell. A screen nobody can navigate to is the "half-wired
   * feature" CLAUDE.md names, and the shell's own doctrine (`admin/layout.tsx`) is that an
   * entry a session cannot use is SHOWN AND DEAD with its reason rather than hidden —
   * "open Admin accounts and add her" is a sentence one operator says to another, and an
   * absent entry reads as a broken build.
   */
  function entry(container: HTMLElement): HTMLElement | null {
    return (
      Array.from(container.querySelectorAll<HTMLElement>("a, span")).find(
        (node) => node.textContent?.trim() === "Admin accounts",
      ) ?? null
    );
  }

  it("is a real link for a super admin and a dead label for a normal admin", async () => {
    const shell = (identity: unknown): Routes => ({
      [ADMIN_ME_PATH]: identity,
      [HOLDS_PATH]: [],
    });

    const live = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell(SUPERADMIN),
    );
    await waitFor(() => expect(entry(live.container)?.tagName).toBe("A"));
    expect(entry(live.container)?.getAttribute("href")).toBe("/admin/operators");
    live.unmount();

    const dead = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell(NORMAL_ADMIN),
    );
    await waitFor(() => expect(entry(dead.container)?.tagName).toBe("SPAN"));
    // The permission name is the part they have to ask for, so it is in the sentence
    // beside the dead entry rather than only in a `title` a mouse has to discover.
    expect(dead.container.textContent).toContain(
      "does not have the admin:operators permission",
    );
  });
});

// ─────────────────────────────────────────────────────────────────────────────────────
// 2. The lockout
// ─────────────────────────────────────────────────────────────────────────────────────

describe("the account you are signed in as", () => {
  it("offers no tier change and no revocation on your own row, and says why", async () => {
    const { container } = renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER, operator())),
    );

    await screen.findByText("Sri J");
    expect(container.textContent).toContain("This is your own account");
    expect(container.textContent).toContain("stops the last super admin removing themselves");
    // The controls are ABSENT on that row, not disabled: the API refuses both acts
    // outright, so a greyed-out button would be one that is never available.
    expect(screen.queryByRole("button", { name: /Change the tier of Sri J/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Revoke the admin access of Sri J/ })).toBeNull();
  });

  it("still offers both on somebody ELSE's row, including another super admin", async () => {
    // The invariant must not be over-applied. A second super admin is demotable — that is
    // how a departing founder is actually replaced — and a screen that refused every
    // super admin would make the tier unadministrable.
    const second = operator({ id: RAVI_ID, name: "Ravi K", role: "superadmin" });
    renderAdminPage(<OperatorsPage />, routes(listOf(FOUNDER, second)));

    await screen.findByText("Ravi K");
    expect(screen.getByRole("button", { name: /Change the tier of Ravi K/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Revoke the admin access of Ravi K/ })).toBeTruthy();
  });

  it("refuses to guess a direction for a tier this build has no words for", async () => {
    // `Operator.role` is a WIRE string, and a deployment whose API is newer could send a
    // third tier. The obvious ternary reads an unknown tier as "not a super admin" and
    // offers to PROMOTE it — the one direction a wrong guess must never take.
    const { container } = renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER, operator({ role: "auditor" }))),
    );

    await screen.findByText("Asha Rao");
    expect(screen.queryByRole("button", { name: /Change the tier of Asha Rao/ })).toBeNull();
    expect(container.textContent).toContain("does not recognise the tier");
    // Revoking needs no opinion about which tier they are in, so it stays — and the row
    // still renders the wire value rather than hiding an account it cannot classify.
    expect(screen.getByRole("button", { name: /Revoke the admin access of Asha Rao/ })).toBeTruthy();
    expect(container.textContent).toContain("auditor");

    expect(tierChangeTarget(operator({ role: "auditor" }))).toBeNull();
    expect(tierChangeTarget(operator({ role: "operator" }))).toBe("superadmin");
    expect(tierChangeTarget(operator({ role: "superadmin" }))).toBe("operator");
  });

  it("blocks self-administration from the id, not from the tier", () => {
    // The rule is "this row is you", and it is a pure function so the screen cannot grow
    // a second opinion about it. A normal admin looking at their own row would be
    // refused for exactly the same reason — they never reach the screen, but the block
    // does not depend on that.
    expect(selfAdministrationBlock(FOUNDER, FOUNDER_ID)).toContain("your own account");
    expect(selfAdministrationBlock(operator(), FOUNDER_ID)).toBeNull();
    // No viewer id (the identity read failed) is NOT a match: refusing every row on an
    // unknown viewer would make the screen useless exactly when it is least explicable,
    // and the API refuses the self case whatever this returns.
    expect(selfAdministrationBlock(FOUNDER, null)).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────────────
// 3. The confirmations
// ─────────────────────────────────────────────────────────────────────────────────────

describe("the typed confirmation on a consequential act", () => {
  it("is the API's own header string, and is what travels in X-Confirm-Action", async () => {
    const { calls } = renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER, operator()), SUPERADMIN, {
        [`PATCH ${OPERATORS_PATH}/${ASHA_ID}`]: operator({ role: "superadmin" }),
      }),
    );

    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: /Change the tier of Asha Rao/ }));

    const confirmation = operatorRoleConfirmation(ASHA_ID);
    type(/Why you are changing Asha Rao's tier/, "she is taking over the platform keys");
    type(new RegExp(`Type ${confirmation}`), confirmation);
    fireEvent.click(screen.getByRole("button", { name: "Promote to super admin" }));

    await waitFor(() => {
      const sent = calls.find((call) => call.method === "PATCH");
      expect(sent, "the promotion was never sent").toBeTruthy();
      expect(sent?.headers["X-Confirm-Action"]).toBe(confirmation);
      expect(JSON.parse(sent?.body ?? "{}")).toEqual({
        role: "superadmin",
        reason: "she is taking over the platform keys",
      });
    });
  });

  it("keeps the button dead until the exact string and a real reason are present", async () => {
    renderAdminPage(<OperatorsPage />, routes(listOf(FOUNDER, operator())));

    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: /Change the tier of Asha Rao/ }));
    const confirmation = operatorRoleConfirmation(ASHA_ID);
    const submit = () =>
      screen.getByRole("button", { name: "Promote to super admin" }) as HTMLButtonElement;

    expect(submit().disabled).toBe(true);

    // A reason of whitespace is not a reason: the API strips it and refuses anything
    // under three characters, so a form that lit up here would teach an operator the API
    // is flaky.
    type(/Why you are changing Asha Rao's tier/, "   ");
    type(new RegExp(`Type ${confirmation}`), confirmation);
    expect(submit().disabled).toBe(true);

    type(/Why you are changing Asha Rao's tier/, "she is taking over the platform keys");
    expect(submit().disabled).toBe(false);
  });

  it("cannot be satisfied by the string that belongs to another account", async () => {
    // The whole point of binding the confirmation to the SUBJECT. A phrase captured or
    // remembered from Ravi's row is not consent to promote Asha.
    renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER, operator(), operator({ id: RAVI_ID, name: "Ravi K" }))),
    );

    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: /Change the tier of Asha Rao/ }));
    type(/Why you are changing Asha Rao's tier/, "swapping their responsibilities");
    type(
      new RegExp(`Type ${operatorRoleConfirmation(ASHA_ID)}`),
      operatorRoleConfirmation(RAVI_ID),
    );

    expect(
      (screen.getByRole("button", { name: "Promote to super admin" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("is cleared when the new admin's tier changes, so it cannot confirm the other one", async () => {
    // `add_operator:<role>` is bound to the ROLE, and this is the reason it is: a phrase
    // typed while the picker said Admin must not survive a switch to Super admin. The
    // model picker clears its confirmation on the same argument.
    renderAdminPage(<OperatorsPage />, routes(listOf(FOUNDER)));

    await screen.findByText("Sri J");
    type(/Email address of the admin to add/, "new@calevate.tech");
    type(/Why you are adding this admin/, "joining as our second onboarding operator");
    type(/Type add_operator:operator/, addOperatorConfirmation("operator"));
    expect((screen.getByRole("button", { name: /^Add admin$/ }) as HTMLButtonElement).disabled).toBe(
      false,
    );

    fireEvent.change(screen.getByLabelText(/Tier for the new admin/), {
      target: { value: "superadmin" },
    });

    const submit = screen.getByRole("button", { name: /^Add super admin$/ }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect((screen.getByLabelText(/Type add_operator:superadmin/) as HTMLInputElement).value).toBe(
      "",
    );
  });

  it("says what promoting somebody actually gives them, before the click", async () => {
    const { container } = renderAdminPage(<OperatorsPage />, routes(listOf(FOUNDER, operator())));

    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: /Change the tier of Asha Rao/ }));
    // The three facts a super admin is actually agreeing to, in the order they matter.
    expect(container.textContent).toContain("the vendor API keys");
    expect(container.textContent).toContain("add and remove admins, including you");
    expect(container.textContent).toContain("Recorded in the audit log");
  });
});

// ─────────────────────────────────────────────────────────────────────────────────────
// 4. Revocation and the setup link
// ─────────────────────────────────────────────────────────────────────────────────────

describe("revoking an account", () => {
  it("POSTs to /revocation with the reason and the confirmation, never a DELETE", async () => {
    const { calls } = renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER, operator()), SUPERADMIN, {
        [`POST ${OPERATORS_PATH}/${ASHA_ID}/revocation`]: operator(),
      }),
    );

    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: /Revoke the admin access of Asha Rao/ }));
    const confirmation = operatorRevocationConfirmation(ASHA_ID);
    type(/Why you are revoking Asha Rao's access/, "left the company on Friday");
    type(new RegExp(`Type ${confirmation}`), confirmation);
    fireEvent.click(screen.getByRole("button", { name: "Revoke access" }));

    await waitFor(() => {
      const sent = calls.find((call) => call.path.endsWith("/revocation"));
      expect(sent, "the revocation was never sent").toBeTruthy();
      expect(sent?.method).toBe("POST");
      expect(sent?.headers["X-Confirm-Action"]).toBe(confirmation);
    });
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  });

  it("says the row survives, so nobody reads it as a data erasure", async () => {
    const { container } = renderAdminPage(<OperatorsPage />, routes(listOf(FOUNDER, operator())));

    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: /Revoke the admin access of Asha Rao/ }));
    expect(container.textContent).toContain("Their row is kept");
    expect(container.textContent).toContain("Nothing about this is a data erasure");
  });
});

describe("the setup link", () => {
  it("is offered only for an account that has never set a password", async () => {
    renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER, operator({ activated: false }), operator({ id: RAVI_ID, name: "Ravi K" }))),
    );

    await screen.findByText("Asha Rao");
    expect(screen.getByRole("button", { name: /Resend the setup link for Asha Rao/ })).toBeTruthy();
    // Ravi has a password. Offering it for him would be offering a password reset, which
    // the API refuses (`operator_already_activated`) and which must not be reachable from
    // the person asking on somebody else's behalf.
    expect(screen.queryByRole("button", { name: /Resend the setup link for Ravi K/ })).toBeNull();
  });

  it("says it is not a password reset, at the control", async () => {
    const { container } = renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER, operator({ activated: false }))),
    );

    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: /Resend the setup link for Asha Rao/ }));
    expect(container.textContent).toContain("never set a password");
    expect(container.textContent).toContain("mails the link to them rather than to you");
  });
});

// ─────────────────────────────────────────────────────────────────────────────────────
// 5. Creating an account, and what must never be on screen
// ─────────────────────────────────────────────────────────────────────────────────────

describe("adding an admin", () => {
  it("sends the role-bound confirmation and reports that a link was MAILED", async () => {
    const created = operator({ id: RAVI_ID, name: null, email: "new@calevate.tech", activated: false });
    const { container, calls } = renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER), SUPERADMIN, { [`POST ${OPERATORS_PATH}`]: created }),
    );

    await screen.findByText("Sri J");
    type(/Email address of the admin to add/, "new@calevate.tech");
    type(/Why you are adding this admin/, "joining as our second onboarding operator");
    type(/Type add_operator:operator/, addOperatorConfirmation("operator"));
    fireEvent.click(screen.getByRole("button", { name: /^Add admin$/ }));

    await screen.findByText(/Setup link sent to new@calevate.tech/);
    const sent = calls.find((call) => call.method === "POST");
    expect(sent?.headers["X-Confirm-Action"]).toBe("add_operator:operator");
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({
      email: "new@calevate.tech",
      name: null,
      role: "operator",
      reason: "joining as our second onboarding operator",
    });
    // THE LINK IS NOT ON SCREEN AND CANNOT BE: the API has no field for one (D-190). What
    // is reported is that it was mailed, and that we cannot show it.
    expect(container.textContent).toContain("cannot show or forward the link");
    expect(container.textContent).not.toMatch(/token/i);
  });

  it("surfaces the API's own refusal verbatim when the address is taken", async () => {
    const { container } = renderAdminPage(
      <OperatorsPage />,
      routes(listOf(FOUNDER), SUPERADMIN, {
        [`POST ${OPERATORS_PATH}`]: problem(409, {
          type: "https://calevate.tech/problems/operator_email_taken",
          title: "Conflict",
          detail: "A live operator account already uses that email address.",
          remediation: "Use the existing account — resend its setup link if the person never finished signing in — or revoke it first.",
        }),
      }),
    );

    await screen.findByText("Sri J");
    type(/Email address of the admin to add/, "asha@calevate.tech");
    type(/Why you are adding this admin/, "adding her a second time by mistake");
    type(/Type add_operator:operator/, addOperatorConfirmation("operator"));
    fireEvent.click(screen.getByRole("button", { name: /^Add admin$/ }));

    await screen.findByText("A live operator account already uses that email address.");
    // The remediation is the actionable half and is printed, not paraphrased.
    expect(container.textContent).toContain("resend its setup link");
  });
});

// ─────────────────────────────────────────────────────────────────────────────────────
// 6. §52
// ─────────────────────────────────────────────────────────────────────────────────────

describe("what the screen says when it has no answer", () => {
  it("is a skeleton while the list is in flight, never a count", async () => {
    const { container } = renderAdminPage(<OperatorsPage />, routes(stillLoading(), SUPERADMIN));

    // Awaited past the IDENTITY skeleton: until `/v1/admin/me` answers, what is on screen
    // is the "checking whether you may see this" shape and the assertion below would be
    // about the wrong loading state.
    await screen.findByText("Add an admin");
    expect(container.querySelector('[role="status"]')).toBeTruthy();
    // A count is a statement about who can reach every client's data. There is none until
    // the server has sent a list, and no empty state either.
    expect(container.textContent).not.toContain("1 account");
    expect(container.textContent).not.toContain("0 accounts");
    expect(container.textContent).not.toContain("No admin accounts are listed");
  });

  it("refuses to state an empty list, or a count, over a failed read", async () => {
    const { container } = renderAdminPage(
      <OperatorsPage />,
      routes(problem(503, { title: "Service unavailable", detail: "The database is unreachable." })),
    );

    await screen.findByText("The database is unreachable.");
    // The sentence that must never appear over a failure: it answers "who else can reach
    // every client's data" with a reassurance nobody checked.
    expect(container.textContent).not.toContain("No admin accounts are listed");
    expect(container.textContent).not.toContain("0 accounts");
    expect(container.textContent).not.toContain("1 account");
  });

  it("drops the rows it had already shown when a refetch fails", async () => {
    // The strict half of §52, and the reason this screen follows `configState` rather
    // than the client realm's team screen: a list that is thirty seconds stale answers
    // "who has access" with somebody another super admin has already removed.
    // Driven through the flow that actually produces it: a successful revocation
    // invalidates the list, and the refetch it triggers is the one that fails.
    let reads = 0;
    const { container } = renderAdminPage(<OperatorsPage />, {
      [ADMIN_ME_PATH]: SUPERADMIN,
      get [OPERATORS_PATH]() {
        reads += 1;
        return reads === 1
          ? listOf(FOUNDER, operator())
          : problem(503, {
              title: "Service unavailable",
              detail: "The database is unreachable.",
            });
      },
      [`POST ${OPERATORS_PATH}/${ASHA_ID}/revocation`]: operator(),
    });

    await screen.findByText("Asha Rao");
    fireEvent.click(screen.getByRole("button", { name: /Revoke the admin access of Asha Rao/ }));
    const confirmation = operatorRevocationConfirmation(ASHA_ID);
    type(/Why you are revoking Asha Rao's access/, "left the company on Friday");
    type(new RegExp(`Type ${confirmation}`), confirmation);
    fireEvent.click(screen.getByRole("button", { name: "Revoke access" }));

    await screen.findByText("The database is unreachable.");
    expect(container.textContent).not.toContain("Asha Rao");
    expect(container.textContent).toContain("would tell you somebody still has access");
  });

  it("states an empty list only when the server actually sent one", async () => {
    const { container } = renderAdminPage(<OperatorsPage />, routes(listOf()));

    await screen.findByText("No admin accounts are listed");
    // And it says out loud that the state is impossible, because it is: the reader is
    // signed in, so at least their own account exists.
    expect(container.textContent).toContain("treat it as an incident");
  });
});

// ─────────────────────────────────────────────────────────────────────────────────────
// 7. The mirror
// ─────────────────────────────────────────────────────────────────────────────────────

describe("the confirmation strings this console sends", () => {
  /**
   * PINNED TO THE API'S OWN SOURCE, the way `agentTransitionsMirror` pins the client's
   * transition table to the server's.
   *
   * These four strings are copied rather than derived — they are a property of the
   * request being sent, and the server is the authority — which means the only thing
   * standing between a rename on either side and a console whose every consequential
   * write is refused with `step_up_required` is this comparison. Rendering that refusal
   * well (`WriteFailure`) is not the same as noticing it before it ships.
   */
  const source = readFileSync(ROUTES_PY, "utf8");
  const rbac = readFileSync(RBAC_PY, "utf8");
  const rbacStart = rbac.indexOf("NORMAL_ADMIN_ROLE: frozenset(");
  const rbacEnd = rbac.indexOf("SUPERADMIN_ROLE:", rbacStart);

  it("match the builders in apps/api/admin/operator_routes.py", () => {
    expect(source, "operator_routes.py no longer builds the create confirmation").toContain(
      'return f"add_operator:{role}"',
    );
    expect(source).toContain('return f"set_operator_role:{operator_id}"');
    expect(source).toContain('return f"revoke_operator:{operator_id}"');
    expect(source).toContain('return f"reissue_operator_setup_link:{operator_id}"');

    expect(addOperatorConfirmation("superadmin")).toBe("add_operator:superadmin");
    expect(operatorRoleConfirmation(ASHA_ID)).toBe(`set_operator_role:${ASHA_ID}`);
    expect(operatorRevocationConfirmation(ASHA_ID)).toBe(`revoke_operator:${ASHA_ID}`);
    expect(operatorSetupLinkConfirmation(ASHA_ID)).toBe(
      `reissue_operator_setup_link:${ASHA_ID}`,
    );
  });

  it("are sent to the paths that router actually serves", () => {
    expect(source).toContain('APIRouter(prefix="/v1/admin/operators"');
    expect(source).toContain('"/{operator_id}/revocation"');
    expect(source).toContain('"/{operator_id}/setup-link"');
    expect(OPERATORS_PATH).toBe("/v1/admin/operators");
  });

  /**
   * WHAT THIS SCREEN TELLS A FOUNDER THE NARROW TIER CANNOT DO, pinned to the table that
   * decides it.
   *
   * `ROLE_COPY.operator.cannot` is the sentence somebody reads while choosing which tier
   * to hand a colleague, and it names four authorities: the vendor API keys, the platform
   * configuration, the incident switches and this screen. Those are exactly the four
   * permissions `ROLE_PERMISSIONS["operator"]` omits, and `core/rbac.py` says the
   * editorial decision to widen the tier is "one line in one dict" — so one line is all
   * it would take to make this copy false, on the screen whose whole job is to describe
   * the tiers accurately.
   *
   * The scan is over the NORMAL tier's own frozenset, not the whole file: `superadmin`
   * holds all four by derivation and every one of them appears in the `Permission` type
   * a few lines up.
   */
  it("describe a narrow tier that the role table still describes the same way", () => {
    expect(rbacStart, "core/rbac.py no longer spells the normal tier this way").toBeGreaterThan(
      -1,
    );
    expect(rbacEnd).toBeGreaterThan(rbacStart);
    const normalTier = rbac.slice(rbacStart, rbacEnd);
    for (const permission of [
      "platform:secrets",
      "platform:config",
      "ops:manage",
      "admin:operators",
    ]) {
      expect(
        normalTier,
        `ROLE_PERMISSIONS["operator"] now holds ${permission}, so this console's ` +
          "description of what an ordinary admin cannot do is false. Update ROLE_COPY in " +
          "lib/api/adminOperators.ts — and the withheld panels on /admin/ops/config with " +
          "it, plus the hidden sidebar entry in app/admin/layout.tsx.",
      ).not.toContain(`"${permission}"`);
    }
  });

  /**
   * THE PREVIEW AND THE ENFORCEMENT, pinned to each other.
   *
   * `selfAdministrationBlock` is the console's preview of a refusal the API owns, and the
   * refusal is what holds the "there is always a live super admin" invariant up. If the
   * server ever stopped raising it — or renamed it — the console would keep printing a
   * sentence about a rule that no longer exists, on the one screen where believing a
   * stale rule costs the platform its last administrator.
   */
  it("preview a refusal the API still raises", () => {
    const operators = readFileSync(OPERATORS_PY, "utf8");
    expect(
      operators,
      "authn/operators.py no longer refuses self-administration. The console's own " +
        "sentence about it (selfAdministrationBlock) is then a rule it invented.",
    ).toContain('code="operator_self_administration"');
    // And it refuses BOTH acts, which is what makes the row hide both controls.
    expect(operators).toContain('_refuse_self(actor, operator_id, act="change the role of")');
    expect(operators).toContain('_refuse_self(actor, operator_id, act="revoke")');
  });

  it("guard a surface only a superadmin can reach", () => {
    // The one fact the whole two-tier design rests on. If this permission ever appeared
    // in the normal tier's set, a normal admin could grant themselves the other three in
    // one request — so the console's gate is pinned to the API's declaration of it.
    expect(source).toContain('permission_meta("admin:operators")');
  });
});

describe("naming an account on a control", () => {
  it("never falls back to a label two accounts could share", () => {
    // Forty identical "Revoke" buttons are forty identical announcements to a screen
    // reader, and "revoke which one?" is the question a mis-click answers wrongly. The
    // ladder ends at the id rather than at a word like "Unnamed".
    expect(operatorLabel(operator())).toBe("Asha Rao");
    expect(operatorLabel(operator({ name: null }))).toBe("asha@calevate.tech");
    expect(operatorLabel(operator({ name: null, email: null }))).toBe(`account ${ASHA_ID}`);
  });
});
