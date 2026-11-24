"use client";

import clsx from "clsx";
import { ChevronRight } from "lucide-react";
import { useId, useState } from "react";

import type { DraftChange } from "@/lib/scriptDraft/stream";

type Block = { kind: "change"; change: DraftChange } | { kind: "same"; changes: DraftChange[] };

/** Runs of unchanged lines fold into one block; everything else stays a line of its own. */
export function diffBlocks(changes: readonly DraftChange[]): Block[] {
  const blocks: Block[] = [];
  for (const change of changes) {
    const last = blocks[blocks.length - 1];
    if (change.op === "same") {
      if (last?.kind === "same") last.changes.push(change);
      else blocks.push({ kind: "same", changes: [change] });
    } else {
      blocks.push({ kind: "change", change });
    }
  }
  return blocks;
}

/** "2 added, 1 removed, 3 changed": what the draft does, before the lines say it. */
export function diffSummary(changes: readonly DraftChange[]): string {
  const count = (op: DraftChange["op"]) => changes.filter((change) => change.op === op).length;
  const parts = [
    [count("added"), "added"],
    [count("removed"), "removed"],
    [count("changed"), "changed"],
  ] as const;
  const said = parts.filter(([n]) => n > 0).map(([n, word]) => `${n} ${word}`);
  return said.length === 0 ? "No changes to your script." : `${said.join(", ")}.`;
}

/**
 * Pip's draft against the saved script, by the part of the script each line belongs to:
 * removed words on red with a minus, new words on green with a plus, a changed line as the
 * pair. The marks are not the only signal (a person who cannot tell red from green reads
 * the + and −, a screen reader hears "Added" and "Removed").
 */
export function ScriptDiff({ changes }: { changes: readonly DraftChange[] }) {
  const blocks = diffBlocks(changes);
  let label: string | null = null;
  return (
    <div className="space-y-1" data-testid="script-diff">
      <p className="text-meta text-ink-muted">{diffSummary(changes)}</p>
      {blocks.map((block, index) => {
        if (block.kind === "same") {
          label = null;
          return <SameRun key={`same-${index}`} changes={block.changes} />;
        }
        const { change } = block;
        const heading = change.label !== label ? change.label : null;
        label = change.label;
        return (
          <div key={`${change.path}-${index}`} className="min-w-0">
            {heading ? <p className="mt-2 text-meta font-medium text-ink-muted">{heading}</p> : null}
            {(change.op === "removed" || change.op === "changed") && change.before !== null ? (
              <DiffLine op="removed" text={change.before} />
            ) : null}
            {(change.op === "added" || change.op === "changed") && change.after !== null ? (
              <DiffLine op="added" text={change.after} />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function DiffLine({ op, text }: { op: "added" | "removed"; text: string }) {
  const added = op === "added";
  return (
    <p
      data-op={op}
      className={clsx(
        "flex gap-2 rounded-sm border-l-2 py-1 pr-2 pl-2 text-sm text-ink [overflow-wrap:anywhere]",
        added ? "border-success bg-success-soft" : "border-danger bg-danger-soft",
      )}
    >
      <span aria-hidden className={clsx("w-3 shrink-0 text-center font-semibold", added ? "text-success" : "text-danger")}>
        {added ? "+" : "−"}
      </span>
      <span className="sr-only">{added ? "Added: " : "Removed: "}</span>
      <span className="min-w-0">{text}</span>
    </p>
  );
}

function SameRun({ changes }: { changes: readonly DraftChange[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const n = changes.length;
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        className="press inline-flex items-center gap-1 rounded-sm py-1 text-meta text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
      >
        <ChevronRight
          aria-hidden
          className={clsx("h-3.5 w-3.5 motion-safe:transition-transform motion-safe:duration-(--duration-fast)", open && "rotate-90")}
        />
        {n === 1 ? "1 unchanged line" : `${n} unchanged lines`}
      </button>
      {open ? (
        <div id={id} className="space-y-1">
          {changes.map((change, index) => (
            <div key={`${change.path}-${index}`}>
              <p className="mt-1 text-meta text-ink-muted">{change.label}</p>
              <p className="py-0.5 pl-7 text-sm text-ink-muted [overflow-wrap:anywhere]">{change.after ?? change.before}</p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
