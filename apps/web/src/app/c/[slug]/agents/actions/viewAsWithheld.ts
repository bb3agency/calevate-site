"use client";

import type { Session } from "@/lib/api/client";
import { useActAccess, useWriteAccess } from "@/lib/api/hooks";

/**
 * The operator's reason when a view-as session may set an action up but may not do `act`
 * to it (`core/rbac.VIEW_AS_WITHHELD_ACTS`: `actions.switch_on`, `actions.test_unapproved`),
 * or null. Null for everyone else too: a staff member's refusal is the ordinary write one
 * the actions screen already shows, so it is not said a second time here.
 */
export function useWithheldFromViewAs(session: Session, act: string, action: string): string | null {
  const write = useWriteAccess(session, "org:manage", action);
  const access = useActAccess(session, "org:manage", act, action);
  return write.allowed && !access.allowed ? access.reason : null;
}

/** Switching an action ON is the owner's (`actions.switch_on`); switching one off is not. */
export function useSwitchOnWithheld(session: Session): string | null {
  return useWithheldFromViewAs(session, "actions.switch_on", "switch an action on");
}
