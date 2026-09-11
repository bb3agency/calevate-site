import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantCreditsPage from "@/app/admin/tenants/[tenantId]/credits/page";
import type { TenantSummary } from "@/lib/api/admin";
import { LEDGER_LIMIT, creditsPath, type Credits } from "@/lib/api/credits";
import {
  startTrialConfirmation,
  trialPath,
  type Trial,
  type TrialStatus,
} from "@/lib/api/trials";

import { expectNoA11yViolations } from "./a11y";
import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, type Routes } from "./harness";

/**
 * Trial periods, from the console — the control that did not exist (D-577).
 *
 * `POST /v1/admin/tenants/{id}/trial` was mounted, in the OpenAPI and callable only by
 * hand-assembling a `curl` with an `X-Confirm-Action` header against production. What
 * makes that worth fixing rather than tolerating is D-551: an empty wallet now stops a
 * client's agents ANSWERING as well as dialling, so a trial is the cheapest answer to "a
 * brand-new client has no credit and their phone stopped after one call" — a thing an
 * operator does while the client is on the telephone.
 *
 * What these pin, worst first:
 *
 * 1. **The confirmation carries the DAYS, and it is the route's own string.** There is no
 *    spend ceiling on a trial by the founder's explicit choice, so the number of days is
 *    the entire bound on what this act can cost. A header this console spelled its own way
 *    is a request the API refuses; a header built from a different number than the one on
 *    screen is a ceremony that protects nobody.
 * 2. **The days are typed twice and the button is dead until they match.** 14 and 140 are
 *    one keystroke apart and there is nothing downstream to catch the difference.
 * 3. **The control states what it does and for how long BEFORE it is pressed** — and says
 *    what a trial does NOT suspend, because "everything is on us" is exactly the sentence
 *    an operator would otherwise read as a compliance exemption.
 * 4. **A failed read withholds the control** (§52 with money on it): "they have never had
 *    a trial" and "we could not find out" are opposite facts, and acting on the first when
 *    the second is true means promising a client something the API will refuse.
 */

const TENANT = "0192f0aa-6666-7000-8000-0000000000a1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const CREDITS_READ = `${creditsPath(TENANT)}?limit=${LEDGER_LIMIT}`;
const TRIAL_PATH = trialPath(TENANT);

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: [],
    capped: false,
  };
}

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-6666-7000-8000-0000000000a2",
  role: "operator",
  permissions: ["org:read", "billing:read", "admin:tenants"],
};

/** An empty wallet — the state an operator is looking at when they reach for a trial. */
function credits(): Credits {
  return {
    tenant_id: TENANT,
    balance_inr: "0.00",
    is_low: true,
    low_balance_threshold_inr: "200.00",
    granted_inr: "0.00",
    paid_inr: "0.00",
    entries: [],
    payments: [],
    lots: [],
    override_packs: [],
  };
}

function trial(over: Partial<TrialStatus> = {}): TrialStatus {
  return {
    tenant_id: TENANT,
    trial_id: "0192f0aa-6666-7000-8000-0000000000b1",
    status: "active",
    active: true,
    days: 14,
    started_at: "2026-09-01T05:30:00Z",
    ends_at: "2026-09-15T05:30:00Z",
    days_remaining: 5,
    ended_at: null,
    ended_reason: null,
    erase_after: "2026-10-15T05:30:00Z",
    erasure_filed_at: null,
    started_by: ME.user_id,
    cost_to_us_inr: "1284.50",
    ...over,
  };
}

function started(over: Partial<Trial> = {}): Trial {
  return {
    tenant_id: TENANT,
    trial_id: "0192f0aa-6666-7000-8000-0000000000b2",
    status: "active",
    active: true,
    days: 14,
    started_at: "2026-09-10T05:30:00Z",
    ends_at: "2026-09-24T05:30:00Z",
    days_remaining: 14,
    ended_at: null,
    ended_reason: null,
    erase_after: "2026-10-24T05:30:00Z",
    erasure_filed_at: null,
    started_by: ME.user_id,
    ...over,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(
    <TenantCreditsPage params={routeParams({ tenantId: TENANT })} />,
    {
      [TENANT_PATH]: tenant(),
      [ADMIN_ME_PATH]: ME,
      [CREDITS_READ]: credits(),
      [TRIAL_PATH]: null,
      ...routes,
    },
  );
}

/** Fill the trial form the way an operator does: days, days again, why. */
async function fillTrial(
  days: string,
  why = "onboarding gift, agreed with the founder",
) {
  fireEvent.change(await screen.findByLabelText("Days on us"), {
    target: { value: days },
  });
  fireEvent.change(screen.getByLabelText("Type the number of days again"), {
    target: { value: days },
  });
  fireEvent.change(
    screen.getByLabelText("Why this client is being carried (required)"),
    {
      target: { value: why },
    },
  );
}

function startButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /^(Start a trial|Carry |Starting)/,
  }) as HTMLButtonElement;
}

describe("the trial control on the credits screen", () => {
  it("sends the days, the reason and the route's own confirmation header", async () => {
    const { calls, container } = await render({
      [`POST ${TRIAL_PATH}`]: started(),
    });

    await fillTrial("14");
    fireEvent.click(startButton());

    await waitFor(() => {
      expect(
        calls.some(
          (call) => call.method === "POST" && call.path === TRIAL_PATH,
        ),
      ).toBe(true);
    });
    const write = calls.find(
      (call) => call.method === "POST" && call.path === TRIAL_PATH,
    )!;
    expect(JSON.parse(write.body!)).toEqual({
      days: 14,
      reason: "onboarding gift, agreed with the founder",
      erasure_grace_days: 30,
    });
    // The route builds this string from the tenant AND the days, and refuses anything
    // else: a confirmation captured for one client must not be replayable against
    // another, and one captured for 14 days must not travel with a request for 140.
    expect(write.headers["X-Confirm-Action"]).toBe(
      startTrialConfirmation(TENANT, 14),
    );
    await expectNoA11yViolations(
      container,
      "admin/tenants/[tenantId]/credits (trial form)",
    );
  });

  it("will not submit until the number of days has been typed twice and matches", async () => {
    await render();

    fireEvent.change(await screen.findByLabelText("Days on us"), {
      target: { value: "14" },
    });
    fireEvent.change(
      screen.getByLabelText("Why this client is being carried (required)"),
      {
        target: { value: "onboarding gift" },
      },
    );
    expect(startButton().disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Type the number of days again"), {
      target: { value: "140" },
    });
    expect(startButton().disabled).toBe(true);
    expect(screen.getByText(/These two do not match/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Type the number of days again"), {
      target: { value: "14" },
    });
    expect(startButton().disabled).toBe(false);
  });

  it("says what it does, for how long, and what it does NOT suspend, before the press", async () => {
    const { container } = await render();
    await screen.findByLabelText("Days on us");
    const text = container.textContent ?? "";

    expect(text).toContain("no spend ceiling");
    expect(text).toContain("their wallet is not debited");
    expect(text).toMatch(/still metered/);
    // The half an operator would otherwise assume away. A trial is a BILLING state: the
    // compliance gates are untouched, and a console that implied otherwise would be
    // teaching people that a commercial gift reaches TRAI.
    expect(text).toContain("A trial is a billing state, not a licence.");
    for (const gate of [
      "KYC",
      "do-not-call",
      "consent",
      "AI disclosure",
      "DLT",
    ]) {
      expect(text).toContain(gate);
    }

    await fillTrial("14");
    // FOR HOW LONG, on the button itself once the figure is known.
    expect(startButton().textContent).toContain("14");
  });

  it("shows what a running trial has cost us, and offers to end it rather than start a second", async () => {
    const { container } = await render({ [TRIAL_PATH]: trial() });
    await screen.findByText(/Cost to Calevate so far/);

    const text = container.textContent ?? "";
    expect(text).toContain("₹1,284.50");
    expect(text).toContain("never shown to the client");
    // The route refuses a second open trial with a 409; offering the form anyway would be
    // a control that can only fail.
    expect(screen.queryByLabelText("Days on us")).toBeNull();
    expect(screen.getByRole("button", { name: "End this trial" })).toBeTruthy();
  });

  it("reports a trial that has ENDED rather than showing nothing", async () => {
    await render({
      [TRIAL_PATH]: trial({
        status: "stopped",
        active: false,
        days_remaining: null,
        ended_at: "2026-09-08T05:30:00Z",
        ended_reason: "They did not buy.",
      }),
    });
    expect(await screen.findByText(/Their trial ended/)).toBeTruthy();
    // And a new one may be started, which is the whole reason the read is "newest" rather
    // than "the open one".
    expect(await screen.findByLabelText("Days on us")).toBeTruthy();
  });

  it("withholds the control when the trial read failed, rather than saying they never had one", async () => {
    const { container } = await render({
      [TRIAL_PATH]: problem(500, { title: "Server error" }),
    });
    await screen.findByText(/We could not read this client's trial/);

    expect(screen.queryByLabelText("Days on us")).toBeNull();
    expect(container.textContent).not.toContain("has never been given a trial");
  });

  it("states plainly that the client has never had one when the server says null", async () => {
    const { container } = await render();
    await screen.findByLabelText("Days on us");
    expect(container.textContent).toContain(
      "Sri Traders has never been given a trial",
    );
  });
});
