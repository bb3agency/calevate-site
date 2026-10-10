import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NewClientPage from "@/app/admin/new/page";
import { OwnerInvitePanel } from "@/app/admin/tenants/[tenantId]/OwnerInvitePanel";
import type { CreateOrgOut } from "@/lib/api/admin";

import { problem, renderAdminPage, stubApi } from "./harness";

/**
 * The new-client wizard (FLOWS §1, steps 1 and 8).
 *
 * D-695: the operator enters only the business and the owner; the client fills in the
 * business in their own setup. Two steps: the business, then the invite.
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
  vertical_template: "clinic",
  invitation_id: "0192f0aa-7777-7000-8000-0000000000e1",
};

const INVITATIONS = `${TENANTS}/${CREATED.id}/invitations`;
// Who this session is, stubbed as a premise.
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

function fillName(value = "Sunrise Clinic") {
  // No business type is chosen for the operator (any trade may be next), so the name's
  // placeholder is the neutral one until a type is picked.
  fireEvent.change(screen.getByPlaceholderText("Sri Traders"), {
    target: { value },
  });
  fireEvent.click(screen.getByRole("radio", { name: /^Clinic/ }));
  // The owner's email is required on step 1: the invite goes to it.
  fireEvent.change(screen.getByPlaceholderText("owner@business.com"), {
    target: { value: "owner@sunrise.example" },
  });
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
    fireEvent.click(screen.getByRole("button", { name: "Create and invite" }));

    await screen.findByText("That slug already belongs to another client.");
    // No creation claim anywhere, and the operator is still on step 1 with their input.
    expect(screen.queryByText("Account created and owner invited")).toBeNull();
    expect(container.textContent).not.toContain("Invite the owner");
    // The refusal is answerable, so the control must stay live to answer it.
    expect(
      (
        screen.getByRole("button", {
          name: "Create and invite",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });

  it("names the account from the server's slug, not from what was typed", async () => {
    const { container } = renderAdminPage(<NewClientPage />, {
      [TENANTS]: CREATED,
      [ADMIN_ME]: OPERATOR,
      [UNFINISHED]: [],
    });

    fillName();
    fireEvent.click(screen.getByRole("button", { name: "Create and invite" }));

    await screen.findByText("Account created and owner invited");
    // The server de-duplicated the slug; the panel quotes what actually exists.
    expect(container.textContent).toContain("/c/sunrise-clinic-2");
    expect(container.textContent).not.toContain("/c/sunrise-clinic ");
  });

  it("asks for the business type rather than assuming one", async () => {
    const { calls } = renderAdminPage(<NewClientPage />, { [TENANTS]: CREATED, [ADMIN_ME]: OPERATOR, [UNFINISHED]: [] });
    fireEvent.change(screen.getByPlaceholderText("Sri Traders"), { target: { value: "Skyline Homes" } });
    fireEvent.change(screen.getByPlaceholderText("owner@business.com"), {
      target: { value: "owner@skyline.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create and invite" }));

    expect(await screen.findByText("Choose the business type.")).toBeTruthy();
    expect(screen.queryByText("Account created and owner invited")).toBeNull();
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("stops offering a control the session is refused, with the server's reason", async () => {
    renderAdminPage(<NewClientPage />, {
      [TENANTS]: problem(403, {
        title: "Forbidden",
        detail: "You do not have permission to do this.",
        remediation: "Ask a superadmin to create the account.",
      }),
      [UNFINISHED]: [],
    });

    fillName();
    fireEvent.click(screen.getByRole("button", { name: "Create and invite" }));

    await screen.findByText("You do not have permission to do this.");
    const button = screen.getByRole("button", {
      name: "Create and invite",
    }) as HTMLButtonElement;
    // A permission refusal will not change on the second click, so the button says so
    // rather than inviting an identical 403.
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(button.title).toBe("Ask a superadmin to create the account.");
    expect(screen.queryByText("Account created and owner invited")).toBeNull();
  });
});

describe("the owner invite", () => {
  /** The row id the response carries so the panel can revoke what it just created. */
  const INVITE_ID = "0192f0aa-7777-7000-8000-0000000000d1";

  /** Create the account; the invite is step 2. */
  async function reachTheInvite(routes: Record<string, unknown>) {
    return renderAdminPage(
      <OwnerInvitePanel created={{ id: CREATED.id, slug: CREATED.slug }} />,
      { [ADMIN_ME]: OPERATOR, ...routes },
    );
  }

  it("confirms the address it was sent to, and never renders a credential", async () => {
    const { container } = await reachTheInvite({
      [INVITATIONS]: {
        id: INVITE_ID,
        delivery: "queued",
        expires_in_hours: 72,
      },
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
    await reachTheInvite({
      [INVITATIONS]: {
        id: INVITE_ID,
        delivery: "queued",
        expires_in_hours: 72,
      },
    });

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
    // A SHAPE THE CLIENT ACCEPTS, so the SERVER is the one doing the refusing — which is
    // what this test is about. `owner@typo` was the address here until the form gained its
    // own validation, and that now stops at the field: a plausible-looking address the
    // server rejects is the only way to drive the sequence this test exists for.
    fireEvent.change(emailBox, { target: { value: "owner@typo.example" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));

    await screen.findByText("That address is not deliverable.");
    expect(screen.queryByText("Invitation sent")).toBeNull();
  });

  it("mints nothing for an address nobody typed", async () => {
    const { calls } = await reachTheInvite({
      [INVITATIONS]: {
        id: INVITE_ID,
        delivery: "queued",
        expires_in_hours: 72,
      },
    });

    // The billing email was left blank in step 1, so the invite opens empty — and an empty
    // invite is a token nobody can use plus a membership row nobody asked for.
    //
    // The button is LIVE and the press is refused at the field, which is the change: a
    // dead button beside an empty box told the operator nothing about which box or why.
    const button = screen.getByRole("button", {
      name: "Create invite",
    }) as HTMLButtonElement;
    fireEvent.click(button);
    await screen.findByText("Enter the owner's email address.");
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
    return renderAdminPage(
      <OwnerInvitePanel created={{ id: CREATED.id, slug: CREATED.slug }} />,
      { [ADMIN_ME]: OPERATOR, ...routes },
    );
  }

  it("offers no cancel until an invite has actually been minted", async () => {
    await reachTheInvite({ [INVITATIONS]: MINTED });

    expect(
      screen.queryByRole("button", { name: /Cancel the unused invite/ }),
    ).toBeNull();
  });

  it("offers the cancel only when the server refused a duplicate, and deletes the row it holds", async () => {
    await reachTheInvite({ [INVITATIONS]: MINTED, [`DELETE ${REVOKE}`]: null });

    const emailBox = screen.getByPlaceholderText("owner@business.com");
    fireEvent.change(emailBox, { target: { value: "owner@sunrise.example" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));
    await screen.findByText("Invitation sent");
    // No cancel yet: a successful mint is not a reason to offer to undo it.
    expect(
      screen.queryByRole("button", { name: /Cancel the unused invite/ }),
    ).toBeNull();

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
    await screen.findByText(
      "There is already an unused invitation for that address.",
    );

    fireEvent.click(
      await screen.findByRole("button", { name: /Cancel the unused invite/ }),
    );

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
    fireEvent.click(
      await screen.findByRole("button", { name: /Cancel the unused invite/ }),
    );

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
          email: "owner@sunrise.example",
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

    await screen.findByText(
      "There is already an unused invitation for that address.",
    );
    // The masked address is what an operator recognises; the raw one is never printed.
    await screen.findByText("owner@sunrise.example");
    expect(
      screen.getByRole("button", { name: "Cancel this invite" }),
    ).toBeTruthy();
  });

  it("re-sends the link the wizard issued, and says the old one has stopped working", async () => {
    /**
     * D-538's founder ask, verbatim: *"the invite link can be re-sent via the admin panel
     * for a client business until that mail sets up their business"*. The route shipped
     * with the decision and NOTHING in this console called it, so the operator staring at
     * `invitation_already_pending` — the state where a lost mail actually shows up — could
     * only CANCEL a live key. This asserts the POST reaches the resend path, not that a
     * button exists.
     */
    await reachTheInvite({ [INVITATIONS]: MINTED });

    fireEvent.change(screen.getByPlaceholderText("owner@business.com"), {
      target: { value: "owner@sunrise.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));
    await screen.findByText("Invitation sent");

    const calls = stubApi({
      [INVITATIONS]: problem(409, {
        type: "https://calevate.tech/problems/invitation_already_pending",
        title: "Invitation already pending",
        detail: "There is already an unused invitation for that address.",
      }),
      [`POST ${REVOKE}/resend`]: {
        id: MINTED.id,
        email: "owner@sunrise.example",
        delivery: "queued",
        expires_at: "2026-08-17T09:00:00Z",
        last_sent_at: "2026-08-14T09:00:00Z",
        send_count: 2,
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create invite" }));
    await screen.findByText(
      "There is already an unused invitation for that address.",
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Send it again" }),
    );

    await waitFor(() => {
      const sent = calls.find(
        (c) => c.method === "POST" && c.path.endsWith("/resend"),
      );
      expect(sent?.path).toBe(`${REVOKE}/resend`);
    });
    // The rotation kills the previous link, so the screen has to say so — an operator who
    // reads "sent again" and nothing else will tell the client to use whichever mail they
    // find first.
    await screen.findByText(/previous one has stopped working/);
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

    await screen.findByText(
      "We could not read the invitations for this account.",
    );
    // Never a cancel control built from an absent list, and never silence: the operator
    // is stuck either way, and only one of those two says so.
    expect(
      screen.queryByRole("button", { name: "Cancel this invite" }),
    ).toBeNull();
  });
});
