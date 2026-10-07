"use client";

/**
 * What a phone number costs a client per month — read and attested by an operator.
 *
 * `GET`/`POST /v1/admin/number-pricing` (`campaigns/number_pricing_routes.py`). Until a
 * figure is attested the API refuses every client purchase (hard rule 7: a price nobody
 * has read from a document may not reach a bill), so this is the one write that opens
 * self-serve number buying. A rate change is a new attestation, never an edit: numbers
 * already bought keep the figure they were sold at.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

export const NUMBER_PRICING_PATH = "/v1/admin/number-pricing";
export const NUMBER_PRICING_QUERY_KEY = ["admin", "number-pricing"] as const;

export type NumberPrice = Schemas["NumberPriceOut"];
export type NumberPriceIn = Schemas["NumberPriceIn"];

/** The step-up string, copied verbatim from the route that checks it. */
export const ATTEST_NUMBER_PRICE_CONFIRMATION = "attest_number_price";

export function useNumberPrice(): UseQueryResult<NumberPrice> {
  return useQuery({
    queryKey: NUMBER_PRICING_QUERY_KEY,
    queryFn: () => apiRequest<NumberPrice>(adminSession(), NUMBER_PRICING_PATH),
  });
}

export function useAttestNumberPrice() {
  const client = useQueryClient();
  return useMutation({
    // The figure travels as the string the operator typed: `inr_per_month` is a Decimal on
    // the server and a JSON float would round it before validation saw it.
    mutationFn: (body: NumberPriceIn & { inr_per_month: string }) =>
      apiRequest<NumberPrice>(adminSession(), NUMBER_PRICING_PATH, {
        method: "POST",
        body,
        confirmAction: ATTEST_NUMBER_PRICE_CONFIRMATION,
      }),
    onSuccess: (price) => {
      client.setQueryData(NUMBER_PRICING_QUERY_KEY, price);
    },
  });
}
