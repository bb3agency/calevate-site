import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, type RenderResult } from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantDetailPage from "@/app/admin/tenants/[tenantId]/page";
import type { KbSource, Margin, TenantSummary } from "@/lib/api/admin";

import { routeParams } from "./adminRoute";
import { problem, stubApi, type Routes } from "./harness";

/**
 * "Approved, awaiting publish" — §52's FIRST clause, on the one panel that had lost it.
 *
 * FLOWS §7 makes approve and publish two steps: approving moves a row to `approved` and
 * touches no engine, and publishing is what the caller actually hears. So an approved
 * source with nowhere to press is a client stuck on "Approved, not live yet" forever, and
 * this panel is the only place anyone can press it.
 *
 * The panel already refused to render an empty list over a FAILED read — that half was
 * fixed and is asserted in `adminTenantDetail.test.tsx`. The other half was still open
 * and is the same sentence drawn a third way:
 *
 *     {publishQueue.error ? refusal : awaitingPublish.length > 0 ? panel : null}
 *
 * `awaitingPublish` is `(publishQueue.data ?? []).filter(...)`, and that `?? []` cannot
 * tell "the request has not come back" from "the server says there are none". While the
 * read is IN FLIGHT the panel therefore rendered NOTHING — an operator's first paint of a
 * client's screen said "nothing is waiting to be published" about a question nobody had
 * answered yet. On a slow read, or a read that is slow because something is wrong, that is
 * the §52 defect in its most expensive direction: the operator closes the tab.
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

const PANEL = "Approved, awaiting publish";

const OPERATOR: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000cc",
  role: "operator",
  permissions: ["org:read", "billing:read", "agents:read", "kb:write", "admin:tenants"],
} as AdminMe;

function source(over: Partial<KbSource> = {}): KbSource {
  return {
    id: "0192f0aa-7777-7000-8000-0000000000dd",
    agent_id: "0192f0aa-7777-7000-8000-0000000000ee",
    name: "Clinic price list",
    kind: "text",
    status: "approved",
    version: 3,
    chunks: 12,
    is_active: false,
    published_at: null,
    ...over,
  } as KbSource;
}

/** Everything green, so each test can break exactly one thing. */
function healthy(): Routes {
  return {
    [TENANT_PATH]: {
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
    } as TenantSummary,
    [ADMIN_ME_PATH]: OPERATOR,
    [QUEUE_PATH]: [],
    [APPROVED_PATH]: [],
    [AGENTS_PATH]: [],
    [NUMBERS_PATH]: [],
    [TEMPLATES_PATH]: [],
    [MARGIN_PATH]: {
      month: "2026-08",
      minutes_used: "1204.5",
      calls: 412,
      revenue_inr: "1015900.00",
      cost_inr: "402350.50",
      margin_inr: "613549.50",
      margin_pct: "60.39",
    } as Margin,
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

async function renderHealthy(over: Partial<Routes> = {}): Promise<RenderResult> {
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
    if (String(input).includes("status=approved")) return new Promise<Response>(() => {});
    return delegate(input, init);
  });
  return renderScreen();
}

describe("the publish queue, in the three states a read can be in", () => {
  it("does not say nothing is awaiting publish while it is still asking", async () => {
    const { container } = await renderWithPendingApprovedQueue();

    // The rest of the screen has loaded — this is a real paint, not a pre-mount snapshot.
    await screen.findByText("Sri Traders");

    expect(
      container.textContent,
      "the panel vanished while its read was in flight, which reads as 'nothing is " +
        "waiting to be published' — §52: loading is a skeleton",
    ).toContain(PANEL);
    // And it is a SKELETON, not a number, a state or an empty list: nothing claims a
    // count, and no Publish button is offered over sources we have not seen.
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
    expect(container.textContent).not.toContain("The agent does not know these");
  });

  it("refuses in words when the read failed", async () => {
    const { container } = await renderHealthy({
      [APPROVED_PATH]: problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this client's approved knowledge.",
        retryable: true,
      }),
    });

    await screen.findByText("We could not read this client's approved knowledge.");
    expect(container.textContent).toContain(PANEL);
  });

  it("stays silent only when the SERVER says there is nothing to publish", async () => {
    const { container } = await renderHealthy();

    await screen.findByText("Nothing awaiting approval");

    // The counterpart to both tests above. With a 200 and an empty list in hand there is
    // genuinely no work, and drawing a panel for it would teach an operator to read past
    // the one that means something. The approval card above already carries the sentence
    // that explains what publishing is for.
    expect(container.textContent).not.toContain(PANEL);
  });

  it("offers Publish for an approved source the server did return", async () => {
    const { container } = await renderHealthy({ [APPROVED_PATH]: [source()] });

    await screen.findByText("Clinic price list");
    expect(container.textContent).toContain(PANEL);
    const publish = screen.getByRole("button", { name: "Publish" }) as HTMLButtonElement;
    expect(publish.disabled, "the one control that makes an approved source live").toBe(false);
  });

  /**
   * The last leg of `runbooks/kb-out-of-sync.md`, which only this screen can carry.
   *
   * `publish_source` produces TWO refusals that mean the same disease and take different
   * cures (`kb_engine_ref_unknown` — withdraw one stale copy you identify by title; and
   * `kb_engine_out_of_sync` — reconcile the whole agent), and the runbook's opening line
   * is that the wrong cure leaves the client's agent quoting old prices. The tests in
   * `tests/kb_flow_promises_test.py` prove the API hands over the right one. That is only
   * half the promise: the advice has to reach the operator's eyes, and the button that
   * produces it is here. `ProblemNotice` renders `remediation` under the detail, so what
   * is asserted below is that the SPECIFIC sentence arrives — not merely that something
   * red appeared.
   */
  it.each([
    [
      "kb_engine_ref_unknown",
      "The live version cannot be withdrawn",
      "Ask support to withdraw the stale copy on the voice platform first.",
    ],
    [
      "kb_engine_out_of_sync",
      "The voice platform holds knowledge we cannot account for",
      "Ask support to reconcile this agent's knowledge on the voice platform.",
    ],
  ])("hands the operator %s's own cure, not the other one", async (code, title, remediation) => {
    const { container } = await renderHealthy({
      [APPROVED_PATH]: [source()],
      [`POST /v1/admin/tenants/${TENANT}/kb/${source().id}/publish`]: problem(422, {
        type: `https://calevate.tech/problems/${code}`,
        title,
        detail: title,
        kind: "business_rule",
        retryable: false,
        remediation,
      }),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Publish" }));

    await screen.findByText(remediation);
    // The two cures must not be interchangeable on screen either: an operator who reads
    // "reconcile the agent" when the finding was a missing handle goes and deletes a
    // document they matched by eye (runbook §A step 3).
    const other = code === "kb_engine_ref_unknown" ? "reconcile" : "withdraw the stale copy";
    expect(container.textContent).not.toContain(other);
  });

  it("does not offer Publish for a source that is already live", async () => {
    // `publish_source` leaves `status` at 'approved' and flips `is_active`, so a live
    // source stays in this list. A second Publish button over it would re-attach a fresh
    // engine copy of text the agent already has (kb/service.py: `attach_kb` is a CREATE).
    const { container } = await renderHealthy({
      [APPROVED_PATH]: [source({ is_active: true, published_at: "2026-08-14T10:00:00Z" })],
    });

    await screen.findByText("Nothing awaiting approval");
    expect(container.textContent).not.toContain(PANEL);
  });
});
