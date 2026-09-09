"use client";

import { type Session } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";

/**
 * May this session build a subject access export?
 *
 * `calls:read_raw`, which is `owner` only in the client realm (`core/rbac.py`), and the
 * permission `export_routes.py` chose deliberately: this response is a strictly greater
 * disclosure than any call or lead surface, assembled into one file that then leaves the
 * building.
 *
 * Local and not `useWriteAccess`, on the precedent the call detail screen already set for
 * this exact permission (`useRawTranscriptAccess`): the export is a READ, `calls:read_raw`
 * is not in `MUTATING_PERMISSIONS`, so an impersonating operator is not refused it by the
 * server — and `useWriteAccess`'s impersonation clause would tell them to "do it from the
 * admin console instead", which is advice about a screen that does not exist. Refused
 * while `/v1/me` is in flight so the control never offers an action it is about to
 * withdraw, and a FAILED `/v1/me` says we could not check rather than implying a refusal
 * nobody made.
 */
export function useSubjectExportAccess(session: Session): {
  allowed: boolean;
  reason: string | null;
} {
  const me = useMe(session);
  if (me.error) {
    return {
      allowed: false,
      reason: "We could not check what you are allowed to see. Reload the page to try again.",
    };
  }
  if (!me.data) return { allowed: false, reason: null };
  if (!me.data.permissions.includes("calls:read_raw")) {
    return {
      allowed: false,
      reason:
        "Only an account owner can build a subject access export. Ask them to run it, or to give you owner access.",
    };
  }
  return { allowed: true, reason: null };
}
