import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantMembersPage from "@/app/admin/tenants/[tenantId]/members/page";
import type { TenantSummary } from "@/lib/api/admin";
import { removeMemberConfirmation, type TenantMember } from "@/lib/api/tenantMembers";
import type { Routes } from "./harness";

import { problem } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * WHO HOLDS A CLIENT ACCOUNT — the screen D-546's three did not include (D-602).
 *
 * Those three are all about the ACCOUNT: its business record, its state, its closure. This
 * one is about the PEOPLE, which is the half the console lost sight of the moment somebody
 * redeemed an invitation — it could cut a key and cancel one still sitting in an inbox, and
 * then knew nothing about a key that had been used.
 *
 * What is pinned here is the seam, plus the two decisions that are this screen's rather
 * than the server's:
 *
 * 1. **The role select sends the role the ROW was showing as `expected_role`.** The
 *    compare-and-swap has to guard the picture the operator actually read, not one
 *    re-derived from a cache at submit time.
 * 2. **The removal is deliberately asymmetric with it** — a typed word, the lead count
 *    said out loud BEFORE the decision, and the confirmation header. The role change sends
 *    no header at all, and a console that attached one to both would be teaching an
 *    operator to clear a prompt without reading it, on the one route where reading it
 *    matters.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000d1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const MEMBERS_PATH = `${TENANT_PATH}/members`;

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000d2",
  role: "operator",
  permissions: ["org:read", "admin:tenants"],
};

const SUMMARY: TenantSummary = {
  id: TENANT,
  name: "Sri Traders",
  slug: "sri-traders",
  status: "active",
  plan_tier: "prepaid",
  vertical_template: "clinic",
  live_agents: 1,
  calls_7d: 12,
  leads: 3,
  last_call_at: null,
  holds: [],
  capped: false,
};

const OWNER: TenantMember = {
  user_id: "0192f0aa-9999-7000-8000-000000000001",
  name: "Lakshmi Rao",
  email: "lakshmi@sri-traders.example",
  role: "owner",
  joined_at: "2026-06-02T05:30:00Z",
  email_verified: true,
  deactivated: false,
  leads_assigned: 0,
};

const STAFF: TenantMember = {
  user_id: "0192f0aa-9999-7000-8000-000000000002",
  name: "Anitha Kumar",
  email: "anitha@sri-traders.example",
  role: "staff",
  joined_at: "2026-07-14T05:30:00Z",
  email_verified: true,
  deactivated: false,
  leads_assigned: 9,
};

function renderMembers(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<TenantMembersPage params={routeParams({ tenantId: TENANT })} />, {
    [ADMIN_ME_PATH]: ME,
    [TENANT_PATH]: SUMMARY,
    [MEMBERS_PATH]: [OWNER, STAFF],
    ...routes,
  });
}

describe("who holds a client account", () => {
  it("renders who can sign in, what they hold and what they are carrying", async () => {
    const { container } = await renderMembers();

    await screen.findByText("Lakshmi Rao");
    // The address is shown in full and on purpose: the operator is about to act on this
    // person by name, and `name` is nullable and not unique.
    expect(container.textContent).toContain("anitha@sri-traders.example");
    // The number that decides a removal, on the row rather than only in the answer.
    expect(container.textContent).toContain("9 leads assigned");
    expect(container.textContent).toContain("no leads assigned");
  });

  it("refuses to report an empty team from a read that failed", async () => {
    const { container } = await renderMembers({
      [MEMBERS_PATH]: problem(503, { title: "Upstream unavailable", retryable: true }),
    });

    // "Nobody has signed in" printed over a 503 is how an operator concludes a client is
    // locked out when they are not — or issues a second owner invitation to an account
    // that already has one.
    await screen.findByRole("alert");
    expect(container.textContent).toContain("Upstream unavailable");
    expect(container.textContent).not.toContain("Nobody has signed in");
  });

  it("says when somebody is deactivated and when their address was never verified", async () => {
    const { container } = await renderMembers({
      [MEMBERS_PATH]: [OWNER, { ...STAFF, deactivated: true, email_verified: false }],
    });

    await screen.findByText("Anitha Kumar");
    // The client's own picker HIDES deactivated people; this must not, because their
    // membership still counts toward the last-owner rule and is still what has to go.
    expect(container.textContent).toContain("deactivated platform-wide");
    expect(container.textContent).toContain("never been verified");
  });

  it("sends the role the row was showing as the CAS guard, and no confirmation header", async () => {
    const { calls } = await renderMembers({
      [`PATCH ${MEMBERS_PATH}/${STAFF.user_id}`]: { ...STAFF, role: "owner" },
    });

    fireEvent.change(await screen.findByLabelText(`Role for ${STAFF.name}`), {
      target: { value: "owner" },
    });

    const path = `${MEMBERS_PATH}/${STAFF.user_id}`;
    await waitFor(() => {
      expect(calls.some((call) => call.method === "PATCH" && call.path === path)).toBe(true);
    });
    const patch = calls.find((call) => call.method === "PATCH" && call.path === path);
    expect(JSON.parse(patch?.body ?? "{}")).toEqual({
      role: "owner",
      // What the ROW rendered, not a value re-read at submit time: that is the whole
      // point of the compare-and-swap.
      expected_role: "staff",
    });
    // A reversible act takes no ceremony — see the API's own argument for why attaching
    // one here would cost the removal's confirmation its meaning.
    expect(patch?.headers["X-Confirm-Action"]).toBeUndefined();
  });

  it("arms a removal only after a typed REMOVE, and sends the person-bound confirmation", async () => {
    const { calls } = await renderMembers({
      [`DELETE ${MEMBERS_PATH}/${STAFF.user_id}`]: {
        user_id: STAFF.user_id,
        previous_role: "staff",
        leads_still_assigned: 9,
      },
    });

    fireEvent.click((await screen.findAllByRole("button", { name: /Remove access/ }))[1]!);

    // The cost is stated BEFORE the decision, not after it.
    expect(screen.getByText(/9 leads assigned to them stay assigned/)).toBeTruthy();
    expect(screen.getByText(/no undo on our side/)).toBeTruthy();

    const submit = screen.getByRole("button", {
      name: /Remove their access/,
    }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/Type REMOVE to confirm/), {
      target: { value: "REMOVE" },
    });
    await waitFor(() => {
      expect(
        (screen.getByRole("button", { name: /Remove their access/ }) as HTMLButtonElement)
          .disabled,
      ).toBe(false);
    });
    fireEvent.click(screen.getByRole("button", { name: /Remove their access/ }));

    const path = `${MEMBERS_PATH}/${STAFF.user_id}`;
    await waitFor(() => {
      expect(calls.some((call) => call.method === "DELETE" && call.path === path)).toBe(true);
    });
    const del = calls.find((call) => call.method === "DELETE" && call.path === path);
    // BOTH ids. A header captured while looking at the staff member must not be replayable
    // against the owner one row above.
    expect(del?.headers["X-Confirm-Action"]).toBe(removeMemberConfirmation(TENANT, STAFF.user_id));
    expect(del?.headers["X-Confirm-Action"]).not.toBe(
      removeMemberConfirmation(TENANT, OWNER.user_id),
    );

    // The work left behind is restated from the server's own count, inside the answer.
    await screen.findByText(/9 leads are still assigned to them/);
  });

  it("offers no removal control at all for the only owner, and says why", async () => {
    const { calls } = await renderMembers();

    fireEvent.click((await screen.findAllByRole("button", { name: /Remove access/ }))[0]!);

    // The server refuses this with `last_owner_protected`; the screen refuses first and
    // gives the remedy, so the operator is not told "no" by a red box after the fact.
    expect(screen.getByText(/only owner on the account/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Remove their access/ })).toBeNull();
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  });

  it("disables both controls for an operator who may not write, with the reason", async () => {
    const { container } = await renderMembers({
      [ADMIN_ME_PATH]: { ...ME, permissions: ["org:read"] },
    });

    const select = (await screen.findByLabelText(`Role for ${STAFF.name}`)) as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    expect(
      (screen.getAllByRole("button", { name: /Remove access/ })[0] as HTMLButtonElement).disabled,
    ).toBe(true);
    // The reason is named in the ACT rather than in the permission string — what an
    // operator needs is which authority they are missing and who has it, not the RBAC
    // token — and it is said on the screen rather than discovered as a 403 after a click.
    expect(container.textContent).toContain("change or remove somebody's access");
    expect(container.textContent).toContain("Ask a superadmin");
  });
});
