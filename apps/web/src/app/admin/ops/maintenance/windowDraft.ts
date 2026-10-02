import { formatISTInput, istInputToInstant } from "@/components/ui";
import type { AmendWindowInput, MaintenanceWindow } from "@/lib/api/maintenance";

/** What the amend form holds: each field in the representation its INPUT holds. */
export interface WindowDraft {
  reason: string;
  startsAt: string;
  endsAt: string;
  drain: string;
}

export function draftOf(current: MaintenanceWindow): WindowDraft {
  return {
    reason: current.reason,
    startsAt: formatISTInput(current.starts_at),
    endsAt: formatISTInput(current.ends_at),
    drain: String(current.max_drain_minutes),
  };
}

/**
 * ONLY WHAT MOVED. Each field is compared in the representation the input holds, not
 * against the ISO string on the row: the two differ by formatting after one round trip
 * through `datetime-local`, so comparing against the row would mark an untouched field as
 * changed on every save. A client-visible change re-notifies every client, so a spurious
 * `ends_at` would email the whole fleet because an operator extended the drain.
 *
 * The start is sent only from `scheduled` and only when it moved: the API refuses a start
 * change on a window that has begun, and a form that resent it unchanged would turn every
 * save into that refusal.
 */
export function amendmentOf(
  current: MaintenanceWindow,
  draft: WindowDraft,
): Omit<AmendWindowInput, "windowId"> {
  const original = draftOf(current);
  const movable = current.state === "scheduled";
  return {
    startsAt:
      !movable || draft.startsAt === original.startsAt
        ? undefined
        : (istInputToInstant(draft.startsAt) ?? undefined),
    reason: draft.reason === current.reason ? undefined : draft.reason,
    endsAt:
      draft.endsAt === original.endsAt ? undefined : (istInputToInstant(draft.endsAt) ?? undefined),
    maxDrainMinutes:
      Number(draft.drain) === current.max_drain_minutes ? undefined : Number(draft.drain),
  };
}

export function hasChanges(amendment: Omit<AmendWindowInput, "windowId">): boolean {
  return Object.values(amendment).some((value) => value !== undefined);
}
