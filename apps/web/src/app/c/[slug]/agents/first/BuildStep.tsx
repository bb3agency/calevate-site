"use client";

import { useId, useState } from "react";
import { ArrowRight, Pencil, RotateCcw } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { FIELD_INLINE, ProblemNotice } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useBuildAgent, useRenameAgent, type FirstRun, type FirstRunBuildStep } from "@/lib/api/firstRun";
import { useClientSession } from "@/lib/api/session";
import { languageLabel, voicePickNote } from "@/lib/firstAgent";

import { BuildStage, type BuildRow, type RowState } from "./LiveStage";
import { StepScreen } from "./shell";

/** Each step's name on the stage, and what it says while it is worked on, in the order the
 *  worker takes them (`apps/workers/first_run.build_first_agent`). */
function wordsOf(step: FirstRunBuildStep["step"], language: string): { title: string; doing: string } {
  switch (step) {
    case "voice":
      return {
        title: "Voice",
        doing: `Choosing a voice for ${languageLabel(language)}`,
      };
    case "script":
      return {
        title: "Script",
        doing: "Writing its script from what you said",
      };
    case "greeting":
      return { title: "Greeting", doing: "Writing how it opens each call" };
    default:
      return { title: "AI notice", doing: "Adding its AI notice" };
  }
}

/** The words the picture carries for a finished step: the voice's name and band. */
export function tagOf(step: FirstRunBuildStep): string | undefined {
  if (step.step !== "voice" || step.state !== "done") return undefined;
  const rung = step.rung === "studio" ? "Studio" : step.rung === "clear" ? "Clear" : null;
  return [step.label, rung].filter(Boolean).join(" · ") || undefined;
}

/** The line under a finished step: what really happened, including the fallbacks. */
export function metaOf(step: FirstRunBuildStep): string | undefined {
  if (step.step === "voice") {
    if (step.state === "done") {
      const rung = step.rung === "studio" ? "Studio" : step.rung === "clear" ? "Clear" : null;
      const name = [step.label, rung].filter(Boolean).join(" · ");
      return [name, voicePickNote(step.fallback, step.not_female)].filter(Boolean).join(". ") || undefined;
    }
    if (step.state === "kept") return "Kept the voice it had";
    if (step.state === "none") return "None could be chosen yet. Pick one before the call.";
  }
  if (step.step === "script")
    return step.state === "ready_made"
      ? "Started from the ready-made script for your trade"
      : "Written from what you said";
  if (step.step === "greeting" && step.state === "ready_made") return "The tried and tested greeting for its language";
  if (step.step === "greeting") return "Short, and ends on a question";
  if (step.step === "notice") {
    if (step.state === "done") return "Said right after its greeting on every call";
    if (step.state === "off") return "Kept off, as you set it";
    if (step.state === "no_room") return "No room after its greeting. Shorten the greeting to add it.";
  }
  return undefined;
}

/** A step's state on the stage. The worker works on one step at a time, in order, so the
 *  first one still waiting while the build runs is the one being worked on. */
export function rowStateOf(step: FirstRunBuildStep, working: boolean, failed: boolean): RowState {
  if (step.state === "none" || step.state === "no_room") return "warn";
  if (step.state !== "waiting") return "done";
  if (working) return failed ? "failed" : "working";
  return "waiting";
}

/**
 * THE BUILD, LIVE (D-855; founder, 23 Oct 2026): the real steps on the dark stage, each one
 * moving when the worker finishes it, never on a timer. Once built, the owner meets the
 * agent by name and can rename it before its first call; the name is the one it gives on the
 * call.
 */
export function BuildStep({
  run,
  agent,
  onBack,
  onDone,
}: {
  run: FirstRun;
  agent: Agent | null;
  onBack: () => void;
  onDone: () => void;
}) {
  const session = useClientSession();
  const retry = useBuildAgent(session);
  const retryFeedback = useActionFeedback(retry, { errorDisplay: "inline" });
  const language = run.language_primary ?? "te-IN";
  const built = run.build.status === "built";
  const failed = run.build.status === "failed";
  const firstWaiting = run.build.steps.findIndex((step) => step.state === "waiting");
  const rows: BuildRow[] = run.build.steps.map((step, index) => ({
    step: step.step,
    ...wordsOf(step.step, language),
    result: metaOf(step),
    tag: tagOf(step),
    state: rowStateOf(step, !built && index === firstWaiting, failed),
  }));

  return (
    <StepScreen
      title={built && agent ? `Meet ${agent.name}` : failed ? "The build stopped" : "Building your agent"}
      hint={
        built
          ? "Version one is ready. Next, it rings your phone so you can hear it."
          : failed
            ? "Nothing you wrote is lost."
            : "A few seconds. Each part appears as it is made."
      }
      onBack={built || failed ? onBack : undefined}
      primary={
        built ? (
          <>
            Hear it on my phone
            <ArrowRight aria-hidden className="h-4 w-4" />
          </>
        ) : undefined
      }
      onSubmit={onDone}
    >
      <BuildStage
        rows={rows}
        name={agent?.name ?? null}
        greeting={agent?.script_opening_line?.trim() || null}
        greetingLang={language}
        built={built}
        failed={failed}
        footer={
          failed ? (
            run.build.builds_left > 0 ? (
              <ActionButton
                status={retryFeedback.status}
                pendingLabel="Starting again…"
                successLabel="Started"
                onClick={() => retryFeedback.run(null)}
              >
                <RotateCcw aria-hidden className="h-4 w-4" />
                Try again
              </ActionButton>
            ) : (
              <p className="text-meta text-ink-muted">Build it from the Agents screen instead.</p>
            )
          ) : null
        }
      />
      {retry.error ? <ProblemNotice error={retry.error} /> : null}
      {built && agent ? <Rename agent={agent} /> : null}
      {run.build.disclosure ? <p className="text-meta text-ink-faint">{run.build.disclosure}</p> : null}
    </StepScreen>
  );
}

/** The agent's name, renameable before its first call. */
function Rename({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const rename = useRenameAgent(session);
  const renameFeedback = useActionFeedback(rename, { errorDisplay: "inline" });
  const id = useId();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(agent.name);
  if (agent.status !== "draft") return null;
  if (!editing) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <p className="text-body text-ink-muted">
          It introduces itself as <span className="font-medium text-ink">{agent.name}</span>.
        </p>
        <button type="button" className={TEXT_ACTION} onClick={() => setEditing(true)}>
          <Pencil aria-hidden className="h-3.5 w-3.5" />
          Change its name
        </button>
      </div>
    );
  }
  const clean = name.trim();
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="text-heading text-ink">
        Its name
      </label>
      <div className="flex flex-wrap gap-2">
        <input
          id={id}
          value={name}
          maxLength={60}
          autoComplete="off"
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            // The step's own form would take Enter as "Hear it".
            if (event.key === "Enter") {
              event.preventDefault();
              if (clean && !rename.isPending) rename.mutate({ name: clean }, { onSuccess: () => setEditing(false) });
            }
          }}
          className={`${FIELD_INLINE} flex-1 basis-48 text-[16px]`}
        />
        <ActionButton
          variant="secondary"
          status={renameFeedback.status}
          successLabel="Saved"
          disabled={!clean || clean === agent.name}
          onClick={() => rename.mutate({ name: clean }, { onSuccess: () => setEditing(false) })}
        >
          Save name
        </ActionButton>
      </div>
      {rename.error ? <ProblemNotice error={rename.error} /> : null}
    </div>
  );
}
