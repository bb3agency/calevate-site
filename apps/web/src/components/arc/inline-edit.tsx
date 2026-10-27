"use client";

/**
 * RENAME IN PLACE: a heading-style text (an agent's name, a campaign's name, a lead's name
 * on its own page) that becomes a field when pressed. Enter or the tick saves, Escape or
 * the cross cancels, leaving the field saves. Adapted from uiarc's `inline-edit` (MIT, see
 * ./LICENSE), with the catalogue's changes: `maxLength` passes through, 44px touch actions,
 * every string a prop, no blur or drawn-tick motion, and the save's outcome comes from the
 * caller's `useActionFeedback(...).status`, so it follows the feedback standard rather than
 * owning a second error surface.
 *
 * While the save runs the field stays open and busy; on success it closes and shows a tick
 * for a moment; on failure it stays open with the person's text and the reason under it.
 * Nothing is sent when the text did not change.
 *
 * Not for a table cell whose text is also a link (the leads table keeps `InlineName`,
 * which puts the pencil beside a link).
 */

import { useEffect, useId, useRef, useState, type ElementType } from "react";
import { Check, LoaderCircle, Pencil, X } from "lucide-react";
import clsx from "clsx";

import { FieldMessage } from "@/components/formValidation";

import type { FeedbackStatus } from "./feedback";

export type InlineEditProps = {
  value: string;
  /** Start the save; give the result back through `status`. */
  onSave: (next: string) => void;
  /** From `useActionFeedback(mutation, …).status`. Omit for a synchronous change. */
  status?: FeedbackStatus;
  /** What the text is: "Agent name". Used in the controls' accessible names. */
  label: string;
  as?: ElementType;
  /** Classes for the text in both modes (size and weight), e.g. "text-title". */
  textClassName?: string;
  maxLength?: number;
  placeholder?: string;
  /** Return a sentence to refuse the text, or null. */
  validate?: (next: string) => string | null;
  /** The failure sentence when `status` is "error". */
  errorMessage?: string;
  editLabel?: (label: string) => string;
  saveLabel?: string;
  cancelLabel?: string;
  savedLabel?: string;
  disabled?: boolean;
  className?: string;
};

export function InlineEdit({
  value,
  onSave,
  status: statusProp,
  label,
  as: Tag = "span",
  textClassName = "text-heading",
  maxLength = 120,
  placeholder,
  validate,
  errorMessage = "That did not save. Your text is still here; try again.",
  editLabel = (what) => `Edit ${what}`,
  saveLabel = "Save",
  cancelLabel = "Cancel",
  savedLabel = "Saved",
  disabled = false,
  className,
}: InlineEditProps) {
  const tracked = statusProp !== undefined;
  const status = statusProp ?? "idle";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [problem, setProblem] = useState<string | null>(null);
  const [awaiting, setAwaiting] = useState(false);
  const [saved, setSaved] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const display = useRef<HTMLButtonElement>(null);
  const messageId = useId();

  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);

  // The caller's mutation decides when an edit is over: success closes, failure keeps it.
  // Only a status reached AFTER this save started counts — a "success" still showing from
  // the previous save must not close the next one.
  const statusAtSend = useRef<FeedbackStatus>("idle");
  const moved = useRef(false);
  useEffect(() => {
    if (!awaiting) return;
    if (status !== statusAtSend.current) moved.current = true;
    if (!moved.current) return;
    if (status === "success") {
      setAwaiting(false);
      setEditing(false);
      setSaved(true);
    } else if (status === "error") {
      setAwaiting(false);
      setProblem(errorMessage);
      input.current?.focus();
    }
  }, [status, awaiting, errorMessage]);

  useEffect(() => {
    if (!saved) return undefined;
    const timer = window.setTimeout(() => setSaved(false), 2000);
    return () => window.clearTimeout(timer);
  }, [saved]);

  // Focus goes back to the text when an edit ends, never on first render.
  const wasEditing = useRef(false);
  useEffect(() => {
    if (wasEditing.current && !editing) display.current?.focus({ preventScroll: true });
    wasEditing.current = editing;
  }, [editing]);

  const begin = () => {
    if (disabled) return;
    setDraft(value);
    setProblem(null);
    setEditing(true);
  };
  const cancel = () => {
    setDraft(value);
    setProblem(null);
    setEditing(false);
  };
  const commit = () => {
    const next = draft.trim();
    if (next === value.trim()) return cancel();
    const refusal = next === "" ? "Enter a name, or press Escape to keep the old one." : (validate?.(next) ?? null);
    if (refusal) {
      setProblem(refusal);
      input.current?.focus();
      return;
    }
    setProblem(null);
    onSave(next);
    // A caller with no `status` changed it synchronously: nothing to wait for.
    if (tracked) {
      statusAtSend.current = status;
      moved.current = false;
      setAwaiting(true);
    }
    else setEditing(false);
  };

  const busy = status === "pending" && awaiting;
  if (!editing) {
    return (
      // The hover pad's optical offset sits on the wrapper, not as `-mx-1` on the button:
      // a negative margin on a shrinkable child inside a content-sized flex box shaves
      // those pixels off the box, and the name truncated with room to spare ("Anj…").
      <Tag className={clsx("group -ml-1 inline-flex max-w-full items-center gap-1.5", className)}>
        <button
          ref={display}
          type="button"
          onClick={begin}
          disabled={disabled}
          aria-label={`${editLabel(label)}: ${value}`}
          className={clsx(
            "press inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md px-1 text-left text-ink hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-default disabled:hover:bg-transparent touch:min-h-11",
            textClassName,
          )}
        >
          <span className="min-w-0 truncate">{value || placeholder}</span>
          {!disabled ? (
            <Pencil aria-hidden className="h-3.5 w-3.5 shrink-0 text-ink-faint opacity-60 group-hover:opacity-100" />
          ) : null}
        </button>
        <span role="status" className="inline-flex items-center gap-1 text-meta text-brand-strong">
          {saved ? (
            <>
              <Check aria-hidden className="h-3.5 w-3.5" />
              {savedLabel}
            </>
          ) : null}
        </span>
      </Tag>
    );
  }

  return (
    <div className={clsx("min-w-0", className)}>
      <form
        noValidate
        className="flex items-center gap-1"
        onSubmit={(event) => {
          event.preventDefault();
          commit();
        }}
      >
        <input
          ref={input}
          aria-label={label}
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? messageId : undefined}
          aria-busy={busy || undefined}
          readOnly={busy}
          value={draft}
          maxLength={maxLength}
          placeholder={placeholder}
          enterKeyHint="done"
          onChange={(event) => {
            setDraft(event.target.value);
            setProblem(null);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              cancel();
            }
          }}
          onBlur={(event) => {
            // Moving to Save or Cancel is not leaving the edit.
            if (event.currentTarget.form?.contains(event.relatedTarget as Node | null)) return;
            if (!busy) commit();
          }}
          className={clsx(
            "min-w-0 flex-1 rounded-md border bg-surface px-1.5 py-0.5 text-ink focus:border-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/25",
            problem ? "border-danger" : "border-line",
            textClassName,
          )}
        />
        <button
          type="submit"
          aria-label={saveLabel}
          disabled={busy}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-brand-strong hover:bg-ink/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
        >
          {busy ? <LoaderCircle aria-hidden className="h-4 w-4 motion-safe:animate-spin" /> : <Check aria-hidden className="h-4 w-4" />}
        </button>
        <button
          type="button"
          aria-label={cancelLabel}
          onClick={cancel}
          disabled={busy}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      </form>
      {problem ? <FieldMessage id={messageId}>{problem}</FieldMessage> : null}
    </div>
  );
}
