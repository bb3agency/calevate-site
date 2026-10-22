"use client";

import { useId, useState } from "react";
import { ArrowRight } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { TaskSteps, type TaskStep } from "@/components/interior/task-steps";
import { FIELD, ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useBuildAgent, useRenameAgent, type FirstRun, type FirstRunBuildStep } from "@/lib/api/firstRun";
import { useClientSession } from "@/lib/api/session";
import { languageLabel, studioFallbackLine } from "@/lib/firstAgent";

import { StepScreen } from "./shell";

/** What each step says while it is worked on and once done, in the order the worker takes
 *  them (`apps/workers/first_run.build_first_agent`). */
function labelOf(step: FirstRunBuildStep["step"], language: string): string {
  switch (step) {
    case "voice":
      return `Choosing a voice for ${languageLabel(language)}`;
    case "script":
      return "Writing its script from what you said";
    case "greeting":
      return "Writing its greeting";
    default:
      return "Adding its AI notice";
  }
}

/** The line under a finished step: what really happened, including the fallbacks. */
export function metaOf(step: FirstRunBuildStep): string | undefined {
  if (step.step === "voice") {
    if (step.state === "done") {
      const rung = step.rung === "studio" ? "Studio" : step.rung === "clear" ? "Clear" : null;
      const name = [step.label, rung].filter(Boolean).join(" · ");
      return [name, studioFallbackLine(step.fallback)].filter(Boolean).join(". ") || undefined;
    }
    if (step.state === "kept") return "Kept the voice it had";
    if (step.state === "none") return "None could be chosen yet. Pick one before the call.";
  }
  if (step.step === "script" && step.state === "ready_made") return "Started from the ready-made script for your trade";
  if (step.step === "greeting" && step.state === "ready_made") return "The tried and tested greeting for its language";
  if (step.step === "notice" && step.state === "done") return "It always says it is an AI when asked";
  return undefined;
}

/**
 * THE BUILD, SHOWN (D-855): the real steps, ticked as the worker finishes each one.
 *
 * Nothing here is timed for effect: a step ticks when the server says it is done. Once
 * built, the owner meets the agent by name and can rename it before its first call; the
 * name is the one it gives on the call.
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
  const language = run.language_primary ?? "te-IN";
  const steps: TaskStep[] = run.build.steps.map((step) => ({
    id: step.step,
    label: labelOf(step.step, language),
    meta: metaOf(step),
  }));
  const firstWaiting = run.build.steps.findIndex((step) => step.state === "waiting");
  const built = run.build.status === "built";
  const failed = run.build.status === "failed";
  const current = built ? steps.length : firstWaiting === -1 ? steps.length - 1 : firstWaiting;

  return (
    <StepScreen
      title={built && agent ? `Meet ${agent.name}` : failed ? "The build stopped" : "Building your agent"}
      hint={
        built
          ? "Version one is ready. Hear it on your own phone next."
          : failed
            ? "Nothing you wrote is lost."
            : "This takes a few seconds."
      }
      onBack={built ? onBack : undefined}
      primary={
        built ? (
          <>
            Hear it
            <ArrowRight aria-hidden className="h-4 w-4" />
          </>
        ) : undefined
      }
      onSubmit={onDone}
    >
      <TaskSteps steps={steps} current={current} failed={failed} size="md" label="Building your agent" />
      {failed ? (
        <div className="space-y-2">
          {run.build.builds_left > 0 ? (
            <button type="button" className={SECONDARY_BUTTON} disabled={retry.isPending} onClick={() => retry.mutate(null)}>
              Try again
            </button>
          ) : (
            <p className="text-meta text-ink-muted">Build it from the Agents screen instead.</p>
          )}
          {retry.error ? <ProblemNotice error={retry.error} /> : null}
        </div>
      ) : null}
      {built && agent ? <Rename agent={agent} /> : null}
      {run.build.disclosure ? <p className="text-meta text-ink-faint">{run.build.disclosure}</p> : null}
    </StepScreen>
  );
}

/** The agent's name, renameable before its first call. */
function Rename({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const rename = useRenameAgent(session);
  const id = useId();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(agent.name);
  if (agent.status !== "draft") return null;
  if (!editing) {
    return (
      <p className="text-body text-ink-muted">
        It introduces itself as <span className="font-medium text-ink">{agent.name}</span>.{" "}
        <button type="button" className={TEXT_ACTION} onClick={() => setEditing(true)}>
          Change its name
        </button>
      </p>
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
              if (clean) rename.mutate({ name: clean }, { onSuccess: () => setEditing(false) });
            }
          }}
          className={`${FIELD} min-w-0 flex-1 basis-48 text-[16px]`}
        />
        <button
          type="button"
          className={SECONDARY_BUTTON}
          disabled={!clean || clean === agent.name || rename.isPending}
          onClick={() => rename.mutate({ name: clean }, { onSuccess: () => setEditing(false) })}
        >
          {rename.isPending ? "Saving…" : "Save name"}
        </button>
      </div>
      {rename.error ? <ProblemNotice error={rename.error} /> : null}
    </div>
  );
}
