"use client";

/**
 * Getting a phone number from the client console — browse, buy, point it at an agent.
 *
 * ## Why these shapes are written out rather than generated
 *
 * `apps/api/campaigns/provisioning_routes.py` landed while this console was being built
 * and the OpenAPI snapshot has not been regenerated, so nothing here comes from
 * `schema.d.ts` yet. Every interface below is a transcription of a model in that file —
 * `HolderIn`/`HolderOut`, `OfferedNumberOut`, `PurchaseIn`/`PurchasedNumberOut`,
 * `AssignIn`/`AssignOut` — and the day `pnpm gen:api` runs, these are replaced by the
 * generated ones and the diff is this file alone.
 *
 * ## There is no "can we sell?" endpoint, and the absence is the design
 *
 * `_assert_supply_open()` refuses the search and the purchase with ONE client-facing
 * sentence whichever of our gates is closed, because the shape of an error must not
 * publish which of our papers is missing. So availability is learnt by asking for the
 * numbers: the refusal carries the server's own `detail` and `remediation`, and the
 * screen renders those instead of a reason it invented. `OPERATOR_LED_CODE` is how a
 * screen recognises it.
 *
 * ## The money is the server's digits and nothing here compares them
 *
 * `inr_per_month` is an exact decimal STRING (hard rule 7) and reaches the screen through
 * `formatINR`. Whether a balance covers it is decided by the API —
 * `number_insufficient_credit` — and never by arithmetic in a browser, which is how a
 * screen comes to disagree with the ledger about what an account can afford.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";

/** THE ONE PLACE A ROUTE IS SPELLED — `router = APIRouter(prefix="/v1/numbers")`. */
export const PATHS = {
  holder: "/v1/numbers/holder",
  available: "/v1/numbers/available",
  purchase: "/v1/numbers/purchase",
  assign: (numberId: string) => `/v1/numbers/${numberId}/assign`,
} as const;

/**
 * The refusals this screen reads by name. Each one is a different next action for the
 * client, which is the only reason to distinguish them here.
 */
/** This deployment may not supply numbers. The sentence travels with it. */
export const OPERATOR_LED_CODE = "number_purchase_is_operator_led";
/** The wallet cannot cover the first month — a top-up, not a fault. */
export const INSUFFICIENT_CREDIT_CODE = "number_insufficient_credit";
/** Somebody else took it between the search and the purchase. */
export const NUMBER_TAKEN_CODE = "number_taken";
/** Bought, held, and not usable until the holder's identity is verified. */
export const NOT_ACTIVATED_CODE = "number_not_activated";

/** Whose name the connection is registered in. */
export type HolderType = "individual" | "business";

/** What a number is for. Recorded at purchase and again when it is given to an agent. */
export type CallDirection = "inbound" | "outbound" | "both";

/** `HolderOut` — `recorded: false` before anything has been asked. */
export interface NumberHolder {
  recorded: boolean;
  holder_type: HolderType | null;
  holder_name: string | null;
  holder_email: string | null;
}

/** `HolderIn`. Accepted once; a second attempt is `number_holder_already_recorded`. */
export interface NumberHolderIn {
  holder_type: HolderType;
  holder_name: string;
  holder_email: string;
}

/** `OfferedNumberOut` — priced in rupees at the rate an operator attested. */
export interface OfferedNumber {
  e164: string;
  region: string | null;
  locality: string | null;
  /** DLT's number class, derived from the number's own prefix. */
  series: string;
  inr_per_month: string;
}

/** `PurchasedNumberOut`. `activated` is false while the holder is unverified. */
export interface PurchasedNumber {
  id: string;
  e164: string;
  series: string;
  direction: CallDirection;
  inr_per_month: string;
  activated: boolean;
}

/**
 * `AssignOut` — what the voice platform was TOLD, so a binding that failed is not
 * reported as one that worked.
 */
export interface NumberAssigned {
  number_id: string;
  agent_id: string | null;
  bound: number;
  released: number;
  failed: number;
  unsupported: number;
}

export const numberKeys = {
  holder: (org: string) => ["number-holder", org] as const,
  available: (org: string) => ["numbers-available", org] as const,
};

/**
 * Who every number on this account is registered to, if anyone yet.
 *
 * `enabled` exists for the screen's outer gate: on a deployment that may not sell, the
 * registrant is a permanent record nobody can use, and asking for it spends a request on
 * a question the client will never be shown the answer to.
 */
export function useNumberHolder(
  session: Session,
  enabled = true,
): UseQueryResult<NumberHolder> {
  return useQuery({
    queryKey: numberKeys.holder(session.orgSlug),
    queryFn: () => apiRequest<NumberHolder>(session, PATHS.holder),
    enabled,
  });
}

/** Record the registrant. Once — the API refuses a second one. */
export function useRecordNumberHolder(
  session: Session,
): UseMutationResult<NumberHolder, Error, NumberHolderIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload) =>
      apiRequest<NumberHolder>(session, PATHS.holder, { method: "POST", body: payload }),
    onSuccess: (holder) => {
      client.setQueryData(numberKeys.holder(session.orgSlug), holder);
    },
  });
}

/**
 * What is on offer — and, on a deployment that may not sell, the refusal that says so.
 *
 * `retry: false` because the two answers this can give are a list and a REFUSAL, and
 * retrying `number_purchase_is_operator_led` three times spends three vendor round trips
 * to be told the same thing. The list is the screen's availability check as well as its
 * inventory: there is no separate capability endpoint (see the header).
 */
export function useOfferedNumbers(session: Session): UseQueryResult<OfferedNumber[]> {
  return useQuery({
    queryKey: numberKeys.available(session.orgSlug),
    queryFn: () => apiRequest<OfferedNumber[]>(session, PATHS.available),
    retry: false,
    staleTime: 60_000,
  });
}

/**
 * Buy one number. **SPENDS MONEY ON A RECURRING COMMITMENT AND IS NOT RETRYABLE AT THE
 * VENDOR.**
 *
 * The engine's purchase endpoint takes no key of its own, so the API requires an
 * `Idempotency-Key` and answers a repeat with the first purchase. The key is the
 * CALLER's, held across that attempt's retries: minting one inside `mutationFn` would
 * satisfy the server's validation and protect nobody, which is the defect
 * `hooks.useCallAssist` records in full. It is safe to reuse after a refusal because the
 * API releases the claim on every refusal raised before the vendor is paid
 * (`provisioning_routes.purchase_number`) — so a client told to top up can press again
 * with the same key.
 *
 * `retry: false` is the app-wide default and is restated here because this is the one
 * mutation on the screen where a framework retry would start a second monthly rental.
 */
export function usePurchaseNumber(
  session: Session,
): UseMutationResult<
  PurchasedNumber,
  Error,
  { e164: string; direction: CallDirection; idempotencyKey: string }
> {
  const client = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: ({ e164, direction, idempotencyKey }) =>
      apiRequest<PurchasedNumber>(session, PATHS.purchase, {
        method: "POST",
        idempotencyKey,
        body: { e164, country: "IN", direction },
      }),
    onSuccess: () => {
      // The client's numbers, what is still on offer and the balance behind it all
      // moved. Invalidated rather than patched: what a purchase did to a wallet is the
      // server's arithmetic.
      void client.invalidateQueries({ queryKey: ["campaign-numbers", session.orgSlug] });
      void client.invalidateQueries({ queryKey: numberKeys.available(session.orgSlug) });
      void client.invalidateQueries({ queryKey: ["wallet", session.orgSlug] });
    },
  });
}

/**
 * Point a number at an agent, or at nobody — and tell the voice platform in the same
 * request.
 *
 * This binding is what makes a number the line an agent answers and the caller ID a
 * campaign dials from, so a campaign whose number is bound elsewhere is refused at
 * launch: every campaign check is invalidated with it, broadly rather than by campaign,
 * because this module cannot know which of them dials from this number.
 */
export function useAssignNumber(
  session: Session,
): UseMutationResult<
  NumberAssigned,
  Error,
  { numberId: string; agentId: string | null; direction: CallDirection | null }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ numberId, agentId, direction }) =>
      apiRequest<NumberAssigned>(session, PATHS.assign(numberId), {
        method: "POST",
        body: { agent_id: agentId, direction },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["campaign-numbers", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["campaign-check", session.orgSlug] });
    },
  });
}
