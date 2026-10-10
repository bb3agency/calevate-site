"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Check, Circle, SkipForward } from "lucide-react";

import { ProgressBar } from "@/components/interior/progress-bar";
import { SectionEditor, stepProblem } from "@/components/businessProfile/SectionEditor";
import {
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import {
  STEPS,
  draftFromProfile,
  fieldMessage,
  stepStates,
  toPatch,
  useBusinessProfile,
  useSaveBusinessProfile,
  useSetupAction,
  type BusinessProfile,
  type ProfileDraft,
  type StepId,
} from "@/lib/api/businessProfile";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { SetupDone } from "./SetupDone";

const EASE = [0.23, 1, 0.32, 1] as const;

/**
 * Business setup: the guided wizard a client meets on first login (D-695).
 *
 * Primary job: get the business's facts in, one topic per step, every step skippable.
 * Progress is the server's (`setup.steps`), so a client who leaves on step 3 resumes on
 * step 3 from any device, and the dashboard checklist reads the same states.
 *
 * Only BUSINESS facts are asked. What each agent says, its voice and its language stay on
 * the agent's own screens.
 */
export function SetupWizard() {
  const { session, href: realmHref } = useClientRealm();
  // Paths below are relative to this account: "/setup" is /c/<slug>/setup.
  const href = (path: string) => realmHref(`/c/${session.orgSlug}${path}`);
  const profile = useBusinessProfile(session);
  const write = useWriteAccess(session, "org:manage", "fill in the business profile");

  useCopilotSurface({
    route: "/c/{slug}/setup",
    title: "Business setup",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: profile.data ? "the setup steps have loaded" : profile.error ? "the setup failed to load" : "still loading",
      },
    ],
    apply: noFill,
  });

  if (profile.isPending) return <Skeleton rows={6} />;
  if (profile.isError)
    return <ProblemNotice error={profile.error} onRetry={() => void profile.refetch()} />;
  return <Wizard profile={profile.data} canWrite={write.allowed} reason={write.reason} href={href} />;
}

function Wizard({
  profile,
  canWrite,
  reason,
  href,
}: {
  profile: BusinessProfile;
  canWrite: boolean;
  reason: string | null;
  href: (path: string) => string;
}) {
  const { session } = useClientRealm();
  const router = useRouter();
  const params = useSearchParams();
  const save = useSaveBusinessProfile(session);
  const setup = useSetupAction(session);
  const reduced = useReducedMotion();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);

  // Seeded once: a refetch must never overwrite what the client is typing.
  const [draft, setDraft] = useState<ProfileDraft>(() => draftFromProfile(profile));
  const requested = params.get("step");
  const firstTodo = profile.setup.steps.findIndex((step) => step.state === "todo");
  const [index, setIndex] = useState(() => {
    const asked = STEPS.findIndex((step) => step.id === requested);
    if (asked >= 0) return asked;
    return firstTodo >= 0 ? firstTodo : STEPS.length;
  });
  const [direction, setDirection] = useState<1 | -1>(1);

  // Opening the wizard is what stops the dashboard sending a client here again.
  const started = useRef(false);
  useEffect(() => {
    if (started.current || profile.setup.started || !canWrite) return;
    started.current = true;
    setup.mutate({ action: "start" });
  }, [canWrite, profile.setup.started, setup]);

  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    headingRef.current?.focus();
  }, [index]);

  const states = stepStates(profile);
  const done = profile.setup.steps.filter((step) => step.state !== "todo").length;
  const go = (to: number) => {
    moved.current = true;
    setDirection(to > index ? 1 : -1);
    save.reset();
    setIndex(to);
    const step = STEPS[to];
    router.replace(href(step ? `/setup?step=${step.id}` : "/setup"), { scroll: false });
  };

  const step = STEPS[index];
  const problem = step ? stepProblem(draft, step.id) : null;
  const fields = save.error instanceof ApiProblem ? save.error.fields : undefined;
  const busy = save.isPending || setup.isPending;

  const saveAndNext = () => {
    if (!step || problem) return;
    save.mutate(toPatch(draft, step.id), { onSuccess: () => go(index + 1) });
  };
  const skip = () => {
    if (!step) return;
    if (!canWrite) return go(index + 1);
    setup.mutate({ action: "skip", step: step.id }, { onSuccess: () => go(index + 1) });
  };

  return (
    <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-[14rem_1fr]">
      <nav aria-label="Setup steps" className="hidden lg:block">
        <ProgressBar value={done} max={STEPS.length} label={`${done} of ${STEPS.length} done`} />
        <ol className="mt-4 space-y-0.5">
          {STEPS.map((item, i) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => go(i)}
                aria-current={i === index ? "step" : undefined}
                className={`press flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-meta focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                  i === index ? "bg-ink/[0.05] font-medium text-ink" : "text-ink-muted hover:text-ink"
                }`}
              >
                <StepMark state={states[item.id]} />
                <span className="min-w-0 truncate">{item.short}</span>
              </button>
            </li>
          ))}
        </ol>
      </nav>

      <div className="min-w-0">
        <p className="mb-3 text-meta tabular-nums text-ink-muted lg:hidden">
          {step ? `Step ${index + 1} of ${STEPS.length}` : "All steps seen"}
        </p>
        {reason && <RestrictionNote reason={reason} />}
        <AnimatePresence mode="wait" initial={false} custom={direction}>
          <motion.section
            key={step?.id ?? "done"}
            custom={direction}
            initial={reduced ? { opacity: 0 } : { opacity: 0, x: direction * 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, x: direction * -16 }}
            transition={{ duration: reduced ? 0 : 0.2, ease: EASE }}
            className="py-2"
          >
            {step ? (
              <form
                noValidate
                onSubmit={(event) => {
                  event.preventDefault();
                  saveAndNext();
                }}
                className="space-y-5"
              >
                <div>
                  <h2 ref={headingRef} tabIndex={-1} className="text-heading text-ink focus-visible:outline-none">
                    {step.title}
                  </h2>
                  <p className="mt-1 text-body text-ink-muted">{step.hint}</p>
                </div>
                <fieldset disabled={!canWrite || busy} className="min-w-0">
                  <SectionEditor
                    step={step.id}
                    draft={draft}
                    onChange={setDraft}
                    disabled={!canWrite}
                    errorAt={(path) => fieldMessage(fields, path)}
                    vertical={profile.vertical_template ?? null}
                  />
                </fieldset>
                {problem && (
                  <p role="alert" className="text-meta font-medium text-danger">
                    {problem}
                  </p>
                )}
                {save.error && <ProblemNotice error={save.error} />}
                {setup.error && <ProblemNotice error={setup.error} />}
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4">
                  <div className="flex gap-2">
                    {index > 0 && (
                      <button type="button" onClick={() => go(index - 1)} disabled={busy} className={SECONDARY_BUTTON}>
                        Back
                      </button>
                    )}
                    <button type="button" onClick={skip} disabled={busy} className={SECONDARY_BUTTON}>
                      <SkipForward aria-hidden className="h-4 w-4" />
                      Skip
                    </button>
                  </div>
                  <button
                    type="submit"
                    disabled={!canWrite || busy || Boolean(problem)}
                    aria-busy={save.isPending || undefined}
                    className={PRIMARY_BUTTON}
                  >
                    {save.isPending ? "Saving…" : index === STEPS.length - 1 ? "Save and finish" : "Save and continue"}
                  </button>
                </div>
              </form>
            ) : (
              <SetupDone profile={profile} href={href} onOpen={(id: StepId) => go(STEPS.findIndex((s) => s.id === id))} />
            )}
          </motion.section>
        </AnimatePresence>
        <p className="mt-3 text-meta text-ink-muted">
          You can change any answer later in{" "}
          <Link href={href("/settings/business")} className="font-medium text-brand-strong hover:underline">
            Business profile
          </Link>
          .
        </p>
      </div>
    </div>
  );
}

function StepMark({ state }: { state: "done" | "skipped" | "todo" | undefined }) {
  if (state === "done")
    return (
      <span aria-label="Done" className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-brand-strong text-white">
        <Check aria-hidden className="h-2.5 w-2.5" strokeWidth={3} />
      </span>
    );
  if (state === "skipped")
    return <SkipForward aria-label="Skipped" className="h-4 w-4 shrink-0 text-ink-faint" />;
  return <Circle aria-label="To do" className="h-4 w-4 shrink-0 text-ink/25" />;
}
