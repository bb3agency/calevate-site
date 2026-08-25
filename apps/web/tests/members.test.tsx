import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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
  email: "ravi@clinic.example",
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
    // The dropdown STAGES the change now (TEAM-1): a stray scroll wheel over a focused
    // select used to grant `org:manage` outright. The write is the named second press.
    expect(calls.filter((c) => c.method === "PATCH")).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Save Priya as Owner" }));

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
    fireEvent.click(screen.getByRole("button", { name: "Save Priya as Owner" }));

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
    // Removal is confirmed now (TEAM-1). The dialog is the second press; the assertion
    // that the FIRST press sent nothing lives in its own test below.
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Remove their access",
      }),
    );

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
  it("confirms the send, shows the address it went to, and never shows the token", async () => {
    const created = {
      id: INVITE.id,
      email: "priya@clinic.example",
      role: "staff",
      invited_at: "2026-08-01T09:00:00Z",
      expires_at: "2026-08-04T09:00:00Z",
      delivery: "queued",
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
    // D-190: the token is not in the response and is therefore not on the screen. This
    // assertion used to be `toContain(created.token)` — the inversion is the fix.
    await waitFor(() => expect(container.textContent).toContain("Invitation sent to"));
    expect(container.textContent).not.toContain("tok_");
    // WAS `not.toContain("priya@clinic.example")` beside a masked-form assertion.
    // D-436: the owner who just typed the address is the one person who has to be able
    // to check it — a typo in an invitation is a key mailed to a stranger. The TOKEN
    // assertion above is the one that matters here and is untouched.
    expect(container.textContent).toContain("priya@clinic.example");
    expect(container.textContent).toContain("We cannot show or re-send the link");
  });

  it("lists a pending invitation with its address and a revoke control for an owner", async () => {
    const { container } = await renderTeam({ invitations: [INVITE] });

    await screen.findByText(INVITE.email);
    expect(
      screen.getByRole("button", { name: `Revoke the invitation for ${INVITE.email}` }),
    ).toBeTruthy();
    expect(container.textContent).toContain("1 unused link");
  });

  it("shows a staff member the pending invites with no revoke control", async () => {
    await renderTeam({ me: STAFF_ME, invitations: [INVITE] });

    await screen.findByText(INVITE.email);
    expect(screen.queryByRole("button", { name: /^Revoke / })).toBeNull();
  });
});

/**
 * TEAM-1 — the screen that governs who can sign in to the business now asks twice.
 *
 * Both controls fired on a single unconfirmed interaction. Selecting "Owner" in a
 * dropdown granted a colleague `billing:read` AND `org:manage` — the ability to see the
 * invoice and to remove other members, INCLUDING the person who just granted it — with no
 * are-you-sure moment anywhere; "Remove" revoked access on one press, styled in the same
 * class as a benign action, and the page then reported how many leads were stranded,
 * which is a consequence disclosed after the fact.
 *
 * The file's own comment already said the rule ("a mis-click cannot cost somebody their
 * own access"); it was applied to exactly one row, the reader's own. These tests apply it
 * to everybody else's.
 *
 * Two different mechanisms on purpose, and the difference is argued in the page: a role
 * change is a change of capability, so it stages in place and names what it will do (the
 * check-answers shape); a removal destroys access, so it gets the modal.
 */
describe("no colleague's access changes on one unconfirmed press", () => {
  it("stages a role change and names what it grants before it is saved", async () => {
    const { container, calls } = await renderTeam();

    await screen.findByText("Priya");
    fireEvent.change(screen.getByRole("combobox", { name: /Role for Priya/ }), {
      target: { value: "owner" },
    });

    expect(calls.filter((c) => c.method === "PATCH")).toEqual([]);
    // The consequence, in capabilities the owner recognises — including the one that
    // makes this irreversible from their side.
    expect(container.textContent).toContain("including you");
    expect(screen.getByRole("button", { name: "Save Priya as Owner" })).toBeTruthy();
  });

  it("lets a mis-selection be put back with nothing sent", async () => {
    const { container, calls } = await renderTeam();

    await screen.findByText("Priya");
    const select = screen.getByRole("combobox", { name: /Role for Priya/ });
    fireEvent.change(select, { target: { value: "owner" } });
    fireEvent.change(select, { target: { value: "staff" } });

    // Back to what the server said, so there is nothing to save and nothing to warn about.
    expect(calls.filter((c) => c.method === "PATCH")).toEqual([]);
    expect(screen.queryByRole("button", { name: /^Save / })).toBeNull();
    expect(container.textContent).not.toContain("including you");
  });

  it("sends no DELETE until the removal dialog is answered", async () => {
    const { calls } = await renderTeam();

    await screen.findByText("Priya");
    fireEvent.click(screen.getByRole("button", { name: "Remove Priya from this account" }));

    const dialog = await screen.findByRole("dialog");
    expect(calls.filter((c) => c.method === "DELETE")).toEqual([]);
    // Names the person — a confirmation that cannot say WHOSE access confirms intent and
    // not target — and states the lead consequence BEFORE the press rather than after.
    expect(dialog.textContent).toContain("Priya");
    expect(dialog.textContent).toContain("stay assigned to them");

    fireEvent.click(within(dialog).getByRole("button", { name: "Remove their access" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1));
  });

  it("keeps the colleague when the owner backs out", async () => {
    const { calls } = await renderTeam();

    await screen.findByText("Priya");
    fireEvent.click(screen.getByRole("button", { name: "Remove Priya from this account" }));
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Keep their access",
      }),
    );

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.filter((c) => c.method === "DELETE")).toEqual([]);
    expect(screen.getByRole("button", { name: "Remove Priya from this account" })).toBeTruthy();
  });
});
