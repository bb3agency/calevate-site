import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import LifecyclePage from "@/app/admin/tenants/[tenantId]/lifecycle/page";
import type { TenantSummary } from "@/lib/api/admin";
import { tenantStatusPath } from "@/lib/api/commercials";
import type { Routes } from "./harness";

import { problem } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";
import type { Closure } from "@/lib/api/closure";

/**
 * Account state — the control that stops a client dialling.
 *
 * `organizations.status` was read by the health board and written by nothing; there was
 * no suspend route in either realm. What the tests pin:
 *
 * 1. **A failed read is a refusal, never a state.** "Active" printed over a 503 is how
 *    an operator suspends the wrong client — the §52 rule at its most expensive.
 * 2. **Each move says what it does to the client before it is made**, including the fact
 *    nobody can guess from a dropdown: outbound stops and inbound does not.
 * 3. **A stop must explain itself.** The API refuses a reasonless suspension; the screen
 *    refuses first so the operator is not told after typing.
 * 4. **A closed account offers no controls at all**, because the API answers 409 — and it
 *    points at the screen that CAN reopen it, which this one deliberately cannot.
 * 5. **An unchanged result is reported as unchanged**, not as a change that happened.
 * 6. **CLOSING IS NOT REACHABLE FROM HERE AT ALL (D-546)**, which is the assertion that
 *    keeps the collapse from being undone by a well-meaning re-add: there is exactly one
 *    way to close a client, and it is `/closure`, which tells them and can be undone.
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
    plan_tier: "prepaid",
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
  return renderAdminRoute(
    <LifecyclePage params={routeParams({ tenantId: TENANT })} />,
    {
      [TENANT_PATH]: tenant(),
      [ADMIN_ME_PATH]: ME,
      ...routes,
    },
  );
}

/** A closed account's screen also reads its closure record. */
const CLOSURE_PATH = `${TENANT_PATH}/closure`;
const CLOSURE = {
  tenant_id: TENANT,
  status: "churned",
  closed_at: "2026-08-20T05:30:00Z",
  erase_after: "2026-09-19T05:30:00Z",
  reason: "The clinic has closed its second branch and is not renewing.",
  closed_by: "0192f0aa-7777-7000-8000-0000000000d2",
  erased_at: null,
  restorable: true,
  days_remaining: 13,
} satisfies Closure;

describe("the account state screen", () => {
  it("refuses to render a state it could not read", async () => {
    const { container } = await render({
      [TENANT_PATH]: problem(503, {
        title: "Upstream unavailable",
        retryable: true,
      }),
    });

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /Suspend/ })).toBeNull();
    });
    expect(container.textContent).not.toContain("Currently active");
  });

  it("says what suspending does — and what it deliberately does not touch", async () => {
    const { container } = await render();

    await screen.findByRole("button", { name: /Suspend/ });
    expect(container.textContent).toContain(
      "Outbound dialling stops at the next dial",
    );
    expect(container.textContent).toContain(
      "Inbound answering is deliberately unaffected",
    );
  });

  it("will not send a suspension with no reason", async () => {
    const { calls } = await render({
      [`POST ${STATUS_PATH}`]: {
        tenant_id: TENANT,
        status: "suspended",
        changed: true,
      },
    });

    const button = (await screen.findByRole("button", {
      name: /Suspend/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(calls.some((call) => call.path === STATUS_PATH)).toBe(false);

    fireEvent.change(screen.getByLabelText("Why"), {
      target: { value: "non-payment, 60 days" },
    });
    await waitFor(() => {
      expect(
        (screen.getByRole("button", { name: /Suspend/ }) as HTMLButtonElement)
          .disabled,
      ).toBe(false);
    });
    fireEvent.click(screen.getByRole("button", { name: /Suspend/ }));
    await waitFor(() => {
      expect(
        calls.some(
          (call) => call.method === "POST" && call.path === STATUS_PATH,
        ),
      ).toBe(true);
    });
    const post = calls.find(
      (call) => call.method === "POST" && call.path === STATUS_PATH,
    );
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
      [`POST ${STATUS_PATH}`]: {
        tenant_id: TENANT,
        status: "active",
        changed: true,
      },
    });

    const button = (await screen.findByRole("button", {
      name: /Reactivate/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);

    await waitFor(() => {
      expect(
        calls.some(
          (call) => call.method === "POST" && call.path === STATUS_PATH,
        ),
      ).toBe(true);
    });
    expect(
      JSON.parse(calls.find((call) => call.method === "POST")?.body ?? "{}")
        .status,
    ).toBe("active");
  });

  it("offers no state control on a closed account, and points at the one that reopens it", async () => {
    const { container } = await render({
      [TENANT_PATH]: tenant("churned"),
      [CLOSURE_PATH]: CLOSURE,
    });

    await screen.findByText("This account is closed");
    expect(screen.queryByRole("button", { name: /Reactivate/ })).toBeNull();
    // NOT "cannot be reopened", which is what this said before D-546 and was true of this
    // screen while reading as true of the product. The undo exists; it is one click away.
    expect(container.textContent).toContain("This screen cannot reopen it");
    // Two of them, and deliberately: the header sentence names the screen for an account
    // in any state, and the closed notice names it again where the operator is standing.
    const links = screen.getAllByRole("link", { name: /Closing the account/ });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(link.getAttribute("href")).toBe(
        `/admin/tenants/${TENANT}/closure`,
      );
    }
  });

  it("reports an already-in-state result as unchanged", async () => {
    const { container } = await render({
      [`POST ${STATUS_PATH}`]: {
        tenant_id: TENANT,
        status: "suspended",
        changed: false,
      },
    });

    fireEvent.change(await screen.findByLabelText("Why"), {
      target: { value: "chargeback" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Suspend/ }));

    await waitFor(() => {
      expect(container.textContent).toContain("was already suspended");
    });
    expect(container.textContent).toContain("no audit row was written");
  });

  it("cannot close an account at all — there is one door and it is not this one", async () => {
    /**
     * THE D-546 COLLAPSE, pinned. Two ways to end a client relationship existed and the
     * reachable one was the worse one: a dropdown here wrote `churned`, told the client
     * nothing, set no erasure deadline and had no undo. What replaced it is that this screen
     * cannot do it at all.
     *
     * An active account is offered exactly one move (Suspend), so the assertion is that NO
     * control on the screen — no button and no option — can close it. An account in some
     * other state still gets the choice, and that choice is checked option by option,
     * because a re-added `churned` with a disabled button would pass a weaker check and
     * would still be a second door the moment somebody enabled it.
     */
    const { container } = await render();

    await screen.findByRole("button", { name: /Suspend/ });
    for (const button of screen.getAllByRole("button")) {
      expect(button.textContent ?? "").not.toMatch(/clos/i);
    }
    expect(container.querySelector("option[value='churned']")).toBeNull();
    // The typed word went with the move it guarded; nothing left here is irreversible.
    expect(screen.queryByLabelText(/to confirm/)).toBeNull();
  });

  it("offers both reversible moves, and only those, from any other state", async () => {
    await render({ [TENANT_PATH]: tenant("onboarding") });

    const select = (await screen.findByLabelText(
      "New state",
    )) as HTMLSelectElement;
    const options = Array.from(select.options).map((option) => option.value);
    expect(options).toEqual(["active", "suspended"]);
  });

  it("offers one move from active and one from suspended, with no pointless choice", async () => {
    await render();
    await screen.findByRole("button", { name: /Suspend/ });
    // The other option of the old dropdown was the state the account was already in.
    expect(screen.queryByLabelText("New state")).toBeNull();
  });

  it("sends the suspend with no confirmation header — the header went with the close", async () => {
    const { calls } = await render({
      [`POST ${STATUS_PATH}`]: {
        tenant_id: TENANT,
        status: "suspended",
        changed: true,
      },
    });

    fireEvent.change(await screen.findByLabelText("Why"), {
      target: { value: "non-payment" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Suspend/ }));
    await waitFor(() => {
      expect(
        calls.some(
          (call) => call.method === "POST" && call.path === STATUS_PATH,
        ),
      ).toBe(true);
    });
    // A confirmation attached to a reversible act is a confirmation of nothing, and it
    // teaches an operator to clear the prompt without reading it.
    expect(
      calls.find((call) => call.method === "POST")?.headers["X-Confirm-Action"],
    ).toBeUndefined();
  });

  it("keeps Suspend one click — the reversible move takes no typed word", async () => {
    await render();
    await screen.findByRole("button", { name: /Suspend/ });
    expect(screen.queryByLabelText(/to confirm/)).toBeNull();
  });

  it("disables the control, with its reason, for a session that may not use it", async () => {
    await render({ [ADMIN_ME_PATH]: { ...ME, permissions: ["org:read"] } });

    const button = (await screen.findByRole("button", {
      name: /Suspend/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/change an account's state/)).toBeDefined();
  });
});
