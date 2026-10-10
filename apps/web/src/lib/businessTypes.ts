import type { components } from "@/lib/api/schema";
import { lookup } from "@/lib/lookup";

/**
 * THE BUSINESS TYPES, as every picker names them — the one list (founder decisions 10 and
 * 15, 10 Oct 2026).
 *
 * The values are the API's own enum (`admin/routes.Vertical`), so a type the server stops
 * accepting fails the build here. The labels are the server's too
 * (`scripts/seed.BUSINESS_TYPE_LABELS`, the order included); `tests/businessTypes.test.ts`
 * holds the two to each other's order, and the order does not start with a clinic because
 * no trade is anybody's default.
 *
 * `hint` says what choosing the type DOES: it picks the details every lead of that
 * business captures on top of the ones every business gets.
 */
export type BusinessType = NonNullable<components["schemas"]["CreateOrgIn"]["vertical_template"]>;

export interface BusinessTypeOption {
  value: BusinessType;
  label: string;
  hint: string;
}

export const BUSINESS_TYPES: readonly BusinessTypeOption[] = [
  { value: "retail", label: "Shop, food or produce", hint: "Product, quantity, pickup or delivery" },
  {
    value: "local_services",
    label: "Salon or local service",
    hint: "Service wanted, at the shop or at home, preferred staff",
  },
  {
    value: "automobile",
    label: "Automobile or repairs",
    hint: "Vehicle, work needed, registration, pickup",
  },
  { value: "clinic", label: "Clinic or health", hint: "Reason for the visit, urgency, preferred doctor" },
  { value: "real_estate", label: "Real estate", hint: "Budget, locality, size, site visit" },
  { value: "insurance", label: "Insurance", hint: "Policy type, cover, renewal date" },
  { value: "education", label: "Education or coaching", hint: "Course, class or year, demo class" },
  {
    value: "custom",
    label: "Something else",
    hint: "Details drafted once from the business's own details",
  },
];

const LABELS: Readonly<Record<BusinessType, string>> = Object.fromEntries(
  BUSINESS_TYPES.map((option) => [option.value, option.label]),
) as Record<BusinessType, string>;

/** How a stored business type reads; an absent or unknown one reads as "Something else". */
export function businessTypeLabel(value: string | null | undefined): string {
  return lookup(LABELS, value) ?? LABELS.custom;
}
