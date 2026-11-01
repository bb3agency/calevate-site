import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  render,
  screen,
  type RenderResult,
} from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantDetailPage from "@/app/admin/tenants/[tenantId]/page";
import type { KbSource, Margin, TenantSummary } from "@/lib/api/admin";

import { routeParams } from "./adminRoute";
import { noReply, problem, stubApi, type Routes } from "./harness";
import { OWNER_JOINED } from "./businessProfileFixture";
import {
  WHATSAPP_NEVER_ASKED,
  adminOverviewSummaryReads,
} from "./fixtures/sharedReads";

/**
 * "Going live" — approved knowledge that is not live yet, in every state its read can be in.
 *
 * Approved means live (D-951): approving queues the publish and the knowledge sweep
 * retries one that did not take, so this panel has no button. It exists so an operator
 * who approved a document can see it is on its way, rather than wondering where it went.
 *
 * `goingLive` is `(approvedQueue.data ?? []).filter(...)`, and that `?? []` cannot tell
 * "the request has not come back" from "the server says there are none". While the read
 * was IN FLIGHT the panel once rendered NOTHING, which said "nothing approved is waiting"
 * about a question nobody had answered yet (§52).
 *
 * `surfaceStatesGuard.test.ts` cannot see it and says so — it deliberately leaves `?? []`
 * outside a JSX child alone, because whether the `[]` reaches a pixel is a question about
 * branch dominance that no AST walk computes. This is the branch that let it through, so
 * it needs a rendering test, which is exactly the division of labour that file describes.
 *
 * WHY THIS FILE HAS ITS OWN RENDER HELPER. The shared harness answers every route
 * immediately, which is right for almost everything and cannot express the state under
 * test here: a request that has not answered YET. `_renderWithPendingApprovedQueue` below
 * wraps the harness's own stub rather than replacing it — every other route still comes
 * from `stubApi`, so this is the real screen making its real requests with exactly one of
 * them left in flight.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000bb";
const SLUG = "sri-traders";

const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const MARGIN_PATH = `${TENANT_PATH}/margin`;
const QUEUE_PATH = "/v1/kb/sources?status=pending_approval";
const APPROVED_PATH = "/v1/kb/sources?status=approved";
const AGENTS_PATH = "/v1/agents";
const NUMBERS_PATH = "/v1/campaigns/numbers";
const TEMPLATES_PATH = "/v1/campaigns/templates";
const CAPS_PATH = "/v1/billing/caps";

const PANEL = "Going live";

const OPERATOR: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000cc",
  role: "operator",
  permissions: [
    "org:read",
    "billing:read",
    "agents:read",
    "kb:write",
    "admin:tenants",
  ],
};

/** A source as the API sends it since D-689: the client's knowledge, shared by all its agents. */
function source(over: Partial<KbSource> = {}): KbSource {
  return {
    id: "0192f0aa-7777-7000-8000-0000000000dd",
    name: "Clinic price list",
    kind: "text",
    status: "approved",
    version: 3,
    chunks: 12,
    is_active: false,
    published_at: null,
    ...over,
  };
}

/** Everything green, so each test can break exactly one thing. */
function healthy(): Routes {
  return {
    [`${TENANT_PATH}/owner-status`]: OWNER_JOINED,
    [`${TENANT_PATH}/business-type`]: noReply(),
    [TENANT_PATH]: {
      id: TENANT,
      name: "Sri Traders",
      slug: SLUG,
      status: "active",
      plan_tier: "prepaid",
      vertical_template: "clinic",
      live_agents: 2,
      calls_7d: 412,
      leads: 96,
      last_call_at: "2026-08-12T09:15:00Z",
      holds: [],
      capped: false,
      // `satisfies`, not `as`, and not an annotation: this literal is a VALUE inside a
      // `Routes` map (`Record<string, unknown>`), so there is no declaration to annotate
      // and the contextual type checks nothing. `as TenantSummary` used to sit here and
      // was worse than nothing — it silenced the compiler on a fixture that has to mirror
      // the wire exactly, which is how five margin fixtures shipped missing a required
      // field. `satisfies` demands every required field and rejects fields the server
      // cannot send, while leaving the value's own type alone.
    } satisfies TenantSummary,
    [ADMIN_ME_PATH]: OPERATOR,
    [QUEUE_PATH]: [],
    [APPROVED_PATH]: [],
    [AGENTS_PATH]: [],
    [NUMBERS_PATH]: [],
    [TEMPLATES_PATH]: [],
    [`${TENANT_PATH}/whatsapp-alerts`]: WHATSAPP_NEVER_ASKED,
    ...adminOverviewSummaryReads(TENANT),
    [MARGIN_PATH]: {
      month: "2026-08",
      minutes_used: "1204.5",
      calls: 412,
      revenue_inr: "1015900.00",
      rental_revenue_inr: "0.00",
      cost_inr: "402350.50",
      margin_inr: "613549.50",
      margin_pct: "60.39",
      legs_unpriced: 0,
      trial_cost_inr: "0.00",
      trial_in_month: false,
      paid_cost_inr: "402350.50",
      paid_margin_inr: "613549.50",
      paid_margin_pct: "60.39",
      tiers: {
        // BOTH SPELLINGS, because that is what the wire carries for one release
        // (hard rule 8 step 1, D-558): `*_base_rung` / `*_second_rung` are the
        // names, `*_premium` / `*_value` are deprecated and carry the identical
        // figure. The screen prefers the new pair;
        // `rungRenameFallback.test.tsx` is the one that omits it.
        minutes_base_rung: "900.00",
        minutes_second_rung: "280.00",
        minutes_premium: "900.00",
        minutes_value: "280.00",
        minutes_unattributed: "24.50",
        cost_base_rung_inr: "300000.00",
        cost_second_rung_inr: "90000.00",
        cost_premium_inr: "300000.00",
        cost_value_inr: "90000.00",
        cost_unattributed_inr: "12350.50",
      },
    } satisfies Margin,
    [CAPS_PATH]: {
      month: "2026-08",
      plan_cap_minutes: 5000,
      plan_cap_spend_inr: "40000.00",
      client_cap_minutes: null,
      client_cap_spend_inr: null,
      effective_cap_minutes: 5000,
      effective_cap_spend_inr: "40000.00",
      minutes_used: "812.00",
      spend_used_inr: "5002.40",
      capped: false,
      trial_active: false,
    },
  };
}

async function renderScreen(): Promise<RenderResult> {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  let result!: RenderResult;
  await act(async () => {
    result = render(
      <QueryClientProvider client={client}>
        <Suspense fallback={null}>
          <TenantDetailPage params={routeParams({ tenantId: TENANT })} />
        </Suspense>
      </QueryClientProvider>,
    );
  });
  return result;
}

async function renderHealthy(
  over: Partial<Routes> = {},
): Promise<RenderResult> {
  stubApi({ ...healthy(), ...over });
  return renderScreen();
}

/**
 * The screen with EVERY read answered except the approved-source list, which stays in
 * flight forever.
 *
 * The harness's own stub is installed first and then delegated to, rather than replaced:
 * a hand-written mock that only knew about this one path would answer the other six
 * requests with a throw, and the panel would then be missing for a reason that has nothing
 * to do with what is being tested.
 */
async function renderWithPendingApprovedQueue(): Promise<RenderResult> {
  stubApi(healthy());
  const delegate = globalThis.fetch;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).includes("status=approved"))
      return new Promise<Response>(() => {});
    return delegate(input, init);
  });
  return renderScreen();
}

describe("approved knowledge going live, in the three states a read can be in", () => {
  it("does not say nothing is going live while it is still asking", async () => {
    const { container } = await renderWithPendingApprovedQueue();

    // The rest of the screen has loaded — this is a real paint, not a pre-mount snapshot.
    await screen.findByText("Live agents");

    expect(
      container.textContent,
      "the panel vanished while its read was in flight, which reads as 'nothing " +
        "approved is waiting' — §52: loading is a skeleton",
    ).toContain(PANEL);
    // And it is a SKELETON, not a count or an empty list.
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
    expect(container.textContent).not.toContain("Nothing to press");
  });

  it("refuses in words when the read failed", async () => {
    const { container } = await renderHealthy({
      [APPROVED_PATH]: problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this client's approved knowledge.",
        retryable: true,
      }),
    });

    await screen.findByText(
      "We could not read this client's approved knowledge.",
    );
    expect(container.textContent).toContain(PANEL);
  });

  it("stays silent only when the SERVER says nothing approved is waiting", async () => {
    const { container } = await renderHealthy();

    await screen.findByText("Nothing awaiting approval");

    // The counterpart to both tests above: with a 200 and an empty list in hand there is
    // nothing on its way, and drawing a panel for it would teach an operator to read past
    // the one that means something.
    expect(container.textContent).not.toContain(PANEL);
  });

  it("shows an approved source as going live, with no Publish button", async () => {
    // Approved means live (D-951): approving queued the publish, so there is nothing
    // for an operator to press.
    const { container } = await renderHealthy({ [APPROVED_PATH]: [source()] });

    await screen.findByText("Clinic price list");
    expect(container.textContent).toContain(PANEL);
    expect(container.textContent).toContain("Nothing to press");
    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull();
  });

  it("does not list a source that is already live", async () => {
    // `publish_source` leaves `status` at 'approved' and flips `is_active`, so a live
    // source stays in the approved list and must be filtered out of this panel.
    const { container } = await renderHealthy({
      [APPROVED_PATH]: [
        source({ is_active: true, published_at: "2026-08-14T10:00:00Z" }),
      ],
    });

    await screen.findByText("Nothing awaiting approval");
    expect(container.textContent).not.toContain(PANEL);
  });
});
