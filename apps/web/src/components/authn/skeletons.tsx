/**
 * The waits of the signed-in auth screens, drawn as skeletons of the layout that follows
 * rather than sentence cards, so nothing jumps when the answer lands (REDESIGN-2). Each
 * wait is one polite status whose words are for a screen reader; the bars are hidden.
 */

const BAR = "animate-pulse rounded bg-ink/[0.06] motion-reduce:animate-none";

/** One bar. Widths are Tailwind classes so they stay on the token scale. */
export function Bar({ className }: { className: string }) {
  return <div aria-hidden className={`${BAR} ${className}`} />;
}

/** A settings row in waiting: a label on the left, a short value on the right. */
export function RowBars({ value = "w-20" }: { value?: string }) {
  return (
    <div className="flex items-center justify-between gap-6 py-4">
      <Bar className="h-3.5 w-28" />
      <Bar className={`h-3.5 ${value}`} />
    </div>
  );
}

/** The header's identity line: an account name and a role pill. */
export function IdentityBars() {
  return (
    <div aria-hidden className="mt-2 flex h-6 items-center gap-2">
      <Bar className="h-4 w-40" />
      <Bar className="h-5 w-14 rounded-full" />
    </div>
  );
}

/** The two account rows, while `/v1/me` is in flight. */
export function AccountRowsSkeleton() {
  return (
    <div role="status" aria-live="polite" className="divide-y divide-line border-y border-line">
      <span className="sr-only">Reading your account…</span>
      <RowBars value="w-32" />
      <RowBars value="w-48" />
    </div>
  );
}

/** Everything under the page heading, while the session itself is being checked. */
export function AccountPageSkeleton() {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">Checking your session…</span>
      <IdentityBars />
      <div className="mt-10 space-y-10">
        {[2, 2, 2].map((rows, section) => (
          <div key={section} aria-hidden>
            <Bar className="mb-3 h-4 w-24" />
            <div className="divide-y divide-line border-y border-line">
              {Array.from({ length: rows }).map((_, row) => (
                <RowBars key={row} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Any guarded screen while its session is checked (`SessionGate`): a heading bar over a
 * few hairline rows, the shape of every screen behind the gate.
 */
export function SessionWaitSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div aria-hidden className="space-y-6">
        <Bar className="h-5 w-40" />
        <div className="divide-y divide-line border-y border-line">
          <RowBars value="w-16" />
          <RowBars value="w-16" />
          <RowBars value="w-16" />
        </div>
      </div>
    </div>
  );
}
