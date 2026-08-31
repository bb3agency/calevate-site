import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import LifecyclePage from "@/app/admin/tenants/[tenantId]/lifecycle/page";
import type { TenantSummary } from "@/lib/api/admin";
import type { TenantErasure } from "@/lib/api/erasure";
import { tenantStatusPath } from "@/lib/api/commercials";
import type { Routes } from "./harness";

import { problem, stillLoading } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * Account state — the control that stops a client dialling.
 *
 * `organizations.status` was read by the health board and written by nothing; there was
 * no suspend route in either realm. What the tests pin:
 *
 * 1. **A failed read is a refusal, never a state.** "Active" printed over a 503 is how
 *    an operator suspends the wrong client — the §52 rule at its most expensive.
 * 2. **Each move says what it does to the client before it is made**, including the two
 *    facts nobody can guess from a dropdown: outbound stops and inbound does not, and
 *    closing an account is not undoable here.
 * 3. **A stop must explain itself.** The API refuses a reasonless suspension; the screen
 *    refuses first so the operator is not told after typing.
 * 4. **A closed account offers no controls at all**, because the API answers 409.
 * 5. **An unchanged result is reported as unchanged**, not as a change that happened.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000d1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const STATUS_PATH = tenantStatusPath(TENANT);
const ERASURE_PATH = `${TENANT_PATH}/erasure`;
/** The submit control, which is also the erasure card's title — hence the role. */
const ERASE_BUTTON = { name: /Erase this client's data/ };

function tenant(status = "active"): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status,
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 12,
    leads: 3,
    last_call_at: null,
    holds: [],
    capped: false,
  };
}

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000d2",
  role: "operator",
  permissions: ["org:read", "admin:tenants"],
};

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<LifecyclePage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: ME,
    [ERASURE_PATH]: [],
    ...routes,
  });
}

/** A superadmin: `ops:manage` is what unlocks the erasure control (admin/routes.py). */
const SUPERADMIN: AdminMe = {
  ...ME,
  role: "superadmin",
  permissions: ["org:read", "admin:tenants", "ops:manage"],
};

/** The erasure panel only ever renders for a CLOSED account — the API 409s any other. */
function renderClosed(routes: Partial<Routes> = {}) {
  return render({ [TENANT_PATH]: tenant("churned"), [ADMIN_ME_PATH]: SUPERADMIN, ...routes });
}

describe("the account state screen", () => {
  it("refuses to render a state it could not read", async () => {
    const { container } = await render({
      [TENANT_PATH]: problem(503, { title: "Upstream unavailable", retryable: true }),
    });

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /Suspend/ })).toBeNull();
    });
    expect(container.textContent).not.toContain("Currently active");
  });

  it("says what suspending does — and what it deliberately does not touch", async () => {
    const { container } = await render();

    await screen.findByRole("button", { name: /Suspend/ });
    expect(container.textContent).toContain("Outbound dialling stops at the next dial");
    expect(container.textContent).toContain("Inbound answering is deliberately unaffected");
  });

  it("will not send a suspension with no reason", async () => {
    const { calls } = await render({
      [`POST ${STATUS_PATH}`]: { tenant_id: TENANT, status: "suspended", changed: true },
    });

    const button = (await screen.findByRole("button", { name: /Suspend/ })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(calls.some((call) => call.path === STATUS_PATH)).toBe(false);

    fireEvent.change(screen.getByLabelText("Why"), { target: { value: "non-payment, 60 days" } });
    await waitFor(() => {
      expect(
        (screen.getByRole("button", { name: /Suspend/ }) as HTMLButtonElement).disabled,
      ).toBe(false);
    });
    fireEvent.click(screen.getByRole("button", { name: /Suspend/ }));
    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path === STATUS_PATH)).toBe(true);
    });
    const post = calls.find((call) => call.method === "POST" && call.path === STATUS_PATH);
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      status: "suspended",
      reason: "non-payment, 60 days",
    });
    // `admin:tenants` is a MUTATING permission — D-22 refuses it to an acting-as session.
    expect(post?.headers["X-Impersonate-Org"]).toBeUndefined();
  });

  it("asks for no reason to reactivate — the state it moves to is the harmless one", async () => {
    const { calls } = await render({
      [TENANT_PATH]: tenant("suspended"),
      [`POST ${STATUS_PATH}`]: { tenant_id: TENANT, status: "active", changed: true },
    });

    const button = (await screen.findByRole("button", {
      name: /Reactivate/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path === STATUS_PATH)).toBe(true);
    });
    expect(
      JSON.parse(calls.find((call) => call.method === "POST")?.body ?? "{}").status,
    ).toBe("active");
  });

  it("offers no control at all on a closed account", async () => {
    const { container } = await render({ [TENANT_PATH]: tenant("churned") });

    await screen.findByText("This account is closed");
    expect(screen.queryByRole("button", { name: /Reactivate/ })).toBeNull();
    expect(container.textContent).toContain("cannot be reopened here");
  });

  it("reports an already-in-state result as unchanged", async () => {
    const { container } = await render({
      [`POST ${STATUS_PATH}`]: { tenant_id: TENANT, status: "suspended", changed: false },
    });

    fireEvent.change(await screen.findByLabelText("Why"), { target: { value: "chargeback" } });
    fireEvent.click(screen.getByRole("button", { name: /Suspend/ }));

    await waitFor(() => {
      expect(container.textContent).toContain("was already suspended");
    });
    expect(container.textContent).toContain("no audit row was written");
  });

  it("arms Close the account only after a reason AND a typed CLOSE — and styles it as danger", async () => {
    const { calls } = await render({
      [`POST ${STATUS_PATH}`]: { tenant_id: TENANT, status: "churned", changed: true },
    });

    // Switch the move to the irreversible one.
    fireEvent.change(await screen.findByLabelText("New state"), {
      target: { value: "churned" },
    });

    const button = (await screen.findByRole("button", {
      name: /Close the account/,
    })) as HTMLButtonElement;
    // LIFECYCLE_COPY.tone === "stop" must reach the pixels: rose, never the brand green
    // that Reactivate wears. A refactor back to ActionButton goes red here.
    expect(button.className).toContain("bg-rose-600");
    expect(button.disabled).toBe(true);

    // A reason alone is not enough for the one move this screen cannot undo.
    fireEvent.change(screen.getByLabelText("Why"), { target: { value: "contract ended" } });
    expect(
      (screen.getByRole("button", { name: /Close the account/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText(/Type CLOSE above to confirm/)).toBeDefined();

    // A near-miss does not arm it.
    const confirm = screen.getByLabelText(/to confirm/);
    fireEvent.change(confirm, { target: { value: "close" } });
    expect(
      (screen.getByRole("button", { name: /Close the account/ }) as HTMLButtonElement).disabled,
    ).toBe(true);

    fireEvent.change(confirm, { target: { value: "CLOSE" } });
    await waitFor(() => {
      expect(
        (screen.getByRole("button", { name: /Close the account/ }) as HTMLButtonElement).disabled,
      ).toBe(false);
    });
    fireEvent.click(screen.getByRole("button", { name: /Close the account/ }));
    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path === STATUS_PATH)).toBe(true);
    });
    expect(
      JSON.parse(calls.find((call) => call.method === "POST")?.body ?? "{}").status,
    ).toBe("churned");
  });

  it("keeps Suspend one click — the reversible move takes no typed word", async () => {
    await render();
    await screen.findByRole("button", { name: /Suspend/ });
    expect(screen.queryByLabelText(/to confirm/)).toBeNull();
  });

  it("disables the control, with its reason, for a session that may not use it", async () => {
    await render({ [ADMIN_ME_PATH]: { ...ME, permissions: ["org:read"] } });

    const button = (await screen.findByRole("button", { name: /Suspend/ })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/change an account's state/)).toBeDefined();
  });
});

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
    const { container } = await renderClosed({ [ERASURE_PATH]: stillLoading() });

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
      [ERASURE_PATH]: problem(503, { title: "Upstream unavailable", retryable: true }),
    });

    // A refusal the operator can act on, naming WHY the form is closed — not a blank
    // card, and inside the erasure panel rather than anywhere on the page. Awaited on
    // the ALERT, not on the card title: the title is on screen during the loading branch
    // too, so scoping off it would look at the skeleton and find no alert.
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Upstream unavailable");
    expect(alert.closest("section")?.querySelector("h2")?.textContent).toBe("Data erasure");
    expect(container.textContent).toContain(
      "we cannot tell you whether this client's data has already",
    );
    expect(container.textContent).toContain("Filing a second one would start a destructive job");
    expect(screen.queryByRole("button", ERASE_BUTTON)).toBeNull();
  });

  it("still offers the form when the read says no erasure has been filed", async () => {
    // The premise of the two above: if the panel never offered the form, they would pass
    // for the wrong reason and this file would be testing nothing at all.
    await renderClosed();

    const button = (await screen.findByRole("button", ERASE_BUTTON)) as HTMLButtonElement;
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

    await screen.findByText(/An erasure has been filed for this client and is running/);
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
