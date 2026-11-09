import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, renderHook, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantMembersPage from "@/app/admin/tenants/[tenantId]/members/page";
import { adminSession, type TenantSummary } from "@/lib/api/admin";
import { useRecordTerms } from "@/lib/api/commercials";
import { useRecordRestatement, useRecordTopUp, type Payment } from "@/lib/api/credits";
import { useEndTrial } from "@/lib/api/trials";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { stillLoading, stubApi } from "./harness";

/**
 * Frontend audit lane Y7 (10 Nov 2026): admin account management.
 */

const TENANT = "0192f0aa-1111-7000-8000-000000000007";

function harness() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidated = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const keys = () => invalidated.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
  return { wrapper, keys };
}

const PAID = JSON.stringify(["admin", "paid", TENANT]);
const TRIAL = JSON.stringify(["admin", "trial", TENANT]);

/*
 * Y7-01. A bank transfer recorded on the wallet, or restated up to the minimum, is the
 * account's first payment (`billing/first_payment.on_payment_credited`): the server marks
 * the account paid and converts a running trial. The Credits page shows both, beside the
 * wallet, and kept saying "has not paid yet" and "trial running" after the click.
 */
describe("a payment credited to the wallet", () => {
  it("refreshes the paid status and the trial, which the first payment changes", async () => {
    stubApi({ [`POST /v1/admin/tenants/${TENANT}/credits`]: { recorded: true } });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useRecordTopUp(adminSession(), TENANT), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ amountInr: "5000", paymentRef: "UTR-1", note: null });
    });

    await waitFor(() => expect(keys()).toEqual(expect.arrayContaining([PAID, TRIAL])));
  });

  it("does the same for a restated payment, which counts once stated correctly", async () => {
    stubApi({ [`POST /v1/admin/tenants/${TENANT}/credits/restatements`]: { recorded: true } });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useRecordRestatement(adminSession(), TENANT), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({
        payment: { payment_ref: "UTR-1" } as Payment,
        correctedAmountInr: "5000",
        reason: "bank statement",
      });
    });

    await waitFor(() => expect(keys()).toEqual(expect.arrayContaining([PAID, TRIAL])));
  });
});

/*
 * Y7-01 (second door). Ending a trial as converted stamps the account paid
 * (`trial_routes.close_trial` -> `on_operator_conversion`), and the paid-status panel sits
 * directly above the trial panel.
 */
describe("ending a trial as converted", () => {
  it("refreshes the paid status beside it", async () => {
    stubApi({ [`POST /v1/admin/tenants/${TENANT}/trial/end`]: { status: "converted" } });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useEndTrial(adminSession(), TENANT), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ outcome: "converted", reason: "signed the order" });
    });

    await waitFor(() => expect(keys()).toEqual(expect.arrayContaining([PAID, TRIAL])));
  });
});

/*
 * Y7-02. "Cancel it" in an invitation's row menu cut the owner's live link the moment it
 * was chosen: one mis-tap in a menu, beside "Wrong address?", and the owner's email stops
 * working. Every other row menu on the admin console that ends something asks first.
 */
describe("cancelling an invitation", () => {
  const PEOPLE_TENANT = "0192f0aa-7777-7000-8000-0000000000d7";
  const PEOPLE_PATH = `/v1/admin/tenants/${PEOPLE_TENANT}`;
  const INVITE = {
    id: "0192f0aa-7777-7000-8000-0000000000e1",
    email: "o***@sri-traders.example",
    role: "owner",
    invited_at: "2026-11-09T05:30:00Z",
    expires_at: "2026-11-12T05:30:00Z",
    last_sent_at: "2026-11-09T05:30:00Z",
    send_count: 1,
  };

  async function renderPeople() {
    return renderAdminRoute(<TenantMembersPage params={routeParams({ tenantId: PEOPLE_TENANT })} />, {
      [ADMIN_ME_PATH]: {
        realm: "admin",
        user_id: "0192f0aa-7777-7000-8000-0000000000d2",
        role: "operator",
        permissions: ["org:read", "admin:tenants"],
      } satisfies AdminMe,
      [PEOPLE_PATH]: {
        id: PEOPLE_TENANT,
        name: "Sri Traders",
        slug: "sri-traders",
        status: "onboarding",
        plan_tier: "prepaid",
        vertical_template: "clinic",
        live_agents: 0,
        calls_7d: 0,
        leads: 0,
        last_call_at: null,
        holds: [],
        capped: false,
      } satisfies TenantSummary,
      [`${PEOPLE_PATH}/members`]: [],
      [`${PEOPLE_PATH}/invitations`]: [INVITE],
      [`DELETE ${PEOPLE_PATH}/invitations/${INVITE.id}`]: null,
      [`${PEOPLE_PATH}/whatsapp-alerts`]: stillLoading(),
    });
  }

  it("asks before the link stops working, and cancels only on the second click", async () => {
    const { calls } = await renderPeople();
    await screen.findByText(INVITE.email);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: `More actions for ${INVITE.email}` }));
    });
    const choice = await screen.findByRole("menuitem", { name: "Cancel it" });
    await act(async () => {
      fireEvent.click(choice);
    });

    const dialog = await screen.findByRole("dialog");
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);

    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel the invitation" }));
    });
    await waitFor(() =>
      expect(calls.some((call) => call.method === "DELETE" && call.path.endsWith(INVITE.id))).toBe(true),
    );
  });
});

/*
 * Y7-03. Recording commercial terms re-arms the spend-cap gate in the same transaction
 * (`billing/terms.record_terms` -> `recompute_capped`), in both directions. The "Capped"
 * pill in the account header above the Commercials form, the directory row, the ceilings
 * panel and the health board all kept the state from before the save.
 */
describe("recording commercial terms", () => {
  it("refreshes every read that carries the spend-cap flag", async () => {
    stubApi({ [`POST /v1/admin/tenants/${TENANT}/commercial-terms`]: { changed: true } });
    const { wrapper, keys } = harness();
    const { result } = renderHook(() => useRecordTerms(adminSession(), TENANT), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ terms: {} as never, confirm: null });
    });

    await waitFor(() =>
      expect(keys()).toEqual(
        expect.arrayContaining([
          JSON.stringify(["admin", "commercial-terms", TENANT]),
          JSON.stringify(["admin", "tenant", TENANT]),
          JSON.stringify(["admin", "tenants"]),
          JSON.stringify(["billing-caps"]),
          JSON.stringify(["admin", "client-health"]),
        ]),
      ),
    );
  });
});
