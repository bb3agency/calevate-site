import { ApiProblem } from "@/lib/api/client";
import type { CreateOrgIn } from "@/lib/api/admin";
import { BUSINESS_TYPES } from "@/lib/businessTypes";

/**
 * The business types, with what choosing one DOES: it picks the lead details every call of
 * that business writes down, on top of the ones every business gets. One list, shared with
 * signup and the client's own screens (`lib/businessTypes.ts`).
 */
export const VERTICALS: readonly {
  value: NonNullable<CreateOrgIn["vertical_template"]>;
  label: string;
  hint: string;
}[] = BUSINESS_TYPES;

/**
 * A refusal already received, as a reason to stop offering the control. Only 403: any
 * other refusal is a reason to try again with different input.
 */
export function refusalReason(error: unknown): string | null {
  if (error instanceof ApiProblem && error.status === 403) {
    return error.remediation ?? error.message;
  }
  return null;
}

/** The owner as the operator heard them: who the invitation goes to. */
export interface OwnerDetails {
  name: string;
  email: string;
  phone: string;
}

