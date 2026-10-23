"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type ReactNode } from "react";
import { Check, ChevronRight } from "lucide-react";

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { ADMIN_PAGE_WIDE } from "@/components/admin/kit";
import {
  MonoValue,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
  formatDuration,
  formatIST,
} from "@/components/ui";
import { lookup } from "@/lib/lookup";
import { viewAsHref } from "@/lib/api/session";
import {
  filtersFromSearch,
  filtersToSearch,
  useNextWaiting,
  useQaSample,
  useReviewQaSample,
  VERDICTS,
  type QaSampleDetail,
  type QaVerdict,
} from "@/lib/api/qaSamples";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill, type CopilotFact } from "@/lib/copilot/types";

import { calls, directionLabel, reviewHref, weekLabel } from "../queueWords";

/**
 * One sampled call, reviewed — where the 5% spot-check actually happens.
 *
 * The transcript is the REDACTED one and there is no control to change that: the API
 * embeds the client's own `CallDetailOut` (`get_call(raw=False)`) and exposes no raw
 * variant. Raw text has one route in this product — `calls:read_raw` plus an `audit_log`
 * write — and a second, convenient path is the one that rots (hard rule 5).
 *
 * Opening this page is audited server-side (`qa_sample.read`), which is why the query does
 * not poll.
 *
 * The verdict is three choices and no free-text box (hard rule 6): a note field on a
 * cross-tenant queue invites typing what the caller said into it. Choosing a card does
 * not record anything; "Record verdict" does, because a verdict is written once and a
 * stray click must not be the thing that writes it.
 */
export function QaReviewScreen({ sampleId }: { sampleId: string }) {
  const detail = useQaSample(sampleId);
  const review = useReviewQaSample(sampleId);
  // The queue's filters ride along in the URL: the back link returns to the same view and
  // "Next call to review" stays inside the same client and week.
  const params = useSearchParams();
  const filters = filtersFromSearch(new URLSearchParams(params.toString()));
  const search = filtersToSearch({ ...filters, page: 1 });

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
              help: "Recorded once, by the reviewer, after they have read the call. Empty means not yet reviewed.",
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

  const queueHref = search ? `/admin/qa-sampling?${search}` : "/admin/qa-sampling";
  return (
    <div className={ADMIN_PAGE_WIDE}>
      <PageHeader
        back={{ href: queueHref, label: "Call quality checks" }}
        title={sample?.tenant_name}
        description={
          call && sample
            ? `${sample.agent_name} · ${formatIST(call.started_at)} · ${directionLabel(call.direction)} · ${formatDuration(call.duration_s)}`
            : undefined
        }
      />

      {detail.isLoading ? (
        <Skeleton rows={8} label="Loading the sampled call" />
      ) : detail.error || !detail.data ? (
        /* A refusal, never an empty review: a reviewer shown a blank transcript would
           record a verdict about a call they never read. A paused read (offline) has no
           error and no data, and gets the same sentence. */
        <div>
          <ProblemNotice error={detail.error} onRetry={() => void detail.refetch()} />
          <p className={`text-body text-ink-muted ${detail.error ? "mt-3" : ""}`}>
            This call could not be read, so it cannot be reviewed. Nothing has been recorded
            against it.
          </p>
        </div>
      ) : (
        <Review
          data={detail.data}
          /* The server's answer wins over the cached row: the POST returns the sample as it
             now stands, so a race resolves to the verdict the server stored, never the one
             this browser sent. */
          verdict={review.data?.verdict ?? detail.data.sample.verdict}
          pending={review.isPending}
          error={review.error}
          onRecord={(verdict) => review.mutate(verdict)}
          next={<NextCall sampleId={sampleId} filters={filters} search={search} queueHref={queueHref} />}
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
  onRecord,
  next,
}: {
  data: QaSampleDetail;
  verdict: QaVerdict | null;
  pending: boolean;
  error: unknown;
  onRecord: (verdict: QaVerdict) => void;
  next: ReactNode;
}) {
  const { sample, call } = data;
  return (
    // Read before judging: the transcript leads, and on a wide screen the review panel
    // stays beside it as the reader scrolls. On a phone the panel follows the transcript.
    <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
      <div className="min-w-0 space-y-8">
        <WhatToCheck />

        <div className="space-y-3">
          <p className="flex flex-wrap items-center gap-1 text-meta text-ink-muted">
            Pick #{sample.selection_rank} of {sample.target} from the{" "}
            {calls(sample.population)} this client finished in the week of{" "}
            {weekLabel(sample.week_start)}.
            <InfoTip label="How this call was picked">
              <p>
                Its place in the pick is fixed by this seed: re-run the pick and this call
                comes back in the same place.
              </p>
              <p>
                Seed <MonoValue className="break-all text-ink">{sample.selection_seed}</MonoValue>
              </p>
            </InfoTip>
          </p>
          <NoticeBox tone="neutral">
            Personal details (phone numbers, account numbers, dates of birth) are hidden in
            this transcript, and there is no way to see them in full on this screen.
          </NoticeBox>
        </div>

        {call.summary && (
          <Section title="Summary">
            <p className="max-w-prose text-body text-ink">{call.summary}</p>
          </Section>
        )}
        <Section title="Transcript">
          {call.transcript?.length ? (
            <ol className="space-y-4">
              {call.transcript.map((turn) => {
                const speaker = lookup(SPEAKERS, turn.speaker);
                return (
                  // A PLAIN SCRIPT (founder, 10 Oct 2026): the speaker's name muted, then the
                  // line. No bubbles and no rule on one side: the reviewer is reading what
                  // was said, and a styled side reads as a verdict on who said it.
                  <li key={turn.idx}>
                    <p className="text-meta font-medium text-ink-muted">{speaker?.label ?? turn.speaker}</p>
                    <p className="mt-0.5 max-w-prose break-words text-body text-ink">{turn.text}</p>
                  </li>
                );
              })}
            </ol>
          ) : (
            <EmptyState
              align="start"
              message={
                <>
                  No transcript on this call{" "}
                  <InfoTip label="A missing transcript">
                    Worth a Concern at least: only finished calls are picked, so this one lost
                    its transcript somewhere.
                  </InfoTip>
                </>
              }
            />
          )}
        </Section>
      </div>
      <aside
        aria-label="Your review"
        className="rounded-card border border-line bg-surface p-4 lg:sticky lg:top-4"
      >
        {verdict ? (
          <Recorded data={data} verdict={verdict} next={next} />
        ) : (
          <VerdictForm pending={pending} error={error} onRecord={onRecord} />
        )}
      </aside>
    </div>
  );
}

const SPEAKERS: Record<string, { label: string; agent: boolean }> = {
  agent: { label: "Agent", agent: true },
  caller: { label: "Caller", agent: false },
};

/** The four things the verdicts are about, in the order a reader meets them in a call. */
const CHECKS = [
  "Did the agent stick to what it was set up to do?",
  "When asked, did it say it is an AI?",
  "Was any detail wrong or made up?",
  "Is anything personal left visible in the transcript?",
] as const;

function WhatToCheck() {
  return (
    <section aria-labelledby="qa-what-to-check">
      <h3 id="qa-what-to-check" className="text-body font-semibold text-ink">
        What to check
      </h3>
      <ul className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {CHECKS.map((check) => (
          // A plain bullet, not a tick: these are questions still to answer.
          <li key={check} className="flex gap-2 text-body text-ink">
            <span aria-hidden className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-ink-faint" />
            {check}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Choose, then record. The cards are a native radio group — the browser gives it arrow
 * keys and one tab stop — and nothing is written until "Record verdict".
 */
function VerdictForm({
  pending,
  error,
  onRecord,
}: {
  pending: boolean;
  error: unknown;
  onRecord: (verdict: QaVerdict) => void;
}) {
  const [choice, setChoice] = useState<QaVerdict | null>(null);
  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (choice) onRecord(choice);
      }}
    >
      <h3 id="qa-verdict-heading" className="text-body font-semibold text-ink">
        What did this call show?
      </h3>
      {/* Above the choices rather than replacing them: a 409 means somebody else reviewed
          this call first, and the reviewer needs that sentence, not a panel gone quiet. */}
      {error !== null && error !== undefined && (
        <div className="mt-3">
          <ProblemNotice error={error} />
        </div>
      )}
      <fieldset disabled={pending} className="mt-3">
        <legend className="sr-only">Verdict</legend>
        <div role="radiogroup" aria-labelledby="qa-verdict-heading" className="space-y-2">
          {(Object.keys(VERDICTS) as QaVerdict[]).map((verdict) => {
            const on = choice === verdict;
            return (
              <label
                key={verdict}
                className={`${CHOICE_CARD} ${on ? CHOICE_ON : CHOICE_OFF} flex gap-3 px-3.5 py-3 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60`}
              >
                <input
                  type="radio"
                  name="qa-verdict"
                  value={verdict}
                  checked={on}
                  onChange={() => setChoice(verdict)}
                  className="sr-only"
                />
                {/* The radio's own mark, drawn: the input is sr-only so the card is the
                    target, and a visible ring says "pick one" before anything is hovered. */}
                <span
                  aria-hidden
                  className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                    on ? "border-brand-strong" : "border-ink-faint"
                  }`}
                >
                  {on && <span className="h-2 w-2 rounded-full bg-brand-strong" />}
                </span>
                <span className="min-w-0">
                  <span className="block text-body font-medium text-ink">{VERDICTS[verdict].label}</span>
                  <span className="mt-0.5 block text-meta text-ink-muted">{VERDICTS[verdict].meaning}</span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <button
        type="submit"
        disabled={choice === null || pending}
        className={`${PRIMARY_BUTTON} mt-4 w-full justify-center`}
      >
        {pending ? "Recording…" : "Record verdict"}
      </button>
      <p className="mt-2 text-meta text-ink-muted">
        {choice === null ? "Pick one to record it." : "A verdict can't be changed once it is recorded."}
      </p>
    </form>
  );
}

/** What was recorded, then what to do about it. */
function Recorded({
  data,
  verdict,
  next,
}: {
  data: QaSampleDetail;
  verdict: QaVerdict;
  next: ReactNode;
}) {
  const { sample, call } = data;
  const recorded = VERDICTS[verdict];
  const followUp = verdict !== "clean";
  return (
    <div className="space-y-4">
      <div>
        <p className="flex items-center gap-2 text-body text-ink" role="status">
          <Check aria-hidden className="h-4 w-4 text-brand-strong" />
          <span>
            Recorded as <strong className="font-semibold">{recorded.label}</strong>
          </span>
        </p>
        <p className="mt-1 text-meta text-ink-muted">{recorded.meaning}</p>
      </div>
      {followUp && (
        <div>
          <h3 className="text-body font-semibold text-ink">Follow it up</h3>
          <ul className="mt-2 space-y-2">
            <li>
              <a href={viewAsHref(sample.tenant_slug, `/agents/${call.agent_id}`)} className={TEXT_ACTION}>
                Open the {sample.agent_name} agent&apos;s set-up, as the client sees it
              </a>
            </li>
            <li>
              <a href={viewAsHref(sample.tenant_slug, `/calls/${call.id}`)} className={TEXT_ACTION}>
                Open this call in the client&apos;s dashboard
              </a>
            </li>
            <li>
              <AskAssistant
                label={`Ask ${ASSISTANT_NAME} about this call`}
                prompt={pipPrompt(sample.tenant_name, sample.agent_name, verdict)}
              />
            </li>
          </ul>
        </div>
      )}
      <div className="border-t border-line pt-4">{next}</div>
    </div>
  );
}

/** What "Ask Pip" writes in Pip's ask box. Names the client and agent, never the caller. */
export function pipPrompt(client: string, agent: string, verdict: QaVerdict): string {
  return `I marked a sampled call from ${client} (agent ${agent}) as ${VERDICTS[verdict].label.toLowerCase()}. What should I check in this agent's set-up?`;
}

/** "Next call to review" under the queue's own client and week, or "All caught up". */
function NextCall({
  sampleId,
  filters,
  search,
  queueHref,
}: {
  sampleId: string;
  filters: { client: string | null; week: string | null };
  search: string;
  queueHref: string;
}) {
  const { next, query } = useNextWaiting(filters, { skip: sampleId });
  if (query.isLoading) return <p className="text-meta text-ink-muted">Finding the next call…</p>;
  if (next) {
    return (
      <div className="space-y-2">
        <Link href={reviewHref(next, search)} className={`${PRIMARY_BUTTON} w-full justify-center`}>
          Next call to review
          <ChevronRight aria-hidden className="h-4 w-4" />
        </Link>
        <p className="text-meta text-ink-muted">
          {next.tenant_name} · {next.agent_name}
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-body font-medium text-ink">
        {next === null ? "All caught up" : "The queue could not be read"}
      </p>
      <p className="text-meta text-ink-muted">
        {next === null
          ? filters.client || filters.week
            ? "Nothing else is waiting under these filters."
            : "Nothing else is waiting for review."
          : "Go back to the queue to see what is waiting."}
      </p>
      <Link href={queueHref} className={`${SECONDARY_BUTTON} w-full justify-center`}>
        Back to the queue
      </Link>
    </div>
  );
}
