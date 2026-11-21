import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { businessTypeOption, type BusinessTypes } from "@/lib/businessTypes";
import { examplesFor, type VerticalExamples } from "@/lib/verticalExamples";

/**
 * `GET /v1/public/business-types` as the server builds it, from the same data file
 * (`packages/shared/src/calevate_shared/verticals.json`), so a test holds the web to what
 * actually ships rather than to a second copy of the list.
 */
interface ShippedType {
  key: string;
  label: string;
  hint: string;
  health: boolean;
  fields: unknown[];
  examples?: Record<string, string>;
}

const SHIPPED = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "..", "..", "packages", "shared", "src", "calevate_shared", "verticals.json"),
    "utf8",
  ),
) as { types: ShippedType[] };

export const BUSINESS_TYPES_FIXTURE: BusinessTypes = {
  custom: "custom",
  choices: SHIPPED.types.map((row) => ({
    value: row.key,
    label: row.label,
    hint: row.hint,
    has_standard_set: row.fields.length > 0,
    examples: row.examples ?? null,
  })),
};

/** Every shipped type's key, in picker order. */
export const SHIPPED_TYPE_KEYS: readonly string[] = SHIPPED.types.map((row) => row.key);
/** The types that give health or medical care: the only ones whose words may be clinical. */
export const HEALTH_TYPE_KEYS: readonly string[] = SHIPPED.types
  .filter((row) => row.health)
  .map((row) => row.key);
/** The types with their own examples, plus `custom`, whose examples are the neutral set. */
export const TYPES_WITH_EXAMPLES: readonly string[] = SHIPPED.types
  .filter((row) => row.examples || row.key === "custom")
  .map((row) => row.key);

/** The examples the admin console shows for a stored type. */
export function examplesOf(value: string | null | undefined): VerticalExamples {
  return examplesFor(businessTypeOption(BUSINESS_TYPES_FIXTURE, value));
}
