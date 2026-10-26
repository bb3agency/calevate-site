import type { ReactNode } from "react";

/**
 * One half of the Training tab's "Try it" card (chat, or a call): a small h4 title, its
 * action beside it, one line under it. Takes `Section`'s props so a part can render in
 * either frame; `info` and `headingLevel` belong to the full section and are not drawn here.
 */
export function TryPart({
  title,
  description,
  action,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  info?: ReactNode;
  action?: ReactNode;
  headingLevel?: 2 | 3;
  children?: ReactNode;
}) {
  return (
    <div className="min-w-0 space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-ink">{title}</h4>
        {action}
      </div>
      {description ? <p className="text-meta text-ink-muted">{description}</p> : null}
      {children}
    </div>
  );
}
