"use client";

/**
 * THE FEEDBACK STANDARD (founder, 24 Oct 2026): every action a person starts shows
 * pending, then success or failure, ON THE CONTROL THEY PRESSED; a failure also reaches
 * the toast stack with the server's plain sentence and its error code; a reversible success
 * may offer Undo there. `tests/feedbackGuard.test.ts` fails any screen that creates a
 * mutation without passing it through `useActionFeedback`.
 *
 * Two pieces:
 *
 * - `useActionFeedback(mutation, options)` wraps a TanStack mutation. Call `run(vars)`
 *   instead of `mutate(vars)`; read `status` for the button. It raises the toasts.
 * - `ActionButton` renders `status` as idle → pending (spinner) → success (tick + short
 *   past-tense word) → back to idle, or → error (cross + "Try again") until the next press.
 *
 * Adapted from the ideas in uiarc's `action-button`, `confirm-morph` and `action-swap`
 * (MIT, see ./LICENSE): one control that morphs through the states of its own action.
 * What is NOT carried over, and why:
 * - the width spring: every face sits in one grid cell, so the button is as wide as its
 *   widest face from the first paint and nothing around it moves;
 * - the label swap for the accessible name: the idle label stays in the DOM (transparent
 *   while another face shows) so the button keeps its name while it works, and a polite
 *   status line inside the button says "Saved" / "Could not save" for a screen reader.
 */

import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import type { UseMutationResult } from "@tanstack/react-query";
import { Check, LoaderCircle, RotateCcw } from "lucide-react";
import clsx from "clsx";

import { ApiProblem } from "@/lib/api/client";
import {
  DANGER_BUTTON,
  PRIMARY_BUTTON,
  PRIMARY_BUTTON_LG,
  PRIMARY_BUTTON_SM,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";

import { useToast, type ToastApi } from "./toast";

export type FeedbackStatus = "idle" | "pending" | "success" | "error";

const FALLBACK_ERROR_TITLE = "That did not go through";

/** How long the success face stays before the button returns to its label. */
export const SUCCESS_HOLD_MS = 2000;

/** The toast fields a failure produces: the server's own words and its machine code. */
export function problemToast(error: unknown, fallbackTitle: string) {
  if (error instanceof ApiProblem) {
    const ref = error.traceId ? ` · ref ${error.traceId}` : "";
    return {
      title: error.title && error.title !== error.message ? error.title : fallbackTitle,
      description: error.remediation ? `${error.message} ${error.remediation}` : error.message,
      code: error.code !== "unknown" ? `${error.code}${ref}` : error.traceId ? `ref ${error.traceId}` : undefined,
    };
  }
  return {
    title: fallbackTitle,
    description:
      error instanceof Error && error.message.trim() ? error.message : "Try again in a moment.",
    code: undefined,
  };
}

export type ActionFeedbackOptions<TData, TVars> = {
  /**
   * Title of the failure toast, naming the action: "Could not save the script". Give it
   * whenever the failure is toasted; the server's own title wins when the problem has one.
   */
  errorTitle?: string;
  /**
   * `toast` (default): the failure also goes to the toast stack. `inline`: the screen shows
   * `ProblemNotice` beside the control itself (a form), so a toast would say it twice.
   * The button shows its error face either way.
   */
  errorDisplay?: "toast" | "inline";
  /**
   * A success toast. Leave it out when the button's own tick says enough, which is most of
   * the time; give it when the result lands somewhere the person is not looking (a row
   * moved to another tab, a message sent) or when there is an Undo to offer.
   */
  successToast?: string | ((data: TData, vars: TVars) => string | null);
  successDescription?: string | ((data: TData, vars: TVars) => string | undefined);
  /**
   * Offered in the success toast. Only where reversing is genuinely safe and the server
   * has a way to do it; never for a call placed, a message sent or money moved.
   */
  undo?: (data: TData, vars: TVars) => void;
  undoLabel?: string;
};

export type ActionFeedback<TVars> = {
  status: FeedbackStatus;
  /** Start the action (`mutation.mutate` without per-call options; either announces). */
  run: (vars: TVars) => void;
  /** The last failure, for a screen that renders it inline (`errorDisplay: "inline"`). */
  error: unknown;
  reset: () => void;
};

/**
 * A short-lived face: `success` for `SUCCESS_HOLD_MS` after `at` changes, then idle.
 * `at` is a counter or timestamp that changes once per success.
 */
function useHeldSuccess(at: number): boolean {
  const [held, setHeld] = useState(false);
  useEffect(() => {
    if (!at) return undefined;
    setHeld(true);
    const timer = window.setTimeout(() => setHeld(false), SUCCESS_HOLD_MS);
    return () => window.clearTimeout(timer);
  }, [at]);
  return held;
}

function raiseFailure(
  toasts: ToastApi,
  id: string,
  error: unknown,
  title: string,
  retry: () => void,
) {
  const retryable = !(error instanceof ApiProblem) || error.retryable;
  toasts.toast({
    id,
    kind: "error",
    ...problemToast(error, title),
    action: retryable ? { label: "Try again", onClick: retry } : undefined,
  });
}

function raiseSuccess<TData, TVars>(
  toasts: ToastApi,
  id: string,
  options: ActionFeedbackOptions<TData, TVars>,
  data: TData,
  vars: TVars,
) {
  const title =
    typeof options.successToast === "function" ? options.successToast(data, vars) : options.successToast;
  if (!title) {
    // A failure toast from an earlier try of this same action is now stale.
    toasts.dismiss(id);
    return;
  }
  const description =
    typeof options.successDescription === "function"
      ? options.successDescription(data, vars)
      : options.successDescription;
  toasts.toast({
    id,
    kind: "success",
    title,
    description,
    action: options.undo
      ? { label: options.undoLabel ?? "Undo", onClick: () => options.undo?.(data, vars) }
      : undefined,
  });
}

/**
 * Watches the mutation rather than wrapping `mutate`, so the outcome is announced however
 * the screen starts it (`run`, `mutate` or `mutateAsync`, with or without per-call
 * callbacks). Each settled submission is announced once, keyed on `submittedAt`.
 */
export function useActionFeedback<TData, TError, TVars, TContext>(
  mutation: UseMutationResult<TData, TError, TVars, TContext>,
  options: ActionFeedbackOptions<TData, TVars>,
): ActionFeedback<TVars> {
  const toasts = useToast();
  const toastId = useId();
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const { mutate, reset, status, submittedAt, data, error, variables } = mutation;
  const held = useHeldSuccess(status === "success" ? submittedAt : 0);

  const announced = useRef("");
  useEffect(() => {
    if (status !== "success" && status !== "error") return;
    const key = `${submittedAt}:${status}`;
    if (announced.current === key) return;
    announced.current = key;
    const current = optionsRef.current;
    if (status === "success") {
      raiseSuccess(toasts, toastId, current, data as TData, variables as TVars);
    } else if ((current.errorDisplay ?? "toast") === "toast") {
      raiseFailure(toasts, toastId, error, current.errorTitle ?? FALLBACK_ERROR_TITLE, () => mutate(variables as TVars));
    }
  }, [status, submittedAt, data, error, variables, mutate, toasts, toastId]);

  const run = useCallback((vars: TVars) => mutate(vars), [mutate]);
  const shown: FeedbackStatus =
    status === "pending" ? "pending" : status === "error" ? "error" : held ? "success" : "idle";
  return { status: shown, run, error, reset };
}

/**
 * The same contract for an action that is not a TanStack mutation (copying, a download, a
 * browser permission). `action` may throw or reject; that is the failure.
 */
export function useAsyncAction<TVars = void>(
  action: (vars: TVars) => Promise<unknown> | unknown,
  options: { errorTitle?: string; errorDisplay?: "toast" | "inline"; successToast?: string },
): ActionFeedback<TVars> {
  const toasts = useToast();
  const toastId = useId();
  const [status, setStatus] = useState<FeedbackStatus>("idle");
  const [error, setError] = useState<unknown>(null);
  const [succeededAt, setSucceededAt] = useState(0);
  const held = useHeldSuccess(succeededAt);
  const actionRef = useRef(action);
  actionRef.current = action;
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const run = useCallback(
    (vars: TVars) => {
      setStatus("pending");
      setError(null);
      Promise.resolve()
        .then(() => actionRef.current(vars))
        .then(
          () => {
            setStatus("success");
            setSucceededAt(Date.now());
            const title = optionsRef.current.successToast;
            if (title) toasts.toast({ id: toastId, kind: "success", title });
            else toasts.dismiss(toastId);
          },
          (failure: unknown) => {
            setStatus("error");
            setError(failure);
            if ((optionsRef.current.errorDisplay ?? "toast") === "toast") {
              raiseFailure(toasts, toastId, failure, optionsRef.current.errorTitle ?? FALLBACK_ERROR_TITLE, () => run(vars));
            }
          },
        );
    },
    [toasts, toastId],
  );

  const reset = useCallback(() => {
    setStatus("idle");
    setError(null);
  }, []);
  const shown: FeedbackStatus = status === "success" && !held ? "idle" : status;
  return { status: shown, run, error, reset };
}

const VARIANT = {
  primary: PRIMARY_BUTTON,
  "primary-lg": PRIMARY_BUTTON_LG,
  "primary-sm": PRIMARY_BUTTON_SM,
  secondary: SECONDARY_BUTTON,
  "secondary-sm": SECONDARY_BUTTON_SM,
  danger: DANGER_BUTTON,
} as const;

export type ActionButtonVariant = keyof typeof VARIANT;

export type ActionButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & {
  /** The idle label: the action, as a verb ("Save changes"). Also the accessible name. */
  children: ReactNode;
  /** From `useActionFeedback(...).status` or `useAsyncAction(...).status`. */
  status?: FeedbackStatus;
  /** What the face says while it works. Default: the idle label beside a spinner. */
  pendingLabel?: ReactNode;
  /** One past-tense word or two: "Saved", "Sent", "Copied". */
  successLabel?: ReactNode;
  /** Default "Try again": the failure's words are in the toast or the inline notice. */
  errorLabel?: ReactNode;
  variant?: ActionButtonVariant;
};

/** Only the idle face is ever in the accessibility tree; the others are pictures of state. */
function Face({ shown, children, keepName = false }: { shown: boolean; children: ReactNode; keepName?: boolean }) {
  return (
    <span
      aria-hidden={keepName ? undefined : true}
      className={clsx(
        "inline-flex items-center justify-center gap-2 whitespace-nowrap [grid-area:1/1] motion-safe:transition-opacity motion-safe:duration-(--duration-fast)",
        shown ? "opacity-100" : "opacity-0",
      )}
    >
      {children}
    </span>
  );
}

/**
 * A button that carries its own action's state. Busy buttons ignore presses (`aria-disabled`
 * rather than `disabled`, so focus stays on the control the person just pressed and a
 * screen reader hears the change where they are).
 */
export const ActionButton = forwardRef<HTMLButtonElement, ActionButtonProps>(function ActionButton(
  {
    children,
    status = "idle",
    pendingLabel,
    successLabel = "Done",
    errorLabel = "Try again",
    variant = "primary",
    className,
    type = "button",
    disabled,
    onClick,
    ...props
  },
  ref,
) {
  const busy = status === "pending";
  const spoken =
    status === "success"
      ? typeof successLabel === "string"
        ? successLabel
        : "Done"
      : status === "error"
        ? "Did not work"
        : "";
  return (
    <>
    <button
      ref={ref}
      type={type}
      disabled={disabled}
      aria-disabled={busy || undefined}
      aria-busy={busy || undefined}
      data-status={status}
      onClick={(event) => {
        if (busy) {
          event.preventDefault();
          return;
        }
        onClick?.(event);
      }}
      className={clsx(
        VARIANT[variant],
        "relative justify-center",
        busy && "cursor-progress",
        status === "error" && variant !== "danger" && "ring-1 ring-danger/50",
        className,
      )}
      {...props}
    >
      <span className="grid">
        <Face shown={status === "idle"} keepName>
          {children}
        </Face>
        <Face shown={status === "pending"}>
          <LoaderCircle aria-hidden className="h-4 w-4 motion-safe:animate-spin" />
          {pendingLabel ?? children}
        </Face>
        <Face shown={status === "success"}>
          <Check aria-hidden className="h-4 w-4" />
          {successLabel}
        </Face>
        <Face shown={status === "error"}>
          <RotateCcw aria-hidden className="h-4 w-4" />
          {errorLabel}
        </Face>
      </span>
    </button>
    {/* Outside the button, so the status words never join its accessible name. */}
    <span role="status" className="sr-only">
      {spoken}
    </span>
    </>
  );
});
