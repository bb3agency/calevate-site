"use client";

/**
 * A FOLDABLE SECTION with its name outside the card (founder, 15 Nov 2026): a coloured pill
 * sits on the card's top edge, and pressing it folds the card to a thin bar. Each section has
 * its own colour so the eye finds it again; the pill keeps the name, so colour is never the
 * only signal.
 *
 * `FoldGroup` adds Collapse all / Expand all for every section inside it. A command is a
 * counter rather than a boolean so pressing the same one twice still reaches sections a
 * person has opened or closed by hand since.
 *
 * Each section remembers whether it was last folded, per page and per browser (founder,
 * 16 Nov 2026), until its own pill or Collapse all / Expand all changes it. Browser storage
 * is right for this: it is one person's view, not shared data, and losing it only reopens
 * the section.
 */

import { ChevronDown } from "lucide-react";
import { InfoTip } from "@/components/console/infoTip";
import { keepInView } from "@/lib/keepInView";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";

type Command = { open: boolean; seq: number };
const FoldCommand = createContext<Command | null>(null);

function readFold(key: string): boolean | null {
  try {
    const value = window.localStorage.getItem(key);
    return value === "open" ? true : value === "closed" ? false : null;
  } catch {
    return null;
  }
}

function writeFold(key: string, open: boolean): void {
  try {
    window.localStorage.setItem(key, open ? "open" : "closed");
  } catch {
    // No storage (a private window): the section still folds, it just is not remembered.
  }
}

export type FoldTone =
  | "task"
  | "materials"
  | "generate"
  | "script"
  | "agent"
  | "test"
  | "compliance"
  | "add"
  | "people"
  | "settings"
  | "progress"
  | "results"
  | "details";

/** One colour per section, none of them a status colour except compliance's amber warning. */
const TONE: Record<FoldTone, { pill: string; card: string }> = {
  task: { pill: "bg-brand-strong text-white", card: "border-success-line border-l-brand-strong bg-brand-soft/30" },
  materials: { pill: "bg-info text-white", card: "border-info-line border-l-info bg-info-soft/40" },
  generate: { pill: "bg-series-5 text-white", card: "border-series-5/30 border-l-series-5 bg-series-5/5" },
  script: { pill: "bg-series-2 text-white", card: "border-series-2/30 border-l-series-2 bg-series-2/5" },
  agent: { pill: "bg-series-3 text-white", card: "border-series-3/30 border-l-series-3 bg-series-3/5" },
  test: { pill: "bg-series-6 text-white", card: "border-series-6/30 border-l-series-6 bg-series-6/5" },
  compliance: { pill: "bg-warn text-white", card: "border-warn-line border-l-warn bg-warn-soft/40" },
  add: { pill: "bg-series-1 text-white", card: "border-series-1/30 border-l-series-1 bg-series-1/5" },
  people: { pill: "bg-series-4 text-white", card: "border-series-4/30 border-l-series-4 bg-series-4/5" },
  settings: { pill: "bg-ink text-surface", card: "border-line border-l-ink bg-surface-muted/60" },
  // A running campaign's page.
  progress: { pill: "bg-brand-deep text-white", card: "border-success-line border-l-brand-deep bg-brand-soft/30" },
  results: { pill: "bg-series-2 text-white", card: "border-series-2/30 border-l-series-2 bg-series-2/5" },
  details: { pill: "bg-series-4 text-white", card: "border-series-4/30 border-l-series-4 bg-series-4/5" },
};

export function FoldGroup({
  header,
  actions,
  children,
  className = "",
}: {
  /** Shown left of the buttons, such as the step's own heading. */
  header?: ReactNode;
  /** More buttons beside Collapse all / Expand all, such as Start campaign. */
  actions?: ReactNode;
  children: ReactNode;
  /** Spacing between the sections. */
  className?: string;
}) {
  const [command, setCommand] = useState<Command | null>(null);
  const press = (open: boolean) => setCommand((c) => ({ open, seq: (c?.seq ?? 0) + 1 }));
  return (
    <FoldCommand.Provider value={command}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        {header ? <div className="min-w-0">{header}</div> : <span />}
        <div className="flex flex-wrap items-center justify-end gap-2">
          {actions}
          <button
            type="button"
            className="rounded-full border border-line bg-surface px-3 py-1.5 text-meta font-medium text-ink hover:bg-surface-muted"
            onClick={(e) => {
              keepInView(e.currentTarget);
              press(false);
            }}
          >
            Collapse all
          </button>
          <button
            type="button"
            className="rounded-full border border-line bg-surface px-3 py-1.5 text-meta font-medium text-ink hover:bg-surface-muted"
            onClick={(e) => {
              keepInView(e.currentTarget);
              press(true);
            }}
          >
            Expand all
          </button>
        </div>
      </div>
      {/* The sections sit close under the buttons; their own spacing is between each other. */}
      <div className={`mt-1 ${className}`}>{children}</div>
    </FoldCommand.Provider>
  );
}

export function FoldSection({
  title,
  tone,
  aside,
  hint,
  info,
  defaultOpen = true,
  id,
  children,
}: {
  title: string;
  tone: FoldTone;
  /** One line under the name, inside the card. */
  hint?: ReactNode;
  /** More about the section, behind an (i). */
  info?: ReactNode;
  /** A short status beside the name, such as "2 checks to answer". */
  aside?: ReactNode;
  defaultOpen?: boolean;
  /** The card's element id, for a link or a scroll to land on. */
  id?: string;
  children: ReactNode;
}) {
  const [open, setOpenState] = useState(defaultOpen);
  const command = useContext(FoldCommand);
  const bodyId = useId();
  const storageKey = `calevate:fold:${usePathname()}:${id ?? title}`;
  const setOpen = useCallback(
    (next: boolean) => {
      setOpenState(next);
      writeFold(storageKey, next);
    },
    [storageKey],
  );
  // Read after mount, not in useState: the server render has no storage to read.
  useEffect(() => {
    const saved = readFold(storageKey);
    if (saved != null) setOpenState(saved);
  }, [storageKey]);
  const lastCommand = useRef<Command | null>(command);
  useEffect(() => {
    if (command && command !== lastCommand.current) setOpen(command.open);
    lastCommand.current = command;
  }, [command, setOpen]);
  const look = TONE[tone];
  return (
    <section id={id} className="relative scroll-mt-24 pt-4">
      <div className="absolute left-4 top-0 z-raised flex items-center gap-3">
        <h2 className="text-body font-semibold">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={(e) => {
              keepInView(e.currentTarget);
              setOpen(!open);
            }}
            className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1 shadow-card ${look.pill}`}
          >
            <ChevronDown aria-hidden className={`h-4 w-4 transition-transform ${open ? "" : "-rotate-90"}`} />
            {title}
          </button>
        </h2>
        {aside ? <span className="rounded-full bg-surface px-2 py-0.5 text-meta">{aside}</span> : null}
      </div>
      <div
        id={bodyId}
        className={`rounded-card border border-l-4 ${look.card} ${open ? "px-4 pb-5 pt-7 sm:px-6" : "h-5"}`}
      >
        {/* Hidden rather than unmounted, so a half-filled form survives a fold. */}
        <div hidden={!open}>
          {hint ? (
            <p className="mb-3 flex items-center gap-1 text-meta text-ink-muted">
              <span className="block">{hint}</span>
              {info ? (
                <InfoTip label={title.toLowerCase()} align="start">
                  {info}
                </InfoTip>
              ) : null}
            </p>
          ) : null}
          {children}
        </div>
      </div>
    </section>
  );
}
