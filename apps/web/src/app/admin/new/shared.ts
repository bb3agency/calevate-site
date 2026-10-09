import { ApiProblem } from "@/lib/api/client";
import type { CreateOrgIn } from "@/lib/api/admin";

/**
 * The business types, with what choosing one DOES: it seeds the lead fields the agent
 * collects, which become the client's CRM columns. The values are the API's own enum.
 */
export const VERTICALS: {
  value: CreateOrgIn["vertical_template"];
  label: string;
  hint: string;
}[] = [
  { value: "clinic", label: "Clinic", hint: "Appointments, department, patient name" },
  { value: "real_estate", label: "Real estate", hint: "Budget, locality, site-visit interest" },
  { value: "insurance", label: "Insurance", hint: "Policy type, renewal date, sum assured" },
  { value: "education", label: "Education", hint: "Course, batch, admission stage" },
  { value: "custom", label: "Custom", hint: "Minimal fields — build them by hand" },
];

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

