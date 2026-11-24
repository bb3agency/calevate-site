"use client";

/**
 * LEAD DETAILS — the screen, for the client and for an operator.
 *
 * Founder decision 15 (10 Oct 2026): every lead carries a fixed core whatever the business,
 * which the client names in their own words. D-1028/D-1029 (22 Nov 2026): what else a call
 * notes belongs to its campaign or inbound line, so the screen shows one card per job, each
 * the same "What it notes" editor the job's own page shows (`campaigns/CampaignNotes.JobNotes`),
 * with its suggested changes and an Import menu. Above them, the business's starting set:
 * what a new campaign or line starts with, which the AI draft and "Start again" put onto the
 * ticked jobs (`ApplyToJobs`).
 *
 * The data and the writes are passed in, and the per-job reads and writes come from a
 * `JobNotesSource`, so the client screen and the operator's screen render one component and
 * differ only in which endpoints they call (`lib/api/leadFields.ts`).
 */

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { Lock, Pencil, Plus } from "lucide-react";
import type { UseMutationResult } from "@tanstack/react-query";

import {
  JobNotes,
  JobNotesSourceProvider,
  lineNotesTakeEffect,
  notesTakeEffect,
  type JobNotesSource,
} from "@/app/c/[slug]/campaigns/CampaignNotes";
import { FoldGroup } from "@/app/c/[slug]/campaigns/FoldSection";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { EmptyState } from "@/components/console/emptyState";
import { Section, TEXT_ACTION } from "@/components/console/section";
import {
  FIELD,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
  formatISTStamp,
} from "@/components/ui";
import type { JobKind } from "@/lib/api/campaignWorkspace";
import type {
  CoreLabelsIn,
  DraftRequestOut,
  DraftReviewIn,
  DraftReviewOut,
  JobRef,
  LeadField,
  LeadFields,
  LeadFieldsDraft,
  LeadFieldsJob,
  ReplaceOut,
} from "@/lib/api/leadFields";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { lookup } from "@/lib/lookup";
import { Why } from "@/components/why";

import { ApplyToJobs, JobStatusPill, appliedSentence, useJobPicks } from "./ApplyToJobs";

/** The core, in the owner's words. The server's labels head each row; these explain them. */
const CORE_MEANING: Readonly<Record<string, string>> = {
  name: "Who called",
  need: "What they want, or why they called",
  preferred_time: "When they'd like it, or a time to call back",
  other_number: "Another number they asked to be reached on",
  language: "The language they spoke",
  notes: "Anything else worth knowing before you call back",
};

export interface LeadDetailsWrites {
  /** The operator's button. On the client's screen the draft is asked of Pip (D-821). */
  draft?: UseMutationResult<DraftRequestOut, Error, void>;
  /** The owner's review of a finished draft: keep these keys, on these jobs. Client only. */
  review?: UseMutationResult<DraftReviewOut, Error, DraftReviewIn>;
  /** The starting set onto the ticked jobs. */
  replace: UseMutationResult<ReplaceOut, Error, { jobs: JobRef[] }>;
  /** The client's names for the core details. */
  nameCore: UseMutationResult<LeadFields, Error, CoreLabelsIn>;
}

/** Where a job's own page is, and where a new one is made; null where this realm has none. */
export interface JobLinks {
  open: (kind: JobKind, jobId: string) => string;
  create: (kind: JobKind) => string;
}

export function LeadDetailsView({
  data,
  audience,
  canWrite,
  writeReason,
  writes,
  source,
  links,
}: {
  data: LeadFields;
  /** "client" speaks to the owner ("your business"); "operator" names the client. */
  audience: "client" | "operator";
  canWrite: boolean;
  writeReason: string | null;
  writes: LeadDetailsWrites;
  source: JobNotesSource;
  links: JobLinks | null;
}) {
  const your = audience === "client" ? "your" : "this client's";
  const campaigns = data.jobs.filter((job) => job.kind === "campaign");
  const lines = data.jobs.filter((job) => job.kind === "line");
  return (
    <div className="max-w-3xl space-y-10">
      <p className="max-w-prose text-body text-ink-muted [text-wrap:pretty]">
        Every call becomes a lead. These are its columns.
      </p>
      {writeReason && <RestrictionNote reason={writeReason} />}

      <CoreFields
        fields={data.core_fields}
        defaults={data.core_default_labels}
        canWrite={canWrite}
        rename={writes.nameCore}
      />

      <Section
        title="New ones start with"
        description={<Origin data={data} your={your} />}
      >
        <StartingSet data={data} canWrite={canWrite} writes={writes} audience={audience} />
      </Section>

      <JobNotesSourceProvider source={source}>
        <JobList
          kind="campaign"
          jobs={campaigns}
          data={data}
          canWrite={canWrite}
          writeReason={writeReason}
          links={links}
          audience={audience}
        />
        <JobList
          kind="line"
          jobs={lines}
          data={data}
          canWrite={canWrite}
          writeReason={writeReason}
          links={links}
          audience={audience}
        />
      </JobNotesSourceProvider>
    </div>
  );
}

/** `CoreLabelsIn.labels`' limit (`lead_fields.CORE_LABEL_MAX_CHARS`). */
const CORE_LABEL_MAX = 40;

function CoreFields({
  fields,
  defaults,
  canWrite,
  rename,
}: {
  fields: LeadField[];
  defaults: Record<string, string>;
  canWrite: boolean;
  rename: UseMutationResult<LeadFields, Error, CoreLabelsIn>;
}) {
  const [names, setNames] = useState<Record<string, string> | null>(null);
  const editing = names !== null;
  const start = () => {
    rename.reset();
    setNames(Object.fromEntries(fields.map((f) => [f.key, f.label])));
  };
  const save = () => {
    if (!names) return;
    // A name left as the default, or cleared, is sent blank: the platform's name again.
    const labels: CoreLabelsIn["labels"] = Object.fromEntries(
      fields.map((f) => {
        const typed = (names[f.key] ?? "").trim();
        return [f.key, typed === defaults[f.key] ? "" : typed];
      }),
    );
    rename.mutate({ labels }, { onSuccess: () => setNames(null) });
  };
  return (
    <Section
      title="Always captured"
      description="On every call. Name them in your own words."
      action={
        canWrite && !editing ? (
          <button type="button" className={TEXT_ACTION} onClick={start}>
            <Pencil aria-hidden className="h-3.5 w-3.5" />
            Rename
          </button>
        ) : undefined
      }
    >
      {editing ? (
        <form
          noValidate
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <ul className="grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
            {fields.map((field) => (
              <li key={field.key} className="min-w-0">
                <label className="block">
                  <span className="block text-meta text-ink-muted">
                    {lookup(CORE_MEANING, field.key) ?? defaults[field.key]}
                  </span>
                  <input
                    value={names[field.key] ?? ""}
                    maxLength={CORE_LABEL_MAX}
                    placeholder={defaults[field.key]}
                    onChange={(event) => setNames({ ...names, [field.key]: event.target.value })}
                    className={FIELD}
                  />
                </label>
              </li>
            ))}
          </ul>
          {rename.error ? <ProblemNotice error={rename.error} /> : null}
          <div className="flex flex-wrap items-center gap-3">
            <ActionButton type="submit" status={rename.isPending ? "pending" : "idle"} pendingLabel="Saving…">
              Save names
            </ActionButton>
            <button type="button" className={SECONDARY_BUTTON} onClick={() => setNames(null)}>
              Cancel
            </button>
            <span className="text-meta text-ink-muted">Leave one empty to use the usual name.</span>
          </div>
        </form>
      ) : (
        <ul className="grid grid-cols-1 gap-x-4 gap-y-3 min-[26rem]:grid-cols-2 sm:gap-x-8">
          {fields.map((field) => (
            <li key={field.key} className="flex min-w-0 items-start gap-2">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-faint" />
              <span className="min-w-0">
                <span className="block text-body font-medium text-ink">{field.label}</span>
                <span className="block text-meta text-ink-muted">
                  {lookup(CORE_MEANING, field.key) ?? field.label}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Origin({ data, your }: { data: LeadFields; your: string }) {
  if (data.draft?.status === "done" && !data.draft.reviewed) {
    return (
      <>
        Drafted from {your} business details. Keep what fits.{" "}
        <Why inline>Nothing changes until they are kept.</Why>
      </>
    );
  }
  if (data.draft?.status === "done" && data.draft.reviewed && data.draft.fields.length > 0) {
    const when = data.draft.completed_at ? ` on ${formatISTStamp(data.draft.completed_at)}` : "";
    return (
      <>
        Drafted from {your} business details{when}.{" "}
        <Why inline>They won&apos;t be drafted again. Each campaign and line keeps its own list.</Why>
      </>
    );
  }
  if (data.has_standard_set) {
    return <>Standard details for {data.business_type_label.toLowerCase()}.</>;
  }
  return <>What a new campaign or line notes first.</>;
}

function StartingSet({
  data,
  canWrite,
  writes,
  audience,
}: {
  data: LeadFields;
  canWrite: boolean;
  writes: LeadDetailsWrites;
  audience: "client" | "operator";
}) {
  const status = data.draft?.status;
  if (status === "queued" || status === "running") return <Drafting />;
  const noFieldsAnywhere = data.jobs.every((job) => job.fields.length === 0) && data.starting_fields.length === 0;
  return (
    <div className="space-y-6">
      {data.can_draft && noFieldsAnywhere && (
        <DraftOffer data={data} canWrite={canWrite} draft={writes.draft} audience={audience} />
      )}
      {data.draft?.status === "done" && !data.draft.reviewed ? (
        <DraftReview
          draft={data.draft}
          jobs={data.jobs}
          canWrite={canWrite}
          review={writes.review}
          audience={audience}
        />
      ) : (
        <StartAgain data={data} canWrite={canWrite} replace={writes.replace} />
      )}
    </div>
  );
}

function Drafting() {
  return (
    <div className="space-y-3">
      <p role="status" aria-live="polite" className="text-sm text-ink-muted">
        Drafting your details. About a minute.
      </p>
      <Skeleton rows={4} label="Drafting the business details" />
    </div>
  );
}

/** What the client asks Pip; the operator's screen keeps its own button. */
export const DRAFT_REQUEST = "Draft the lead details for my business from its business details.";

function DraftOffer({
  data,
  canWrite,
  draft,
  audience,
}: {
  data: LeadFields;
  canWrite: boolean;
  draft: LeadDetailsWrites["draft"];
  audience: "client" | "operator";
}) {
  const failed = data.draft?.status === "failed";
  return (
    <div className="rounded-card border border-line p-4">
      <p className="text-sm font-medium text-ink">
        {failed ? "The details could not be drafted last time." : "Nothing here yet."}
      </p>
      <p className="mt-1 max-w-prose text-sm text-ink-muted [text-wrap:pretty]">
        {audience === "client" ? ASSISTANT_NAME : "Calevate"} can draft these for you.{" "}
        <Why inline label="How it works">
          Drafted from what {audience === "client" ? "you sell" : "it sells"} and what callers
          ask. You choose what to keep and which campaigns and lines get it. Fill in the business
          profile first for a better draft.
        </Why>
      </p>
      {draft?.error && (
        <div className="mt-3">
          <ProblemNotice error={draft.error} />
        </div>
      )}
      {draft ? (
        <ActionButton
          className="mt-3"
          status={draft.isPending ? "pending" : "idle"}
          pendingLabel="Starting…"
          disabled={!canWrite}
          onClick={() => draft.mutate()}
        >
          {failed ? "Try again" : "Draft from the business details"}
        </ActionButton>
      ) : (
        <AskAssistant
          label={`Let ${ASSISTANT_NAME} draft them`}
          prompt={DRAFT_REQUEST}
          size="md"
          disabled={!canWrite}
          className="mt-3"
        />
      )}
    </div>
  );
}

/**
 * THE DRAFT, KEPT FIELD BY FIELD (D-821), and the campaigns and lines that take it (D-1029).
 * Every field starts ticked, and every job nobody customised. What is kept is also what a new
 * campaign or line starts with. Once reviewed, it is never offered again. An operator sees it
 * and waits for the owner.
 */
function DraftReview({
  draft,
  jobs,
  canWrite,
  review,
  audience,
}: {
  draft: LeadFieldsDraft;
  jobs: LeadFieldsJob[];
  canWrite: boolean;
  review: LeadDetailsWrites["review"];
  audience: "client" | "operator";
}) {
  const [kept, setKept] = useState<Set<string>>(() => new Set(draft.fields.map((f) => f.key)));
  const picks = useJobPicks(jobs);
  const count = kept.size;
  const owner = audience === "client" && review !== undefined;
  const busy = review?.isPending ?? false;
  const keepingNone = review?.variables?.keep.length === 0;
  return (
    <section aria-labelledby="draft-review-heading" className="space-y-4 rounded-card border border-line p-4">
      <div>
        <h3 id="draft-review-heading" className="text-body font-semibold text-ink">
          {draft.fields.length === 1 ? "1 drafted detail" : `${draft.fields.length} drafted details`}
        </h3>
        <p className="mt-1 text-sm text-ink-muted">
          {owner ? "Untick what you don't want." : "Waiting for the owner to keep the ones that fit."}{" "}
          {owner ? <Why inline>What you keep is what new campaigns and lines start with.</Why> : null}
        </p>
      </div>
      <ul className="divide-y divide-line border-y border-line">
        {draft.fields.map((field) => {
          const on = kept.has(field.key);
          return (
            <li key={field.key}>
              <label className={`flex items-start gap-3 py-2.5 ${owner ? "cursor-pointer" : ""} ${on ? "" : "opacity-55"}`}>
                {owner && (
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 shrink-0 accent-[var(--brand-strong)]"
                    checked={on}
                    disabled={!canWrite || busy}
                    onChange={(e) =>
                      setKept((current) => {
                        const next = new Set(current);
                        if (e.target.checked) next.add(field.key);
                        else next.delete(field.key);
                        return next;
                      })
                    }
                  />
                )}
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-ink">{field.label}</span>
                  {field.reason && <span className="block text-xs text-ink-muted">{field.reason}</span>}
                </span>
              </label>
            </li>
          );
        })}
      </ul>
      {owner && review && (
        <>
          <ApplyToJobs jobs={jobs} picks={picks} disabled={!canWrite || busy} legend="Add them to" />
          {review.error && <ProblemNotice error={review.error} />}
          <div className="flex flex-wrap items-center gap-2">
            {/* The pressed one spins; the other is held. "Keep none" is the only press that
                sends an empty `keep`, since Keep needs at least one ticked. */}
            <ActionButton
              status={busy && !keepingNone ? "pending" : "idle"}
              pendingLabel="Keeping…"
              disabled={!canWrite || count === 0 || (busy && keepingNone)}
              onClick={() => review.mutate({ keep: [...kept], jobs: picks.refs })}
            >
              {count === draft.fields.length ? `Keep all ${count}` : `Keep ${count} of ${draft.fields.length}`}
            </ActionButton>
            <ActionButton
              variant="secondary"
              status={busy && keepingNone ? "pending" : "idle"}
              disabled={!canWrite || (busy && !keepingNone)}
              onClick={() => review.mutate({ keep: [], jobs: [] })}
            >
              Keep none
            </ActionButton>
          </div>
        </>
      )}
    </section>
  );
}

/** The starting set's names, and "Start again" onto the ticked jobs. */
function StartAgain({
  data,
  canWrite,
  replace,
}: {
  data: LeadFields;
  canWrite: boolean;
  replace: LeadDetailsWrites["replace"];
}) {
  const [open, setOpen] = useState(false);
  const fields = data.starting_fields;
  if (fields.length === 0) {
    return <p className="text-sm text-ink-muted">Only the details above. Add more on each campaign or line.</p>;
  }
  return (
    <div className="space-y-4">
      <ul aria-label="Starting details" className="flex flex-wrap gap-1.5">
        {fields.map((field) => (
          <li key={field.key} className="rounded bg-ink/[0.06] px-2 py-0.5 text-sm text-ink">
            {field.label}
          </li>
        ))}
      </ul>
      {canWrite && data.jobs.length > 0 && !open && (
        <button type="button" className={TEXT_ACTION} onClick={() => setOpen(true)}>
          Use on campaigns and lines
        </button>
      )}
      {open && (
        <StartAgainPanel
          jobs={data.jobs}
          fields={fields}
          replace={replace}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}

function StartAgainPanel({
  jobs,
  fields,
  replace,
  onClose,
}: {
  jobs: LeadFieldsJob[];
  fields: LeadField[];
  replace: LeadDetailsWrites["replace"];
  onClose: () => void;
}) {
  const picks = useJobPicks(jobs);
  const [confirming, setConfirming] = useState(false);
  const feedback = useActionFeedback(replace, { errorDisplay: "inline" });
  return (
    <div className="space-y-3 rounded-card border border-line p-4">
      <ApplyToJobs jobs={jobs} picks={picks} disabled={replace.isPending} legend="Replace the list on" />
      {replace.data && !confirming && (
        <p role="status" className="text-sm text-ink-muted">
          {appliedSentence(replace.data)}
        </p>
      )}
      {replace.error && !confirming && <ProblemNotice error={replace.error} />}
      <div className="flex flex-wrap items-center gap-2">
        {/* Opens the confirmation, whose own button carries the work; held while it runs. */}
        <ActionButton
          disabled={picks.refs.length === 0 || replace.isPending}
          onClick={() => {
            replace.reset();
            setConfirming(true);
          }}
        >
          Replace on {picks.refs.length}
        </ActionButton>
        <button type="button" className={SECONDARY_BUTTON} onClick={onClose}>
          Close
        </button>
      </div>
      {confirming && (
        <ConfirmDialog
          title={`Replace the list on ${picks.refs.length === 1 ? "1 campaign or line" : `${picks.refs.length} campaigns and lines`}?`}
          confirmLabel="Replace"
          pendingLabel="Replacing…"
          status={feedback.status}
          successLabel="Replaced"
          error={replace.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() => replace.mutate({ jobs: picks.refs }, { onSuccess: () => setConfirming(false) })}
        >
          <p>They will note {fields.map((field) => field.label).join(", ")} from their next call.</p>
          <p>Past answers stay on their leads and calls.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}

const LIST_COPY: Record<JobKind, { title: string; empty: string; create: string; hint: string }> = {
  campaign: {
    title: "Campaigns",
    empty: "No campaigns yet",
    create: "New campaign",
    hint: "Each campaign notes its own list.",
  },
  line: {
    title: "Inbound lines",
    empty: "No Inbound lines yet",
    create: "New line",
    hint: "Each line notes its own list.",
  },
};

function JobList({
  kind,
  jobs,
  data,
  canWrite,
  writeReason,
  links,
  audience,
}: {
  kind: JobKind;
  jobs: LeadFieldsJob[];
  data: LeadFields;
  canWrite: boolean;
  writeReason: string | null;
  links: JobLinks | null;
  audience: "client" | "operator";
}) {
  const copy = LIST_COPY[kind];
  const offered = data.starting_fields.length
    ? { label: data.has_standard_set ? `Standard ${data.business_type_label.toLowerCase()} details` : "The starting details", fields: data.starting_fields }
    : null;
  return (
    <Section title={copy.title} description={copy.hint}>
      {jobs.length === 0 ? (
        <EmptyState
          align="start"
          message={copy.empty}
          hint={audience === "operator" ? "The client has none yet." : "New ones start with the details above."}
          action={
            links && canWrite ? (
              <Link href={links.create(kind)} className={PRIMARY_BUTTON_SM}>
                <Plus aria-hidden className="h-4 w-4" />
                {copy.create}
              </Link>
            ) : undefined
          }
        />
      ) : (
        <FoldGroup className="space-y-8">
          {jobs.map((job) => (
            <JobNotes
              key={job.id}
              kind={kind}
              jobId={job.id}
              title={job.name}
              aside={<JobStatusPill job={job} />}
              hint={<JobHint job={job} links={links} />}
              canWrite={canWrite}
              refusal={writeReason ?? undefined}
              offered={offered}
              takeEffect={(now) => (kind === "campaign" ? notesTakeEffect(now, job.status) : lineNotesTakeEffect(now))}
            />
          ))}
        </FoldGroup>
      )}
    </Section>
  );
}

function JobHint({ job, links }: { job: LeadFieldsJob; links: JobLinks | null }): ReactNode {
  return (
    <span className="flex flex-wrap items-center gap-x-2">
      <span>In {job.agent_name}&apos;s voice.</span>
      {links && (
        <Link href={links.open(job.kind, job.id)} className="font-medium text-brand-strong hover:underline">
          {job.kind === "campaign" ? "Open campaign" : "Open line"}
        </Link>
      )}
    </span>
  );
}

