"use client";

import Link from "next/link";
import { ArrowRight, Check, ChevronRight, PhoneCall } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useStartFirstWork, type FirstRun } from "@/lib/api/firstRun";
import { useClientRealm } from "@/lib/api/session";
import { FIRST_WORKS, jobCard, workHref, type FirstWork, type FirstWorkJob, type JobCard } from "@/lib/firstAgent";

import { StepScreen } from "./shell";
import { FIRST } from "../../_ui/copy";

/**
 * STEP 3, WHAT FIRST? (Phase 3b, founder 16 Nov 2026): two cards. "Answer my calls" drafts an
 * inbound line in the agent's voice, with no number needed; "Call people" drafts a campaign.
 * Either way Pip writes what it says from the owner's words and saves it, and the step waits
 * on the screen until it has, so the test call has something to say.
 *
 * The card pressed is the server's (`run.jobs`); pressing the other drafts that work too, so
 * going back never loses a script already written.
 */
export function WorkStep({
  run,
  agent,
  work,
  onBack,
  onDone,
}: {
  run: FirstRun;
  agent: Agent;
  work: FirstWork | null;
  onBack: () => void;
  onDone: () => void;
}) {
  const { session, href } = useClientRealm();
  const start = useStartFirstWork(session);
  const startFeedback = useActionFeedback(start, { errorDisplay: "inline" });
  const chosen = (run.jobs[0] as FirstWorkJob | undefined) ?? null;
  // Pip was not available (no AI allowance left, or its draft failed), so the server gave the
  // work the ready-made script for its job (`first_run/work.save_ready_made`).
  const readyMade = run.build.steps.some((step) => step.step === "script" && step.state === "ready_made");
  const pick = (job: FirstWorkJob) => {
    if (job !== chosen || work === null) start.mutate({ job });
  };

  return (
    <StepScreen
      title={`What should ${agent.name} do first?`}
      hint={FIRST.workHint}
      onBack={onBack}
      primary={
        work?.ready ? (
          <>
            <PhoneCall aria-hidden className="h-4 w-4" />
            Hear it
          </>
        ) : undefined
      }
      status={startFeedback.status}
      onSubmit={onDone}
    >
      <fieldset className="space-y-2.5">
        <legend className="sr-only">Its first work</legend>
        {FIRST_WORKS.map((job) => {
          const card = jobCard(job);
          return card ? (
            <WorkChoice
              key={job}
              card={card}
              checked={chosen === job && work !== null}
              disabled={start.isPending}
              onChange={() => pick(job)}
            />
          ) : null;
        })}
      </fieldset>

      {work && !work.ready ? (
        work.failed ? (
          <div role="alert" className="space-y-2">
            <p className="text-body text-ink">{FIRST.workFailed}</p>
            <Link href={href(workHref(session.orgSlug, work))} className={SECONDARY_BUTTON}>
              Open it and write it
              <ArrowRight aria-hidden className="h-4 w-4" />
            </Link>
          </div>
        ) : (
          <p role="status" className="text-meta text-ink-muted">
            <span className="text-shimmer">{FIRST.workWriting}</span>
          </p>
        )
      ) : null}
      {work?.ready && readyMade ? (
        <div role="status" className="space-y-2">
          <p className="text-body text-ink">{FIRST.workReadyMade}</p>
          <Link href={href(workHref(session.orgSlug, work))} className={SECONDARY_BUTTON}>
            Change what it says
            <ArrowRight aria-hidden className="h-4 w-4" />
          </Link>
        </div>
      ) : work?.ready ? (
        <p role="status" className="inline-flex items-center gap-1.5 text-meta text-ink-muted">
          <Check aria-hidden className="h-3.5 w-3.5 text-brand-strong" />
          Written. Hear it next.
        </p>
      ) : null}

      {start.error ? <ProblemNotice error={start.error} /> : null}
    </StepScreen>
  );
}

/** One work as a card: its mark, name and line, then its three links. A real radio underneath. */
function WorkChoice({
  card,
  checked,
  disabled,
  onChange,
}: {
  card: JobCard;
  checked: boolean;
  disabled: boolean;
  onChange: () => void;
}) {
  const Icon = card.icon;
  return (
    <label
      className={`press relative block cursor-pointer rounded-card border px-4 py-2.5 transition-[border-color,box-shadow] duration-(--duration-fast) has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app has-[:disabled]:cursor-default ${
        checked ? CHOICE_ON : CHOICE_OFF
      }`}
    >
      <input
        type="radio"
        name="work"
        value={card.job}
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        className="sr-only"
      />
      <span className="flex items-start gap-3">
        <span
          aria-hidden
          className={`grid h-10 w-10 shrink-0 place-items-center rounded-[10px] transition-colors duration-(--duration-fast) ${
            checked ? "bg-brand-strong text-white" : "bg-brand-soft text-brand-strong"
          }`}
        >
          <Icon className="h-5 w-5" strokeWidth={1.75} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-body font-semibold text-ink">{card.title}</span>
          <span className="block text-meta text-ink-muted">{card.line}</span>
        </span>
      </span>
      {/* The flow repeats the line above as pictures, so it is hidden from the radio's name. */}
      <span aria-hidden className="mt-2 flex flex-wrap items-center gap-x-1 gap-y-1.5 sm:pl-[3.25rem]">
        {card.flow.map((link, index) => {
          const LinkIcon = link.icon;
          return (
            <span key={link.label} className="inline-flex items-center gap-1">
              {index > 0 ? <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ink-faint" /> : null}
              <span className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2 py-0.5 text-[12px] leading-5 text-ink-muted">
                <LinkIcon className="h-3 w-3 shrink-0 text-brand-strong" />
                {link.label}
              </span>
            </span>
          );
        })}
      </span>
    </label>
  );
}
