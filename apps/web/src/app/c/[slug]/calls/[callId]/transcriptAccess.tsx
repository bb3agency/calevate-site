"use client";

import { useMutation } from "@tanstack/react-query";
import { Download, Eye, EyeOff } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ApiProblem, apiRequest, type CallDetail, type Session } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useMe } from "@/lib/api/hooks";

/**
 * THE UNREDACTED TRANSCRIPT AND THE RECORDING — the audited reads on this screen,
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
      {/* THE REASON IS NOT HERE ANY MORE, and its absence is the fix rather than a
          regression. It was a `hidden … sm:inline` span in this row, so the ONE reader
          the doctrine designs for — a small-business owner on a mid-range Android phone
          (§8.6) — met a greyed control with nothing beside it and no way to reach the
          `title` either: a disabled button takes no focus and a touch screen has no
          hover. It now renders in the card body as a `RestrictionNote`
          (`TranscriptCard`), at every width, which is §4's "on the control AND on the
          screen". Two spellings of one sentence in one card would be the §5 defect, so
          there is one, and this row keeps only the `title`. */}
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
            ? "Shows the full text, personal details included."
            : (access.reason ?? undefined)
        }
        className="press inline-flex shrink-0 items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink-muted enabled:hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 touch:min-h-11 dark:enabled:hover:bg-white/5"
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

/**
 * Saving the recording — the third audited read on this screen, with its own audit action
 * (`recording.download`) so "who took a copy away" is answerable apart from "who listened".
 *
 * The link is minted on the press, lives five minutes, and is handed to a throwaway anchor
 * that is clicked and removed at once: the server signs it as an attachment with the file's
 * name, so the browser saves it without leaving the page, and the signed URL is never left
 * in the DOM or in history.
 */
export function useRecordingDownload(session: Session, callId: string) {
  return useMutation({
    mutationFn: () =>
      apiRequest<components["schemas"]["RecordingDownloadOut"]>(
        session,
        `/v1/calls/${callId}/recording/download`,
      ),
    onSuccess: ({ url, filename }) => {
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.rel = "noopener";
      document.body.appendChild(link);
      link.click();
      link.remove();
    },
  });
}

/**
 * The words for a download that did not happen: the refusal's own sentence whenever one
 * arrived. "Try again in a moment" is only true of a failure that never reached a reason;
 * said over a refusal (no recording, a role that lost access) it sends the person round
 * a loop that cannot succeed.
 */
function downloadRefusal(error: unknown): string {
  if (error instanceof ApiProblem) return error.message;
  return "The recording could not be downloaded just now. Try again in a moment.";
}

/** "Download recording", beside the player's speed and volume. Owner-only, like playing. */
export function DownloadRecordingButton({ session, callId }: { session: Session; callId: string }) {
  const download = useRecordingDownload(session, callId);
  // The refusal is said under the button (`downloadRefusal`), so it is not toasted too.
  const feedback = useActionFeedback(download, { errorDisplay: "inline" });
  return (
    <>
      <ActionButton
        variant="secondary-sm"
        status={feedback.status}
        pendingLabel="Preparing…"
        successLabel="Downloaded"
        onClick={() => feedback.run()}
        aria-label="Download recording"
        title="Download recording"
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        Download
      </ActionButton>
      {download.error != null && (
        <p role="alert" className="basis-full text-meta text-warn">
          {downloadRefusal(download.error)}
        </p>
      )}
    </>
  );
}
