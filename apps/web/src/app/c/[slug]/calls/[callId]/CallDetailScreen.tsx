"use client";

import Link from "next/link";
import { useCallback, useRef, useState } from "react";
import {
  ArrowLeft,
  ShieldAlert,
} from "lucide-react";

import { NoticeBox, ProblemNotice } from "@/components/ui";
import { LiveCallPanel } from "@/components/console/liveCallPanel";
import { LIVE_STATUS } from "@/components/console/liveCalls";
import { useCallSpeaking } from "@/lib/api/callSpeaking";
import type { CallAudioPlayerHandle } from "@/components/callAudioPlayer";
import { useClientRealm } from "@/lib/api/session";
import {
  useCall,
  useCallBack,
  useCallbackEligibility,
  useWriteAccess,
} from "@/lib/api/hooks";
import { MakeCallTest } from "@/components/improvement/MakeCallTest";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { isLive } from "../callColumns";

import { AssistCard } from "./AssistCard";
import { CallDetailSkeleton } from "./CallDetailSkeleton";
import { CallHeader } from "./CallHeader";
import { CallVerdict } from "./CallVerdict";
import { CapturedDetails } from "./CapturedDetails";
import { DisclosureNotice } from "./DisclosureNotice";
import { FollowUpAction } from "./FollowUpAction";
import { KeyMomentsCard } from "./KeyMomentsCard";
import { RecordingCard } from "./RecordingCard";
import { TranscriptCard } from "./TranscriptCard";
import {
  useRawTranscript,
  useRawTranscriptAccess,
  useRecordingLink,
} from "./transcriptAccess";

/**
 * One call, end to end — and the single most sensitive screen in the product, because
 * it is the only one that renders a TRANSCRIPT.
 *
 * PRIMARY JOB: know how the call ended and act on it. So the verdict (outcome, reason,
 * summary, next step, the booked call back and the one action) is first; the recording
 * sits directly above the transcript it plays; captured details, key moments and the
 * assistant's second reading sit beside them on a wide screen and after them on a phone.
 *
 * What this screen must never do, in the order the damage runs:
 *
 * 1. Put a caller's number in a URL. The number itself is rendered IN FULL (D-436) —
 *    it is the client's own contact data and this screen exists to act on it — but an
 *    `href` is a different thing from text: URLs reach browser history, referrers and
 *    access logs, which is hard rule 6's territory and is unchanged. Numbers go in
 *    the DOM and in request BODIES, never in a path or a query string.
 * 2. Show raw transcript text to a session that has not earned it. `text_redacted` is
 *    the default view (hard rule 5); the unredacted one is a SEPARATE endpoint behind
 *    `calls:read_raw` that writes an `audit_log` row in the same transaction as the
 *    read (crm/routes.py). So the control here is gated on that permission, disabled
 *    WITH the reason rather than clicking into a 403, and says out loud that using it
 *    is recorded — a person deciding whether to look should know before they look, not
 *    find out from a compliance review afterwards.
 * 3. Render an empty transcript over a failed read. "This call had no conversation" and
 *    "we could not read this call" send an owner in opposite directions, and only one
 *    of them is true. Loading is a `Skeleton`, failure is a `ProblemNotice`, and the
 *    raw view failing falls BACK to the redacted turns rather than blanking them.
 *
 * Two seams the API had built and this screen ignored are wired here rather than left
 * dangling: `has_recording` (a presigned, short-lived link to OUR copy of the audio —
 * never the engine's URL) and `disclosure_played`, which is the on-screen evidence that
 * the call carried the disclosure line every agent is required to have.
 */


export function CallDetailScreen({ slug, callId }: { slug: string; callId: string }) {
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const call = useCall(session, callId);
  const eligibility = useCallbackEligibility(session, callId);
  const callback = useCallBack(session, callId);
  /**
   * The eligibility QUERY is `leads:read` on purpose — the server made it a read so this
   * button could render disabled with a reason — while the POST behind the button is
   * `leads:dispatch`, which `staff` does not hold. ⚠ IT ALSO SAID the POST is "refused
   * while impersonating" (D-22): D-587 made `leads:dispatch` writable in a view-as
   * session, so an operator now gets a working button and an audit row naming them.
   */
  const write = useWriteAccess(session, "leads:dispatch", "place a follow-up call");
  const testWrite = useWriteAccess(session, "org:manage", "save a call as a test");

  const rawAccess = useRawTranscriptAccess(session);
  const [showRaw, setShowRaw] = useState(false);
  const raw = useRawTranscript(session, callId);
  const recording = useRecordingLink(session, callId);
  /*
   * WHO IS SPEAKING, while the call is live (D-656): an SSE stream opened only for an
   * in-progress call. `session` is the realm's memoised object — a fresh one per render
   * would reopen the stream. `live` turns false when the call ends, and the screen falls
   * back to the post-call view that the 60-second poll fills in.
   */
  const speaking = useCallSpeaking(session, callId, {
    enabled: call.data?.status === LIVE_STATUS,
  });
  /**
   * One press, one request, one audit row — in BOTH directions.
   *
   * Opening always mints a request even if the same transcript was open a moment ago;
   * closing throws the answer away rather than parking it. The access check is repeated
   * here and not only on the disabled button: fail closed, and a control that is disabled
   * for a reason should also be inert for that reason.
   */
  const toggleRaw = () => {
    if (showRaw) {
      setShowRaw(false);
      raw.reset();
      return;
    }
    if (!rawAccess.allowed) return;
    setShowRaw(true);
    raw.mutate();
  };
  // Shared between the two panels: the player publishes where it is, the transcript
  // reads it to highlight the turn being spoken and writes back when a turn is clicked.
  const playerRef = useRef<CallAudioPlayerHandle>(null);
  const [playhead, setPlayhead] = useState<number | null>(null);
  const seekToMs = useCallback((ms: number) => playerRef.current?.seekTo(ms / 1000), []);
  const audioLoaded = recording.data != null;

  /*
   * THIS CALL, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * ABOVE THE §52 BRANCHES because a hook cannot be called conditionally, which is also
   * why every fact below is guarded on `call.data` and the `state` fact says which of the
   * three screens the reader is actually looking at.
   *
   * WHAT IS DELIBERATELY NOT HERE IS MOST OF THIS SCREEN. `caller_e164` is rendered in
   * full at the top (D-436) and does not leave the browser; neither does a single
   * transcript turn, redacted or raw, nor the summary, nor any extracted field value —
   * those are a caller's own words and details, and hard rule 6 plus D-127 G-2 put them
   * out of reach of a US provider whatever the redaction pass would have made of them.
   * What is left is the SHAPE of the call: how long, which way, how it ended, how much
   * transcript there is, and whether the raw view is open. That is enough for "why does
   * this call have no recording" and nowhere near enough to identify anybody.
   */
  useCopilotSurface({
    route: "/c/{slug}/calls/{callId}",
    title: "Call detail",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: call.data
          ? "the call below has loaded"
          : call.error
            ? "the call failed to load"
            : "still loading",
      },
      { key: "call_id", label: "Call id", value: callId },
      ...(call.data
        ? [
            { key: "agent_id", label: "Agent id that handled it", value: call.data.agent_id },
            { key: "direction", label: "Direction", value: call.data.direction },
            { key: "status", label: "Status", value: call.data.status },
            {
              key: "duration_s",
              label: "Length in seconds",
              value: call.data.duration_s == null ? "not recorded" : String(call.data.duration_s),
            },
            { key: "outcome_tag", label: "Outcome tag", value: call.data.outcome_tag ?? "none" },
            { key: "sentiment", label: "Sentiment", value: call.data.sentiment ?? "not scored" },
            {
              key: "disclosure_played",
              label: "Was the AI disclosure played at the start?",
              value:
                call.data.disclosure_played == null
                  ? "not known for this call"
                  : call.data.disclosure_played
                    ? "yes"
                    : "no",
            },
            { key: "has_recording", label: "Is there a recording?", value: call.data.has_recording ? "yes" : "no" },
            { key: "lead_id", label: "Lead id this call belongs to", value: call.data.lead_id ?? "none" },
            {
              key: "extraction_valid",
              label: "Did the captured details pass validation?",
              value: call.data.extraction_valid ? "yes" : "no",
            },
            {
              key: "extraction_needs_review",
              label: "Captured fields flagged for review",
              value: String(Object.keys(call.data.extraction_needs_review ?? {}).length),
            },
            { key: "moments", label: "Marked moments on the timeline", value: String(call.data.moments.length) },
          ]
        : []),
      {
        key: "transcript_turns",
        label: "Transcript turns on screen",
        // The same expression the render below narrows to `turns`, not a second one: the
        // raw view replaces the redacted turns only once the raw read has answered.
        value: String(((showRaw ? raw.data?.transcript : undefined) ?? call.data?.transcript ?? []).length),
      },
      {
        key: "transcript_view",
        label: "Which transcript is showing",
        value:
          showRaw && raw.data?.transcript !== undefined
            ? "the raw one, opened deliberately and audited"
            : "the redacted one",
      },
      { key: "recording_loaded", label: "Is the player loaded?", value: audioLoaded ? "yes" : "no" },
    ],
    apply: noFill,
  });

  if (call.isLoading) return <CallDetailSkeleton />;
  if (call.error) return <ProblemNotice error={call.error} onRetry={() => void call.refetch()} />;
  if (!call.data) {
    // Not an empty state dressed as data: react-query only lands here when the query
    // resolved with nothing, which is a broken premise rather than a call with no
    // content. Say we have nothing rather than describing the call as having none.
    return (
      <NoticeBox tone="neutral" icon={<ShieldAlert className="h-5 w-5" />} title="Nothing to show">
        We could not read this call. Reload the page, or go back to the call log.
      </NoticeBox>
    );
  }

  const detail = call.data;
  // The raw view REPLACES the redacted turns only once the raw request has actually
  // answered. While it is in flight, or if it was refused, the redacted turns stay on
  // screen — a transcript that empties itself while someone waits for a permission
  // check reads as data loss.
  const rawTurns = showRaw ? raw.data?.transcript : undefined;
  const turns = rawTurns ?? detail.transcript ?? [];
  const showingRaw = rawTurns !== undefined;

  const leadHref = detail.lead_id ? href(`/c/${slug}/leads/${detail.lead_id}`) : null;
  const leadName = detail.lead_name?.trim();

  return (
    <div className="max-w-5xl space-y-8 pb-12">
      {/* No <h1>: the app shell renders the page title from the nav list. */}
      <Link
        href={href(`/c/${slug}/calls`)}
        className="inline-flex items-center gap-1.5 rounded-sm text-sm font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 touch:min-h-11"
      >
        <ArrowLeft aria-hidden className="h-4 w-4" />
        Call logs
      </Link>

      <CallHeader detail={detail} />

      {isLive(detail) && (
        <LiveCallPanel
          startedAt={detail.started_at}
          agentName={detail.agent_name ?? null}
          speaker={speaking.live ? speaking.speaker : null}
        />
      )}

      <CallVerdict
        detail={detail}
        action={
          <FollowUpAction
            eligibility={eligibility}
            callback={callback}
            write={write}
            leadHref={leadHref}
            leadLabel={leadName ? `Open ${leadName}'s lead` : "Open the lead"}
          />
        }
      />

      <DisclosureNotice played={detail.disclosure_played} />

      {/* Two columns from `lg`: the conversation is long-form reading and takes the
          width; captured details, key moments and the second reading sit beside it. In
          the DOM the captured details come first, so a phone reads them before the
          transcript, and the rest after it. */}
      <div className="grid items-start gap-10 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-12">
        <div className="lg:col-start-2 lg:row-start-1">
          <CapturedDetails detail={detail} />
        </div>

        <TranscriptCard
          className="lg:col-start-1 lg:row-span-2 lg:row-start-1"
          detail={detail}
          turns={turns}
          showingRaw={showingRaw}
          showRaw={showRaw}
          rawError={raw.error}
          rawPending={raw.isPending}
          onRetryRaw={() => raw.mutate()}
          rawAccess={rawAccess}
          onToggleRaw={toggleRaw}
          player={
            detail.has_recording ? (
              <RecordingCard
                recording={recording}
                playerRef={playerRef}
                onTimeUpdate={setPlayhead}
                durationS={detail.duration_s ?? null}
                moments={detail.moments}
              />
            ) : null
          }
          noRecording={!detail.has_recording && detail.status === "completed"}
          audioLoaded={audioLoaded}
          playhead={playhead}
          onSeek={seekToMs}
        />

        <aside aria-label="More about this call" className="space-y-8 lg:col-start-2 lg:row-start-2">
          {detail.moments.length > 0 && (
            <KeyMomentsCard
              moments={detail.moments}
              audioLoaded={audioLoaded}
              playhead={playhead}
              onSeek={seekToMs}
            />
          )}
          {detail.status === "completed" && turns.length > 0 && (
            <MakeCallTest callId={callId} canWrite={testWrite.allowed} />
          )}
          {/* D-127: always offered, whatever the stored summary looks like; it carries
              its own refusals and changes nothing already saved. */}
          <AssistCard session={session} callId={callId} />
        </aside>
      </div>
    </div>
  );
}
