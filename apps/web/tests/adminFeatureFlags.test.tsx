import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import FeatureFlagsPage from "@/app/admin/tenants/[tenantId]/feature-flags/page";
import type { TenantSummary } from "@/lib/api/admin";
import {
  featureFlagPath,
  featureFlagsPath,
  type FeatureFlag,
  type FeatureFlags,
} from "@/lib/api/featureFlags";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, type Routes } from "./harness";

/**
 * Per-tenant feature flags, admin side (SURFACES §1).
 *
 * What these pin, worst first:
 *
 * 1. **§52 — a failed read is a REFUSAL and the controls go with it.** This write
 *    replaces whatever is on file, so acting while the current state is unreadable can
 *    undo a colleague's change with nobody seeing it. The forms are WITHHELD, not
 *    disabled and not empty, and the screen never renders a default position.
 * 2. **Resolution is SHOWN, not collapsed.** The platform default, this client's
 *    override and the resolved answer are three separate facts on screen. A client with
 *    no row must read as "follows the default", never as an explicit off.
 * 3. **A flag nothing reads says so.** `consumed_by: null` is a legitimate state — a
 *    flag can land before the code that consults it — but an operator flipping it for a
 *    client on the phone must be told it changes nothing yet.
 * 4. **"Follow the platform default" is a reachable, distinct choice.** Offering only
 *    on/off would leave a client pinned to a value nobody meant to pin them to.
 * 5. **A control the session may not use is disabled with its reason**, before the click
 *    — `admin:tenants` is what the route requires.
 */

const TENANT = "0192f0aa-8888-7000-8000-0000000000a1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const FLAGS_PATH = featureFlagsPath(TENANT);
const FLAG = "call_timing_breakdown";

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: [],
    capped: false,
  };
}

function me(permissions: string[]): AdminMe {
  return {
    realm: "admin",
    user_id: "0192f0aa-8888-7000-8000-0000000000a2",
    role: "operator",
    permissions,
  };
}

const OPERATOR = me(["org:read", "admin:tenants"]);
const READ_ONLY = me(["org:read"]);

function flag(over: Partial<FeatureFlag> = {}): FeatureFlag {
  return {
    flag: FLAG,
    declared: true,
    description: "Show the per-call timing breakdown on this client's call detail screen.",
    consumed_by: "apps.api.crm.calls",
    platform_default: false,
    override: null,
    enabled: false,
    source: "platform_default",
    reason: null,
    set_by_admin_id: null,
    set_at: null,
    ...over,
  };
}

function flags(...items: FeatureFlag[]): FeatureFlags {
  return { tenant_id: TENANT, items };
}

/** The save control, typed — this suite has no jest-dom, so `disabled` is read directly. */
function saveButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "Save this flag" }) as HTMLButtonElement;
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<FeatureFlagsPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: OPERATOR,
    [FLAGS_PATH]: flags(flag()),
    ...routes,
  });
}

describe("the feature-flag screen", () => {
  it("withholds every control when the flag list could not be read", async () => {
    const { container } = await render({
      [FLAGS_PATH]: problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this client's feature flags.",
        retryable: true,
      }),
    });

    await screen.findByText("Cannot change a flag while the current state is unreadable");

    // Not a disabled radio and not an empty form: no position control exists at all,
    // because a blind write here replaces whatever a colleague set.
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /Save this flag/ })).toBeNull();
    // And nothing on screen states a position we do not know.
    expect(container.textContent).not.toContain("In effect");
  });

  it("renders a client with NO row as following the platform default", async () => {
    const { container } = await render({
      [FLAGS_PATH]: flags(flag({ platform_default: false, override: null, enabled: false })),
    });

    await screen.findByText("None — follows the default");
    // The resolution is shown as three facts, not collapsed into one verdict.
    expect(container.textContent).toContain("Platform default");
    expect(container.textContent).toContain("from the default");
  });

  it("tells the operator when nothing reads the flag yet", async () => {
    await render({ [FLAGS_PATH]: flags(flag({ consumed_by: null })) });
    await screen.findByText("Nothing reads this flag yet");
  });

  it("does not cry wolf when the flag has a consumer", async () => {
    await render({ [FLAGS_PATH]: flags(flag({ consumed_by: "apps.api.crm.calls" })) });
    await screen.findByText(/Platform default/);
    expect(screen.queryByText("Nothing reads this flag yet")).toBeNull();
  });

  it("offers 'follow the platform default' as its own choice, and sends null for it", async () => {
    const { calls } = await render({
      [FLAGS_PATH]: flags(
        flag({
          override: true,
          enabled: true,
          source: "tenant_override",
          reason: "Beta trial, ticket 4471.",
          set_at: "2026-08-13T04:30:00Z",
        }),
      ),
      [`PUT ${featureFlagPath(TENANT, FLAG)}`]: {
        tenant_id: TENANT,
        flag: FLAG,
        changed: true,
        before: { enabled: true, source: "tenant_override" },
        after: { enabled: false, source: "platform_default" },
      },
    });

    fireEvent.click(await screen.findByRole("radio", { name: /Follow the platform default/ }));
    fireEvent.change(screen.getByLabelText("Why (recorded)"), {
      target: { value: "Beta trial finished; back on the platform default." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save this flag" }));

    await screen.findByText(/Changed from/);
    const write = calls.find((call) => call.method === "PUT");
    expect(write, "the screen must send the clear").toBeTruthy();
    expect(JSON.parse(write!.body ?? "{}")).toEqual({
      enabled: null,
      reason: "Beta trial finished; back on the platform default.",
    });
    // No step-up header, because the route asks for none (apps/api/flags/routes.py).
    expect(write!.headers["X-Confirm-Action"]).toBeUndefined();
  });

  it("refuses to send a change with no reason, before the click", async () => {
    await render();
    fireEvent.click(await screen.findByRole("radio", { name: /On for this client/ }));
    expect(saveButton().disabled).toBe(true);
    await screen.findByText(/Say why/);
  });

  it("refuses to send a position that is already on file", async () => {
    await render({
      [FLAGS_PATH]: flags(
        flag({
          override: true,
          enabled: true,
          source: "tenant_override",
          reason: "Beta trial, ticket 4471.",
        }),
      ),
    });
    // The form opens on the stored position, so the button is dead until something moves.
    fireEvent.change(await screen.findByLabelText("Why (recorded)"), {
      target: { value: "Beta trial, ticket 4471." },
    });
    expect(saveButton().disabled).toBe(true);
    await screen.findByText(/already what is on file/);
  });

  it("says plainly when a write changed nothing", async () => {
    await render({
      [FLAGS_PATH]: flags(flag({ override: false, source: "tenant_override", reason: "Pinned." })),
      [`PUT ${featureFlagPath(TENANT, FLAG)}`]: {
        tenant_id: TENANT,
        flag: FLAG,
        changed: false,
        before: { enabled: false, source: "tenant_override" },
        after: { enabled: false, source: "tenant_override" },
      },
    });

    fireEvent.click(await screen.findByRole("radio", { name: /On for this client/ }));
    fireEvent.change(screen.getByLabelText("Why (recorded)"), {
      target: { value: "Turning the timing view on for the week." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save this flag" }));

    await screen.findByText(/no row moved and no audit entry was written/);
  });

  it("disables the controls, with the reason, for a session that may not write", async () => {
    await render({ [ADMIN_ME_PATH]: READ_ONLY });
    await screen.findByText(/does not have the admin:tenants permission/);
    for (const radio of screen.getAllByRole("radio"))
      expect((radio as HTMLInputElement).disabled).toBe(true);
    expect(saveButton().disabled).toBe(true);
  });

  it("shows a leftover row from an older release, and offers to clear it", async () => {
    await render({
      [FLAGS_PATH]: flags(
        flag({
          flag: "retired_beta_view",
          declared: false,
          description: null,
          consumed_by: null,
          platform_default: null,
          override: true,
          enabled: false,
          source: "tenant_override",
          reason: "Left over from an older release.",
        }),
      ),
    });

    await screen.findByText("Left over from an older release");
    // Setting it is refused (it would store a row nothing reads); clearing it is not.
    fireEvent.click(screen.getByRole("radio", { name: /On for this client/ }));
    fireEvent.change(screen.getByLabelText("Why (recorded)"), {
      target: { value: "Trying to set a flag this build does not declare." },
    });
    expect(saveButton().disabled).toBe(true);
    await screen.findByText(/does not declare this flag/);

    fireEvent.click(screen.getByRole("radio", { name: /Follow the platform default/ }));
    expect(saveButton().disabled).toBe(false);
  });

  it("surfaces a refused write rather than pretending it landed", async () => {
    await render({
      [`PUT ${featureFlagPath(TENANT, FLAG)}`]: problem(409, {
        title: "Changed concurrently",
        detail: "The call_timing_breakdown flag was changed by someone else.",
        remediation: "Re-read the flag and send the change again.",
      }),
    });

    fireEvent.click(await screen.findByRole("radio", { name: /On for this client/ }));
    fireEvent.change(screen.getByLabelText("Why (recorded)"), {
      target: { value: "Turning the timing view on for the week." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save this flag" }));

    await screen.findByText(/changed by someone else/);
    expect(screen.queryByText(/Changed from/)).toBeNull();
  });
});
