import { ApiProblem } from "@/lib/api/client";

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

