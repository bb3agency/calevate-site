import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import LifecyclePage from "@/app/admin/tenants/[tenantId]/lifecycle/page";
import type { TenantSummary } from "@/lib/api/admin";
import { tenantStatusPath } from "@/lib/api/commercials";
import type { Routes } from "./harness";

import { problem } from "./harness";
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
  } as TenantSummary;
}

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000d2",
  role: "operator",
  permissions: ["org:read", "admin:tenants"],
} as AdminMe;

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<LifecyclePage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: ME,
    ...routes,
  });
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

  it("disables the control, with its reason, for a session that may not use it", async () => {
    await render({ [ADMIN_ME_PATH]: { ...ME, permissions: ["org:read"] } });

    const button = (await screen.findByRole("button", { name: /Suspend/ })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/change an account's state/)).toBeDefined();
  });
});
