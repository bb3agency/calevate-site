import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TeamPage from "@/app/c/[slug]/settings/team/page";
import type { Me } from "@/lib/api/client";
import type { Member, PendingInvitation } from "@/lib/api/members";

import { problem, renderClientPage } from "./harness";

/**
 * The team screen — the one client surface where a click changes what a future request
 * is ALLOWED to do.
 *
 * Two obligations meet here, and they fail in opposite directions:
 *
 * - **The gate.** `staff` and a read-only impersonating operator (D-22) both see the
 *   list and neither may change it. A gate that renders the control anyway teaches a
 *   client that our permission rules are a bug; a gate that hides the control with no
 *   explanation gets filed as one. So every refusal is asserted together with the
 *   sentence that explains it, in the place the control would have been.
 * - **§52's rule, where the empty state is a security claim.** "Nobody is on this
 *   account yet" printed over a FAILED request is the worst sentence this screen can
 *   produce: it reads as "nobody else has access", to the person who came to check
 *   exactly that, and it invites re-inviting colleagues who already have access. Failure
 *   is the refusal notice and NOTHING else.
 */

const ME: Me = {
  impersonating: false,
  permissions: ["org:read", "org:manage", "leads:read"],
  realm: "client",
  role: "owner",
  user_id: "0192f0aa-1111-7000-8000-000000000001",
  organization: null,
};

/** A viewer who may look at the team and change nothing (`staff`). */
const STAFF_ME: Me = { ...ME, permissions: ["org:read", "leads:read"], role: "staff" };

/** A support engineer inside "view as client" — D-22 read-only. */
const IMPERSONATING_ME: Me = { ...ME, impersonating: true };

const OWNER: Member = { id: ME.user_id as string, name: "Anita", role: "owner" };
const STAFF: Member = { id: "0192f0aa-2222-7000-8000-000000000002", name: "Priya", role: "staff" };

const INVITE: PendingInvitation = {
  id: "0192f0aa-3333-7000-8000-000000000003",
  email_masked: "r•••@clinic.example",
  role: "staff",
  invited_at: "2026-08-01T09:00:00Z",
  expires_at: "2026-08-04T09:00:00Z",
};

async function renderTeam(
  over: {
    /* `unknown`, not `Me`: one test hands this a `problem()` so the screen meets a FAILED
       `/v1/me`, and the route map takes `unknown` — asserting a refusal into the wire
       type would be exactly what `wireFixtureGuard.test.ts` bans. */
    me?: unknown;
    members?: unknown;
    invitations?: unknown;
  } = {},
) {
  return await renderClientPage(<TeamPage />, {
    "/v1/me": over.me ?? ME,
    "/v1/members": over.members ?? [OWNER, STAFF],
    "/v1/invitations": over.invitations ?? [],
  });
}

describe("who may change the team", () => {
  it("gives an owner a role control and a Remove for a colleague", async () => {
    await renderTeam();

    await screen.findByText("Priya");
    expect(
      screen.getByRole("button", { name: "Remove Priya from this account" }),
    ).toBeTruthy();
    expect(screen.getByRole("combobox", { name: /Role for Priya/ })).toBeTruthy();
  });

  it("offers a staff member no controls, and says why where they would be", async () => {
    const { container } = await renderTeam({ me: STAFF_ME });

    await screen.findByText("Priya");
    expect(screen.queryByRole("button", { name: /^Remove / })).toBeNull();
    expect(screen.queryByRole("combobox", { name: /Role for/ })).toBeNull();
    // The reason, not just the absence: a control that vanishes without a sentence is
    // indistinguishable from a screen that failed to render it.
    expect(container.textContent).toContain("Only an account owner can");
    expect(container.textContent).not.toContain("Invite a colleague");
  });

  it("refuses an impersonating operator the controls while keeping the list", async () => {
    const { container } = await renderTeam({ me: IMPERSONATING_ME });

    // D-22: support must be able to SEE who has access.
    await screen.findByText("Priya");
    await screen.findByText("Anita");
    expect(screen.queryByRole("button", { name: /^Remove / })).toBeNull();
    expect(container.textContent).toContain("read-only");
    expect(container.textContent).toContain("admin console");
  });

  it("never offers a control on your own row, and explains that too", async () => {
    const { container } = await renderTeam();

    await screen.findByText("Anita");
    expect(screen.queryByRole("button", { name: /Remove Anita/ })).toBeNull();
    expect(screen.queryByRole("combobox", { name: /Role for Anita/ })).toBeNull();
    expect(container.textContent).toContain("You cannot change your own access");
  });

  /**
   * When `/v1/me` fails, the screen does not know WHICH ROW IS YOU — `myId` is null, so
   * `isMe` is false for every row and the "(you)" marker and the sentence beside it are
   * gone. The obvious worry is that the owner is then offered a role select and a Remove
   * on themselves, which the API refuses with a 403 that nobody can read as a boundary.
   *
   * **That does not happen, and this test is here so it cannot start.** `useWriteAccess`
   * reads the SAME `/v1/me` query, so a failure that blanks `myId` also makes
   * `write.allowed` false and `write.reason` "We could not check whether you can …" — the
   * row renders that sentence where the controls would be, and no control is offered to
   * anybody on any row. The two derivations agreeing is what makes the screen safe, and
   * it would stop being true the moment `myId` came from somewhere else — a prop, a
   * second query, a cached session.
   */
  it("offers nobody a control when it does not know who you are", async () => {
    const { container } = await renderTeam({
      me: problem(503, { title: "Service unavailable", retryable: false }),
    });

    await screen.findByText("Anita");
    expect(screen.queryByRole("button", { name: /^Remove / })).toBeNull();
    expect(screen.queryByRole("combobox", { name: /Role for/ })).toBeNull();
    expect(container.textContent).toContain("We could not check whether you can");
    // …and the screen does not claim to know which row is you, either way round.
    expect(container.textContent).not.toContain("(you)");
    expect(container.textContent).not.toContain("You cannot change your own access");
  });
});

describe("what a click actually sends", () => {
  it("sends the role the row was SHOWING as the compare-and-swap guard", async () => {
    const { calls } = await renderTeam();

    await screen.findByText("Priya");
    fireEvent.change(screen.getByRole("combobox", { name: /Role for Priya/ }), {
      target: { value: "owner" },
    });

    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH");
      expect(patch, "the role change must reach the API").toBeTruthy();
      // `expected_role` is what makes a stale screen a 409 instead of a silent
      // overwrite of another owner's decision.
      expect(JSON.parse(patch!.body ?? "{}")).toEqual({
        role: "owner",
        expected_role: "staff",
      });
      expect(patch!.path).toBe(`/v1/members/${STAFF.id}`);
    });
  });

  it("shows the API's refusal rather than a generic failure", async () => {
    const { container } = await renderClientPage(<TeamPage />, {
      "/v1/me": ME,
      "/v1/members": [OWNER, STAFF],
      "/v1/invitations": [],
      [`/v1/members/${STAFF.id}`]: problem(422, {
        title: "Request rejected by a business rule",
        detail: "This is the only owner on the account, so their access cannot be reduced.",
        remediation: "Make someone else an owner first",
        kind: "business_rule",
      }),
    });

    await screen.findByText("Priya");
    fireEvent.change(screen.getByRole("combobox", { name: /Role for Priya/ }), {
      target: { value: "owner" },
    });

    await waitFor(() =>
      expect(container.textContent).toContain("only owner on the account"),
    );
  });

  it("states how many leads a removed colleague still owns", async () => {
    const { container } = await renderClientPage(<TeamPage />, {
      "/v1/me": ME,
      "/v1/members": [OWNER, STAFF],
      "/v1/invitations": [],
      [`/v1/members/${STAFF.id}`]: {
        user_id: STAFF.id,
        previous_role: "staff",
        leads_still_assigned: 4,
      },
    });

    await screen.findByText("Priya");
    fireEvent.click(screen.getByRole("button", { name: "Remove Priya from this account" }));

    // Removing somebody does not unassign their work, so a screen that said nothing
    // would leave four leads quietly belonging to a person who can no longer sign in.
    await waitFor(() => expect(container.textContent).toContain("4 leads are still assigned"));
  });
});

describe("failure is never an empty state", () => {
  it("does not say the account has nobody on it when the list failed", async () => {
    const { container } = await renderTeam({ members: problem(503, { detail: "database down" }) });

    // The refusal itself, from the server's problem+json — not a generic apology.
    await waitFor(() => expect(container.textContent).toContain("database down"));
    expect(container.textContent).not.toContain("Nobody is on this account yet");
    // Nor a count invented from a list that never arrived.
    expect(container.textContent).not.toContain("0 people");
    expect(container.textContent).not.toContain("1 person");
  });

  it("does not claim there are no unused invite links when that list failed", async () => {
    const { container } = await renderTeam({
      invitations: problem(503, { detail: "database down" }),
    });

    await screen.findByText("Priya");
    expect(container.textContent).not.toContain("No unused invites");
    expect(container.textContent).not.toContain("0 unused links");
  });

  it("still renders the empty state when the server actually said empty", async () => {
    const { container } = await renderTeam({ members: [], invitations: [] });

    await screen.findByText("Nobody is on this account yet");
    expect(container.textContent).toContain("No unused invites");
  });
});

describe("what the invite flow shows", () => {
  it("shows the one-time link and never an unmasked address", async () => {
    const created = {
      id: INVITE.id,
      email_masked: "p••••@clinic.example",
      role: "staff",
      invited_at: "2026-08-01T09:00:00Z",
      expires_at: "2026-08-04T09:00:00Z",
      token: "tok_abcdefghijklmnopqrstuvwxyz012345",
    };
    // The harness keys its routes by PATH, so the GET of the pending list and the POST
    // that creates one share this entry. This test is about the POST; the list panel
    // reads the same object, finds no length and renders its empty state, which is
    // harmless here and is asserted properly in the tests above.
    const { container, calls } = await renderClientPage(<TeamPage />, {
      "/v1/me": ME,
      "/v1/members": [OWNER],
      "/v1/invitations": created,
    });

    await screen.findByText("Anita");
    fireEvent.change(screen.getByRole("textbox", { name: "Email address to invite" }), {
      target: { value: "priya@clinic.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create invite link/ }));

    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST");
      expect(post?.path).toBe("/v1/invitations");
    });
    await waitFor(() => expect(container.textContent).toContain(created.token));
    // The address the owner typed is echoed only in its masked form.
    expect(container.textContent).not.toContain("priya@clinic.example");
    expect(container.textContent).toContain("p••••@clinic.example");
    expect(container.textContent).toContain("We cannot show this link again");
  });

  it("lists a pending invitation masked, with a revoke control for an owner", async () => {
    const { container } = await renderTeam({ invitations: [INVITE] });

    await screen.findByText(INVITE.email_masked);
    expect(
      screen.getByRole("button", { name: `Revoke the invitation for ${INVITE.email_masked}` }),
    ).toBeTruthy();
    expect(container.textContent).toContain("1 unused link");
  });

  it("shows a staff member the pending invites with no revoke control", async () => {
    await renderTeam({ me: STAFF_ME, invitations: [INVITE] });

    await screen.findByText(INVITE.email_masked);
    expect(screen.queryByRole("button", { name: /^Revoke / })).toBeNull();
  });
});
