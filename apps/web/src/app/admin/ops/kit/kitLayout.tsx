import type { ReactNode } from "react";

/**
 * The frame of the living kit page: one section per component family, one labelled
 * specimen per state. Specimens are real components with real props, never screenshots,
 * so the page is what the browser checks at 375, 768 and 1280 px.
 */
export function KitSection({
  id,
  title,
  lead,
  children,
}: {
  id: string;
  title: string;
  /** One sentence: when to reach for this family. */
  lead?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-6 space-y-4 border-t border-line pt-6">
      <div>
        <h2 id={`${id}-title`} className="text-heading text-ink">
          {title}
        </h2>
        {lead ? <p className="mt-1 max-w-prose text-body text-ink-muted">{lead}</p> : null}
      </div>
      {children}
    </section>
  );
}

export function KitDemo({
  label,
  note,
  children,
  wide = false,
}: {
  /** The component and state shown: "ActionButton · pending". */
  label: string;
  note?: ReactNode;
  children: ReactNode;
  /** Takes the full row instead of a grid cell. */
  wide?: boolean;
}) {
  return (
    <div className={`min-w-0 space-y-2 rounded-card border border-line bg-surface p-4 ${wide ? "md:col-span-2" : ""}`}>
      <h3 className="text-meta font-semibold text-ink-muted">{label}</h3>
      <div className="min-w-0">{children}</div>
      {note ? <p className="text-meta text-ink-faint">{note}</p> : null}
    </div>
  );
}

export function KitGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 md:grid-cols-2">{children}</div>;
}
