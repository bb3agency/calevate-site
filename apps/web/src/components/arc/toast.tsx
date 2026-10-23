"use client";

/**
 * THE toast stack: the one place a short, non-blocking result of an action appears when it
 * cannot be shown beside the control that did it. Mounted once per realm, in
 * `app/c/[slug]/layout.tsx` and `app/admin/layout.tsx`.
 *
 * Adapted from uiarc's `toast-stack` (MIT, see ./LICENSE): an external store read through
 * `useSyncExternalStore` (so a toast can be raised from a mutation callback that outlives
 * the component that started it), update-in-place by id (a "Sending" toast becomes its
 * result rather than stacking a second card), pause while hovered, focused or the tab is
 * hidden, and swipe to dismiss. Arc's tucked-card fan, rolling text and blur crossfades are
 * not carried over: they decorate rather than explain state.
 *
 * Where it sits (founder, 24 Oct 2026): bottom-right on a desktop, top of the screen on a
 * phone, where a bottom stack would cover the thumb's actions and the bottom sheet.
 *
 * What a toast is NOT for, so the stack stays quiet:
 * - a success the button already shows (the kit's `ActionButton` turns into a tick);
 * - a form error that belongs beside its field (`ProblemNotice` / `FieldError`);
 * - anything the person must act on before continuing (that is a `ConfirmDialog`).
 *
 * Errors stay until dismissed (or replaced by the same action's next result), because a
 * failure that disappears on a timer can be missed entirely; successes and notes leave
 * after five seconds.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useReducedMotion, type PanInfo } from "motion/react";
import { CircleCheck, CircleX, Info, LoaderCircle, TriangleAlert, X } from "lucide-react";
import clsx from "clsx";

import { MOTION } from "./motion";

export type ToastKind = "success" | "info" | "warning" | "error" | "loading";

export type ToastAction = {
  /** Say what it does: "Undo", "View lead", "Retry". */
  label: string;
  onClick: () => void;
};

export type ToastOptions = {
  /** Reuse an id to replace a toast in place (its timer restarts) instead of stacking one. */
  id?: string;
  kind?: ToastKind;
  /** One short line: what happened, in the client's words. */
  title: string;
  /** At most one more sentence. For an error, the problem's own plain message. */
  description?: string;
  /** The machine code of a failure (`ApiProblem.code`), shown small so support can find it. */
  code?: string;
  action?: ToastAction;
  /** Milliseconds before it leaves. Default 5000; errors and `loading` stay until replaced or closed. */
  duration?: number;
};

export type ToastApi = {
  toast: (options: ToastOptions) => string;
  update: (id: string, patch: Partial<Omit<ToastOptions, "id">>) => void;
  dismiss: (id?: string) => void;
};

type ToastRecord = Required<Pick<ToastOptions, "title">> &
  Omit<ToastOptions, "id" | "kind" | "duration"> & {
    id: string;
    kind: ToastKind;
    duration: number;
    /** Bumped on every update so the item's timer restarts. */
    version: number;
  };

type Store = ToastApi & {
  subscribe: (listener: () => void) => () => void;
  snapshot: () => ToastRecord[];
};

const DEFAULT_DURATION = 5000;
const MAX_VISIBLE = 3;
const QUEUE_LIMIT = 12;
const EMPTY: ToastRecord[] = [];

function durationFor(kind: ToastKind, requested: number | undefined): number {
  if (requested !== undefined) return requested;
  return kind === "error" || kind === "loading" ? Infinity : DEFAULT_DURATION;
}

function createStore(): Store {
  let toasts: ToastRecord[] = [];
  let seq = 0;
  const listeners = new Set<() => void>();
  const commit = (next: ToastRecord[]) => {
    toasts = next;
    for (const listener of listeners) listener();
  };
  const update: ToastApi["update"] = (id, patch) => {
    const found = toasts.find((t) => t.id === id);
    if (!found) return;
    const kind = patch.kind ?? found.kind;
    const next: ToastRecord = {
      ...found,
      ...patch,
      kind,
      // A changed kind takes its own default lifetime unless the patch names one.
      duration: patch.duration ?? (patch.kind ? durationFor(kind, undefined) : found.duration),
      version: found.version + 1,
    };
    commit(toasts.map((t) => (t.id === id ? next : t)));
  };
  const toast: ToastApi["toast"] = ({ id, kind = "info", duration, ...rest }) => {
    if (id && toasts.some((t) => t.id === id)) {
      update(id, { kind, duration, ...rest });
      return id;
    }
    seq += 1;
    const record: ToastRecord = {
      ...rest,
      id: id ?? `toast-${seq}`,
      kind,
      duration: durationFor(kind, duration),
      version: 0,
    };
    commit([record, ...toasts].slice(0, QUEUE_LIMIT));
    return record.id;
  };
  const dismiss: ToastApi["dismiss"] = (id) => {
    if (id === undefined) commit([]);
    else if (toasts.some((t) => t.id === id)) commit(toasts.filter((t) => t.id !== id));
  };
  return {
    toast,
    update,
    dismiss,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    snapshot: () => toasts,
  };
}

/*
 * The default is a working no-op rather than `null`, so a screen rendered outside a realm
 * shell (a unit test, the a11y sweep's page-only render) can call `useToast()` without a
 * provider. The provider is mounted in both shells, so in the product a toast always shows.
 */
const NO_OP: ToastApi = { toast: () => "", update: () => {}, dismiss: () => {} };
const ToastContext = createContext<Store | null>(null);

export function useToast(): ToastApi {
  const store = useContext(ToastContext);
  return store ?? NO_OP;
}

export type ToastProviderProps = {
  children: ReactNode;
  /** Accessible name of the notifications region. */
  label?: string;
  /** Accessible name of each toast's close button. */
  dismissLabel?: string;
};

export function ToastProvider({
  children,
  label = "Notifications",
  dismissLabel = "Dismiss",
}: ToastProviderProps) {
  const [store] = useState(createStore);
  return (
    <ToastContext.Provider value={store}>
      {children}
      <ToastViewport store={store} label={label} dismissLabel={dismissLabel} />
    </ToastContext.Provider>
  );
}

const ICON: Record<ToastKind, typeof Info> = {
  success: CircleCheck,
  info: Info,
  warning: TriangleAlert,
  error: CircleX,
  loading: LoaderCircle,
};

const ICON_TONE: Record<ToastKind, string> = {
  success: "text-brand-strong",
  info: "text-ink-muted",
  warning: "text-warn",
  error: "text-danger",
  loading: "text-ink-muted motion-safe:animate-spin",
};

/** Spoken before the title, so tone is not carried by colour alone. */
const KIND_LABEL: Record<ToastKind, string> = {
  success: "Done",
  info: "Note",
  warning: "Warning",
  error: "Error",
  loading: "Working",
};

function useDocumentHidden(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      document.addEventListener("visibilitychange", onChange);
      return () => document.removeEventListener("visibilitychange", onChange);
    },
    () => document.visibilityState === "hidden",
    () => false,
  );
}

function ToastViewport({
  store,
  label,
  dismissLabel,
}: {
  store: Store;
  label: string;
  dismissLabel: string;
}) {
  const toasts = useSyncExternalStore(store.subscribe, store.snapshot, () => EMPTY);
  const hidden = useDocumentHidden();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const paused = hidden || hovered || focused;
  const visible = toasts.slice(0, MAX_VISIBLE);
  // Portalled into <body> once mounted, so no stacking context in a shell can trap the layer.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // Two live regions, filled with the newest toast's words: errors interrupt (assertive),
  // everything else waits its turn (polite). The cards themselves are not live regions,
  // because a region that re-renders on every timer tick re-announces.
  const newest = toasts[0];
  const spoken = newest ? `${KIND_LABEL[newest.kind]}: ${newest.title}${newest.description ? `. ${newest.description}` : ""}` : "";
  const assertive = newest?.kind === "error" ? spoken : "";
  const polite = newest && newest.kind !== "error" ? spoken : "";

  if (!mounted) return null;
  return createPortal(
    <section
      aria-label={label}
      onPointerOver={() => setHovered(true)}
      onPointerOut={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHovered(false);
      }}
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false);
      }}
      // Phones: a full-width strip under the status bar, newest on top. From `sm`: the
      // bottom-right corner, newest nearest the edge. `pointer-events-none` lets clicks fall
      // through the gaps; each card takes its own pointer events back.
      className="pointer-events-none fixed inset-x-3 top-[calc(0.75rem+env(safe-area-inset-top,0px))] z-toast flex flex-col gap-2 sm:inset-x-auto sm:top-auto sm:right-4 sm:bottom-[calc(1rem+env(safe-area-inset-bottom,0px))] sm:w-[22.5rem] sm:flex-col-reverse"
    >
      <span role="status" aria-live="polite" className="sr-only">
        {polite}
      </span>
      <span role="alert" aria-live="assertive" className="sr-only">
        {assertive}
      </span>
      <AnimatePresence initial={false}>
        {visible.map((t) => (
          <ToastCard
            key={t.id}
            toast={t}
            paused={paused}
            dismissLabel={dismissLabel}
            store={store}
          />
        ))}
      </AnimatePresence>
    </section>,
    document.body,
  );
}

function ToastCard({
  toast,
  paused,
  dismissLabel,
  store,
}: {
  toast: ToastRecord;
  paused: boolean;
  dismissLabel: string;
  store: Store;
}) {
  const { id } = toast;
  const onDismiss = useCallback(() => store.dismiss(id), [store, id]);
  const reduced = useReducedMotion() === true;
  const remaining = useRef(toast.duration);
  const startedAt = useRef(0);

  // A new version restarts the countdown: the toast now says something new.
  useEffect(() => {
    remaining.current = toast.duration;
  }, [toast.version, toast.duration]);

  // Count down only while nothing pauses the stack; bank what ran so a resumed toast
  // finishes its own budget instead of starting over.
  useEffect(() => {
    if (paused || !Number.isFinite(remaining.current)) return undefined;
    startedAt.current = Date.now();
    const handle = window.setTimeout(onDismiss, Math.max(0, remaining.current));
    return () => {
      window.clearTimeout(handle);
      remaining.current -= Date.now() - startedAt.current;
    };
  }, [paused, toast.version, onDismiss]);

  const onDragEnd = useCallback(
    (_: unknown, info: PanInfo) => {
      if (Math.abs(info.offset.x) > 72 || Math.abs(info.velocity.x) > 500) onDismiss();
    },
    [onDismiss],
  );

  const Icon = ICON[toast.kind];
  const enterFrom = reduced ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.98 };

  return (
    <motion.div
      layout={reduced ? false : "position"}
      initial={enterFrom}
      animate={{ opacity: 1, y: 0, x: 0, scale: 1 }}
      exit={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.98, transition: { duration: MOTION.duration.fast } }}
      transition={reduced ? { duration: MOTION.duration.fast } : MOTION.spring.snappy}
      drag={reduced ? false : "x"}
      dragSnapToOrigin
      dragElastic={0.4}
      onDragEnd={onDragEnd}
      role="group"
      aria-label={`${KIND_LABEL[toast.kind]}: ${toast.title}`}
      data-kind={toast.kind}
      onKeyDown={(event) => {
        if (event.key === "Escape") onDismiss();
      }}
      className="pointer-events-auto touch-pan-y rounded-card border border-line bg-surface shadow-overlay"
    >
      <div className="flex items-start gap-3 p-3">
        <Icon aria-hidden className={clsx("mt-0.5 h-4 w-4 shrink-0", ICON_TONE[toast.kind])} />
        <div className="min-w-0 flex-1">
          <p className="break-words text-body font-medium text-ink">{toast.title}</p>
          {toast.description ? (
            <p className="mt-0.5 break-words text-meta text-ink-muted">{toast.description}</p>
          ) : null}
          {toast.code ? (
            <p className="mt-1 font-mono text-[11px] leading-4 text-ink-faint">
              <span className="sr-only">Error code </span>
              {toast.code}
            </p>
          ) : null}
          {toast.action ? (
            <button
              type="button"
              onClick={() => {
                toast.action?.onClick();
                onDismiss();
              }}
              className="press mt-2 inline-flex min-h-8 items-center rounded-md border border-line bg-surface px-2.5 text-meta font-semibold text-ink hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 touch:px-4"
            >
              {toast.action.label}
            </button>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label={dismissLabel}
          className="-mr-1 -mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-faint hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      </div>
    </motion.div>
  );
}

