import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NewClientPage from "@/app/admin/new/page";
import type { CreateOrgOut } from "@/lib/api/admin";

import { problem, renderAdminPage, stubApi } from "./harness";

/**
 * The new-client wizard (FLOWS §1, steps 1 and 8).
 *
 * Step 3 — the intake — landed between steps 1 and 8 and has its own file
 * (`adminNewIntake.test.tsx`). What changed HERE is only the wizard's shape, and this
 * file was updated for it rather than around it: the counter reads "of 3", the account
 * confirmation now sits above both post-creation steps, and reaching the invite means
 * walking past the intake. Every assertion below is the one it always was.
 *
 * Lower blast radius than the ops screen — one account rather than every tenant — but it
 * is the screen that mints a single-use OWNER CREDENTIAL, and every assertion below is
 * about the console claiming something the server did not say:
 *
 * 1. **A creation that failed must not render as a created account.** Everything after
 *    step 1 — the slug an operator will quote, the invite form that posts to a tenant id —
 *    reads off the server's response, so a success panel drawn from local state would
 *    send an operator to a `/c/…` that does not exist and, worse, would stop them
 *    retrying.
 * 2. **The account is named by what came BACK.** The server may normalise or de-duplicate
 *    a slug; a panel built from the typed one tells the operator the wrong URL.
 * 3. **The token is not on screen at all, and the confirmation for one address must never
 *    sit under a refusal for another.** D-198 moved the link into the invitee's mailbox and
 *    replaced `token` with `delivery`, for the reason D-190 gives on the client realm's
 *    twin: a token an operator can read is a token the operator can redeem. What is
 *    rendered is the ADDRESS it went to, and that must still be cleared at submit — "sent
 *    to owner@a" standing under a refusal for owner@b is a claim about mail nobody sent.
 * 4. **A refused control stops offering itself, with the server's reason.** Both writes
 *    are `admin:tenants`, which both admin roles hold, so a 403 here is a genuine
 *    surprise — and a surprise is the worst thing to answer with an identical retry.
 */

const TENANTS = "/v1/admin/tenants";

const CREATED: CreateOrgOut = {
  id: "0192f0aa-7777-7000-8000-000000000001",
  slug: "sunrise-clinic-2",
  status: "active",
  agent_id: "0192f0aa-7777-7000-8000-0000000000a1",
  extraction_schema_id: "0192f0aa-7777-7000-8000-0000000000b1",
};

const INVITATIONS = `${TENANTS}/${CREATED.id}/invitations`;
const INTAKE = `${TENANTS}/${CREATED.id}/agents/${CREATED.agent_id}/intake`;
// Step 3 previews its own permission (`agents:write`), so reaching it asks the admin
// realm who this session is. Stubbed here as premise rather than assertion — this file's
// subject is the invite, and `adminNewIntake.test.tsx` owns the gate.
const ADMIN_ME = "/v1/admin/me";
// Step 1 lists the onboardings somebody started and did not finish, so an operator
// resumes instead of recreating a client under a slug the first attempt already holds
// (slugs are immutable). Stubbed EMPTY as a premise: this file's subject is the invite,
// and an unstubbed read renders that panel's refusal card over every test here — which
// is the panel behaving correctly, and noise in the wrong file.
const UNFINISHED = "/v1/admin/onboarding/unfinished";
const OPERATOR = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000f2",
  role: "operator",
  permissions: ["org:read", "agents:read", "agents:write", "admin:tenants"],
};

/** A brand-new agent's intake: the API answers 200 with everything empty, not a 404. */
const NO_INTAKE = {
  business_hours: {},
  escalation_contacts: [],
  languages: [],
  prose_answers: null,
  compiled_t0_context: null,
  submitted_at: null,
};

function fillName(value = "Sunrise Clinic") {
  fireEvent.change(screen.getByPlaceholderText("Sunrise Clinic"), { target: { value } });
}

describe("creating the account", () => {
  it("does not report success it has not received", async () => {
    const { container } = renderAdminPage(<NewClientPage />, {
      [TENANTS]: problem(409, {
        title: "Slug taken",
        detail: "That slug already belongs to another client.",
        remediation: "Choose a different slug.",
      }),
      [UNFINISHED]: [],
    });

    fillName();
    fireEvent.click(screen.getByRole("button", { name: "Create client" }));

    await screen.findByText("That slug already belongs to another client.");
    // No creation claim anywhere, and the operator is still on step 1 with their input.
    expect(screen.queryByText("Account created")).toBeNull();
    expect(container.textContent).not.toContain("Invite the owner");
    expect(container.textContent).toContain("Step 1 of 3");
    // The refusal is answerable, so the control must stay live to answer it.
    expect(
      (screen.getByRole("button", { name: "Create client" }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("names the account from the server's slug, not from what was typed", async () => {
    const { container } = renderAdminPage(<NewClientPage />, {
      [TENANTS]: CREATED,
      [ADMIN_ME]: OPERATOR,
      [INTAKE]: NO_INTAKE,
      [UNFINISHED]: [],
    });

    fillName();
    fireEvent.click(screen.getByRole("button", { name: "Create client" }));

    await screen.findByText("Account created");
    // The server de-duplicated the slug; the panel quotes what actually exists.
    expect(container.textContent).toContain("/c/sunrise-clinic-2");
    expect(container.textContent).not.toContain("/c/sunrise-clinic ");
    expect(container.textContent).toContain("Step 2 of 3");
  });

  it("stops offering a control the session is refused, with the server's reason", async () => {
    renderAdminPage(<NewClientPage />, {
      [TENANTS]: problem(403, {
        title: "Forbidden",
        detail: "This action requires the admin:tenants permission.",
        remediation: "Ask a superadmin to create the account.",
      }),
      [UNFINISHED]: [],
    });

    fillName();
    fireEvent.click(screen.getByRole("button", { name: "Create client" }));

    await screen.findByText("This action requires the admin:tenants permission.");
    const button = screen.getByRole("button", { name: "Create client" }) as HTMLButtonElement;
    // A permission refusal will not change on the second click, so the button says so
    // rather than inviting an identical 403.
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(button.title).toBe("Ask a superadmin to create the account.");
    expect(screen.queryByText("Account created")).toBeNull();
  });
});

describe("the owner invite", () => {
  /** The row id the response carries so the panel can revoke what it just created. */
  const INVITE_ID = "0192f0aa-7777-7000-8000-0000000000d1";

  /** Create the account, then walk past step 3 — the invite is the LAST step now. */
  async function reachTheInvite(routes: Record<string, unknown>) {
    const render = renderAdminPage(<NewClientPage />, {
      [TENANTS]: CREATED,
      [ADMIN_ME]: OPERATOR,
      [INTAKE]: NO_INTAKE,
      [UNFINISHED]: [],
      ...routes,
    });
    fillName();
    fireEvent.click(screen.getByRole("button", { name: "Create client" }));
    await screen.findByText("Account created");
    // `findBy`, not `getBy`: the intake step is a skeleton until its prefill lands, and
    // the control that leaves it does not exist while it is one.
    fireEvent.click(await screen.findByRole("button", { name: /Continue to the owner invite/ }));
    return render;
  }

  it("confirms the address it was sent to, and never renders a credential", async () => {
    const { container } = await reachTheInvite({
      [INVITATIONS]: { id: INVITE_ID, delivery: "queued", expires_in_hours: 72 },
    });

    fireEvent.change(screen.getByPlaceholderText("owner@business.com"), {
      target: { value: "owner@sunrise.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));

    await screen.findByText("Invitation sent");
    expect(container.textContent).toContain("owner@sunrise.example");
    expect(container.textContent).toContain("becomes an owner of");
    // D-198: the secret exists in the invitee's mailbox and nowhere else. A screen that
    // renders it is a screen an operator can copy it off.
    expect(container.textContent).not.toContain("inv_live_");
  });

  it("clears the previous confirmation before a second attempt, so no refusal sits over another address's mail", async () => {
    await reachTheInvite({ [INVITATIONS]: { id: INVITE_ID, delivery: "queued", expires_in_hours: 72 } });

    const emailBox = screen.getByPlaceholderText("owner@business.com");
    fireEvent.change(emailBox, { target: { value: "owner@sunrise.example" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));
    await screen.findByText("Invitation sent");

    // The second address is refused. Re-stubbing the network mid-test is the only way to
    // give one path two answers, and the point of the test is the SEQUENCE: the first
    // owner's credential must not still be on screen under the second one's error.
    stubApi({
      [INVITATIONS]: problem(422, {
        title: "Invalid email",
        detail: "That address is not deliverable.",
      }),
    });
    fireEvent.change(emailBox, { target: { value: "owner@typo" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));

    await screen.findByText("That address is not deliverable.");
    expect(screen.queryByText("Invitation sent")).toBeNull();
  });

  it("mints nothing for an address nobody typed", async () => {
    const { calls } = await reachTheInvite({
      [INVITATIONS]: { id: INVITE_ID, delivery: "queued", expires_in_hours: 72 },
    });

    // The billing email was left blank in step 1, so the invite opens empty — and an empty
    // invite is a token nobody can use plus a membership row nobody asked for.
    const button = screen.getByRole("button", { name: "Create invite" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(calls.some((c) => c.path === INVITATIONS)).toBe(false);
  });
});

/**
 * The way out of the refusal the server now gives (`invitation_already_pending`).
 *
 * One live token per address is the right rule — two keys to a client's account in one
 * inbox, only one of them revocable — but on its own it strands the operator: the revoke
 * that already existed is client-realm, and this invite is minted before anybody can sign
 * in, so nobody could press it. `DELETE /v1/admin/tenants/{id}/invitations/{id}` is the
 * console's control, and the panel only offers it for the invitation THIS wizard issued.
 */
describe("cancelling an invite the wizard already issued", () => {
  const MINTED = {
    id: "0192f0aa-7777-7000-8000-0000000000e1",
    delivery: "queued",
    expires_in_hours: 72,
  };
  const REVOKE = `${INVITATIONS}/${MINTED.id}`;

  async function reachTheInvite(routes: Record<string, unknown>) {
    const render = renderAdminPage(<NewClientPage />, {
      [TENANTS]: CREATED,
      [ADMIN_ME]: OPERATOR,
      [INTAKE]: NO_INTAKE,
      [UNFINISHED]: [],
      ...routes,
    });
    fillName();
    fireEvent.click(screen.getByRole("button", { name: "Create client" }));
    await screen.findByText("Account created");
    fireEvent.click(await screen.findByRole("button", { name: /Continue to the owner invite/ }));
    return render;
  }

  it("offers no cancel until an invite has actually been minted", async () => {
    await reachTheInvite({ [INVITATIONS]: MINTED });

    expect(screen.queryByRole("button", { name: /Cancel the unused invite/ })).toBeNull();
  });

  it("offers the cancel only when the server refused a duplicate, and deletes the row it holds", async () => {
    await reachTheInvite({ [INVITATIONS]: MINTED, [`DELETE ${REVOKE}`]: null });

    const emailBox = screen.getByPlaceholderText("owner@business.com");
    fireEvent.change(emailBox, { target: { value: "owner@sunrise.example" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));
    await screen.findByText("Invitation sent");
    // No cancel yet: a successful mint is not a reason to offer to undo it.
    expect(screen.queryByRole("button", { name: /Cancel the unused invite/ })).toBeNull();

    // Re-stubbing replaces the network AND the call log, so the new log is the one that
    // can see the DELETE.
    const calls = stubApi({
      [INVITATIONS]: problem(409, {
        // The `type` URL's last segment IS the machine code the screen keys on.
        type: "https://calevate.tech/problems/invitation_already_pending",
        title: "Invitation already pending",
        detail: "There is already an unused invitation for that address.",
      }),
      [`DELETE ${REVOKE}`]: null,
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));
    await screen.findByText("There is already an unused invitation for that address.");

    fireEvent.click(await screen.findByRole("button", { name: /Cancel the unused invite/ }));

    await waitFor(() => {
      const deleted = calls.find((c) => c.method === "DELETE");
      expect(deleted?.path).toBe(REVOKE);
    });
  });

  it("shows the server's refusal when the cancel itself is refused, and claims nothing", async () => {
    await reachTheInvite({ [INVITATIONS]: MINTED });

    fireEvent.change(screen.getByPlaceholderText("owner@business.com"), {
      target: { value: "owner@sunrise.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));
    await screen.findByText("Invitation sent");

    stubApi({
      [INVITATIONS]: problem(409, {
        type: "https://calevate.tech/problems/invitation_already_pending",
        title: "Already pending",
        detail: "Already pending.",
      }),
      [`DELETE ${REVOKE}`]: problem(404, {
        title: "Invitation not found",
        detail: "That invitation has already been used.",
      }),
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));
    await screen.findByText("Already pending.");
    fireEvent.click(await screen.findByRole("button", { name: /Cancel the unused invite/ }));

    // The server's sentence, not a reassuring one of ours — and the duplicate refusal
    // stays on screen, because nothing about it stopped being true.
    await screen.findByText("That invitation has already been used.");
    expect(screen.getByText("Already pending.")).toBeTruthy();
  });

  it("lists the pending invites this session did not issue, so the refusal is actionable", async () => {
    // No prior success in this tab: the first link was issued by a colleague, so the
    // component has no id of its own and must ask.
    await reachTheInvite({
      [`POST ${INVITATIONS}`]: problem(409, {
        type: "https://calevate.tech/problems/invitation_already_pending",
        title: "Invitation already pending",
        detail: "There is already an unused invitation for that address.",
      }),
      [`GET ${INVITATIONS}`]: [
        {
          id: MINTED.id,
          email_masked: "o\u2022\u2022\u2022\u2022@sunrise.example",
          role: "owner",
          invited_at: "2026-08-14T09:00:00Z",
          expires_at: "2026-08-17T09:00:00Z",
        },
      ],
      [`DELETE ${REVOKE}`]: null,
    });

    fireEvent.change(screen.getByPlaceholderText("owner@business.com"), {
      target: { value: "owner@sunrise.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));

    await screen.findByText("There is already an unused invitation for that address.");
    // The masked address is what an operator recognises; the raw one is never printed.
    await screen.findByText("o\u2022\u2022\u2022\u2022@sunrise.example");
    expect(screen.getByRole("button", { name: "Cancel this invite" })).toBeTruthy();
  });

  it("refuses rather than reporting an empty list when the pending read fails", async () => {
    await reachTheInvite({
      [`POST ${INVITATIONS}`]: problem(409, {
        type: "https://calevate.tech/problems/invitation_already_pending",
        title: "Invitation already pending",
        detail: "There is already an unused invitation for that address.",
      }),
      [`GET ${INVITATIONS}`]: problem(503, {
        title: "Unavailable",
        detail: "We could not read the invitations for this account.",
      }),
    });

    fireEvent.change(screen.getByPlaceholderText("owner@business.com"), {
      target: { value: "owner@sunrise.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));

    await screen.findByText("We could not read the invitations for this account.");
    // Never a cancel control built from an absent list, and never silence: the operator
    // is stuck either way, and only one of those two says so.
    expect(screen.queryByRole("button", { name: "Cancel this invite" })).toBeNull();
  });
});
