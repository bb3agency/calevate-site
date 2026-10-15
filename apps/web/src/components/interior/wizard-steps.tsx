"use client";

// Adapted from interior.dev (github.com/ddoemonn/interior @3148000), MIT License,
// Copyright (c) 2026 ozzy. Full notice: ./LICENSE.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

const EASE = [0.23, 1, 0.32, 1] as const;
const EXIT_EASE = [0.4, 0, 1, 1] as const;

const RAIL = { type: "spring", stiffness: 520, damping: 40, mass: 0.5 } as const;
const CROSSFADE = { type: "spring", stiffness: 260, damping: 34, mass: 0.8 } as const;

export type WizardDirection = 1 | -1;

export type UseWizardOptions = {
  total: number;
  index?: number;
  defaultIndex?: number;
  onIndexChange?: (index: number, direction: WizardDirection) => void;
  onComplete?: () => void;
};

export type UseWizardReturn = {
  index: number;
  direction: WizardDirection;
  furthest: number;
  total: number;
  isFirst: boolean;
  isLast: boolean;
  next: () => void;
  back: () => void;
  goTo: (index: number) => void;
};

function clampIndex(value: number, total: number) {
  if (total < 1) return 0;
  return Math.max(0, Math.min(total - 1, Math.trunc(value)));
}

export function useWizard({
  total,
  index,
  defaultIndex = 0,
  onIndexChange,
  onComplete,
}: UseWizardOptions): UseWizardReturn {
  const [internal, setInternal] = useState(() => clampIndex(defaultIndex, total));
  const current = clampIndex(index ?? internal, total);

  const [seen, setSeen] = useState<{ index: number; direction: WizardDirection }>({
    index: current,
    direction: 1,
  });
  if (seen.index !== current) {
    setSeen({ index: current, direction: current > seen.index ? 1 : -1 });
  }

  const [furthest, setFurthest] = useState(current);
  if (furthest < current) setFurthest(current);

  const emit = useRef(onIndexChange);
  emit.current = onIndexChange;
  const finish = useRef(onComplete);
  finish.current = onComplete;

  const controlled = index !== undefined;

  const goTo = useCallback(
    (to: number) => {
      const target = clampIndex(to, total);
      if (target === current) return;
      const direction: WizardDirection = target > current ? 1 : -1;
      if (!controlled) setInternal(target);
      emit.current?.(target, direction);
    },
    [controlled, current, total],
  );

  const next = useCallback(() => {
    if (current >= total - 1) {
      finish.current?.();
      return;
    }
    goTo(current + 1);
  }, [current, goTo, total]);

  const back = useCallback(() => goTo(current - 1), [current, goTo]);

  return {
    index: current,
    direction: seen.direction,
    furthest: Math.min(furthest, Math.max(total - 1, 0)),
    total,
    isFirst: current === 0,
    isLast: current === total - 1,
    next,
    back,
    goTo,
  };
}

export type WizardStep = {
  id: string;
  label: string;
  content: ReactNode;
};

export type WizardStepsProps = {
  steps: WizardStep[];
  index?: number;
  defaultIndex?: number;
  onIndexChange?: (index: number, direction: WizardDirection) => void;
  onComplete?: () => void;

  complete?: boolean;
  /**
   * A fixed panel height in px (the original catalogue shape, for short steps), or
   * "auto": the panel is as tall as its step, which a real form step needs.
   */
  height?: number | "auto";
  /**
   * Asked before Next moves on (and before Finish runs). Return false to stay, after
   * showing the step's own errors: the gate the catalogue copy lacked.
   */
  canAdvance?: (index: number) => boolean;
  /** Draw the panel without its card (border, shadow, inset), on the page's own ground. */
  framed?: boolean;
  /** Finish is in flight: the button stays put, disabled, saying so. */
  finishing?: boolean;
  finishingLabel?: string;
  /** Disables Next and Finish, e.g. while the person may not write. */
  advanceDisabled?: boolean;
  /** Rendered between Back and Next, e.g. a Cancel text action. */
  extraActions?: ReactNode;
  /** The current step's name above the rail. Off when each step heads itself. */
  showCurrentLabel?: boolean;
  backLabel?: string;
  nextLabel?: string;
  finishLabel?: string;
  completeLabel?: string;
  completeHint?: string;
  label?: string;
  className?: string;
};

export function WizardSteps({
  steps,
  index,
  defaultIndex = 0,
  onIndexChange,
  onComplete,
  complete = false,
  height = 184,
  canAdvance,
  framed = true,
  finishing = false,
  finishingLabel = "Working…",
  advanceDisabled = false,
  extraActions,
  showCurrentLabel = true,
  backLabel = "Back",
  nextLabel = "Next",
  finishLabel = "Finish",
  completeLabel = "All set",
  completeHint = "Step back to change anything",
  label = "Steps",
  className = "",
}: WizardStepsProps) {
  const wizard = useWizard({
    total: steps.length,
    index,
    defaultIndex,
    onIndexChange,
    onComplete,
  });
  const reduced = useReducedMotion();

  const listRef = useRef<HTMLOListElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const intent = useRef<"list" | "panel" | null>(null);

  const { index: at, direction, furthest, total, isFirst, isLast, next, back, goTo } = wizard;

  useEffect(() => {
    const move = intent.current;
    intent.current = null;
    if (move === "list") {
      listRef.current
        ?.querySelector<HTMLButtonElement>('button[data-current="true"]')
        ?.focus();
      return;
    }
    if (move === "panel") viewportRef.current?.focus({ preventScroll: true });
  }, [at]);

  const variants = useMemo(
    () => ({
      enter: (d: WizardDirection) => (reduced ? { opacity: 0 } : { opacity: 0, x: d * 22 }),
      center: reduced ? { opacity: 1 } : { opacity: 1, x: 0 },
      exit: (d: WizardDirection) =>
        reduced
          ? { opacity: 0, transition: { duration: 0 } }
          : {
              opacity: 0,
              x: d * -22,
              transition: { duration: 0.14, ease: EXIT_EASE },
            },
    }),
    [reduced],
  );

  const panelTransition = reduced ? { duration: 0 } : CROSSFADE;

  const onStepKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    let target = at;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") target = at + 1;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") target = at - 1;
    else if (e.key === "Home") target = 0;
    else if (e.key === "End") target = furthest;
    else return;
    e.preventDefault();
    target = Math.min(clampIndex(target, total), furthest);
    if (target === at) return;
    intent.current = "list";
    goTo(target);
  };

  const step = steps[at];
  if (!step) return null;
  const auto = height === "auto";
  const advance = () => {
    if (canAdvance && !canAdvance(at)) return;
    if (!isLast) intent.current = "panel";
    next();
  };

  const position = `Step ${at + 1} of ${total}: ${step.label}`;

  return (
    <div className={`w-full ${className}`}>
      <p aria-live="polite" className="sr-only">
        {position}
      </p>
      {showCurrentLabel && (
      <span
        aria-hidden
        className="mb-2 grid select-none text-[13px] font-medium text-ink"
      >
        {steps.map((s, i) => (
          <motion.span
            key={s.id}
            className="col-start-1 row-start-1 truncate"
            initial={false}
            animate={{ opacity: i === at ? 1 : 0 }}
            transition={reduced ? { duration: 0 } : CROSSFADE}
          >
            {s.label}
          </motion.span>
        ))}
      </span>
      )}
      <ol
        ref={listRef}
        aria-label={label}
        className="mb-4 flex list-none items-center gap-1 p-0"
      >
        {steps.map((s, i) => {
          const done = complete || i < at;
          const here = !complete && i === at;

          const tile = (
            <motion.span
              aria-hidden
              className={`grid size-7 place-items-center rounded-[8px] border text-[11.5px] font-medium tabular-nums transition-colors duration-150 ${
                done
                  ? "border-brand-strong bg-brand-strong text-white"
                  : here
                    ? "border-line bg-surface text-ink"
                    : "border-line bg-surface text-ink-faint"
              }`}
              initial={false}
              animate={{ scale: here ? 1 : 0.92 }}
              transition={reduced ? { duration: 0 } : RAIL}
            >
              {done ? (
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 256 256"
                  fill="none"
                  aria-hidden="true"
                >
                  <polyline
                    points="216 72 104 184 48 128"
                    stroke="currentColor"
                    strokeWidth="24"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              ) : (
                i + 1
              )}
            </motion.span>
          );

          const name = (
            <span
              aria-hidden
              className={`hidden whitespace-nowrap pl-2 pr-1 text-[13px] sm:inline ${
                here ? "font-medium text-ink" : done ? "text-ink-muted" : "text-ink-faint"
              }`}
            >
              {s.label}
            </span>
          );

          return (
            <li key={s.id} className="flex flex-1 items-center gap-1 last:flex-none">

              {i <= furthest ? (
                <button
                  type="button"
                  data-current={here ? "true" : undefined}
                  tabIndex={here ? 0 : -1}
                  aria-current={here ? "step" : undefined}
                  aria-label={`Step ${i + 1} of ${total}: ${s.label}`}
                  onKeyDown={onStepKeyDown}
                  onClick={() => {
                    if (here) return;
                    intent.current = "list";
                    goTo(i);
                  }}
                  className="inline-flex items-center rounded-[8px] outline-none touch:min-h-11 focus-visible:ring-2 focus-visible:ring-brand"
                >
                  {tile}
                  {name}
                </button>
              ) : (
                <span className="inline-flex items-center">
                  <span className="sr-only">{`Step ${i + 1} of ${total}: ${s.label}`}</span>
                  {tile}
                  {name}
                </span>
              )}

              {i < total - 1 ? (
                <span
                  aria-hidden
                  className="relative h-[3px] flex-1 overflow-hidden rounded-[2px] bg-ink/[0.06]"
                >
                  <motion.span
                    className="absolute inset-0 origin-left rounded-[2px] bg-brand"
                    initial={false}
                    animate={{ scaleX: complete || i < at ? 1 : 0 }}
                    transition={reduced ? { duration: 0 } : RAIL}
                  />
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
      <div
        ref={viewportRef}
        tabIndex={-1}
        role="group"
        aria-label={position}
        style={auto ? undefined : { height }}
        className={`relative outline-none ${auto ? "" : "overflow-hidden"} ${
          framed
            ? "rounded-[11px] border border-line bg-surface transition-[border-color] duration-150 focus-visible:border-brand dark:focus-visible:border-brand-bright"
            : "rounded-sm focus-visible:ring-2 focus-visible:ring-brand"
        }`}
      >
        {auto ? (
          // A step as tall as its content cannot overlap the outgoing one, so it only
          // enters (a short slide from the side it came from) and the old step leaves at
          // once: the right asymmetry for a form, where the new fields are what matter.
          <motion.div
            key={complete ? "__complete" : step.id}
            custom={direction}
            variants={variants}
            initial="enter"
            animate="center"
            transition={panelTransition}
            className={framed ? "p-4" : ""}
          >
            {complete ? (
              <div className="py-6">
                <p className="text-body font-medium text-ink">{completeLabel}</p>
                <p className="text-meta text-ink-muted">{completeHint}</p>
              </div>
            ) : (
              step.content
            )}
          </motion.div>
        ) : (
        <AnimatePresence initial={false} custom={direction}>
          <motion.div
            key={complete ? "__complete" : step.id}
            custom={direction}
            variants={variants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={panelTransition}
            style={{ scrollbarGutter: "stable" }}
            className="absolute inset-0 overflow-y-auto overscroll-contain p-4 text-[13.5px] leading-relaxed text-ink"
          >

            {complete ? (
              <div className="flex h-full flex-col items-center justify-center gap-1.5">
                <p className="text-[13px] font-medium text-ink">
                  {completeLabel}
                </p>
                <p className="text-[12.5px] text-ink-faint">
                  {completeHint}
                </p>
              </div>
            ) : (
              step.content
            )}
          </motion.div>
        </AnimatePresence>
        )}
      </div>
      <div className={`flex flex-wrap items-center gap-3 ${auto ? "mt-8 border-t border-line pt-5" : "mt-3"}`}>
        <AnimatePresence initial={false}>
          {isFirst ? null : (
            <motion.button
              key="back"
              type="button"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{
                opacity: 0,
                transition: reduced ? { duration: 0 } : { duration: 0.12, ease: EXIT_EASE },
              }}
              transition={reduced ? { duration: 0 } : { duration: 0.16, ease: EASE }}
              onClick={() => {
                intent.current = "panel";
                back();
              }}
              className="h-9 touch:h-11 rounded-[9px] border border-line bg-surface px-3 text-[13px] font-medium text-ink outline-none transition-[border-color] duration-150 hover:border-ink/20 focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
            >
              {backLabel}
            </motion.button>
          )}
        </AnimatePresence>
        {extraActions ? <div className="ml-auto flex items-center gap-3">{extraActions}</div> : null}
        <AnimatePresence initial={false}>
          {complete ? null : (
            <motion.button
              key="advance"
              type="button"
              aria-label={isLast ? finishLabel : nextLabel}
              disabled={advanceDisabled || finishing}
              onClick={advance}
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{
                opacity: 0,
                scale: 0.96,
                transition: reduced
                  ? { duration: 0 }
                  : { duration: 0.14, ease: EXIT_EASE },
              }}
              transition={reduced ? { duration: 0 } : CROSSFADE}
              className={`${extraActions ? "" : "ml-auto"} grid h-9 touch:h-11 place-items-center rounded-[9px] bg-brand-strong px-3.5 text-[13px] font-medium text-white outline-none transition-colors duration-150 [&:not(:disabled)]:hover:bg-brand-deep disabled:cursor-not-allowed disabled:bg-ink/[0.08] disabled:text-ink-faint focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2`}
            >
              <span aria-hidden className="invisible col-start-1 row-start-1">
                {finishLabel.length > nextLabel.length ? finishLabel : nextLabel}
              </span>
              <motion.span
                aria-hidden
                className="col-start-1 row-start-1"
                initial={false}
                animate={{ opacity: isLast ? 0 : 1 }}
                transition={reduced ? { duration: 0 } : CROSSFADE}
              >
                {nextLabel}
              </motion.span>
              <motion.span
                aria-hidden
                className="col-start-1 row-start-1"
                initial={false}
                animate={{ opacity: isLast ? 1 : 0 }}
                transition={reduced ? { duration: 0 } : CROSSFADE}
              >
                {isLast && finishing ? finishingLabel : finishLabel}
              </motion.span>
            </motion.button>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
