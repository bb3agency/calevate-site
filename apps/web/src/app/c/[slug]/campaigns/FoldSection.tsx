"use client";

/**
 * A FOLDABLE SECTION (founder, 25 Nov 2026, in the deal screen's style): a white card with a
 * coloured left edge, and a header row of chevron, tinted icon, the name in the section's
 * colour and its one-line description beside it. Pressing the row folds the card to that
 * row. Each section has its own colour so the eye finds it again; the name and icon go with
 * it, so colour is never the only signal.
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

import {
  Activity,
  BarChart3,
  Bot,
  ChevronDown,
  FileText,
  Info,
  PhoneCall,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Target,
  UserPlus,
  Users,
  type LucideIcon,
} from "lucide-react";
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

/** One colour and icon per section, none of them a status colour except compliance's amber
 *  warning. Full class names, so the build keeps them. */
const TONE: Record<FoldTone, { edge: string; title: string; chip: string; icon: LucideIcon }> = {
  task: { edge: "border-l-brand-strong", title: "text-brand-strong", chip: "bg-brand-soft text-brand-strong", icon: Target },
  materials: { edge: "border-l-info", title: "text-info", chip: "bg-info-soft text-info", icon: FileText },
  generate: { edge: "border-l-series-5", title: "text-series-5", chip: "bg-series-5/10 text-series-5", icon: Sparkles },
  script: { edge: "border-l-series-2", title: "text-series-2", chip: "bg-series-2/10 text-series-2", icon: ScrollText },
  agent: { edge: "border-l-series-3", title: "text-series-3", chip: "bg-series-3/10 text-series-3", icon: Bot },
  test: { edge: "border-l-series-6", title: "text-series-6", chip: "bg-series-6/10 text-series-6", icon: PhoneCall },
  compliance: { edge: "border-l-warn", title: "text-warn", chip: "bg-warn-soft text-warn", icon: ShieldCheck },
  add: { edge: "border-l-series-1", title: "text-series-1", chip: "bg-series-1/10 text-series-1", icon: UserPlus },
  people: { edge: "border-l-series-4", title: "text-series-4", chip: "bg-series-4/10 text-series-4", icon: Users },
  settings: { edge: "border-l-ink", title: "text-ink", chip: "bg-ink/[0.07] text-ink", icon: SlidersHorizontal },
  // A running campaign's page.
  progress: { edge: "border-l-brand-deep", title: "text-brand-deep", chip: "bg-brand-soft text-brand-deep", icon: Activity },
  results: { edge: "border-l-series-2", title: "text-series-2", chip: "bg-series-2/10 text-series-2", icon: BarChart3 },
  details: { edge: "border-l-series-4", title: "text-series-4", chip: "bg-series-4/10 text-series-4", icon: Info },
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
            className="rounded-full border border-line bg-surface px-3 py-1.5 text-meta font-medium text-ink hover:bg-surface-muted touch:min-h-11"
            onClick={(e) => {
              keepInView(e.currentTarget);
              press(false);
            }}
          >
            Collapse all
          </button>
          <button
            type="button"
            className="rounded-full border border-line bg-surface px-3 py-1.5 text-meta font-medium text-ink hover:bg-surface-muted touch:min-h-11"
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
  // A link that names this section (`#line-test-call`, from the agent's Try it) opens it over
  // a remembered fold. The page drew it only after its data loaded, so the browser's own
  // jump found no target: scroll to it here.
  const sectionRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const named = id != null && window.location.hash.slice(1) === id;
    const saved = readFold(storageKey);
    if (named) {
      setOpenState(true);
      sectionRef.current?.scrollIntoView?.({ block: "start" });
    } else if (saved != null) setOpenState(saved);
  }, [storageKey, id]);
  const lastCommand = useRef<Command | null>(command);
  useEffect(() => {
    if (command && command !== lastCommand.current) setOpen(command.open);
    lastCommand.current = command;
  }, [command, setOpen]);
  const look = TONE[tone];
  const Icon = look.icon;
  return (
    <section
      ref={sectionRef}
      id={id}
      className={`scroll-mt-24 rounded-card border border-line border-l-4 bg-surface shadow-card ${look.edge}`}
    >
      {/* The button holds only the name, and its ::after stretches over the whole row so
          pressing anywhere on it folds. The hint sits beside the button rather than inside it:
          inside, it became part of the button's name and any link in it (a job's "Open line")
          was a control nested in a control. The hint lets presses through to the row; its
          links and the (i) sit above the stretched target. */}
      <div className="relative flex items-center gap-2 pr-3 sm:pr-4">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 py-3 pl-3 sm:pl-4">
          <h2 className="min-w-0">
            <button
              type="button"
              aria-expanded={open}
              aria-controls={bodyId}
              onClick={(e) => {
                keepInView(e.currentTarget);
                setOpen(!open);
              }}
              className="flex min-w-0 items-center gap-3 rounded-sm text-left after:absolute after:inset-0 after:rounded-card after:content-[''] focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-brand touch:min-h-11"
            >
              <ChevronDown
                aria-hidden
                className={`h-4 w-4 shrink-0 text-ink-muted transition-transform ${open ? "" : "-rotate-90"}`}
              />
              <span aria-hidden className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${look.chip}`}>
                <Icon className="h-4 w-4" />
              </span>
              <span className={`text-body font-semibold ${look.title}`}>{title}</span>
            </button>
          </h2>
          {hint ? (
            <span className="pointer-events-none text-meta text-ink-muted [&_a]:pointer-events-auto [&_a]:relative">
              {hint}
            </span>
          ) : null}
        </div>
        {info ? (
          <span className="relative shrink-0">
            <InfoTip label={title.toLowerCase()} align="end">
              {info}
            </InfoTip>
          </span>
        ) : null}
        {aside ? <span className="shrink-0 rounded-full bg-surface-muted px-2 py-0.5 text-meta">{aside}</span> : null}
      </div>
      {/* Hidden rather than unmounted, so a half-filled form survives a fold. */}
      <div id={bodyId} hidden={!open} className="mx-3 border-t border-line px-1 pb-5 pt-4 sm:mx-4">
        {children}
      </div>
    </section>
  );
}
