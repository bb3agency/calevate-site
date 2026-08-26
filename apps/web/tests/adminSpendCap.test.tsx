import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantDetailPage from "@/app/admin/tenants/[tenantId]/page";
import { spendCapConfirmation, type Margin, type TenantSummary } from "@/lib/api/admin";
import type { Caps } from "@/lib/api/caps";

import { problem, type Routes } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * The spend-cap panel on a client's own screen — the console path for
 * `POST /v1/ops/tenants/{id}/spend-cap/recompute`.
 *
 * Until this landed, `runbooks/calls-stopped.md` §2 told an operator to hand-write a curl
 * with a step-up header carrying a tenant uuid, mid-incident, to release a client whose
 * calls had stopped. Everything below is a failure that curl could produce and this panel
 * must not, ranked worst first:
 *
 * 1. **Reporting a client released when nothing was read.** The button's whole subject is
 *    a boolean; offered over an unreadable one, "recomputed" is a sentence an operator
 *    repeats to a client on the phone.
 * 2. **The wrong client.** The route binds its confirmation to the tenant id precisely so
 *    a header captured for one account cannot be replayed against another, and the panel
 *    lives on that account's screen rather than behind a picker for the same reason. The
 *    header this screen sends is pinned here.
 * 3. **Reading `capped: true` after a recompute as a failure.** It is the route working:
 *    the ceiling is still the smaller number. A screen that said "failed" would send the
 *    operator to re-run it instead of to raise the ceiling.
 * 4. **A refusal after the click rather than before it.** This is the one control on the
 *    screen that is `ops:manage` rather than `admin:tenants`, so an `operator` — who may
 *    do everything else here — must be told which permission is missing, beside the
 *    button, before pressing it.
 *
 * Money is asserted as FORMATTED STRINGS: `spend_used_inr` and the ceilings are exact
 * decimals the API sent as text (hard rule 7), and nothing on this path may parse them.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000bb";
const SLUG = "sri-traders";

const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const RECOMPUTE_PATH = `/v1/ops/tenants/${TENANT}/spend-cap/recompute`;
const CAPS_PATH = "/v1/billing/caps";

function me(permissions: string[]): AdminMe {
  return {
    realm: "admin",
    user_id: "0192f0aa-7777-7000-8000-0000000000cc",
    role: permissions.includes("ops:manage") ? "superadmin" : "operator",
    permissions,
  };
}

/** Holds `ops:manage`, so the panel is live. */
const SUPERADMIN = me(["org:read", "billing:read", "admin:tenants", "ops:manage"]);
/** Runs onboarding and support across tenants, and may NOT touch `/v1/ops`. */
const OPERATOR = me(["org:read", "billing:read", "admin:tenants"]);

function tenant(over: Partial<TenantSummary> = {}): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: SLUG,
    status: "active",
    vertical_template: "clinic",
    live_agents: 2,
    calls_7d: 412,
    leads: 96,
    last_call_at: "2026-08-12T09:15:00Z",
    holds: [],
    capped: false,
    ...over,
  };
}

/** A client stopped by their own ceiling: ₹5,002.40 spent against a ₹5,000.00 limit. */
function caps(over: Partial<Caps> = {}): Caps {
  return {
    month: "2026-08",
    plan_cap_minutes: 5000,
    plan_cap_spend_inr: "40000.00",
    client_cap_minutes: null,
    client_cap_spend_inr: "5000.00",
    effective_cap_minutes: 5000,
    effective_cap_spend_inr: "5000.00",
    minutes_used: "812.00",
    spend_used_inr: "5002.40",
    capped: true,
    ...over,
  };
}

/** Everything else on this screen green, so each case breaks exactly one thing. */
function healthy(): Routes {
  return {
    [TENANT_PATH]: tenant({ capped: true }),
    [ADMIN_ME_PATH]: SUPERADMIN,
    [CAPS_PATH]: caps(),
    "/v1/kb/sources?status=pending_approval": [],
    "/v1/kb/sources?status=approved": [],
    "/v1/agents": [],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    [`${TENANT_PATH}/margin`]: {
      month: "2026-08",
      minutes_used: "812.00",
      calls: 412,
      revenue_inr: "5002.40",
      cost_inr: "2001.00",
      margin_inr: "3001.40",
      margin_pct: "59.99",
      tiers: {
        minutes_premium: "600.00",
        minutes_value: "200.00",
        minutes_unattributed: "12.00",
        cost_premium_inr: "1500.00",
        cost_value_inr: "480.00",
        cost_unattributed_inr: "21.00",
      },
    } satisfies Margin,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<TenantDetailPage params={routeParams({ tenantId: TENANT })} />, {
    ...healthy(),
    ...routes,
  });
}

/**
 * The panel renders its button before `GET /v1/admin/me` has answered, disabled and with
 * no sentence beside it — a control must never flash an explanation it is about to
 * withdraw. So arming waits for the verdict rather than reading the first paint.
 */
async function arm(): Promise<HTMLButtonElement> {
  const button = (await screen.findByRole("button", {
    name: /Recompute this client's spend cap/,
  })) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(true));
  fireEvent.change(screen.getByPlaceholderText("RECOMPUTE"), { target: { value: "RECOMPUTE" } });
  await waitFor(() => expect(button.disabled).toBe(false));
  return button;
}

describe("the two ceilings, and which of them this console can move", () => {
  it("offers an edit path for OUR ceiling and none for the client's own", async () => {
    /* The panel already told an operator to "raise the ceiling first if that is the
       fix" and pointed nowhere — an instruction with a dead end in the middle of it.

       Only one of the two ceilings is ours. `plan_cap_*` is set through the admin-realm
       commercial-terms route, so it gets a link. `client_cap_*` is the client's own
       instruction to stop them at a figure, `PUT /v1/billing/caps` is client-realm and
       stays that way (D-22: no acting-as), and there is no operator route that writes
       it — so a link there would promise a control this console does not have. The
       absence is asserted, not just the presence, because "add an edit link to both"
       is the obvious wrong fix and would leave a 403 waiting at the end of it. */
    await render();

    const ours = await screen.findByRole("link", { name: /change on commercials/i });
    expect(ours.getAttribute("href")).toBe(`/admin/tenants/${TENANT}/commercials`);

    // One link in the ceilings grid, not two.
    expect(screen.getAllByRole("link", { name: /change on commercials/i })).toHaveLength(1);
    expect(screen.getByText("Their own ceiling")).toBeTruthy();
  });
});

describe("the spend-cap panel when the cap state cannot be read", () => {
  it("offers no recompute at all, and does not claim the client is uncapped", async () => {
    const { container } = await render({
      [CAPS_PATH]: problem(503, {
        title: "Service unavailable",
        detail: "We could not read this client's spending limits.",
        retryable: true,
      }),
    });

    await screen.findByText("We could not read this client's spending limits.");
    expect(container.textContent).toContain("The cap state could not be read");
    // Neither verdict, because we have neither.
    expect(screen.queryByText(/Outbound calling is STOPPED for this client/)).toBeNull();
    expect(screen.queryByText(/Not capped/)).toBeNull();
    // And nothing to press over a flag nobody read.
    expect(
      screen.queryByRole("button", { name: /Recompute this client's spend cap/ }),
    ).toBeNull();
  });
});

describe("the spend-cap panel's permission gate", () => {
  it("tells an operator which permission is missing BEFORE the click", async () => {
    // This is the only control on this screen that is `ops:manage`; the KB decisions and
    // the telecom setup beside it are `admin:tenants`, which this session holds. A gate
    // copied from its neighbours would offer a button whose only outcome is a 403.
    const { container, calls } = await render({ [ADMIN_ME_PATH]: OPERATOR });

    const button = (await screen.findByRole("button", {
      name: /Recompute this client's spend cap/,
    })) as HTMLButtonElement;
    await waitFor(() => {
      expect(container.textContent).toContain("recompute a client's spend cap");
    });
    expect(container.textContent).toContain("does not have permission to");
    expect(container.textContent).toContain("Ask a superadmin");

    // Typing the word does not revive it, and the endpoint is never reached.
    fireEvent.change(screen.getByPlaceholderText("RECOMPUTE"), { target: { value: "RECOMPUTE" } });
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(calls.some((c) => c.path === RECOMPUTE_PATH)).toBe(false);
  });
});

describe("the spend-cap recompute", () => {
  it("does not fire without its typed confirmation", async () => {
    const { calls } = await render({ [RECOMPUTE_PATH]: recomputed() });

    const button = (await screen.findByRole("button", {
      name: /Recompute this client's spend cap/,
    })) as HTMLButtonElement;
    // A near-miss is not a confirmation.
    fireEvent.change(screen.getByPlaceholderText("RECOMPUTE"), { target: { value: "recompute" } });
    await waitFor(() => {
      expect(screen.getByText(/This client only/)).toBeDefined();
    });
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(calls.some((c) => c.path === RECOMPUTE_PATH)).toBe(false);
  });

  it("says what it will and will NOT do before the click", async () => {
    const { container } = await render({ [RECOMPUTE_PATH]: recomputed() });

    await screen.findByRole("button", { name: /Recompute this client's spend cap/ });
    // The half that keeps this from being read as an "un-cap" button.
    expect(container.textContent).toContain(
      "This client only — it re-derives the flag, it does not lift the cap",
    );
    expect(container.textContent).toContain("raise the ceiling first if that is the fix");
    expect(container.textContent).toContain("never affects inbound calls");
  });

  it("sends the confirmation bound to THIS tenant, not to the verb", async () => {
    const { calls } = await render({ [RECOMPUTE_PATH]: recomputed() });

    fireEvent.click(await arm());

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === RECOMPUTE_PATH)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === RECOMPUTE_PATH);
    expect(post?.headers["X-Confirm-Action"]).toBe(`recompute_spend_cap:${TENANT}`);
    // Pinned against the helper as well, so a reformat of one has to move the other.
    expect(post?.headers["X-Confirm-Action"]).toBe(spendCapConfirmation(TENANT));
    // The admin session, never the impersonating one: `ops:manage` is a MUTATING
    // permission and D-22 refuses those to an acting-as session.
    expect(post?.headers["X-Impersonate-Org"]).toBeUndefined();
  });

  it("renders a still-capped result as the explanation it is, with the numbers", async () => {
    // The route did its job; the ceiling is simply still the smaller number. A screen
    // that read this as a failure sends the operator to press the button again.
    const { container } = await render({
      [RECOMPUTE_PATH]: recomputed({ capped: true, capped_before: true }),
    });

    fireEvent.click(await arm());

    await screen.findByText("Recomputed — this client is still capped");
    expect(screen.queryByText(/the cap is released/)).toBeNull();
    // Money formatted from the STRING the server sent, never parsed.
    expect(container.textContent).toContain("₹5,002.40");
    expect(container.textContent).toContain("₹5,000.00");
  });

  it("says the cap is released only when the server says the flag moved", async () => {
    await render({
      [RECOMPUTE_PATH]: recomputed({ capped_before: true, capped: false }),
    });

    fireEvent.click(await arm());
    await screen.findByText("Recomputed — the cap is released");
  });

  it("does not report a release when the recompute FAILED", async () => {
    const { container } = await render({
      [RECOMPUTE_PATH]: problem(404, {
        title: "Not found",
        detail: "Organization not found.",
      }),
    });

    fireEvent.click(await arm());

    await screen.findByText("Organization not found.");
    expect(container.textContent).not.toContain("Recomputed —");
    // The pre-click state is untouched: still capped, still stopped.
    expect(
      screen.getByText("Outbound calling is STOPPED for this client by the spend cap"),
    ).toBeDefined();
  });
});

describe("which flag the panel believes", () => {
  it("reports the gate's answer, and explains a directory badge that disagrees", async () => {
    // `TenantSummary.capped` is `SELECT capped FROM spend_state` with NO month predicate
    // (`admin/service.py`), while `spend_capped()` and `CapsOut.capped` both treat a row
    // stamped with a closed month as no cap. A client capped in July therefore shows as
    // capped on the directory in August while nothing refuses their dials — and an
    // operator who "fixes" that spends an afternoon on a cap that is not in force.
    const { container } = await render({
      [TENANT_PATH]: tenant({ capped: true }),
      [CAPS_PATH]: caps({ capped: false }),
    });

    await screen.findByText("Not capped — the spend cap is not stopping this client");
    expect(container.textContent).toContain("The client directory shows this account as capped");
    expect(container.textContent).toContain("closed month");
  });

  it("says nothing about a disagreement when the two agree", async () => {
    const { container } = await render({
      [TENANT_PATH]: tenant({ capped: true }),
      [CAPS_PATH]: caps({ capped: true }),
    });

    await screen.findByText("Outbound calling is STOPPED for this client by the spend cap");
    expect(container.textContent).not.toContain("which disagrees");
  });
});

/** The route's response shape (`SpendCapRecomputeOut`), defaulted to a release. */
function recomputed(over: Record<string, unknown> = {}) {
  return {
    tenant_id: TENANT,
    month: "2026-08",
    capped_before: true,
    capped: false,
    minutes_used: "812.00",
    spend_used_inr: "5002.40",
    effective_cap_minutes: 5000,
    effective_cap_spend_inr: "5000.00",
    ...over,
  };
}
