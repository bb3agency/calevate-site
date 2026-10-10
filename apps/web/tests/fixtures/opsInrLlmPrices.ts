import type { components } from "@/lib/api/schema";

type InrLlmPrices = components["schemas"]["InrLlmPricesOut"];
type InrLlmPrice = components["schemas"]["InrLlmPriceOut"];

/** `GET /v1/ops/inr-llm-prices` as the API publishes it: one rupee-billed model, unconfirmed.
 *  Every screen that renders `ModelPricingPanel` reads it, so every harness stubs it. */
export function inrLlmRow(over: Partial<InrLlmPrice> = {}): InrLlmPrice {
  return {
    model: "sarvam-105b",
    billable: false,
    in_inr_per_mtok: null,
    cached_in_inr_per_mtok: null,
    out_inr_per_mtok: null,
    source_note: null,
    reference_in_inr_per_mtok: "29.28",
    reference_cached_in_inr_per_mtok: "10.98",
    reference_out_inr_per_mtok: "73.20",
    reference_source: "https://www.sarvam.ai/api-pricing",
    reference_read_on: "2026-10-10",
    ...over,
  };
}

export function inrLlmPrices(rows: InrLlmPrice[] = [inrLlmRow()]): InrLlmPrices {
  return { prices: rows, as_of: "2026-10-10T06:30:00Z" };
}

export const OPS_INR_LLM_PRICES = inrLlmPrices();
