import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

/**
 * THE GUIDED CHOOSER: "what do you want to do?" as a list of jobs, each one line of what
 * it does, each opening the next step. The first step of every guided flow (an agent's
 * actions; later, adding a lead source or a destination).
 *
 * A list of buttons between hairlines rather than a grid of cards: the reader scans down
 * one column of sentences and picks one, which is the Hick's-law case doctrine §0 names,
 * and a grid of equal tiles is the "everything equal" defect in another shape. The
 * choice card (`console/choiceCard`) is still the control for picking an OPTION inside a
 * form; this is for picking a JOB, which navigates.
 */
export function Chooser({ label, children }: { label: string; children: ReactNode }) {
  return (
    <ul aria-label={label} className="divide-y divide-line border-y border-line">
      {children}
    </ul>
  );
}

export function ChooserItem({
  title,
  description,
  icon,
  note,
  disabled,
  onSelect,
}: {
  title: string;
  description: ReactNode;
  icon?: ReactNode;
  /** A short state beside the title: "On", "Not available yet". */
  note?: ReactNode;
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        disabled={disabled}
        onClick={onSelect}
        className="group flex w-full items-center gap-4 py-3.5 text-left transition-colors duration-(--duration-fast) hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand disabled:cursor-not-allowed disabled:hover:bg-transparent sm:px-2 touch:min-h-11"
      >
        {icon ? (
          <span aria-hidden className="shrink-0 text-ink-muted group-disabled:text-ink-faint">
            {icon}
          </span>
        ) : null}
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-body font-medium text-ink group-disabled:text-ink-muted">{title}</span>
            {note ? <span className="text-meta text-ink-muted">{note}</span> : null}
          </span>
          <span className="mt-0.5 block text-meta text-ink-muted">{description}</span>
        </span>
        <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-ink-faint group-disabled:opacity-0" />
      </button>
    </li>
  );
}
