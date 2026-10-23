"use client";

import { Fragment, useState } from "react";
import { ArrowRight, Check, ChevronRight } from "lucide-react";

import { CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { ProblemNotice } from "@/components/ui";
import type { FirstRun, FirstRunJob } from "@/lib/api/firstRun";
import { useSaveJob } from "@/lib/api/firstRun";
import { useClientSession } from "@/lib/api/session";
import { defaultExtraLanguages } from "@/lib/agentState";
import {
  JOBS,
  LANGUAGES,
  jobPayload,
  jobsOf,
  languageGlyph,
  languageShortLabel,
  sortJobs,
  type JobCard,
} from "@/lib/firstAgent";

import { ChipChoice, StepScreen } from "./shell";

/**
 * STEP 1, ITS JOB (D-855; founder, 23 Oct 2026): what the agent does, then the language it
 * speaks.
 *
 * The jobs are a multiple choice: one agent does every job picked, with one voice and one
 * script that has a part for each. Each card shows its job as three things that happen, so
 * an owner who has never seen a voice agent can tell the jobs apart without reading a
 * paragraph. All are open on a free trial: a test call rings the owner from any ready agent
 * (D-853). Once the agent is built its jobs are fixed (the server refuses
 * `first_run_job_locked`), so the choice is shown, not offered.
 *
 * Languages are tiles carrying a syllable in their own script, so the owner finds theirs
 * by sight before reading its English name.
 */
export function JobStep({
  run,
  defaultLanguage,
  onDone,
}: {
  run: FirstRun;
  defaultLanguage: string;
  onDone: () => void;
}) {
  const session = useClientSession();
  const save = useSaveJob(session);
  const locked = run.agent_id !== null;
  const [jobs, setJobs] = useState<FirstRunJob[]>(() => jobsOf(run));
  const [primary, setPrimary] = useState(run.language_primary ?? defaultLanguage);
  const [extra, setExtra] = useState<string[]>(
    run.language_primary ? run.languages_extra : defaultExtraLanguages(defaultLanguage),
  );

  const choosePrimary = (tag: string) => {
    setPrimary(tag);
    setExtra((current) => current.filter((other) => other !== tag));
  };
  const toggleJob = (job: FirstRunJob, on: boolean) =>
    setJobs((current) => sortJobs(on ? [...current, job] : current.filter((chosen) => chosen !== job)));

  return (
    <StepScreen
      title="What should your agent do?"
      hint="Pick one or more. One agent does them all, and you can change this later."
      primary={
        <>
          {save.isPending ? "Saving…" : "Continue"}
          <ArrowRight aria-hidden className="h-4 w-4" />
        </>
      }
      disabled={jobs.length === 0}
      pending={save.isPending}
      onSubmit={() => {
        if (jobs.length === 0) return;
        save.mutate(jobPayload(jobs, primary, extra), { onSuccess: onDone });
      }}
    >
      <fieldset className="space-y-2.5">
        <legend className="sr-only">Its jobs</legend>
        {JOBS.filter((card) => !locked || jobs.includes(card.job)).map((card) => (
          <JobChoice
            key={card.job}
            card={card}
            checked={jobs.includes(card.job)}
            disabled={locked}
            onChange={(on) => toggleJob(card.job, on)}
          />
        ))}
        {locked ? (
          <p className="text-meta text-ink-muted">Your agent is built for this. Change what it does on its own page.</p>
        ) : null}
      </fieldset>

      <fieldset>
        <legend className="text-heading text-ink">Which language does it speak first?</legend>
        <p className="text-meta text-ink-muted">Every call starts in it.</p>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {LANGUAGES.map((language) => (
            <LanguageTile
              key={language.tag}
              tag={language.tag}
              checked={primary === language.tag}
              onChange={() => choosePrimary(language.tag)}
            />
          ))}
        </div>
      </fieldset>

      <fieldset className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <legend className="sr-only">It also speaks</legend>
        <span aria-hidden className="text-body font-medium text-ink">
          It also speaks
        </span>
        <div className="flex flex-wrap gap-2">
          {LANGUAGES.filter((language) => language.tag !== primary).map((language) => (
            <ChipChoice
              key={language.tag}
              type="checkbox"
              name="also"
              value={language.tag}
              size="sm"
              checked={extra.includes(language.tag)}
              onChange={(on) =>
                setExtra((current) => (on ? [...current, language.tag] : current.filter((tag) => tag !== language.tag)))
              }
            >
              <span lang={language.tag} aria-hidden className="font-semibold">
                {languageGlyph(language.tag)}
              </span>
              {languageShortLabel(language.tag)}
            </ChipChoice>
          ))}
        </div>
        <span className="text-meta text-ink-muted">It switches when a caller does.</span>
      </fieldset>

      {save.error ? <ProblemNotice error={save.error} /> : null}
    </StepScreen>
  );
}

/** One job as a card: its mark, name and line, then its three links. A real checkbox
 *  underneath, so the group is one tab stop per card and a screen reader says "checked". */
function JobChoice({
  card,
  checked,
  disabled,
  onChange,
}: {
  card: JobCard;
  checked: boolean;
  disabled: boolean;
  onChange: (on: boolean) => void;
}) {
  const Icon = card.icon;
  return (
    <label
      className={`press relative block cursor-pointer rounded-card border px-4 py-2.5 transition-[border-color,box-shadow] duration-(--duration-fast) has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app has-[:disabled]:cursor-default ${
        checked ? CHOICE_ON : CHOICE_OFF
      }`}
    >
      <input
        type="checkbox"
        name="job"
        value={card.job}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
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
          <span className="block text-meta text-ink-muted max-sm:sr-only">{card.line}</span>
        </span>
        <span
          aria-hidden
          className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-[5px] border-[1.5px] transition-colors duration-(--duration-fast) ${
            checked ? "border-brand-strong bg-brand-strong text-white" : "border-ink/30"
          }`}
        >
          {checked ? <Check className="h-3 w-3" strokeWidth={3} /> : null}
        </span>
      </span>
      {/* The flow repeats the line above as pictures, so it is hidden from the checkbox's name. */}
      <span aria-hidden className="mt-2 flex flex-wrap items-center gap-x-1 gap-y-1.5 sm:pl-[3.25rem]">
        {card.flow.map((link, index) => {
          const LinkIcon = link.icon;
          return (
            <Fragment key={link.label}>
              {index > 0 ? <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-ink-faint" /> : null}
              <span
                aria-hidden
                className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2 py-0.5 text-[12px] leading-5 text-ink-muted"
              >
                <LinkIcon className="h-3 w-3 shrink-0 text-brand-strong" />
                {link.label}
              </span>
            </Fragment>
          );
        })}
      </span>
    </label>
  );
}

/** A language as a tile: its own script's syllable, then its name. */
function LanguageTile({ tag, checked, onChange }: { tag: string; checked: boolean; onChange: () => void }) {
  return (
    <label
      className={`press flex min-h-12 min-w-0 cursor-pointer items-center gap-2.5 rounded-card border px-2.5 py-2 transition-[border-color,box-shadow] duration-(--duration-fast) has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 ${
        checked ? CHOICE_ON : CHOICE_OFF
      }`}
    >
      <input type="radio" name="language" value={tag} checked={checked} onChange={onChange} className="sr-only" />
      <span
        aria-hidden
        lang={tag}
        className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg text-[15px] font-semibold transition-colors duration-(--duration-fast) ${
          checked ? "bg-brand-strong text-white" : "bg-brand-soft text-brand-strong"
        }`}
      >
        {languageGlyph(tag)}
      </span>
      <span className={`min-w-0 truncate text-body ${checked ? "font-semibold text-ink" : "text-ink"}`}>
        {languageShortLabel(tag)}
      </span>
    </label>
  );
}
