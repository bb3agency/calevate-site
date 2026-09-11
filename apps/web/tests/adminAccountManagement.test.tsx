import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import ClosurePage from "@/app/admin/tenants/[tenantId]/closure/page";
import TenantProfilePage from "@/app/admin/tenants/[tenantId]/profile/page";
import TenantInvitationsPage from "@/app/admin/tenants/[tenantId]/invitations/page";
import type { TenantSummary } from "@/lib/api/admin";
import type { Closure } from "@/lib/api/closure";
import type { TenantProfile } from "@/lib/api/tenantProfile";
import { closureConfirmation } from "@/lib/api/closure";
import { noticeAddressConfirmation } from "@/lib/api/tenantProfile";
import type { Routes } from "./harness";

import { problem } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * CLIENT ACCOUNT MANAGEMENT — the three screens D-546 wired to APIs that already existed.
 *
 * Every route these screens call shipped with D-538 and had NO CALLER in this console: the
 * founder opened a client and found no way to correct a name, no way to re-send an invite,
 * and no way to close an account except a dropdown that told the client nothing. So what
 * these tests pin is mostly the SEAM — that the screen sends what the API demands, and
 * refuses what it would refuse — plus the two decisions that are ours rather than the
 * server's:
 *
 * 1. **The address change carries its confirmation and the other fields do not.** A header
 *    on every save is a confirmation of nothing.
 * 2. **The retarget is SAID.** Notices already queued resolve their recipient at delivery,
 *    so they follow the address. That is kept — the alternative mails a closure notice to
 *    the dead mailbox an operator just replaced — and it must never be silent.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000d1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const CLOSURE_PATH = `${TENANT_PATH}/closure`;
const PROFILE_PATH = `${TENANT_PATH}/profile`;
const INVITES_PATH = `${TENANT_PATH}/invitations`;

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

const OPEN: Closure = {
  tenant_id: TENANT,
  status: "active",
  closed_at: null,
  erase_after: null,
  reason: null,
  closed_by: null,
  erased_at: null,
  restorable: false,
  days_remaining: null,
};

const CLOSED: Closure = {
  tenant_id: TENANT,
  status: "churned",
  closed_at: "2026-08-20T05:30:00Z",
  erase_after: "2026-09-19T05:30:00Z",
  reason: "Not renewing after the pilot.",
  closed_by: ME.user_id,
  erased_at: null,
  restorable: true,
  days_remaining: 13,
};

const PROFILE: TenantProfile = {
  tenant_id: TENANT,
  name: "Sri Traders",
  slug: "sri-traders",
  status: "active",
  billing_email: "accounts@sri.example",
  vertical_template: "clinic",
  verticals: ["clinic", "real_estate", "insurance", "education", "custom"],
};

function renderClosure(routes: Partial<Routes> = {}) {
  return renderAdminRoute(
    <ClosurePage params={routeParams({ tenantId: TENANT })} />,
    {
      [ADMIN_ME_PATH]: ME,
      [TENANT_PATH]: SUMMARY,
      [CLOSURE_PATH]: OPEN,
      ...routes,
    },
  );
}

function renderProfile(routes: Partial<Routes> = {}) {
  return renderAdminRoute(
    <TenantProfilePage params={routeParams({ tenantId: TENANT })} />,
    {
      [ADMIN_ME_PATH]: ME,
      [PROFILE_PATH]: PROFILE,
      ...routes,
    },
  );
}

function renderInvitations(routes: Partial<Routes> = {}) {
  return renderAdminRoute(
    <TenantInvitationsPage params={routeParams({ tenantId: TENANT })} />,
    {
      [ADMIN_ME_PATH]: ME,
      [TENANT_PATH]: SUMMARY,
      [INVITES_PATH]: [],
      ...routes,
    },
  );
}

describe("closing a client account", () => {
  it("refuses to render a closure state it could not read", async () => {
    const { container } = await renderClosure({
      [CLOSURE_PATH]: problem(503, {
        title: "Upstream unavailable",
        retryable: true,
      }),
    });

    // "Not closed" printed over a 503, next to a Close button, is how an account gets
    // closed twice — or how an operator concludes a closure they filed never took.
    await screen.findByRole("alert");
    expect(
      screen.queryByRole("button", { name: /Close this account/ }),
    ).toBeNull();
    expect(container.textContent).toContain("Upstream unavailable");
  });

  it("arms the close only after a reason AND a typed CLOSE, and sends the confirmation", async () => {
    const { calls } = await renderClosure({ [`POST ${CLOSURE_PATH}`]: CLOSED });

    const button = (await screen.findByRole("button", {
      name: /Close this account/,
    })) as HTMLButtonElement;
    // The most destructive control on the screen is rose, never brand green.
    expect(button.className).toContain("bg-rose-600");
    expect(button.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/Why this account is closing/), {
      target: { value: "Not renewing after the pilot." },
    });
    expect(
      (
        screen.getByRole("button", {
          name: /Close this account/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);

    fireEvent.change(screen.getByLabelText(/Type CLOSE to confirm/), {
      target: { value: "CLOSE" },
    });
    await waitFor(() => {
      expect(
        (
          screen.getByRole("button", {
            name: /Close this account/,
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false);
    });
    fireEvent.click(screen.getByRole("button", { name: /Close this account/ }));

    await waitFor(() => {
      expect(
        calls.some(
          (call) => call.method === "POST" && call.path === CLOSURE_PATH,
        ),
      ).toBe(true);
    });
    const post = calls.find(
      (call) => call.method === "POST" && call.path === CLOSURE_PATH,
    );
    // The step-up string is the CLOSURE one, never the status route's old `close_account:`
    // — a confirmation captured for ending a relationship must not authorise an erasure.
    expect(post?.headers["X-Confirm-Action"]).toBe(closureConfirmation(TENANT));
    // No `grace_days`: the server's own GRACE_DAYS stays the single place the window is
    // decided, and a console that always sent a number would be a second one.
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      reason: "Not renewing after the pilot.",
    });
  });

  it("shows a closed account what happens next and by when, off the server's clock", async () => {
    const { container } = await renderClosure({ [CLOSURE_PATH]: CLOSED });

    await screen.findByText(/Records are erased on/);
    // The countdown is the SERVER's `days_remaining`, not a number derived here: a
    // countdown to destruction computed on the viewer's laptop disagrees with the sweep.
    expect(container.textContent).toContain("13 days");
    expect(container.textContent).toContain("Not renewing after the pilot.");
    // The disclosure the client's own notice makes, made here too.
    expect(container.textContent).toContain("still pointed at the agent");
    expect(
      screen.queryByRole("button", { name: /Close this account/ }),
    ).toBeNull();
  });

  it("reopens in one click, with no typed word and no confirmation header", async () => {
    const { calls } = await renderClosure({
      [CLOSURE_PATH]: CLOSED,
      [`DELETE ${CLOSURE_PATH}`]: OPEN,
    });

    fireEvent.click(
      await screen.findByRole("button", { name: /Reopen the account/ }),
    );
    await waitFor(() => {
      expect(
        calls.some(
          (call) => call.method === "DELETE" && call.path === CLOSURE_PATH,
        ),
      ).toBe(true);
    });
    // The asymmetry is the point: a second factor on the recovery path means the operator
    // who closed the wrong client at a coffee shop cannot fix it from the same coffee shop.
    expect(
      calls.find((call) => call.method === "DELETE")?.headers[
        "X-Confirm-Action"
      ],
    ).toBeUndefined();
  });

  it("offers no undo once the erasure has run", async () => {
    const { container } = await renderClosure({
      [CLOSURE_PATH]: {
        ...CLOSED,
        erased_at: "2026-09-19T06:00:00Z",
        restorable: false,
      },
    });

    await screen.findByText(/records have been erased/);
    expect(
      screen.queryByRole("button", { name: /Reopen the account/ }),
    ).toBeNull();
    expect(container.textContent).toContain("cannot be undone");
  });
});

describe("correcting a client's business record", () => {
  it("refuses to pre-fill a form from a read that failed", async () => {
    // A form filled from a failed read saves a guess over a real value.
    await renderProfile({
      [PROFILE_PATH]: problem(503, {
        title: "Upstream unavailable",
        retryable: true,
      }),
    });

    await screen.findByRole("alert");
    expect(screen.queryByRole("button", { name: /Save changes/ })).toBeNull();
  });

  it("shows the slug and will not let anybody change it", async () => {
    const { container } = await renderProfile();

    await screen.findByLabelText("Business name");
    expect(container.textContent).toContain("/c/sri-traders");
    // Not an input at all — a frozen field rendered as one is a field somebody types into.
    expect(screen.queryByLabelText(/Web address/)).toBeNull();
    expect(container.textContent).toContain("bookmarked");
  });

  it("sends only the fields that moved, and no confirmation for a name change", async () => {
    const { calls } = await renderProfile({
      [`PATCH ${TENANT_PATH}`]: {
        tenant_id: TENANT,
        changed: ["name"],
        pending_notices_retargeted: 0,
      },
    });

    fireEvent.change(await screen.findByLabelText("Business name"), {
      target: { value: "Sri Traders & Co" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "PATCH")).toBe(true);
    });
    const patch = calls.find((call) => call.method === "PATCH");
    expect(JSON.parse(patch?.body ?? "{}")).toEqual({
      name: "Sri Traders & Co",
    });
    // A header on a change that redirects nothing is a confirmation of nothing.
    expect(patch?.headers["X-Confirm-Action"]).toBeUndefined();
  });

  it("will not save until an address change is typed out, then sends its confirmation", async () => {
    const { calls } = await renderProfile({
      [`PATCH ${TENANT_PATH}`]: {
        tenant_id: TENANT,
        changed: ["billing_email"],
        pending_notices_retargeted: 2,
      },
    });

    fireEvent.change(
      await screen.findByLabelText(/Where this account's notices go/),
      {
        target: { value: "billing@sri.example" },
      },
    );
    const save = screen.getByRole("button", {
      name: /Save changes/,
    }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/Type CHANGE ADDRESS to confirm/), {
      target: { value: "CHANGE ADDRESS" },
    });
    await waitFor(() => {
      expect(
        (
          screen.getByRole("button", {
            name: /Save changes/,
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false);
    });
    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "PATCH")).toBe(true);
    });
    const patch = calls.find((call) => call.method === "PATCH");
    expect(patch?.headers["X-Confirm-Action"]).toBe(
      noticeAddressConfirmation(TENANT),
    );
    expect(JSON.parse(patch?.body ?? "{}")).toEqual({
      billing_email: "billing@sri.example",
    });
  });

  it("says how many queued notices follow the address, rather than letting it happen quietly", async () => {
    const { container } = await renderProfile({
      [`PATCH ${TENANT_PATH}`]: {
        tenant_id: TENANT,
        changed: ["billing_email"],
        pending_notices_retargeted: 2,
      },
    });

    fireEvent.change(
      await screen.findByLabelText(/Where this account's notices go/),
      {
        target: { value: "billing@sri.example" },
      },
    );
    fireEvent.change(screen.getByLabelText(/Type CHANGE ADDRESS to confirm/), {
      target: { value: "CHANGE ADDRESS" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));

    await waitFor(() => {
      expect(container.textContent).toContain("2 notices were already queued");
    });
    expect(container.textContent).toContain("delivered to the new address");
    // The other half of OWASP's control, reported where the operator can read it back.
    expect(container.textContent).toContain("previous address has been told");
  });

  it("refuses to clear the address, which would leave the account with no channel", async () => {
    const { container, calls } = await renderProfile();

    fireEvent.change(
      await screen.findByLabelText(/Where this account's notices go/),
      {
        target: { value: "" },
      },
    );
    expect(
      (
        screen.getByRole("button", {
          name: /Save changes/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(container.textContent).toContain("nowhere to send its notices");
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);
  });

  it("offers exactly the verticals the server said it would accept", async () => {
    await renderProfile();

    const select = (await screen.findByLabelText(
      "Vertical",
    )) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.value)).toEqual(
      PROFILE.verticals,
    );
  });
});

describe("a client's invitations", () => {
  it("never claims nobody holds a key when the read failed", async () => {
    // An operator who believes "no invitation is outstanding" issues a second link to an
    // address that already holds one — which the API then refuses.
    const { container } = await renderInvitations({
      [INVITES_PATH]: problem(503, {
        title: "Upstream unavailable",
        retryable: true,
      }),
    });

    await screen.findByRole("alert");
    expect(container.textContent).not.toContain("Nobody is holding a key");
  });

  it("shows when the link last went and how many have gone", async () => {
    const { container } = await renderInvitations({
      [INVITES_PATH]: [
        {
          id: "0192f0aa-8888-7000-8000-000000000002",
          email: "reception@sri.example",
          role: "staff",
          invited_at: "2026-09-01T05:30:00Z",
          expires_at: "2026-09-07T05:30:00Z",
          last_sent_at: "2026-09-04T09:15:00Z",
          send_count: 4,
        },
      ],
    });

    await screen.findByText("reception@sri.example");
    // `invited_at` is the MINT and `last_sent_at` is the SEND; after a resend they differ,
    // and reading the wrong one tells an operator to wait when they need not.
    expect(container.textContent).toContain("sent 4 times");
    expect(container.textContent).toContain("Link last sent");
  });

  it("re-sends with an empty body — the same invitation, re-cut", async () => {
    const invite = {
      id: "0192f0aa-8888-7000-8000-000000000001",
      email: "owner@sri.example",
      role: "owner",
      invited_at: "2026-09-05T05:30:00Z",
      expires_at: "2026-09-08T05:30:00Z",
      last_sent_at: "2026-09-05T05:30:00Z",
      send_count: 1,
    };
    const resendPath = `${INVITES_PATH}/${invite.id}/resend`;
    const { calls } = await renderInvitations({
      [INVITES_PATH]: [invite],
      [`POST ${resendPath}`]: {
        id: invite.id,
        email: invite.email,
        delivery: "queued",
        expires_at: "2026-09-09T05:30:00Z",
        last_sent_at: "2026-09-06T05:30:00Z",
        send_count: 2,
      },
    });

    fireEvent.click(
      await screen.findByRole("button", { name: /Send the link again/ }),
    );
    await waitFor(() => {
      expect(
        calls.some(
          (call) => call.method === "POST" && call.path === resendPath,
        ),
      ).toBe(true);
    });
    // No address, so the server sends to the one on file. NOT a revoke-then-invite: the
    // token rotates on the same row, so two live keys for one address cannot exist.
    expect(
      JSON.parse(calls.find((call) => call.path === resendPath)?.body ?? "{}"),
    ).toEqual({});
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  });

  it("will not re-address an invitation without a note saying how the address was established", async () => {
    const invite = {
      id: "0192f0aa-8888-7000-8000-000000000001",
      email: "typo@sri.example",
      role: "owner",
      invited_at: "2026-09-05T05:30:00Z",
      expires_at: "2026-09-08T05:30:00Z",
      last_sent_at: "2026-09-05T05:30:00Z",
      send_count: 1,
    };
    const resendPath = `${INVITES_PATH}/${invite.id}/resend`;
    const { calls } = await renderInvitations({
      [INVITES_PATH]: [invite],
      [`POST ${resendPath}`]: {
        id: invite.id,
        email: "owner@sri.example",
        delivery: "queued",
        expires_at: "2026-09-09T05:30:00Z",
        last_sent_at: "2026-09-06T05:30:00Z",
        send_count: 2,
      },
    });

    fireEvent.click(
      await screen.findByRole("button", { name: /Wrong address/ }),
    );
    fireEvent.change(screen.getByLabelText("Send it to"), {
      target: { value: "owner@sri.example" },
    });
    const send = screen.getByRole("button", {
      name: /Send to the corrected address/,
    }) as HTMLButtonElement;
    // An attestation with no stated ground is a claim rather than a record — and the API
    // refuses it with a 422, so the screen refuses first.
    expect(send.disabled).toBe(true);
    expect(calls.some((call) => call.path === resendPath)).toBe(false);

    fireEvent.change(screen.getByLabelText("How you established it"), {
      target: { value: "confirmed on a call with the owner" },
    });
    await waitFor(() => {
      expect(
        (
          screen.getByRole("button", {
            name: /Send to the corrected address/,
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false);
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Send to the corrected address/ }),
    );
    await waitFor(() => {
      expect(calls.some((call) => call.path === resendPath)).toBe(true);
    });
    expect(
      JSON.parse(calls.find((call) => call.path === resendPath)?.body ?? "{}"),
    ).toEqual({
      email: "owner@sri.example",
      attestation: "confirmed on a call with the owner",
    });
  });

  it("never puts a token on the screen", async () => {
    const invite = {
      id: "0192f0aa-8888-7000-8000-000000000001",
      email: "owner@sri.example",
      role: "owner",
      invited_at: "2026-09-05T05:30:00Z",
      expires_at: "2026-09-08T05:30:00Z",
      last_sent_at: "2026-09-05T05:30:00Z",
      send_count: 1,
    };
    const { container } = await renderInvitations({ [INVITES_PATH]: [invite] });

    await screen.findByText("owner@sri.example");
    // D-198: the link is mailed by the server and never handed back, so there is nothing
    // here to be shouted into a screenshot. Asserted on the WORD as well as the shape,
    // because a future `InviteOut` growing a token field would pass a shape-only check.
    expect(container.textContent).not.toMatch(/token/i);
    expect(container.textContent).not.toMatch(/accept-invitation\?/);
  });
});
