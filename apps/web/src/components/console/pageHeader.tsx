import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";

/**
 * THE TOP OF A SCREEN: what this is, its state, and the action that matters.
 *
 * - `title` names the thing (an agent's name, a campaign's name). On a screen whose
 *   subject is already the shell's page title (the nav label), omit `title` and use
 *   `description` alone — the shell prints that title as the page's `h1`, and a second
 *   one is a visible duplicate (UX-DOCTRINE §2).
 * - `description` is ONE line naming the job. Reasoning goes behind an ⓘ, not here.
 * - `status` is a pill or two: state, never a paragraph about state.
 * - `actions` holds the screen's one primary action and at most a quiet secondary or a
 *   `RowMenu`. On a phone they wrap under the title, full width.
 *
 * The heading is an `h2` by default because the shell already owns the page's `h1`.
 */
export function PageHeader({
  title,
  description,
  status,
  actions,
  back,
  headingLevel = 2,
  className = "",
}: {
  title?: ReactNode;
  description?: ReactNode;
  status?: ReactNode;
  actions?: ReactNode;
  back?: { href: string; label: string };
  headingLevel?: 1 | 2;
  className?: string;
}) {
  const Heading = headingLevel === 1 ? "h1" : "h2";
  return (
    <header className={`space-y-2 ${className}`}>
      {back && (
        <Link
          href={back.href}
          className="inline-flex items-center gap-1.5 rounded-sm text-[13px] font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          {back.label}
        </Link>
      )}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1 basis-64">
          {title && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <Heading className="min-w-0 break-words text-xl font-semibold tracking-tight text-ink">
                {title}
              </Heading>
              {status}
            </div>
          )}
          {!title && status && <div className="flex flex-wrap items-center gap-2">{status}</div>}
          {description && (
            <p className={`max-w-prose text-[14px] text-ink-muted ${title || status ? "mt-1" : ""}`}>
              {description}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto [&>*]:max-sm:flex-1">
            {actions}
          </div>
        )}
      </div>
    </header>
  );
}
