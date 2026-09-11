"use client";

import Link from "next/link";
import { useCallback, useRef, useState } from "react";
import {
  ArrowLeft,
  ShieldAlert,
} from "lucide-react";

import {
  Card,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  StatusBadge,
  formatDuration,
  formatIST,
} from "@/components/ui";
import type { CallAudioPlayerHandle } from "@/components/callAudioPlayer";
import { useClientRealm } from "@/lib/api/session";
import {
  useCall,
  useCallBack,
  useCallbackEligibility,
  useWriteAccess,
} from "@/lib/api/hooks";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { AssistCard } from "./AssistCard";
import { DisclosureNotice } from "./DisclosureNotice";
import { KeyMomentsCard } from "./KeyMomentsCard";
import { FollowUpCard } from "./FollowUpCard";
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

  const rawAccess = useRawTranscriptAccess(session);
  const [showRaw, setShowRaw] = useState(false);
  const raw = useRawTranscript(session, callId);
  const recording = useRecordingLink(session, callId);
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

  if (call.isLoading) return <Skeleton rows={8} />;
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

  return (
    <div className="space-y-4 pb-12">
      {/* No <h1>: the app shell renders the page title from the nav list
          (c/[slug]/layout.tsx), and a second heading is how a renamed screen ends up
          arguing with its own header. */}
      <Link
        href={href(`/c/${slug}/calls`)}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
      >
        <ArrowLeft className="h-4 w-4" />
        Call logs
      </Link>

      <Card bodyClassName="p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {/* IN FULL (D-436). Text, never an `href` — see rule 1 above. */}
          <span className="text-lg font-semibold tabular-nums text-ink">
            {detail.caller_e164 ?? "Unknown number"}
          </span>
          <StatusBadge value={detail.status} kind="call" />
          {detail.outcome_tag && (
            <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[11px] font-semibold capitalize text-brand-strong">
              {detail.outcome_tag.replace(/_/g, " ")}
            </span>
          )}
        </div>
        <p className="mt-1.5 text-[13px] text-ink-muted">
          {formatIST(detail.started_at)} · {formatDuration(detail.duration_s)} ·{" "}
          {detail.agent_name ?? "Agent"} · {detail.direction}
          {detail.sentiment ? ` · ${detail.sentiment}` : ""}
        </p>
      </Card>

      <DisclosureNotice played={detail.disclosure_played} />

      {callback.error && <ProblemNotice error={callback.error} />}

      {/* A BENTO GRID, not a column of full-width strips.

          Every panel below is a SHORT fact — a follow-up verdict, a two-sentence
          summary, a handful of captured fields, a recording control — and each was
          rendered as its own full-bleed row. On a desktop that is a metre of
          whitespace to the right of every one of them, and the reader scrolls past
          six screens to reach the transcript. Two columns put the short things side
          by side and cost nothing on a phone, where the grid is one column and the
          order is exactly the DOM order it already had.

          `auto-rows-min` so a card is as tall as its content rather than stretching
          to its neighbour, and `grid-flow-row-dense` because most of these panels are
          CONDITIONAL: with a full-width tile in the middle of the flow, a missing
          card would otherwise leave a hole rather than closing up. Dense flow is safe
          here precisely because these are independent panels — it can reorder them
          visually, and none of them reads as a sequence.

          The two that stay full width earn it: the transcript is long-form reading
          and the assistant is an input people type sentences into, and both are
          worse in a half-width column than a stat card is in a full-width one. */}
      <div className="grid auto-rows-min grid-flow-row-dense gap-4 lg:grid-cols-2">
        <FollowUpCard eligibility={eligibility} callback={callback} write={write} />

        {detail.summary && (
          <Card title="Summary">
            {/* The summary as the API redacted it: it is transcript-DERIVED prose and goes
                through the same `redact()` pass as `text_redacted` (crm/schemas.py). */}
            <p className="text-sm text-ink">{detail.summary}</p>
            {detail.lead_id && (
              <Link
                href={href(`/c/${slug}/leads/${detail.lead_id}`)}
                className="mt-3 inline-block text-sm font-medium text-brand-strong hover:underline"
              >
                View the lead this call created
              </Link>
            )}
          </Card>
        )}

        {/* D-127. Rendered UNCONDITIONALLY, above the transcript and below the summary it
            offers a second reading of — not hidden behind "the extraction failed", because
            the reasons a person wants another reading are not knowable from this row: a
            summary that is thin, a call they are about to ring back, a lead they are
            writing up. The card carries its own refusals; nothing about it depends on a
            read this page has not made. */}
        {/* Full width: this is a prompt box, and a half-column one invites two-word
            questions. `AssistCard` owns its own `Card`, so the span goes on a wrapper. */}
        <div className="lg:col-span-2">
          <AssistCard session={session} callId={callId} />
        </div>

        {Object.keys(detail.extraction ?? {}).length > 0 && (
          <Card title="Captured details">
            {/* These keys are the agent's extraction schema (TRD §7) — the same
                definition that becomes the Leads table columns and the CSV export. */}
            <dl className="grid gap-x-8 gap-y-2 sm:grid-cols-2">
              {Object.entries(detail.extraction as Record<string, unknown>).map(([key, value]) => {
                // A captured field the extractor flagged for a human to confirm before
                // acting on it (today: a phone that is not a standard Indian mobile). The
                // value still shows — it is usable — with an amber note carrying the reason.
                const review = detail.extraction_needs_review?.[key];
                // dt and dd are DIRECT children of the single wrapper div — a <dl> accepts
                // a <div> that groups a dt/dd, but NOT a div nesting another div around them
                // (axe definition-list / dlitem). The review note is a full-width sibling
                // that wraps beneath via flex-wrap.
                return (
                  <div
                    key={key}
                    className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-line py-1.5 text-sm"
                  >
                    <dt className="capitalize text-ink-muted">{key.replace(/_/g, " ")}</dt>
                    <dd className="text-right font-medium text-ink">{formatValue(value)}</dd>
                    {review && (
                      <p className="mt-1 w-full text-xs text-amber-700 dark:text-amber-400">
                        {review}
                      </p>
                    )}
                  </div>
                );
              })}
            </dl>
            {!detail.extraction_valid && (
              <p className="mt-3 text-xs text-amber-700 dark:text-amber-400">
                We could not capture some details cleanly from this call.
              </p>
            )}
          </Card>
        )}

        {detail.has_recording && (
          <RecordingCard
            recording={recording}
            playerRef={playerRef}
            onTimeUpdate={setPlayhead}
            durationS={detail.duration_s ?? null}
          />
        )}

        {detail.moments.length > 0 && (
          <KeyMomentsCard
            moments={detail.moments}
            audioLoaded={audioLoaded}
            playhead={playhead}
            onSeek={seekToMs}
          />
        )}

        <TranscriptCard
          turns={turns}
          showingRaw={showingRaw}
          showRaw={showRaw}
          rawError={raw.error}
          rawPending={raw.isPending}
          onRetryRaw={() => raw.mutate()}
          rawAccess={rawAccess}
          onToggleRaw={toggleRaw}
          audioLoaded={audioLoaded}
          playhead={playhead}
          onSeek={seekToMs}
        />
      </div>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}
