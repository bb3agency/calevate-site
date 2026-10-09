import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import ClosurePage from "@/app/admin/tenants/[tenantId]/closure/page";
import TenantProfilePage from "@/app/admin/tenants/[tenantId]/profile/page";
// Invitations are part of the People page since D-661; `/invitations` only redirects there.
import TenantMembersPage from "@/app/admin/tenants/[tenantId]/members/page";
import type { TenantSummary } from "@/lib/api/admin";
import type { Closure } from "@/lib/api/closure";
import type { TenantErasure } from "@/lib/api/erasure";
import type { TenantProfile } from "@/lib/api/tenantProfile";
import { closureConfirmation } from "@/lib/api/closure";
import { noticeAddressConfirmation } from "@/lib/api/tenantProfile";
import type { Routes } from "./harness";
import { adminBusinessProfileFixture, OWNER_JOINED } from "./businessProfileFixture";

import { problem, stillLoading } from "./harness";
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
const ERASURE_PATH = `${TENANT_PATH}/erasure`;
/** The erasure submit control, which is also the erasure card's title — hence the role. */
const ERASE_BUTTON = { name: /Erase this client's data/ };

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
  forfeited_credit_inr: "0.00",
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
  forfeited_credit_inr: "0.00",
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
      [`${TENANT_PATH}/business-profile`]: adminBusinessProfileFixture(),
      [`${TENANT_PATH}/owner-status`]: OWNER_JOINED,
      [CLOSURE_PATH]: OPEN,
      // A closed account's screen also carries the erasure panel, which reads this.
      [ERASURE_PATH]: [],
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
      [`${TENANT_PATH}/business-profile`]: adminBusinessProfileFixture(),
      ...routes,
    },
  );
}

function renderInvitations(routes: Partial<Routes> = {}) {
  return renderAdminRoute(
    <TenantMembersPage params={routeParams({ tenantId: TENANT })} />,
    {
      [ADMIN_ME_PATH]: ME,
      [TENANT_PATH]: SUMMARY,
      [`${TENANT_PATH}/business-profile`]: adminBusinessProfileFixture(),
      [`${TENANT_PATH}/owner-status`]: OWNER_JOINED,
      [INVITES_PATH]: [],
      [`${TENANT_PATH}/members`]: [],
      [`${TENANT_PATH}/whatsapp-alerts`]: stillLoading(),
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
    expect(container.textContent).toContain("numbers were disconnected from the agents");
    expect(container.textContent).toContain("The numbers are not released");
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

/** A superadmin: `ops:manage` is what unlocks the erasure control (admin/routes.py). */
const SUPERADMIN: AdminMe = {
  ...ME,
  role: "superadmin",
  permissions: ["org:read", "admin:tenants", "ops:manage"],
};

/**
 * The erasure panel lives on the Closing screen beside the clock it ends (it moved from
 * Account state), and renders only for a CLOSED account — the API 409s any other.
 */
function renderClosed(routes: Partial<Routes> = {}) {
  return renderClosure({
    [ADMIN_ME_PATH]: SUPERADMIN,
    [CLOSURE_PATH]: CLOSED,
    ...routes,
  });
}

/**
 * The erasure panel, and the §52 defect that lived in it — the most expensive one this
 * console has held.
 *
 * `useTenantErasures`'s `isLoading` and `error` were read NOWHERE, and `filed.data?.[0]`
 * is undefined in both of those states. The undefined fell straight through to the
 * "Erase this client's data" FORM. So while the read was in flight, and forever after it
 * 503d, the screen told an operator that no erasure had been filed and offered to start
 * an irreversible, tenant-wide DPDP erasure — one that may already have been running.
 *
 * Both tests assert the REPLACEMENT is on screen, not merely that the form is gone. A
 * panel that rendered nothing at all would satisfy "no erase button" and would be its own
 * §52 violation; that is the trap this suite has walked into before.
 */
describe("the erasure panel", () => {
  it("shows a skeleton, and no erasure form, while the filed-erasures read is in flight", async () => {
    const { container } = await renderClosed({
      [ERASURE_PATH]: stillLoading(),
    });

    // The card is there and it is visibly waiting — `Skeleton` is the only thing in this
    // app that animates, and it is `aria-hidden`, so the class is how a test sees it.
    // Scoped to the card, so a skeleton belonging to some other query cannot stand in.
    const card = (await screen.findByText("Data erasure")).closest("section");
    expect(card, "the erasure panel is not a Card any more").not.toBeNull();
    expect(
      card!.querySelectorAll(".animate-pulse").length,
      "no skeleton in the erasure panel while the read is in flight",
    ).toBeGreaterThan(0);
    expect(screen.queryByRole("button", ERASE_BUTTON)).toBeNull();
    expect(container.textContent).not.toContain("Type the confirmation");
  });

  it("refuses, rather than offering an erasure it could not rule out", async () => {
    const { container } = await renderClosed({
      [ERASURE_PATH]: problem(503, {
        title: "Upstream unavailable",
        retryable: true,
      }),
    });

    // A refusal the operator can act on, naming WHY the form is closed — not a blank
    // card, and inside the erasure panel rather than anywhere on the page. Awaited on
    // the ALERT, not on the card title: the title is on screen during the loading branch
    // too, so scoping off it would look at the skeleton and find no alert.
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Upstream unavailable");
    expect(alert.closest("section")?.querySelector("h2")?.textContent).toBe(
      "Data erasure",
    );
    expect(container.textContent).toContain(
      "we cannot tell you whether this client's data has already",
    );
    expect(container.textContent).toContain(
      "Filing a second one would start a destructive job",
    );
    expect(screen.queryByRole("button", ERASE_BUTTON)).toBeNull();
  });

  it("still offers the form when the read says no erasure has been filed", async () => {
    // The premise of the two above: if the panel never offered the form, they would pass
    // for the wrong reason and this file would be testing nothing at all.
    await renderClosed();

    const button = (await screen.findByRole(
      "button",
      ERASE_BUTTON,
    )) as HTMLButtonElement;
    expect(button.disabled).toBe(true); // no reason typed yet
    // The most irreversible submit in the product is rose, never brand green (F-2).
    expect(button.className).toContain("bg-rose-600");
    expect(screen.getByText("Type the confirmation")).toBeDefined();
  });

  it("reports an erasure that has already been filed, and offers no second one", async () => {
    await renderClosed({
      // `satisfies TenantErasure`, which this fixture did not carry and needed: it
      // named the key `id` (the server sends `request_id`) and claimed a status of
      // "running", which `TenantErasureOut`'s enum is `pending | completed` and no
      // server can answer with. Neither showed, because the screen's ladder tests for
      // "completed" and treats everything else as in-flight — a fixture lying in the
      // direction the screen ignores, which is `wireFixtureGuard.test.ts`'s subject.
      [ERASURE_PATH]: [
        {
          request_id: "0192f0aa-7777-7000-8000-0000000000e1",
          tenant_id: TENANT,
          status: "pending",
          reason: "client asked, ticket 4471",
          requested_at: "2026-08-14T10:00:00Z",
          completed_at: null,
          proof: null,
          limitations: [],
        } satisfies TenantErasure,
      ],
    });

    await screen.findByText(
      /An erasure has been filed for this client and is running/,
    );
    expect(screen.queryByRole("button", ERASE_BUTTON)).toBeNull();
  });

  /**
   * THE CERTIFICATE'S DATES ARE IST, IN WHATEVER TIMEZONE THE OPERATOR'S LAPTOP IS ON.
   *
   * Both lines interpolated a bare `new Date(...).toLocaleString()` /
   * `.toLocaleDateString()` — no locale and no `timeZone` — so this panel took the
   * BROWSER's zone and the browser's locale while every other instant in both consoles
   * goes through `formatIST` (CLAUDE.md: stored UTC, shown IST at the edge). On a laptop
   * still set to a US timezone the DPDP erasure certificate — the record that answers
   * "when was this destroyed" — read "8/19/2026, 4:00:00 PM" and named the PREVIOUS day.
   *
   * The fixture picks two instants that fall on a different calendar day either side of
   * the boundary, and the timezone is moved for real rather than mocked, so this test
   * is about the code and not about the machine it runs on.
   */
  it("dates the erasure certificate in IST from a browser outside India", async () => {
    const original = process.env.TZ;
    process.env.TZ = "America/New_York";
    try {
      const { container } = await renderClosed({
        [ERASURE_PATH]: [ERASED],
      });

      await screen.findByText(/This client's data was erased on/);
      // 19 Aug 20:00Z is 20 Aug 01:30 IST — and 19 Aug 16:00 in New York.
      expect(container.textContent).toContain("erased on 20 Aug, 01:30 am");
      // 15 Nov 18:45Z is 16 Nov 00:15 IST — a retention deadline off by a day is a
      // recording kept, or destroyed, on the wrong side of the TRAI floor.
      expect(container.textContent).toContain("destroyed by 16 Nov, 12:15 am");
      // What the browser's own formatting would have produced.
      expect(container.textContent).not.toContain("8/19/2026");
      expect(container.textContent).not.toContain("11/15/2026");
    } finally {
      if (original === undefined) delete process.env.TZ;
      else process.env.TZ = original;
    }
  });
});

/**
 * A COMPLETED erasure with its certificate — `satisfies TenantErasure` so the compiler
 * checks it against the generated wire type. The route map takes `unknown`, which is
 * exactly the hole `tests/wireFixtureGuard.test.ts` documents: a fixture nothing checks
 * drifts from the server silently.
 */
const ERASED = {
  request_id: "0192f0aa-7777-7000-8000-0000000000e2",
  tenant_id: TENANT,
  status: "completed",
  reason: "client asked, ticket 4471",
  requested_at: "2026-08-19T19:00:00Z",
  completed_at: "2026-08-19T20:00:00Z",
  proof: {
    tenant_id: TENANT,
    executed_at: "2026-08-19T20:00:00Z",
    scope: {
      calls_erased: 128,
      transcript_turns_erased: 2140,
      call_extractions_erased: 128,
      leads_erased: 44,
      campaign_contacts_erased: 44,
      recordings_destroyed: 96,
      recordings_within_trai_floor: 32,
      webhook_bodies_erased: 12,
      // Present-and-numeric is the shape a proof written today carries. `null` is a
      // different state the server also sends — a proof from before `caller_chunks`
      // existed, which could not look — and `_caller_sentences` says the two in two
      // different sentences rather than rendering a `0` for both.
      caller_vectors_erased: 812,
      caller_memories_erased: 19,
      // The managed-retrieval box's own count, on the same footing as the two above: a
      // number is a proof that looked, `null` is a proof from before that store existed.
      indexed_documents_purged: 37,
    },
    recording_hold_until: "2026-11-15T18:45:00Z",
    actions: { calls: "stripped", leads: "anonymised" },
    engine_deletion: "requested, unconfirmed",
    not_erased: [],
    limitations: [],
    limitations_version: "1",
  },
  limitations: [],
} satisfies TenantErasure;

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
  it("shows a new invitation in the list the moment it is sent", async () => {
    // The success notice says the link "appears in the list above", so the list has to be
    // read again after the POST rather than left on the answer from before it.
    const minted = {
      id: "0192f0aa-8888-7000-8000-000000000003",
      email: "n***@sri.example",
      role: "staff",
      invited_at: "2026-09-06T05:30:00Z",
      expires_at: "2026-09-09T05:30:00Z",
      last_sent_at: "2026-09-06T05:30:00Z",
      send_count: 1,
    };
    let sent = false;
    await renderInvitations({
      [INVITES_PATH]: () => (sent ? [minted] : []),
      [`POST ${INVITES_PATH}`]: () => {
        sent = true;
        return { id: minted.id, delivery: "queued", expires_in_hours: 72 };
      },
    });

    // The form opens in a drawer from the page's one action (D-661).
    fireEvent.click(await screen.findByRole("button", { name: "Invite somebody" }));
    const address = await screen.findByLabelText("Their email address");
    await waitFor(() => expect((address as HTMLInputElement).disabled).toBe(false));
    fireEvent.change(address, { target: { value: "new.person@sri.example" } });
    fireEvent.click(screen.getByRole("button", { name: /Send the invitation/ }));

    expect(await screen.findByText("n***@sri.example")).toBeTruthy();
  });

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

    // "Wrong address?" is a row-menu item since D-661: one visible action per row
    // ("Send the link again"), the rest behind "More actions".
    fireEvent.click(
      await screen.findByRole("button", { name: /More actions for typo@sri\.example/ }),
    );
    fireEvent.click(await screen.findByRole("menuitem", { name: /Wrong address/ }));
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
