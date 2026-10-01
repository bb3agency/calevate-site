"use client";

/**
 * THE BUILDER'S STICKY TOOLBAR — where the agent is, which version callers hear, and the
 * one action that matters right now.
 *
 * One primary at any moment, chosen by state: **Save** while there are unsaved edits (or
 * nothing is waiting), **Apply to live calls** once a saved version is staged and the
 * editor is clean.
 *
 * Also the builder's other chrome: the mode toggle and the compiled-prompt drawer. Apply is never offered over unsaved edits, because it would put live
 * the version on file rather than the one on screen.
 */

import Link from "next/link";
import { ArrowLeft, Sparkles } from "lucide-react";

import { PRIMARY_BUTTON, SECONDARY_BUTTON, formatCount } from "@/components/ui";
import { Drawer } from "@/components/console/drawer";
import { RowMenu } from "@/components/console/rowMenu";

// Soft budget from PROMPT-GUIDE §1 (~2,500 tokens). Characters, because the client has no
// tokenizer; guidance, not a hard stop.
const CHAR_BUDGET = 9000;

export function ScriptToolbar({
  backHref,
  agentName,
  version,
  hasPending,
  unsaved,
  canWrite,
  writeReason,
  saving,
  applying,
  onSave,
  onApply,
  onUndo,
  onPreview,
  onAssist,
}: {
  backHref: string;
  agentName: string;
  version: number | null;
  hasPending: boolean;
  unsaved: boolean;
  canWrite: boolean;
  writeReason: string | null;
  saving: boolean;
  applying: boolean;
  onSave: () => void;
  onApply: () => void;
  onUndo: () => void;
  onPreview: () => void;
  onAssist: () => void;
}) {
  const state = unsaved
    ? { label: "Unsaved changes", tone: "border-warn-line bg-warn-soft text-ink" }
    : hasPending
      ? { label: `v${version ?? "?"} waiting to apply`, tone: "border-warn-line bg-warn-soft text-ink" }
      : version === null
        ? { label: "No script yet", tone: "border-line bg-app text-ink-muted" }
        : { label: `v${version} saved`, tone: "border-line bg-app text-ink-muted" };

  const applyFirst = hasPending && !unsaved;

  return (
    <div className="sticky -top-4 z-20 -mx-4 -mt-4 border-b border-line bg-app/95 px-4 py-3 backdrop-blur-sm lg:-top-6 lg:-mx-8 lg:-mt-6 lg:px-8">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-1 basis-56 items-center gap-3">
          <Link
            href={backHref}
            aria-label={`Back to ${agentName}`}
            className="press flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
          >
            <ArrowLeft aria-hidden className="h-4 w-4" />
          </Link>
          <div className="min-w-0">
            <h2 className="truncate text-[17px] font-semibold text-ink">Script</h2>
            <p className="truncate text-xs text-ink-muted">{agentName}</p>
          </div>
          <span
            role="status"
            className={`shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-medium ${state.tone}`}
          >
            {state.label}
          </span>
        </div>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <button type="button" onClick={onAssist} className={`${SECONDARY_BUTTON} max-sm:flex-1`}>
            <Sparkles aria-hidden className="h-4 w-4" />
            Draft with AI
          </button>
          {applyFirst ? (
            <button
              type="button"
              className={`${PRIMARY_BUTTON} max-sm:flex-1`}
              disabled={!canWrite || applying}
              title={writeReason ?? undefined}
              onClick={onApply}
            >
              {applying ? "Applying…" : "Apply to live calls"}
            </button>
          ) : (
            <button
              type="button"
              className={`${PRIMARY_BUTTON} max-sm:flex-1`}
              disabled={!canWrite || saving}
              title={writeReason ?? undefined}
              onClick={onSave}
            >
              {saving ? "Saving…" : "Save script"}
            </button>
          )}
          <RowMenu
            label="this script"
            items={[
              { id: "preview", label: "View compiled prompt", onSelect: onPreview },
              ...(hasPending
                ? [
                    {
                      id: "undo",
                      label: "Undo changes",
                      onSelect: onUndo,
                      disabled: !canWrite,
                      hint: writeReason ?? undefined,
                    },
                  ]
                : []),
            ]}
          />
        </div>
      </div>
    </div>
  );
}

export function ModeToggle({
  raw,
  onStructured,
  onRaw,
}: {
  raw: boolean;
  onStructured: () => void;
  onRaw: () => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-line text-xs" role="group" aria-label="Editing mode">
      <button
        type="button"
        aria-pressed={!raw}
        onClick={onStructured}
        className={`rounded-l-md px-3 py-1.5 font-medium transition-colors duration-(--duration-fast) ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset touch:min-h-11 ${!raw ? "bg-brand-strong text-white focus-visible:ring-white" : "text-ink-muted hover:bg-black/5 focus-visible:ring-brand"}`}
      >
        Structured
      </button>
      <button
        type="button"
        aria-pressed={raw}
        onClick={onRaw}
        className={`rounded-r-md px-3 py-1.5 font-medium transition-colors duration-(--duration-fast) ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset touch:min-h-11 ${raw ? "bg-brand-strong text-white focus-visible:ring-white" : "text-ink-muted hover:bg-black/5 focus-visible:ring-brand"}`}
      >
        Raw text
      </button>
    </div>
  );
}

export function CompiledPrompt({
  text,
  chars,
  onClose,
}: {
  text: string;
  chars: number | null;
  onClose: () => void;
}) {
  return (
    <Drawer
      open
      onClose={onClose}
      title="Compiled prompt"
      description="Exactly what the calling system runs."
      width="lg"
      initialFocus="container"
    >
      <p className="mb-3 text-sm text-ink-muted">
        This is exactly what the calling system runs — your opening, your script, and the
        platform rules the agent must always follow, which you cannot remove.
      </p>
      {/* Focusable because it scrolls vertically and no key scrolls a non-focusable element. */}
      <pre
        role="region"
        aria-label="Compiled prompt"
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a region that scrolls must take focus, or no key can scroll it
        tabIndex={0}
        className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-md border border-line bg-ink/[0.03] p-3 text-xs text-ink"
      >
        {text}
      </pre>
      {chars !== null && (
        <p className={`mt-2 text-xs ${chars > CHAR_BUDGET ? "text-danger" : "text-ink-faint"}`}>
          Compiled length {formatCount(chars)} characters
          {chars > CHAR_BUDGET ? " — over the recommended budget" : ""}
        </p>
      )}
    </Drawer>
  );
}
