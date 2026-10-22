"use client";

import { useState } from "react";
import { ArrowRight } from "lucide-react";

import { ProblemNotice } from "@/components/ui";
import type { FirstRun, FirstRunJob } from "@/lib/api/firstRun";
import { useSaveJob } from "@/lib/api/firstRun";
import { useClientSession } from "@/lib/api/session";
import { defaultExtraLanguages } from "@/lib/agentState";
import { JOBS, LANGUAGES } from "@/lib/firstAgent";

import { ChipChoice, ChoiceCard, StepScreen } from "./shell";

/**
 * STEP 1, ITS JOB (D-855): what the agent does, then the language it speaks.
 *
 * Three jobs, each with a three-step picture of what happens, all open on a free trial: a
 * test call rings the owner from any ready agent (D-853). Once the agent is built its job is
 * fixed (the server refuses `first_run_job_locked`), so the choice is shown, not offered.
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
  const [job, setJob] = useState<FirstRunJob | null>(run.job);
  const [primary, setPrimary] = useState(run.language_primary ?? defaultLanguage);
  const [extra, setExtra] = useState<string[]>(
    run.language_primary ? run.languages_extra : defaultExtraLanguages(defaultLanguage),
  );

  const choosePrimary = (tag: string) => {
    setPrimary(tag);
    setExtra((current) => current.filter((other) => other !== tag));
  };

  return (
    <StepScreen
      title="What should your agent do?"
      hint="Pick its main job. You can change everything else later."
      primary={
        <>
          {save.isPending ? "Saving…" : "Continue"}
          <ArrowRight aria-hidden className="h-4 w-4" />
        </>
      }
      disabled={job === null}
      pending={save.isPending}
      onSubmit={() => {
        if (job === null) return;
        save.mutate({ job, language_primary: primary, languages_extra: extra }, { onSuccess: onDone });
      }}
    >
      <fieldset className="space-y-3">
        <legend className="sr-only">Its job</legend>
        {JOBS.filter((card) => !locked || card.job === run.job).map((card) => (
          <ChoiceCard
            key={card.job}
            type="radio"
            name="job"
            value={card.job}
            checked={job === card.job}
            onChange={(on) => {
              if (on) setJob(card.job);
            }}
          >
            <span className="block text-heading text-ink">{card.title}</span>
            <span className="mt-0.5 block text-meta text-ink-muted">{card.line}</span>
            <span className="mt-3 grid gap-1 rounded-md bg-ink/[0.03] px-3 py-2 text-meta text-ink-muted">
              {card.chips.map((chip, index) => (
                <span key={chip} className="flex items-center gap-2">
                  <span
                    aria-hidden
                    className="grid h-4 w-4 shrink-0 place-items-center rounded-full border border-ink/20 text-[10px] tabular-nums text-ink-muted"
                  >
                    {index + 1}
                  </span>
                  {chip}
                </span>
              ))}
            </span>
          </ChoiceCard>
        ))}
        {locked ? (
          <p className="text-meta text-ink-muted">Your agent is built for this job. Change what it does on its own page.</p>
        ) : null}
      </fieldset>

      <fieldset>
        <legend className="text-heading text-ink">Which language does it speak first?</legend>
        <p className="mt-0.5 text-meta text-ink-muted">Every call starts in this language.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {LANGUAGES.map((language) => (
            <ChipChoice
              key={language.tag}
              type="radio"
              name="language"
              value={language.tag}
              checked={primary === language.tag}
              onChange={(on) => on && choosePrimary(language.tag)}
            >
              {language.label}
            </ChipChoice>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-heading text-ink">It also speaks</legend>
        <p className="mt-0.5 text-meta text-ink-muted">It switches when a caller does.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {LANGUAGES.filter((language) => language.tag !== primary).map((language) => (
            <ChipChoice
              key={language.tag}
              type="checkbox"
              name="also"
              value={language.tag}
              checked={extra.includes(language.tag)}
              onChange={(on) =>
                setExtra((current) => (on ? [...current, language.tag] : current.filter((tag) => tag !== language.tag)))
              }
            >
              {language.label}
            </ChipChoice>
          ))}
        </div>
      </fieldset>

      {save.error ? <ProblemNotice error={save.error} /> : null}
    </StepScreen>
  );
}
