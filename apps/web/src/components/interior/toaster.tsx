"use client";

/*
 * Toaster — transient, self-dismissing notifications in the CollapsibleBanner visual
 * family (rounded-[11px] border border-line bg-surface, tone-coloured icon chip).
 *
 * Design notes worth carrying forward:
 *  - The stack shows at most MAX_VISIBLE toasts; anything beyond that waits in state and
 *    is promoted (and only THEN starts counting down) as a visible one leaves. A queued
 *    toast has no timer, so a burst of ten never expires nine of them off-screen.
 *  - Countdown pauses while the whole STACK is hovered or focused, and resumes on leave.
 *    We bank the elapsed time into a `remaining` map on every pause/relayout so a resumed
 *    toast finishes its ORIGINAL budget rather than restarting it.
 *  - Ids come from a monotonic ref counter, never Math.random/Date.now — stable keys that
 *    cannot collide within a session and are deterministic in tests.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

const ENTER = { type: "spring", stiffness: 420, damping: 34, mass: 0.9 } as const;
const LEAVE = [0.4, 0, 1, 1] as const;
const INSTANT = { duration: 0 } as const;

const MAX_VISIBLE = 3;
const DEFAULT_DURATION = 5000;

export type ToastTone = "info" | "success" | "warning" | "danger";

// Tone only recolors the icon chip, matching CollapsibleBanner: `info` is resting muted
// ink; green success is brand/brand-bright; amber/red have no token so they stay on the
// Tailwind ramps with an explicit dark variant.
const TONE_TEXT: Record<ToastTone, string> = {
  info: "text-ink-muted",
  success: "text-brand dark:text-brand-bright",
  warning: "text-amber-600 dark:text-amber-400",
  danger: "text-red-600 dark:text-red-400",
};

// Spoken prefix for the polite live region — the tone half of "tone + title".
const TONE_LABEL: Record<ToastTone, string> = {
  info: "Notification",
  success: "Success",
  warning: "Warning",
  danger: "Error",
};

const TONE_ICON: Record<ToastTone, React.ReactNode> = {
  info: (
    <svg width="15" height="15" viewBox="0 0 256 256" fill="none" aria-hidden="true">
      <circle cx="128" cy="128" r="96" stroke="currentColor" strokeWidth="16" />
      <polyline
        points="120 120 128 120 128 176 136 176"
        stroke="currentColor"
        strokeWidth="16"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="124" cy="84" r="12" fill="currentColor" />
    </svg>
  ),
  success: (
    <svg width="15" height="15" viewBox="0 0 256 256" fill="none" aria-hidden="true">
      <circle cx="128" cy="128" r="96" stroke="currentColor" strokeWidth="16" />
      <polyline
        points="86 130 114 158 170 98"
        stroke="currentColor"
        strokeWidth="16"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  ),
  warning: (
    <svg width="15" height="15" viewBox="0 0 256 256" fill="none" aria-hidden="true">
      <path
        d="M128 48 224 208 32 208 Z"
        stroke="currentColor"
        strokeWidth="16"
        strokeLinejoin="round"
      />
      <line
        x1="128"
        y1="112"
        x2="128"
        y2="156"
        stroke="currentColor"
        strokeWidth="16"
        strokeLinecap="round"
      />
      <circle cx="128" cy="186" r="11" fill="currentColor" />
    </svg>
  ),
  danger: (
    <svg width="15" height="15" viewBox="0 0 256 256" fill="none" aria-hidden="true">
      <circle cx="128" cy="128" r="96" stroke="currentColor" strokeWidth="16" />
      <line
        x1="160"
        y1="96"
        x2="96"
        y2="160"
        stroke="currentColor"
        strokeWidth="16"
        strokeLinecap="round"
      />
      <line
        x1="96"
        y1="96"
        x2="160"
        y2="160"
        stroke="currentColor"
        strokeWidth="16"
        strokeLinecap="round"
      />
    </svg>
  ),
};

const CLOSE = (
  <svg width="13" height="13" viewBox="0 0 256 256" fill="none" aria-hidden="true">
    <line
      x1="200"
      y1="56"
      x2="56"
      y2="200"
      stroke="currentColor"
      strokeWidth="16"
      strokeLinecap="round"
    />
    <line
      x1="200"
      y1="200"
      x2="56"
      y2="56"
      stroke="currentColor"
      strokeWidth="16"
      strokeLinecap="round"
    />
  </svg>
);

export type ToastAction = { label: string; onClick: () => void };

export type ToastInput = {
  title: string;
  description?: string;
  tone?: ToastTone;
  action?: ToastAction;
  /** Override the auto-dismiss window (ms). Defaults to the provider's `duration`. */
  duration?: number;
};

type ToastRecord = {
  id: number;
  title: string;
  description?: string;
  tone: ToastTone;
  action?: ToastAction;
  duration: number;
};

export type ToastContextValue = {
  /** Enqueue a toast; returns its id so the caller can dismiss it early. */
  toast: (input: ToastInput) => number;
  dismiss: (id: number) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a <ToastProvider>");
  return ctx;
}

export type ToastProviderProps = {
  children: React.ReactNode;
  /** Auto-dismiss window in ms (per toast overridable). Default 5000. */
  duration?: number;
  /** Max toasts shown at once; the rest queue. Default 3. */
  max?: number;
  /** Accessible name for the notifications region. */
  label?: string;
  dismissLabel?: string;
};

export function ToastProvider({
  children,
  duration = DEFAULT_DURATION,
  max = MAX_VISIBLE,
  label = "Notifications",
  dismissLabel = "Dismiss notification",
}: ToastProviderProps) {
  const reduced = useReducedMotion() === true;

  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const [announce, setAnnounce] = useState("");

  // Pause the whole stack's countdown while the pointer is over it or focus is inside it.
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const paused = hovered || focused;

  const idRef = useRef(0);
  // Per-toast countdown bookkeeping. `remaining` holds the budget still owed; `startedAt`
  // is when the current running segment began, so a pause can subtract exactly what ran.
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  const remaining = useRef<Map<number, number>>(new Map());
  const startedAt = useRef<Map<number, number>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (input: ToastInput) => {
      idRef.current += 1;
      const id = idRef.current;
      const tone = input.tone ?? "info";
      const record: ToastRecord = {
        id,
        title: input.title,
        description: input.description,
        tone,
        action: input.action,
        duration: input.duration ?? duration,
      };
      remaining.current.set(id, record.duration);
      setToasts((list) => [...list, record]);
      setAnnounce(`${TONE_LABEL[tone]}: ${input.title}`);
      return id;
    },
    [duration],
  );

  const visible = toasts.slice(0, max);
  const visibleKey = visible.map((t) => t.id).join(",");
  // The scheduling effect reads ids from `visibleKey`; the objects come through this ref
  // so the effect need not list `visible` (a fresh array each render) as a dependency.
  const visibleRef = useRef<ToastRecord[]>(visible);
  visibleRef.current = visible;

  // Drive the countdown. Re-runs whenever the visible set changes or pause toggles: the
  // cleanup banks each running toast's elapsed time back into `remaining`, then the body
  // reschedules from the banked budget — so promotion, dismissal and pause/resume all
  // preserve each toast's original window.
  useEffect(() => {
    if (paused) return;
    // Capture the (stable) ref maps into locals so the cleanup closes over the same maps
    // eslint flags reading `x.current` in a cleanup (the value could differ by then); these
    // refs are never reassigned — only mutated in place — so a captured local is equivalent
    // and satisfies the rule.
    const timerMap = timers.current;
    const startedMap = startedAt.current;
    const remainingMap = remaining.current;
    for (const t of visibleRef.current) {
      const left = remainingMap.get(t.id) ?? t.duration;
      startedMap.set(t.id, Date.now());
      const handle = setTimeout(() => dismiss(t.id), Math.max(0, left));
      timerMap.set(t.id, handle);
    }
    return () => {
      const now = Date.now();
      for (const [id, handle] of timerMap) {
        clearTimeout(handle);
        const start = startedMap.get(id);
        if (start != null) {
          const prev = remainingMap.get(id) ?? duration;
          remainingMap.set(id, Math.max(0, prev - (now - start)));
        }
      }
      timerMap.clear();
    };
  }, [visibleKey, paused, dismiss, duration]);

  // Purge bookkeeping for toasts that have left, so the maps track live state only.
  useEffect(() => {
    const live = new Set(toasts.map((t) => t.id));
    for (const id of remaining.current.keys())
      if (!live.has(id)) remaining.current.delete(id);
    for (const id of startedAt.current.keys())
      if (!live.has(id)) startedAt.current.delete(id);
  }, [toasts]);

  useEffect(
    () => () => {
      for (const handle of timers.current.values()) clearTimeout(handle);
      timers.current.clear();
    },
    [],
  );

  const value = useMemo<ToastContextValue>(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}

      {/* Bottom-right on >= sm at a viewport-capped fixed width; full-width edge-inset
          strip on narrow screens. pointer-events-none so clicks fall through the gaps to
          the page; each toast re-enables its own pointer events. */}
      <div
        role="region"
        aria-label={label}
        // pointerover/pointerout BUBBLE (unlike enter/leave) so they reach this handler
        // from a child toast even though the region itself is pointer-events-none. The
        // relatedTarget guard ignores movement between toasts within the stack.
        onPointerOver={() => setHovered(true)}
        onPointerOut={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
            setHovered(false);
          }
        }}
        onFocus={() => setFocused(true)}
        onBlur={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
            setFocused(false);
          }
        }}
        className="pointer-events-none fixed inset-x-3 bottom-3 z-[60] flex flex-col items-stretch gap-2 sm:inset-x-auto sm:bottom-4 sm:right-4 sm:w-[360px] sm:max-w-[calc(100vw-2rem)]"
      >
        <span role="status" aria-live="polite" className="sr-only">
          {announce}
        </span>

        <AnimatePresence initial={false}>
          {visible.map((t) => (
            <motion.div
              key={t.id}
              layout={reduced ? false : "position"}
              initial={reduced ? { opacity: 0 } : { opacity: 0, x: 24, scale: 0.98 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={
                reduced
                  ? { opacity: 0, transition: INSTANT }
                  : {
                      opacity: 0,
                      x: 24,
                      scale: 0.98,
                      transition: { duration: 0.16, ease: LEAVE },
                    }
              }
              transition={reduced ? INSTANT : ENTER}
              role="group"
              aria-label={`${TONE_LABEL[t.tone]}: ${t.title}`}
              className="pointer-events-auto overflow-hidden rounded-[11px] border border-line bg-surface shadow-[0_1px_2px_rgba(28,25,23,0.07),0_16px_36px_-18px_rgba(28,25,23,0.5)] dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.06),0_2px_12px_rgba(0,0,0,0.55)]"
            >
              <div className="flex items-start gap-2.5 p-2.5">
                <span
                  aria-hidden="true"
                  className={`grid size-[26px] shrink-0 place-items-center rounded-[7px] bg-ink/[0.06] ${TONE_TEXT[t.tone]} shadow-[inset_0_1px_2px_rgba(28,25,23,0.06)] dark:shadow-[inset_0_1px_2px_rgba(0,0,0,0.4)]`}
                >
                  {TONE_ICON[t.tone]}
                </span>

                <div className="min-w-0 flex-1">
                  <p className="break-words text-[13px] font-medium leading-5 text-ink">
                    {t.title}
                  </p>
                  {t.description ? (
                    <p className="mt-0.5 break-words text-[12.5px] leading-relaxed text-ink-muted">
                      {t.description}
                    </p>
                  ) : null}
                  {t.action ? (
                    <div className="mt-2">
                      <button
                        type="button"
                        onClick={() => {
                          t.action?.onClick();
                          dismiss(t.id);
                        }}
                        className="inline-flex h-8 touch:h-11 select-none items-center whitespace-nowrap rounded-[7px] border border-line bg-surface px-2.5 text-[12px] font-medium text-ink shadow-[inset_0_1.5px_0_rgba(255,255,255,0.95),inset_0_-1px_0_rgba(28,25,23,0.06),0_1px_2px_rgba(28,25,23,0.08)] outline-none transition-[background-color,border-color,box-shadow] duration-150 hover:bg-ink/[0.04] focus-visible:border-brand active:translate-y-px dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.07),0_1px_2px_rgba(0,0,0,0.4)] dark:focus-visible:border-brand-bright"
                      >
                        {t.action.label}
                      </button>
                    </div>
                  ) : null}
                </div>

                <button
                  type="button"
                  onClick={() => dismiss(t.id)}
                  aria-label={dismissLabel}
                  className="-mr-0.5 grid size-[26px] shrink-0 place-items-center rounded-[7px] text-ink-faint transition-colors duration-150 hover:bg-ink/[0.06] hover:text-ink focus-visible:bg-brand/[0.06] focus-visible:shadow-[inset_0_0_0_1px_#16a05d] focus-visible:outline-none dark:focus-visible:bg-brand-bright/[0.1] dark:focus-visible:shadow-[inset_0_0_0_1px_#22c55e]"
                >
                  {CLOSE}
                </button>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
