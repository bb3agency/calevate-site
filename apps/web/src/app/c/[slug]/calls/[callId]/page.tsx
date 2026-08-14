"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  AudioLines,
  Bot,
  Eye,
  EyeOff,
  PhoneForwarded,
  ShieldAlert,
  ShieldCheck,
  User,
} from "lucide-react";

import {
  Card,
  EmptyState,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  StatusBadge,
  formatDuration,
  formatIST,
} from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { apiRequest, type CallDetail, type Session } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useCall, useCallBack, useCallbackEligibility, useMe, useWriteAccess } from "@/lib/api/hooks";
import { lookup } from "@/lib/lookup";

/**
 * One call, end to end — and the single most sensitive screen in the product, because
 * it is the only one that renders a TRANSCRIPT.
 *
 * What this screen must never do, in the order the damage runs:
 *
 * 1. Print a caller's number. `caller_masked` is the only form the API sends and the
 *    only form allowed in the DOM or in an `href` (hard rule 6). URLs reach browser
 *    history, referrers and access logs, so the rule is stricter for a link than for
 *    text.
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

/**
 * Who said it, and how the turn is dressed.
 *
 * `speaker` is a two-value union in the generated types, but it is a string the SERVER
 * chose at runtime and a union is a claim this build makes, not one the server is bound
 * by — so it is read with `lookup` and falls back VISIBLY: an unrecognised speaker keeps
 * its turn on screen with its own name printed, because a transcript line we cannot
 * attribute is the last thing that should silently vanish.
 */
const SPEAKERS: Record<string, { label: string; icon: typeof Bot; medallion: string }> = {
  agent: { label: "Agent", icon: Bot, medallion: "bg-brand-soft text-brand-strong" },
  caller: { label: "Caller", icon: User, medallion: "bg-black/5 text-ink-muted dark:bg-white/10" },
};

export default function CallDetailPage({
  params,
}: {
  params: Promise<{ slug: string; callId: string }>;
}) {
  const { slug, callId } = use(params);
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const call = useCall(session, callId);
  const eligibility = useCallbackEligibility(session, callId);
  const callback = useCallBack(session, callId);
  /**
   * D-22 read-only. The eligibility QUERY is `leads:read` on purpose — the server made
   * it a read so this button could render disabled with a reason — but the POST behind
   * the button is `leads:dispatch`, which is mutating and refused while impersonating.
   * Without this the eligibility check says "yes" to an operator and the click rings
   * nobody, which is the exact failure the eligibility query was introduced to remove.
   */
  const write = useWriteAccess(session, "leads:dispatch", "place a follow-up call");

  const rawAccess = useRawTranscriptAccess(session);
  const [showRaw, setShowRaw] = useState(false);
  const raw = useRawTranscript(session, callId, showRaw && rawAccess.allowed);
  const recording = useRecordingLink(session, callId);

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

      <Card bodyClassName="p-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {/* MASKED, always. The API sends no other form to this screen, and no other
              form may reach the DOM (hard rule 6). */}
          <span className="text-lg font-semibold tabular-nums text-ink">
            {detail.caller_masked ?? "Unknown number"}
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

      {/* D-21 M2. Rendered whenever the API has an opinion — disabled WITH the reason
          rather than hidden, so "why can't I follow this up?" is answered on screen.
          The refusals are mostly protective (we have already followed up twice; the
          call is a fortnight old), and a client who cannot see them assumes a bug. */}
      {eligibility.data && (
        <Card title="Follow up">
          {callback.data?.status === "queued" ? (
            <NoticeBox tone="ok" icon={<PhoneForwarded className="h-5 w-5" />}>
              Calling back now — follow-up #{callback.data.follow_up_number}. It will appear in
              your call log in a moment.
            </NoticeBox>
          ) : callback.data?.status === "blocked" ? (
            /* A refusal by the compliance gate comes back 200 with a reason, not as an
               error. Falling through to the enabled button rendered it as a no-op: the
               client presses "Call back", nothing visibly happens, and they press it
               again. The server has already recorded the answer against this call, so
               it says why instead of offering another attempt. */
            <NoticeBox tone="warn" icon={<ShieldAlert className="h-5 w-5" />}>
              {callback.data.blocked_reason ?? "This follow-up call was not allowed."}
              {callback.data.blocked_rule ? ` (${callback.data.blocked_rule})` : ""}
            </NoticeBox>
          ) : eligibility.data.eligible && write.allowed ? (
            <div className="space-y-3">
              <p className="text-sm text-ink-muted">
                Our agent will call back and pick up where this conversation stopped.
              </p>
              <button
                type="button"
                disabled={callback.isPending}
                onClick={() => callback.mutate()}
                className="inline-flex items-center gap-2 rounded-md bg-brand-strong px-4 py-2 text-sm font-semibold text-white hover:bg-brand disabled:cursor-not-allowed disabled:opacity-50"
              >
                <PhoneForwarded className="h-4 w-4" />
                {callback.isPending ? "Calling…" : "Call back with AI"}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Two different refusals, one presentation. The server's eligibility
                  reason ("we have already followed this up twice") and D-22's
                  read-only both end in the same dead button, and both belong NEXT to
                  it — the eligibility query exists so this button never answers with a
                  403, and the read-only sweep would have reintroduced exactly that. */}
              <p className="text-sm text-ink-muted">
                {eligibility.data.eligible
                  ? (write.reason ?? "Checking what you can do in this account…")
                  : eligibility.data.reason}
              </p>
              <button
                type="button"
                disabled
                className="inline-flex cursor-not-allowed items-center gap-2 rounded-md border border-line bg-surface px-4 py-2 text-sm font-semibold text-ink-faint"
              >
                <PhoneForwarded className="h-4 w-4" />
                Call back with AI
              </button>
            </div>
          )}
        </Card>
      )}

      {detail.summary && (
        <Card title="Summary">
          {/* The summary as the API redacted it: it is transcript-DERIVED prose and goes
              through the same `redact()` pass as `text_redacted` (crm/schemas.py). */}
          <p className="text-sm text-ink">{detail.summary}</p>
          {detail.lead_id && (
            <Link
              href={href(`/c/${slug}/leads`)}
              className="mt-3 inline-block text-sm font-medium text-brand-strong hover:underline"
            >
              View the lead this call created
            </Link>
          )}
        </Card>
      )}

      {Object.keys(detail.extraction ?? {}).length > 0 && (
        <Card title="Captured details">
          {/* These keys are the agent's extraction schema (TRD §7) — the same
              definition that becomes the Leads table columns and the CSV export. */}
          <dl className="grid gap-x-8 gap-y-2 sm:grid-cols-2">
            {Object.entries(detail.extraction as Record<string, unknown>).map(([key, value]) => (
              <div key={key} className="flex justify-between gap-4 border-b border-line py-1.5 text-sm">
                <dt className="capitalize text-ink-muted">{key.replace(/_/g, " ")}</dt>
                <dd className="text-right font-medium text-ink">{formatValue(value)}</dd>
              </div>
            ))}
          </dl>
          {!detail.extraction_valid && (
            <p className="mt-3 text-xs text-amber-700 dark:text-amber-400">
              Some fields could not be captured cleanly from this call.
            </p>
          )}
        </Card>
      )}

      {detail.has_recording && <RecordingCard recording={recording} />}

      <Card
        title="Transcript"
        action={
          <RawTranscriptControl
            access={rawAccess}
            showRaw={showRaw}
            pending={showRaw && raw.isFetching && !raw.data}
            onToggle={() => setShowRaw((on) => !on)}
          />
        }
      >
        <div className="space-y-4">
          {/* The state of the transcript in front of you, said before you read it.
              Hard rule 5 is invisible otherwise: a client sees an odd-looking number in
              a line and assumes the agent misheard it. */}
          {showingRaw ? (
            <NoticeBox tone="warn" icon={<Eye className="h-5 w-5" />} title="Unredacted transcript">
              You are reading the full text, personal details included. This view was recorded
              in your account&apos;s audit log against your name.
            </NoticeBox>
          ) : (
            <NoticeBox tone="neutral" icon={<ShieldCheck className="h-5 w-5" />}>
              Personal details — phone numbers, account numbers, dates of birth — are hidden in
              this view.
            </NoticeBox>
          )}

          {/* The raw request failing must not take the redacted transcript with it. The
              refusal is stated and the turns below stay exactly as they were. */}
          {showRaw && raw.error && (
            <ProblemNotice error={raw.error} onRetry={() => void raw.refetch()} />
          )}

          {turns.length ? (
            <ol className="space-y-3">
              {turns.map((turn) => {
                const speaker = lookup(SPEAKERS, turn.speaker);
                const Icon = speaker?.icon ?? User;
                return (
                  <li key={turn.idx} className="flex gap-3">
                    <span
                      className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                        speaker?.medallion ?? "bg-black/5 text-ink-muted dark:bg-white/10"
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5" />
                    </span>
                    <div className="min-w-0">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                        {speaker?.label ?? turn.speaker}
                      </p>
                      <p className="text-sm text-ink">{turn.text}</p>
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <EmptyState
              title="No transcript yet"
              hint="Transcripts arrive a couple of minutes after the call ends."
            />
          )}
        </div>
      </Card>
    </div>
  );
}

/**
 * Was the disclosure line played? — the one compliance fact this screen can prove.
 *
 * Every agent must carry a non-null disclosure line (hard rule 5), and this column is
 * the per-call evidence that it reached the caller. Three states, not two: `null` means
 * the pipeline never recorded an answer, which is NOT the same as "no" and must not be
 * rendered as one — an owner told their call was non-compliant when we simply do not
 * know would go and change something that was never broken.
 */
function DisclosureNotice({ played }: { played: boolean | null | undefined }) {
  if (played === true) return null;
  if (played === false) {
    return (
      <NoticeBox
        tone="stop"
        icon={<ShieldAlert className="h-5 w-5" />}
        title="No disclosure was played on this call"
      >
        Callers must be told they are speaking to an automated agent. Tell us about this call
        so we can check the agent&apos;s configuration.
      </NoticeBox>
    );
  }
  return null;
}

/**
 * A short-lived, presigned link to OUR copy of the audio — never the engine's URL.
 *
 * Fetched on a click rather than with the page: the endpoint mints a signed URL with a
 * ticking expiry AND writes an `audit_log` row (crm/routes.py), so requesting one for
 * every visitor who never presses play would both burn the link and record a listen
 * that did not happen.
 *
 * Rendered into an `<audio>` element rather than an anchor. A signed URL in an `href`
 * is a URL a browser keeps in history and hands to the next page as a referrer, and the
 * signature is the credential.
 */
function RecordingCard({
  recording,
}: {
  recording: ReturnType<typeof useRecordingLink>;
}) {
  return (
    <Card title="Recording">
      {recording.error && <ProblemNotice error={recording.error} />}
      {recording.data ? (
        <div className="space-y-2">
          {/* No <track>: the transcript above IS this recording's caption track, in the
              same view, and a second copy behind a control nobody opens is a copy that
              drifts. Disabled at the SITE rather than in eslint.config.mjs, so the next
              <audio>/<video> added anywhere still has to answer the rule — the reason
              here ("the captions are already on screen, as text") is specific to this
              panel and does not generalise.
              WCAG 1.2.2 is met by the transcript, not by the absence of a track. */}
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <audio controls src={recording.data.url} className="w-full" />
          <p className="text-xs text-ink-faint">
            This link stops working in about {Math.max(1, Math.round(recording.data.expires_in_s / 60))}{" "}
            minutes. Ask again to get a fresh one.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <button
            type="button"
            disabled={recording.isPending}
            onClick={() => recording.mutate()}
            className="inline-flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/5"
          >
            <AudioLines className="h-4 w-4" />
            {recording.isPending ? "Preparing…" : "Listen to this call"}
          </button>
          <p className="text-xs text-ink-faint">Opening the recording is recorded in your audit log.</p>
        </div>
      )}
    </Card>
  );
}

/**
 * The control that reveals the unredacted transcript — refused before the click.
 *
 * The doctrine this app already follows for dispatch, for the CSV export and for D-22
 * impersonation: a gated action renders disabled WITH the reason beside it, because an
 * answer given before the click beats a 403 dressed as a fault after it. The server
 * still refuses either way; this is a preview of its answer, never a substitute.
 */
function RawTranscriptControl({
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
            ? "Shows the full text, personal details included. The read is written to your audit log."
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

interface RawTranscriptAccess {
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
function useRawTranscriptAccess(session: Session): RawTranscriptAccess {
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
 * The unredacted transcript — a GET WITH A SIDE EFFECT, and treated as one.
 *
 * `/v1/calls/{id}/transcript/raw` writes an `audit_log` row in the same transaction as
 * the read (crm/routes.py), so every automatic refetch would both re-expose personal
 * data and forge an audit entry naming a person who did not ask for it. All of the
 * library's implicit refetching is therefore off and the answer never goes stale: this
 * request happens when someone presses the button, and at no other moment.
 *
 * `retry: false` for the same reason — a 403 must surface once, not three times.
 */
function useRawTranscript(session: Session, callId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["call-transcript-raw", session.orgSlug, callId],
    queryFn: () => apiRequest<CallDetail>(session, `/v1/calls/${callId}/transcript/raw`),
    enabled,
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });
}

function useRecordingLink(session: Session, callId: string) {
  return useMutation({
    mutationFn: () =>
      apiRequest<components["schemas"]["RecordingLinkOut"]>(
        session,
        `/v1/calls/${callId}/recording`,
      ),
  });
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}
