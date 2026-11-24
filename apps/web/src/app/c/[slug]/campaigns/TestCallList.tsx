"use client";

/**
 * THE TEST CALLS THIS CAMPAIGN MADE, under the Test call form (founder, 16 Nov 2026): when,
 * how long, how it went, its recording to play, the call's own page, and a way to take it
 * off the list. Taking one off leaves the call in the call logs, where its recording is
 * erased on the account's usual schedule; nothing here deletes a recording.
 *
 * The recording plays through the same short-lived, audited link the call page uses
 * (`/v1/calls/{id}/recording`), minted on the press rather than for every row.
 */

import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import { PhoneOff, Play, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { CallAudioPlayer } from "@/components/callAudioPlayer";
import { ConfirmDialog } from "@/components/confirmDialog";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice, SECONDARY_BUTTON_SM, formatIST } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import {
  useCampaignTestCalls,
  useEndCampaignTestCall,
  useRemoveCampaignTestCall,
  type CampaignTestCallItem,
} from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";

import { useRecordingLink } from "../calls/[callId]/transcriptAccess";

const STATUS_WORDS: Record<string, string> = {
  queued: "Calling…",
  ringing: "Ringing…",
  in_progress: "On the call",
  completed: "Answered",
  no_answer: "Not answered",
  busy: "Busy",
  voicemail: "Voicemail",
  failed: "Did not connect",
};

/** Still on the line: End call is offered. */
const LIVE = ["queued", "ringing", "in_progress"];

function length(seconds: number | null): string {
  if (seconds == null) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function TestCallList({
  slug,
  campaignId,
  canWrite,
  refusal,
}: {
  slug: string;
  campaignId: string;
  canWrite: boolean;
  refusal?: string;
}) {
  const { session } = useClientRealm();
  const calls = useCampaignTestCalls(session, campaignId);
  const remove = useRemoveCampaignTestCall(session, campaignId);
  const end = useEndCampaignTestCall(session, campaignId);
  useActionFeedback(end, { errorTitle: "Could not end the call", successToast: "Call ended" });
  return (
    <TestCallRows slug={slug} calls={calls} remove={remove} end={end} canWrite={canWrite} refusal={refusal} />
  );
}

/**
 * The list itself, for a campaign's test calls or an inbound line's. `remove` takes one off
 * the list; a screen with no such list to edit leaves it out and offers no Delete. `end`
 * hangs up a call still on the line; without it no End call is offered.
 */
export function TestCallRows({
  slug,
  calls,
  remove,
  end,
  canWrite,
  refusal,
}: {
  slug: string;
  calls: UseQueryResult<CampaignTestCallItem[]>;
  remove?: UseMutationResult<void, Error, string>;
  end?: UseMutationResult<void, Error, string>;
  canWrite: boolean;
  refusal?: string;
}) {
  if (calls.error || !calls.data) {
    return calls.error ? <ProblemNotice error={calls.error} onRetry={() => calls.refetch()} /> : null;
  }
  const items = calls.data;
  if (items.length === 0) return null;
  return (
    <div className="mt-5 border-t border-line pt-4">
      <h3 className="text-body font-semibold text-ink">Your test calls</h3>
      <ul className="mt-2 divide-y divide-line">
        {items.map((call) => (
          <TestCallRow
            key={call.call_id}
            slug={slug}
            call={call}
            remove={remove}
            end={end}
            canWrite={canWrite}
            refusal={refusal}
          />
        ))}
      </ul>
    </div>
  );
}

function TestCallRow({
  slug,
  call,
  remove,
  end,
  canWrite,
  refusal,
}: {
  slug: string;
  call: CampaignTestCallItem;
  remove?: UseMutationResult<void, Error, string>;
  end?: UseMutationResult<void, Error, string>;
  canWrite: boolean;
  refusal?: string;
}) {
  const { session, href } = useClientRealm();
  const link = useRecordingLink(session, call.call_id);
  useActionFeedback(link, { errorDisplay: "inline" });
  // As on the call's own page (`RecordingCard`): a re-mint clears `link.data`, so the last
  // link is held or the player unmounts mid-play, and one re-mint per row, whose failure is
  // the player's own refusal rather than an unhandled rejection.
  const lastLink = useRef(link.data);
  if (link.data) lastLink.current = link.data;
  const recording = link.data ?? lastLink.current;
  const remints = useRef(0);
  const remint = async (): Promise<string | null> => {
    if (remints.current >= 1) return null;
    remints.current += 1;
    try {
      return (await link.mutateAsync()).url ?? null;
    } catch {
      return null;
    }
  };
  // One End mutation serves every row, so its state counts only for the row it ended.
  const mine = end?.variables === call.call_id;
  const ending = mine && end?.isPending === true;
  const live = end != null && LIVE.includes(call.status) && !(mine && end.isSuccess);
  const words = lookup(STATUS_WORDS, call.status) ?? call.status;

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-body text-ink">{formatIST(call.placed_at)}</span>
        <span className="text-meta text-ink-muted">
          {words}
          {call.duration_s ? ` · ${length(call.duration_s)}` : ""}
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-2">
          {call.has_recording && !recording && (
            <ActionButton
              variant="secondary-sm"
              status={link.isPending ? "pending" : "idle"}
              pendingLabel="Opening…"
              onClick={() => link.mutate()}
            >
              <Play aria-hidden className="h-3.5 w-3.5" />
              Play recording
            </ActionButton>
          )}
          {live && (
            <button
              type="button"
              className={`${SECONDARY_BUTTON_SM} border-danger text-danger`}
              disabled={!canWrite || ending}
              title={refusal}
              onClick={() => end.mutate(call.call_id)}
              aria-label={`End the test call of ${formatIST(call.placed_at)}`}
            >
              <PhoneOff aria-hidden className="h-3.5 w-3.5" />
              {ending ? "Ending…" : "End call"}
            </button>
          )}
          <Link
            href={href(`/c/${slug}/calls/${call.call_id}`)}
            className="inline-flex items-center text-meta text-brand-strong underline touch:min-h-11"
          >
            Open the call
          </Link>
          {remove ? <RemoveTestCall call={call} remove={remove} canWrite={canWrite} refusal={refusal} /> : null}
        </span>
      </div>
      {link.error != null && (
        <div className="mt-2">
          <ProblemNotice error={link.error} />
        </div>
      )}
      {recording && (
        <div className="mt-3">
          <CallAudioPlayer
            src={recording.url}
            fallbackDurationS={call.duration_s}
            onExpired={remint}
          />
        </div>
      )}
    </li>
  );
}

function RemoveTestCall({
  call,
  remove,
  canWrite,
  refusal,
}: {
  call: CampaignTestCallItem;
  remove: UseMutationResult<void, Error, string>;
  canWrite: boolean;
  refusal?: string;
}) {
  // Every row watches the one shared mutation, so only the row whose call was removed says so.
  const removeFeedback = useActionFeedback(remove, {
    errorDisplay: "inline",
    successToast: (_data, id) => (id === call.call_id ? "Test call removed" : null),
  });
  const [confirming, setConfirming] = useState(false);
  return (
    <>
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={!canWrite}
        title={refusal}
        onClick={() => setConfirming(true)}
        aria-label={`Delete the test call of ${formatIST(call.placed_at)}`}
      >
        <Trash2 aria-hidden className="h-3.5 w-3.5" />
        Delete
      </button>
      {confirming && (
        <ConfirmDialog
          title="Delete this test call?"
          confirmLabel="Delete"
          pendingLabel="Deleting"
          cancelLabel="Keep it"
          status={removeFeedback.status}
          error={removeFeedback.error ?? null}
          onCancel={() => {
            removeFeedback.reset();
            setConfirming(false);
          }}
          onConfirm={() => remove.mutate(call.call_id, { onSuccess: () => setConfirming(false) })}
        >
          <span className="block">It comes off this list. The call stays in your call logs.</span>
        </ConfirmDialog>
      )}
    </>
  );
}
