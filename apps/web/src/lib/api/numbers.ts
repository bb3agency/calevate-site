/**
 * Buying, linking and releasing a phone number — the operator's half of D-537.
 *
 * ## Why these are not in `admin.ts`
 *
 * Every hook in that file is about a client's RECORD. These spend money at a vendor on a
 * recurring commitment, and one of them cannot be undone by retrying — the vendor's
 * purchase endpoint takes no idempotency key, so a repeat buys a second number and starts
 * a second monthly rental. A caller reaching for `useBuyNumber` should have to import it
 * from a file whose name says what it does.
 *
 * ## The price is the vendor's, in USD, and is never converted here
 *
 * The server publishes the vendor's own quote in the vendor's own currency; the rupee is
 * struck once, monthly, when the rental is metered, at that month's published rate. A
 * conversion in the browser would put a second exchange rate on a screen that would not
 * match the ledger, and a screen that disagrees with the ledger about money is worse than
 * one that shows the source figure.
 *
 * ## `monthly_price_usd` travels from the search into the purchase
 *
 * It is the operator's ACCEPTANCE of a quoted price, not a re-fetch: the vendor's buy
 * response carries a one-off price and a renewal flag and no recurring figure at all, so
 * this is the only path by which the recurring cost gets a value. An offer with no price
 * cannot be bought, and the screen says so rather than offering a button that refuses.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

export type AvailableNumber = components["schemas"]["AvailableNumberOut"];
export type TenantNumberCost = components["schemas"]["TenantNumberCostOut"];
export type BoughtNumber = components["schemas"]["BoughtNumberOut"];

/** What the voice platform could sell us. Read-only, spends nothing, still gated. */
export function useAvailableNumbers(
  country: "IN" | "US",
  pattern: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["admin", "available-numbers", country, pattern],
    queryFn: () => {
      const query = new URLSearchParams({ country });
      if (pattern) query.set("pattern", pattern);
      return apiRequest<AvailableNumber[]>(
        adminSession(),
        `/v1/admin/numbers/available?${query.toString()}`,
      );
    },
    // MANUAL, never on mount. A search is a vendor round trip on a rate-limited account,
    // and a screen that fired one every time an operator opened a client would spend that
    // budget on a question nobody asked.
    enabled,
    staleTime: 60_000,
    retry: false,
  });
}

/** This client's numbers, whether we bought them, and what each costs US. */
export function useTenantNumberCosts(tenantId: string) {
  return useQuery({
    queryKey: ["admin", "number-costs", tenantId],
    queryFn: () =>
      apiRequest<TenantNumberCost[]>(adminSession(), `/v1/admin/numbers/tenants/${tenantId}`),
    enabled: Boolean(tenantId),
  });
}

/** **SPENDS MONEY AND IS NOT RETRYABLE.** `retry: false` is a correctness property here,
 * not a preference: the default retry ladder would buy a second number on a timeout. */
export function useBuyNumber(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: (payload: {
      e164: string;
      country: "IN" | "US";
      provider: string | null;
      monthly_price_usd: string;
    }) =>
      apiRequest<BoughtNumber>(adminSession(), `/v1/admin/numbers/tenants/${tenantId}/buy`, {
        method: "POST",
        body: payload,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["admin", "number-costs"] });
      void client.invalidateQueries({ queryKey: ["admin", "numbers"] });
      void client.invalidateQueries({ queryKey: ["admin", "available-numbers"] });
    },
  });
}

/**
 * Record the voice platform's own handle for a number the CLIENT brought.
 *
 * Without it an agent set to answer that number will not — the publish reports success and
 * the phone does not ring, which is the state every number on this platform was in before
 * D-537. The response says what the platform was told, so the screen can report a bind
 * that failed rather than implying one that did not happen.
 */
export function useSetNumberEngineRef(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ numberId, ref }: { numberId: string; ref: string }) =>
      apiRequest<components["schemas"]["EngineRefOut"]>(
        adminSession(),
        `/v1/admin/numbers/tenants/${tenantId}/${numberId}/engine-ref`,
        { method: "POST", body: { engine_number_ref: ref } },
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["admin", "number-costs"] });
      void client.invalidateQueries({ queryKey: ["admin", "numbers"] });
    },
  });
}

/** Give a bought number back and stop the monthly rental. Offboarding only. */
export function useReleaseNumber(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (numberId: string) =>
      apiRequest<void>(
        adminSession(),
        `/v1/admin/numbers/tenants/${tenantId}/${numberId}/release`,
        { method: "POST" },
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["admin", "number-costs"] });
      void client.invalidateQueries({ queryKey: ["admin", "numbers"] });
    },
  });
}
