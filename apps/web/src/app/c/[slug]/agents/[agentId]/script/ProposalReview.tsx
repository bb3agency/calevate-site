"use client";

/**
 * AN AI PROPOSAL, REVIEWED BEFORE IT TOUCHES ANYTHING.
 *
 * Every change is its own row with its own "Keep" box, all kept to start with; the owner
 * unticks what they do not want and only the rest is applied to their draft (`applyChanges`).
 * Nothing goes live from here: the draft still waits for "Put it live".
 */

import { useMemo, useState, type ReactNode } from "react";

import { PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { CallScript } from "@/lib/api/script";

import { applyChanges, diffScripts, type Change } from "./scriptDiff";
import { sectionDetail } from "./scriptModel";

export function ProposalReview({
  current,
  proposal,
  onApply,
  onDiscard,
  gate,
  children,
}: {
  current: CallScript;
  proposal: CallScript;
  onApply: (next: CallScript) => void;
  onDiscard: () => void;
  /** A reason "Keep" must wait (the owner has not confirmed the unplaced lines yet). */
  gate?: string | null;
  /** Shown above the changes: the server's account of how it was written, unplaced lines. */
  children?: ReactNode;
}) {
  const changes = useMemo(() => diffScripts(current, proposal), [current, proposal]);
  const [kept, setKept] = useState<Set<string>>(() => new Set(changes.map((c) => c.id)));
  const keptCount = changes.filter((c) => kept.has(c.id)).length;

  const toggle = (id: string, on: boolean) =>
    setKept((k) => {
      const next = new Set(k);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  return (
    <section aria-labelledby="proposal-heading" className="space-y-4">
      <div>
        <h3 id="proposal-heading" className="text-heading text-ink">
          Suggested changes
        </h3>
        <p className="mt-1 text-meta text-ink-muted">
          Untick anything you do not want. What you keep goes into your draft; callers hear it
          only after you put it live.
        </p>
      </div>
      {children}
      {changes.length === 0 ? (
        <p className="text-body text-ink-muted">The suggestion is the same as your script. Nothing to change.</p>
      ) : (
        <ul className="divide-y divide-line border-y border-line">
          {changes.map((change) => (
            <li key={change.id} className="py-3">
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={kept.has(change.id)}
                  onChange={(e) => toggle(change.id, e.target.checked)}
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-body font-medium text-ink">{headline(change)}</span>
                  <ChangeBody change={change} />
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={PRIMARY_BUTTON_SM}
          disabled={keptCount === 0 || Boolean(gate)}
          title={gate ?? undefined}
          onClick={() => onApply(applyChanges(current, proposal, kept))}
        >
          {keptCount === changes.length ? "Keep all changes" : `Keep ${keptCount} of ${changes.length}`}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDiscard}>
          Discard
        </button>
      </div>
      {gate && <p className="text-meta text-ink-muted">{gate}</p>}
    </section>
  );
}

function headline(change: Change): string {
  switch (change.kind) {
    case "part":
      return change.label;
    case "section-added":
      return `New section: ${change.label}`;
    case "section-removed":
      return `Remove section: ${change.label}`;
    case "section-changed":
      return `Section: ${change.label}`;
  }
}

function ChangeBody({ change }: { change: Change }) {
  if (change.kind === "part") return <BeforeAfter before={change.before} after={change.after} />;
  if (change.kind === "section-added") return <Quote tone="after" text={sectionDetail(change.after)} />;
  if (change.kind === "section-removed") return <Quote tone="before" text={sectionDetail(change.before)} />;
  const before = [change.before.name !== change.after.name && `Name: ${change.before.name}`, sectionDetail(change.before)]
    .filter(Boolean)
    .join("\n");
  const after = [change.before.name !== change.after.name && `Name: ${change.after.name}`, sectionDetail(change.after)]
    .filter(Boolean)
    .join("\n");
  return <BeforeAfter before={before} after={after} />;
}

function BeforeAfter({ before, after }: { before: string; after: string }) {
  return (
    <span className="mt-1 block space-y-1">
      {before && <Quote tone="before" text={before} />}
      <Quote tone="after" text={after || "(left empty)"} />
    </span>
  );
}

function Quote({ tone, text }: { tone: "before" | "after"; text: string }) {
  return (
    <span
      className={`block whitespace-pre-wrap rounded-md px-2.5 py-1.5 text-meta ${
        tone === "before" ? "bg-ink/[0.04] text-ink-muted" : "bg-brand-soft text-ink"
      }`}
    >
      <span className="block text-[11px] font-medium text-ink-muted">{tone === "before" ? "Now" : "Suggested"}</span>
      {text}
    </span>
  );
}
