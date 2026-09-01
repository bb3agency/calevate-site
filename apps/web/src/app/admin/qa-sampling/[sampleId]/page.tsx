"use client";

import Link from "next/link";
import { use } from "react";
import { ArrowLeft, Bot, ShieldCheck, TriangleAlert, User } from "lucide-react";

import {
  Card,
  EmptyState,
  MonoValue,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatDuration,
  formatIST,
} from "@/components/ui";
import { lookup } from "@/lib/lookup";
import {
  useQaSample,
  useReviewQaSample,
  VERDICTS,
  type QaVerdict,
} from "@/lib/api/qaSamples";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill, type CopilotFact } from "@/lib/copilot/types";

/**
 * One sampled call, reviewed — the screen where our 5% spot-check actually happens.
 *
 * **The transcript here is the REDACTED one, and there is no control to change that.**
 * The API embeds the same `CallDetailOut` the client's own call screen receives
 * (`crm.service.get_call(raw=False)`), every turn carrying `redacted: true`, and the
 * admin router deliberately exposes no raw variant. Raw transcript text has exactly one
 * route in this product — `calls:read_raw` plus an `audit_log` write in the same
 * transaction — and a reviewer who genuinely needs it goes through that one and is
 * audited like anybody else (hard rule 5). A convenience toggle here would be a second
 * path to raw, and the second path is the one that rots.
 *
 * Opening this page is itself audited (`qa_sample.read`), because it discloses one
 * tenant's conversation to somebody outside that tenant. The screen says so — a person
 * deciding whether to look should know before they look, not learn it from a compliance
 * review afterwards. That is also why the query does not poll: a refetch loop would turn
 * one review into a page of audit entries and make the trail unreadable.
 *
 * The verdict is three buttons and no free-text box, deliberately (hard rule 6): a note
 * field on a cross-tenant queue is an invitation to type what the caller said into it.
 * A finding the enum cannot express belongs in the incident it justifies.
 */
export default function QaSampleReviewPage({
  params,
}: {
  params: Promise<{ sampleId: string }>;
}) {
  const { sampleId } = use(params);
  const detail = useQaSample(sampleId);
  const review = useReviewQaSample(sampleId);

  /*
   * ONE SAMPLED CALL, DECLARED TO THE SCREEN ASSISTANT.
   *
   * THE CONVERSATION DOES NOT LEAVE THIS SCREEN, and that is the whole shape of this
   * declaration. The transcript rendered below is redacted, but redacted is not the same
   * as safe to forward: the header above says raw text has exactly one audited route in
   * this product, and a copilot declaration would be a second one that nobody signed off.
   * The `summary` is left out for a sharper reason — it is model-written prose ABOUT the
   * raw transcript (`workers/extraction.py` runs the first pass on Sarvam, over unredacted
   * text), so it can name a caller that no redaction pass afterwards would catch.
   *
   * What DOES go is the draw's own evidence and the call's metadata: rank, target,
   * population, week, duration, direction, tags. That is exactly what a reviewer asks
   * about — "why was this one picked", "has it been reviewed", "was the disclosure
   * played" — and none of it is a person.
   *
   * THE VERDICT IS READ-ONLY. It is written once, cannot be overwritten, and is recorded
   * against the reviewer's own name; a machine-filled judgement about a call the model has
   * not been shown would be the worst kind of assistance this console could offer.
   */
  const sample = detail.data?.sample;
  const call = detail.data?.call;
  useCopilotSurface({
    route: "/admin/qa-sampling/{sampleId}",
    title: "Review a sampled call",
    realm: "admin",
    fields:
      sample === undefined
        ? []
        : [
            {
              id: "qa-verdict",
              label: "Verdict",
              type: "select",
              value: review.data?.verdict ?? sample.verdict ?? "",
              options: (Object.keys(VERDICTS) as QaVerdict[]).map((verdict) => ({
                value: verdict,
                label: VERDICTS[verdict].label,
              })),
              writable: false,
              help: "Written once, against the reviewer's own name, after they have read the call. Empty means not yet reviewed.",
            },
          ],
    facts:
      sample !== undefined && call !== undefined
        ? ([
            { key: "client", label: "Client whose call this is", value: sample.tenant_name },
            { key: "agent", label: "Agent that took the call", value: sample.agent_name },
            { key: "week_start", label: "Draw week", value: sample.week_start },
            {
              key: "draw",
              label: "Where this call came in the published draw",
              value: `${sample.selection_rank} of ${sample.target}, drawn from ${sample.population} completed calls`,
            },
            { key: "direction", label: "Direction", value: call.direction },
            {
              key: "duration_s",
              label: "Duration (seconds)",
              value: call.duration_s === null ? "not recorded" : String(call.duration_s),
            },
            {
              key: "disclosure_played",
              label: "AI disclosure played at the start",
              value:
                call.disclosure_played === null
                  ? "not recorded"
                  : call.disclosure_played
                    ? "yes"
                    : "no",
            },
            { key: "outcome_tag", label: "Outcome tag", value: call.outcome_tag ?? "none" },
            { key: "sentiment", label: "Sentiment", value: call.sentiment ?? "not scored" },
            {
              key: "turns",
              label: "Turns in the transcript (the text itself is not sent)",
              value: String(call.transcript?.length ?? 0),
            },
          ] satisfies CopilotFact[])
        : [
            {
              key: "call",
              label: "This sampled call",
              value: detail.error ? "could not be read" : "still loading",
            },
          ],
    apply: noFill,
  });

  return (
    <div className="space-y-4 pb-12">
      <Link
        href="/admin/qa-sampling"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
      >
        <ArrowLeft className="h-4 w-4" />
        Sampling queue
      </Link>

      {detail.isLoading ? (
        <Card>
          <Skeleton rows={8} />
        </Card>
      ) : detail.error ? (
        /* A refusal, never an empty review screen: a reviewer shown a blank transcript
           would record a verdict about a call they never read. */
        <Card>
          <ProblemNotice error={detail.error} onRetry={() => void detail.refetch()} />
          <p className="mt-3 text-sm text-ink-muted">
            This call could not be read, so it cannot be reviewed. Nothing has been recorded
            against it.
          </p>
        </Card>
      ) : !detail.data ? (
        <Card>
          <NoticeBox
            tone="neutral"
            icon={<TriangleAlert className="h-5 w-5" />}
            title="Nothing to show"
          >
            We could not read this sampled call. Go back to the queue and try again.
          </NoticeBox>
        </Card>
      ) : (
        <>
          <Card>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className="text-lg font-semibold text-ink">
                {detail.data.sample.tenant_name}
              </span>
              <span className="text-sm text-ink-muted">
                {formatIST(detail.data.call.started_at)} ·{" "}
                {formatDuration(detail.data.call.duration_s)} · {detail.data.call.direction}
              </span>
            </div>
            {/* WHY this call: the whole draw, in one sentence a reviewer can repeat to a
                client. The seed is printed because it is the thing that makes the claim
                checkable by somebody who does not trust us. */}
            <p className="mt-2 text-sm text-ink-muted">
              Drawn #{detail.data.sample.selection_rank} of {detail.data.sample.target} from the{" "}
              {detail.data.sample.population} calls this client completed in the week of{" "}
              {detail.data.sample.week_start}.
            </p>
            <p className="mt-1 text-xs text-ink-faint">
              This call&apos;s place in the draw is fixed by the seed{" "}
              <MonoValue>{detail.data.sample.selection_seed}</MonoValue> — re-run it and this
              call comes back in the same place.
            </p>
          </Card>

          <NoticeBox tone="neutral" icon={<ShieldCheck className="h-5 w-5" />}>
            Personal details — phone numbers, account numbers, dates of birth — are hidden in
            this transcript, and there is no way to see them in full on this screen. Opening
            this call was recorded in the audit log against your name.
          </NoticeBox>

          <Verdicts
            /* The SERVER's answer wins over the cached row: the POST returns the sample
               as it now stands, so the panel switches to "recorded" on that rather than
               waiting for a refetch — and it shows the verdict the server stored, never
               the one this browser sent, so a race resolves to the truth. */
            sampleVerdict={review.data?.verdict ?? detail.data.sample.verdict}
            pending={review.isPending}
            error={review.error}
            onChoose={(verdict) => review.mutate(verdict)}
          />

          {detail.data.call.summary && (
            <Card title="Summary">
              <p className="text-sm text-ink">{detail.data.call.summary}</p>
            </Card>
          )}

          <Card title="Transcript">
            {detail.data.call.transcript?.length ? (
              <ol className="space-y-3">
                {detail.data.call.transcript.map((turn) => {
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
                title="No transcript on this call"
                hint="A sampled call with no transcript is worth flagging: the draw only takes completed calls, so this one lost its turns somewhere."
              />
            )}
          </Card>
        </>
      )}
    </div>
  );
}

const SPEAKERS: Record<string, { label: string; icon: typeof Bot; medallion: string }> = {
  agent: { label: "Agent", icon: Bot, medallion: "bg-brand-soft text-brand-strong" },
  caller: { label: "Caller", icon: User, medallion: "bg-black/5 text-ink-muted dark:bg-white/10" },
};

function Verdicts({
  sampleVerdict,
  pending,
  error,
  onChoose,
}: {
  sampleVerdict: QaVerdict | null;
  pending: boolean;
  error: unknown;
  onChoose: (verdict: QaVerdict) => void;
}) {
  if (sampleVerdict) {
    const recorded = VERDICTS[sampleVerdict];
    return (
      <Card title="Review">
        <p className="text-sm text-ink">
          Recorded as <strong>{recorded.label}</strong>. {recorded.meaning}
        </p>
        <p className="mt-2 text-xs text-ink-faint">
          A verdict is written once. Changing our mind about this call is a new decision, made
          deliberately — not an edit that erases the first one.
        </p>
      </Card>
    );
  }
  return (
    <Card title="Review">
      {/* The refusal renders ABOVE the buttons rather than replacing them: a 409 means
          somebody else reviewed this call first, and the reviewer needs to see that
          sentence, not a screen that silently stops responding. */}
      {error !== null && error !== undefined && <ProblemNotice error={error} />}
      <fieldset disabled={pending}>
        <legend className="text-sm text-ink-muted">
          What did this call show? The verdict is recorded against your name and cannot be
          overwritten by the next person to open it.
        </legend>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {(Object.keys(VERDICTS) as QaVerdict[]).map((verdict) => (
            <button
              key={verdict}
              type="button"
              onClick={() => onChoose(verdict)}
              className="rounded-card border border-line bg-surface p-4 text-left hover:bg-black/[0.02] disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/[0.03]"
            >
              <span className="block text-sm font-semibold text-ink">
                {VERDICTS[verdict].label}
              </span>
              <span className="mt-1 block text-xs text-ink-muted">{VERDICTS[verdict].meaning}</span>
            </button>
          ))}
        </div>
      </fieldset>
    </Card>
  );
}
