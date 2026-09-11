import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantNumbersPage from "@/app/admin/tenants/[tenantId]/numbers/page";
import type { TenantSummary } from "@/lib/api/admin";
import type { TenantNumberCost } from "@/lib/api/numbers";

import { type Routes } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * THE NUMBERS SCREEN — the console half of D-576.
 *
 * The defect this file pins: `phone_numbers.agent_id` had exactly one writer and it was
 * the INSERT, so every number on this platform was attached to nobody — and no screen in
 * either console said so or could change it. The only place a number could be recorded at
 * all was `CampaignSetup`, a panel about CAMPAIGNS, with the series selector preselected
 * to `160`; an operator onboarding an inbound-only client was sent there, with a DLT class
 * already chosen for them, to do the one step that makes the phone ring.
 *
 * Four claims, each of which was false before this change:
 *
 * 1. A number with no agent SAYS SO, in words an operator can act on, on its own row.
 * 2. The picker is on that row and posts to the attach route.
 * 3. Detaching is offered as an ordinary choice ("Nobody"), because it is the only way out
 *    of a wrong attachment — `release_number` refuses a client-owned connection and
 *    `phone_numbers.e164` is globally UNIQUE.
 * 4. Recording a number is on THIS screen, and its series default is `standard` — a
 *    client's own published business line — not a regulated DLT class.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000ee";
const SLUG = "attach-clinic";
const NUMBER = "0192f0aa-7777-7000-8000-000000000111";
const AGENT = "0192f0aa-7777-7000-8000-000000000222";

const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const COSTS_PATH = `/v1/admin/numbers/tenants/${TENANT}`;
const ATTACH_PATH = `/v1/admin/tenants/${TENANT}/numbers/${NUMBER}/agent`;
const RECORD_PATH = `/v1/admin/tenants/${TENANT}/numbers`;

const SUPERADMIN: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000cc",
  role: "superadmin",
  permissions: ["org:read", "billing:read", "admin:tenants"],
};

function number(overrides: Partial<TenantNumberCost> = {}): TenantNumberCost {
  return {
    id: NUMBER,
    e164: "+918041234567",
    series: "standard",
    dlt_status: "pending",
    provider: "plivo",
    engine_owned: false,
    engine_linked: true,
    agent_id: null,
    agent_name: null,
    monthly_rental_usd: null,
    released: false,
    ...overrides,
  };
}

function healthy(numbers: TenantNumberCost[]): Routes {
  return {
    [ADMIN_ME_PATH]: SUPERADMIN,
    [TENANT_PATH]: {
      id: TENANT,
      name: "Attach Clinic",
      slug: SLUG,
      status: "active",
      plan_tier: "starter",
      vertical_template: "clinic",
      leads: 0,
      calls_7d: 0,
      live_agents: 1,
      last_call_at: null,
      capped: false,
      holds: [],
    } satisfies TenantSummary,
    [COSTS_PATH]: numbers,
    "/v1/agents": [
      {
        id: AGENT,
        name: "Front desk",
        direction: "inbound",
        status: "live",
        archived_at: null,
        language_primary: "te-IN",
        disclosure_line: "This is an AI assistant. This call is recorded.",
        ai_disclosure_line: "This is an AI assistant.",
        ai_disclosure_enabled: true,
        recording_notice_line: "This call is recorded.",
        recording_notice_enabled: true,
        caller_memory_notice_line: "I may remember you.",
        caller_memory_enabled: false,
        opening_line: "This is an AI assistant. This call is recorded.",
        truthful_answer_rule: "Always answer truthfully.",
      },
      {
        id: "0192f0aa-7777-7000-8000-000000000333",
        name: "Outbound dialler",
        direction: "outbound",
        status: "live",
        archived_at: null,
        language_primary: "te-IN",
        disclosure_line: "This is an AI assistant. This call is recorded.",
        ai_disclosure_line: "This is an AI assistant.",
        ai_disclosure_enabled: true,
        recording_notice_line: "This call is recorded.",
        recording_notice_enabled: true,
        caller_memory_notice_line: "I may remember you.",
        caller_memory_enabled: false,
        opening_line: "This is an AI assistant. This call is recorded.",
        truthful_answer_rule: "Always answer truthfully.",
      },
    ],
  };
}

function render(routes: Routes) {
  return renderAdminRoute(
    <TenantNumbersPage params={routeParams({ tenantId: TENANT })} />,
    routes,
  );
}

describe("a number nobody answers says so, and the fix is on the row", () => {
  it("states that no agent answers the number, in words, rather than showing a complete-looking row", async () => {
    await render(healthy([number()]));

    expect(
      await screen.findByText(/No agent answers this number/),
    ).toBeTruthy();
    // The consequence, not just the state — this is the sentence whose absence let a
    // publish report success over a phone that does not ring.
    expect(
      screen.getByText(/publishing an agent will report success/),
    ).toBeTruthy();
  });

  it("offers only agents that ANSWER incoming calls, plus the detach choice", async () => {
    await render(healthy([number()]));

    const picker = (await screen.findByLabelText(
      "Answered by",
    )) as HTMLSelectElement;
    const options = [...picker.options].map((option) => option.textContent);
    expect(options).toContain("Front desk");
    // An outbound-only agent would be refused by the server (`agent_does_not_answer_
    // inbound`), so offering it here would be a choice whose only outcome is a refusal.
    expect(options.some((label) => label?.includes("Outbound dialler"))).toBe(
      false,
    );
    // DETACH IS AN ORDINARY CHOICE, not a hidden one: it is the only way out of a wrong
    // attachment, and before D-576 there was none at all.
    expect(options[0]).toMatch(/Nobody/);
  });

  it("posts the chosen agent to the attach route and reports what the platform was told", async () => {
    const calls: unknown[] = [];
    await render({
      ...healthy([number()]),
      [ATTACH_PATH]: (call: { body: string | null }) => {
        calls.push(JSON.parse(call.body ?? "null"));
        return {
          number_id: NUMBER,
          agent_id: AGENT,
          bound: 1,
          released: 0,
          failed: 0,
          unsupported: 0,
        };
      },
    });

    const picker = await screen.findByLabelText("Answered by");
    fireEvent.change(picker, { target: { value: AGENT } });

    await waitFor(() => expect(calls).toEqual([{ agent_id: AGENT }]));
    expect(
      await screen.findByText(
        /the voice platform now answers this number with that agent/,
      ),
    ).toBeTruthy();
  });

  it("sends null when the operator detaches, and says the platform stopped answering", async () => {
    const calls: unknown[] = [];
    await render({
      ...healthy([number({ agent_id: AGENT, agent_name: "Front desk" })]),
      [ATTACH_PATH]: (call: { body: string | null }) => {
        calls.push(JSON.parse(call.body ?? "null"));
        return {
          number_id: NUMBER,
          agent_id: null,
          bound: 0,
          released: 1,
          failed: 0,
          unsupported: 0,
        };
      },
    });

    expect(await screen.findByText("Answered by Front desk.")).toBeTruthy();
    // `findBy`, not `getBy`: the sentence above renders from the NUMBER, which is in the
    // first paint, while the picker waits on the agents query — so a synchronous lookup
    // here raced the fetch and failed on a row that was about to be correct. The sibling
    // attach case already awaited it; this one did not, and only the full-suite timing
    // made the difference visible.
    fireEvent.change(await screen.findByLabelText("Answered by"), {
      target: { value: "" },
    });

    await waitFor(() => expect(calls).toEqual([{ agent_id: null }]));
    expect(
      await screen.findByText(
        /the voice platform no longer answers this number/,
      ),
    ).toBeTruthy();
  });

  it("reports a routing the voice platform REFUSED instead of implying a phone that rings", async () => {
    await render({
      ...healthy([number()]),
      [ATTACH_PATH]: {
        number_id: NUMBER,
        agent_id: AGENT,
        bound: 0,
        released: 0,
        failed: 1,
        unsupported: 0,
      },
    });

    fireEvent.change(await screen.findByLabelText("Answered by"), {
      target: { value: AGENT },
    });

    expect(
      await screen.findByText(/the voice platform refused the routing/),
    ).toBeTruthy();
  });
});

describe("recording a number is on the numbers screen, not on a campaign screen", () => {
  it("is the screen's primary surface and defaults the series to standard, not a DLT class", async () => {
    await render(healthy([]));

    const submit = (await screen.findByRole("button", {
      name: "Record this number",
    })) as HTMLButtonElement;
    // UX §1: exactly one PRIMARY_BUTTON_LG per screen, and it is this one. `px-5 py-3` is
    // that class's own size — asserted so a refactor that demotes recording back into a
    // small control beside the buy form goes red rather than merely looking different.
    expect(submit.className).toContain("px-5 py-3");

    const series = (await screen.findByLabelText(
      "Series",
    )) as HTMLSelectElement;
    expect(series.value).toBe("standard");
  });

  it("records through the admin route and asks for no agent at create time", async () => {
    const calls: unknown[] = [];
    await render({
      ...healthy([]),
      [RECORD_PATH]: (call: { body: string | null }) => {
        calls.push(JSON.parse(call.body ?? "null"));
        return {
          id: NUMBER,
          e164: "+918041234567",
          series: "standard",
          dlt_status: "pending",
        };
      },
    });

    fireEvent.change(
      await screen.findByLabelText("The number, with its country code"),
      { target: { value: "+918041234567" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Record this number" }));

    // NO `agent_id`. The console decides which agent answers in ONE place — the picker on
    // the row — and never at the moment the operator knows least (D-576).
    await waitFor(() =>
      expect(calls).toEqual([{ e164: "+918041234567", series: "standard" }]),
    );
  });
});
