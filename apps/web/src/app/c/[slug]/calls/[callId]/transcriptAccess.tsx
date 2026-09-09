"use client";

import { useMutation } from "@tanstack/react-query";
import { Eye, EyeOff } from "lucide-react";

import { apiRequest, type CallDetail, type Session } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useMe } from "@/lib/api/hooks";

/**
 * THE UNREDACTED TRANSCRIPT AND THE RECORDING — the two audited reads on this screen,
 * with the control that offers the first and the permission check behind both.
 *
 * One subject, one file: both are GETs with a side effect, both write an `audit_log` row,
 * and both are therefore mutations rather than queries (see `useRawTranscript`). Keeping
 * them together is what stops the next reader treating one of them as a cache-able read.
 */

/**
 * The control that reveals the unredacted transcript — refused before the click.
 *
 * The doctrine this app already follows for dispatch, for the CSV export and for D-22
 * impersonation: a gated action renders disabled WITH the reason beside it, because an
 * answer given before the click beats a 403 dressed as a fault after it. The server
 * still refuses either way; this is a preview of its answer, never a substitute.
 */
export function RawTranscriptControl({
  access,
  showRaw,
  pending,
  onToggle,
}: {
  access: RawTranscriptAccess;
  showRaw: boolean;
  pending: boolean;
  onToggle: () => void;
}) {
  const Icon = showRaw ? EyeOff : Eye;
  return (
    <div className="flex items-center gap-3">
      {!access.allowed && access.reason && (
        <span className="hidden text-xs text-ink-faint sm:inline">{access.reason}</span>
      )}
      <button
        type="button"
        // Enabled while `pending`: someone who pressed this and changed their mind must
        // be able to press it again. Disabling mid-flight strands them on a request
        // they no longer want, which for THIS request means waiting for personal data
        // to arrive on screen.
        disabled={!access.allowed}
        aria-pressed={showRaw}
        onClick={onToggle}
        title={
          access.allowed
            ? "Shows the full text, personal details included. Opening it is recorded in your audit log."
            : (access.reason ?? undefined)
        }
        className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink-muted hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/5"
      >
        <Icon className="h-3.5 w-3.5" />
        {pending ? "Opening…" : showRaw ? "Hide full transcript" : "Show full transcript"}
      </button>
    </div>
  );
}

export interface RawTranscriptAccess {
  allowed: boolean;
  /** Why not, in the client's words. Null while we do not yet know. */
  reason: string | null;
}

/**
 * May this session open the unredacted transcript?
 *
 * Read off `/v1/me` — the SERVER's answer about this session — rather than from a
 * hardcoded role list, and starts REFUSED while the answer is in flight, so the control
 * never offers an action it is about to withdraw. `calls:read_raw` is `owner` only in
 * the client realm; an impersonating operator does not hold it either (core/rbac.py),
 * so the permission check covers D-22 without a second condition.
 *
 * `useWriteAccess` was the obvious reuse and is the wrong tool: this read is not a
 * mutation, so its impersonation clause ("do it from the admin console instead") would
 * give an operator advice that does not apply.
 */
export function useRawTranscriptAccess(session: Session): RawTranscriptAccess {
  const me = useMe(session);
  if (me.error) {
    return {
      allowed: false,
      reason: "We could not check what you are allowed to see. Reload the page to try again.",
    };
  }
  if (!me.data) return { allowed: false, reason: null };
  if (!me.data.permissions.includes("calls:read_raw")) {
    return { allowed: false, reason: "Only an account owner can open the full transcript." };
  }
  return { allowed: true, reason: null };
}

/**
 * The unredacted transcript — a GET WITH A SIDE EFFECT, and therefore a MUTATION.
 *
 * `/v1/calls/{id}/transcript/raw` writes an `audit_log` row in the same transaction as
 * the read (crm/routes.py). Hard rule 5 and SURFACES §3.1 are explicit about what that
 * row is for: "who opened this transcript" has to be answerable, and it is a question a
 * DPDP enquiry asks about EVERY opening, not the first one.
 *
 * This was a `useQuery` with `staleTime: Infinity` and all three implicit refetches off.
 * Those options were the right answer to the wrong half of the problem — they correctly
 * stopped the library re-exposing personal data on a window focus or a reconnect, and
 * they also stopped a DELIBERATE second opening from being a request. Press "Show", press
 * "Hide", press "Show": the unredacted text came back out of the cache with no network
 * call and no second audit row. Same for navigating to another call and back inside
 * `gcTime`. The audit trail recorded the first read of a raw transcript and under-reported
 * every one after it.
 *
 * A mutation is not a workaround for the cache, it is the accurate description: this
 * request CHANGES SERVER STATE, so it has no business in a cache keyed by what it reads.
 * `useMutation` gives exactly the semantics the options above were approximating — never
 * deduplicated, never refetched on its own, never restored from cache — and it is already
 * how the sibling audited read on this same screen works (`useRecordingLink` below). One
 * rule, one mechanism.
 *
 * The second thing it buys: `reset()` on "Hide" actually DROPS the unredacted turns.
 * `enabled: false` kept the observer subscribed, so the personal data stayed in the JS
 * heap for the life of the page after the reader had said they were done with it.
 *
 * No `retry` for the reason the query gave: a 403 must surface once, not three times.
 * TanStack Query v5 defaults mutations to `retry: 0`, so this is the default rather than
 * an override (https://tanstack.com/query/v5/docs/framework/react/guides/mutations).
 */
export function useRawTranscript(session: Session, callId: string) {
  return useMutation({
    mutationFn: () => apiRequest<CallDetail>(session, `/v1/calls/${callId}/transcript/raw`),
  });
}

export function useRecordingLink(session: Session, callId: string) {
  return useMutation({
    mutationFn: () =>
      apiRequest<components["schemas"]["RecordingLinkOut"]>(
        session,
        `/v1/calls/${callId}/recording`,
      ),
  });
}
