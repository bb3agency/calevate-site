"use client";

import { ShieldCheck } from "lucide-react";

import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import {
  Card,
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
  type QaSampleDetail,
  type QaVerdict,
} from "@/lib/api/qaSamples";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill, type CopilotFact } from "@/lib/copilot/types";

/**
 * One sampled call, reviewed — where the 5% spot-check actually happens.
 *
 * The transcript is the REDACTED one and there is no control to change that: the API
 * embeds the client's own `CallDetailOut` (`get_call(raw=False)`) and exposes no raw
 * variant. Raw text has one route in this product — `calls:read_raw` plus an `audit_log`
 * write — and a second, convenient path is the one that rots (hard rule 5).
 *
 * Opening this page is audited (`qa_sample.read`), because it discloses one tenant's
 * conversation to somebody outside that tenant; the screen says so before the reader
 * reads. That is also why the query does not poll.
 *
 * The verdict is three choices and no free-text box (hard rule 6): a note field on a
 * cross-tenant queue invites typing what the caller said into it.
 */
export function QaReviewScreen({ sampleId }: { sampleId: string }) {
  const detail = useQaSample(sampleId);
  const review = useReviewQaSample(sampleId);

  /*
   * The conversation does not leave this screen. Redacted is not safe to forward, and the
   * `summary` is model prose about the RAW transcript (`workers/extraction.py`), so it can
   * name a caller no later redaction would catch. The draw's evidence and the call's
   * metadata go — what a reviewer asks about, and none of it a person. The verdict is
   * read-only: a machine-filled judgement about a call the model was not shown would be
   * the worst assistance this console could offer.
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
    <div className="space-y-5 pb-12">
      <PageHeader
        back={{ href: "/admin/qa-sampling", label: "Call quality checks" }}
        title={sample?.tenant_name}
        description={
          call
            ? `${formatIST(call.started_at)} · ${formatDuration(call.duration_s)} · ${call.direction}`
            : undefined
        }
      />

      {detail.isLoading ? (
        <Card>
          <Skeleton rows={8} label="Loading the sampled call" />
        </Card>
      ) : detail.error || !detail.data ? (
        /* A refusal, never an empty review: a reviewer shown a blank transcript would
           record a verdict about a call they never read. A paused read (offline) has no
           error and no data, and gets the same sentence. */
        <Card>
          <ProblemNotice error={detail.error} onRetry={() => void detail.refetch()} />
          <p className={`text-sm text-ink-muted ${detail.error ? "mt-3" : ""}`}>
            This call could not be read, so it cannot be reviewed. Nothing has been recorded
            against it.
          </p>
        </Card>
      ) : (
        <Review
          data={detail.data}
          /* The server's answer wins over the cached row: the POST returns the sample as it
             now stands, so a race resolves to the verdict the server stored, never the one
             this browser sent. */
          verdict={review.data?.verdict ?? detail.data.sample.verdict}
          pending={review.isPending}
          error={review.error}
          onChoose={(verdict) => review.mutate(verdict)}
        />
      )}
    </div>
  );
}

function Review({
  data,
  verdict,
  pending,
  error,
  onChoose,
}: {
  data: QaSampleDetail;
  verdict: QaVerdict | null;
  pending: boolean;
  error: unknown;
  onChoose: (verdict: QaVerdict) => void;
}) {
  const { sample, call } = data;
  return (
    <>
      {/* WHY this call, in one sentence a reviewer can repeat to a client. The seed is what
          makes the claim checkable by somebody who does not trust us. */}
      <div className="space-y-1">
        <p className="text-sm text-ink-muted">
          Drawn #{sample.selection_rank} of {sample.target} from the {sample.population} calls
          this client completed in the week of {sample.week_start}.
        </p>
        <p className="flex flex-wrap items-center gap-1 text-xs text-ink-muted">
          Seed <MonoValue className="break-all text-ink">{sample.selection_seed}</MonoValue>
          <InfoTip label="The seed">
            This call&apos;s place in the draw is fixed by the seed — re-run it and this call
            comes back in the same place.
          </InfoTip>
        </p>
      </div>

      <NoticeBox tone="neutral" icon={<ShieldCheck aria-hidden className="h-5 w-5" />}>
        Personal details — phone numbers, account numbers, dates of birth — are hidden in this
        transcript, and there is no way to see them in full on this screen. Opening this call
        was recorded in the audit log against your name.
      </NoticeBox>

      {/* Read before judging: the transcript leads, and on a wide screen the verdict
          stays beside it as the reader scrolls. */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
        <div className="min-w-0 space-y-5">
          {call.summary && (
            <Card title="Summary" density="compact">
              <p className="text-sm text-ink">{call.summary}</p>
            </Card>
          )}
          <Card title="Transcript" density="compact">
            {call.transcript?.length ? (
              <ol className="space-y-4">
                {call.transcript.map((turn) => {
                  const speaker = lookup(SPEAKERS, turn.speaker);
                  return (
                    <li key={turn.idx} className={speaker?.agent ? "border-l-2 border-brand/40 pl-3" : "pl-3.5"}>
                      <p className="text-xs font-medium text-ink-muted">{speaker?.label ?? turn.speaker}</p>
                      <p className="mt-0.5 break-words text-sm text-ink">{turn.text}</p>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <EmptyState
                message={
                  <>
                    No transcript on this call{" "}
                    <InfoTip label="A missing transcript">
                      Worth flagging: the draw only takes completed calls, so this one lost its
                      turns somewhere.
                    </InfoTip>
                  </>
                }
              />
            )}
          </Card>
        </div>
        <div className="lg:sticky lg:top-4">
          <Verdicts verdict={verdict} pending={pending} error={error} onChoose={onChoose} />
        </div>
      </div>
    </>
  );
}

const SPEAKERS: Record<string, { label: string; agent: boolean }> = {
  agent: { label: "Agent", agent: true },
  caller: { label: "Caller", agent: false },
};

/**
 * One click records the verdict, deliberately with no confirm step: the three choices are
 * described cards, and the recorded verdict replaces them at once with what was stored.
 */
function Verdicts({
  verdict,
  pending,
  error,
  onChoose,
}: {
  verdict: QaVerdict | null;
  pending: boolean;
  error: unknown;
  onChoose: (verdict: QaVerdict) => void;
}) {
  if (verdict) {
    const recorded = VERDICTS[verdict];
    return (
      <Card title="Review" density="compact">
        <p className="text-sm text-ink">
          Recorded as <strong>{recorded.label}</strong>. {recorded.meaning}
        </p>
        <p className="mt-2 text-xs text-ink-muted">
          A verdict is written once. Changing our mind about this call is a new decision, made
          deliberately — not an edit that erases the first one.
        </p>
      </Card>
    );
  }
  return (
    <Card title="Review" density="compact">
      {/* Above the choices rather than replacing them: a 409 means somebody else reviewed
          this call first, and the reviewer needs that sentence, not a screen gone quiet. */}
      {error !== null && error !== undefined && (
        <div className="mb-3">
          <ProblemNotice error={error} />
        </div>
      )}
      <fieldset disabled={pending}>
        <legend className="text-sm text-ink-muted">
          What did this call show? The verdict is recorded against your name and cannot be
          overwritten by the next person to open it.
        </legend>
        <div className="mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-1">
          {(Object.keys(VERDICTS) as QaVerdict[]).map((choice) => (
            <button
              key={choice}
              type="button"
              onClick={() => onChoose(choice)}
              // Colour-only feedback, no scale: a card this wide shrinking reads as the grid
              // wobbling. `enabled:` so a fieldset disabled mid-submit stops answering.
              className="min-h-11 rounded-card border border-line bg-surface p-3 text-left transition-[background-color,border-color] duration-(--duration-fast) ease-out enabled:hover:border-ink-faint/40 enabled:hover:bg-ink/[0.025] enabled:active:bg-ink/[0.05] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
            >
              <span className="block text-sm font-semibold text-ink">{VERDICTS[choice].label}</span>
              <span className="mt-0.5 block text-xs text-ink-muted">{VERDICTS[choice].meaning}</span>
            </button>
          ))}
        </div>
      </fieldset>
    </Card>
  );
}
