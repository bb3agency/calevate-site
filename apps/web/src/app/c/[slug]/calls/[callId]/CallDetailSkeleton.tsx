/**
 * The call screen while it loads, drawn in the page's own shape — the name, the verdict
 * and its action, the player and a few transcript rows — so nothing jumps when the call
 * arrives. One announcement for the whole screen; the bars are hidden from the
 * accessibility tree, as `Skeleton`'s are.
 */
export function CallDetailSkeleton() {
  const bar = "animate-pulse rounded bg-ink/[0.06] motion-reduce:animate-none";
  return (
    <div role="status" aria-live="polite" className="max-w-5xl space-y-8 pb-12">
      <span className="sr-only">Loading this call</span>
      <div aria-hidden className="space-y-8">
        <div className={`${bar} h-4 w-24`} />
        <div className="space-y-2">
          <div className={`${bar} h-7 w-56 max-w-full`} />
          <div className={`${bar} h-4 w-72 max-w-full`} />
        </div>
        <div className="space-y-3">
          <div className={`${bar} h-6 w-40`} />
          <div className={`${bar} h-4 w-full max-w-prose`} />
          <div className={`${bar} h-4 w-5/6 max-w-prose`} />
          <div className={`${bar} mt-4 h-10 w-56 max-w-full`} />
        </div>
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-12">
          <div className="space-y-4">
            <div className={`${bar} h-12 w-full`} />
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="grid grid-cols-[3rem_minmax(0,1fr)] gap-x-2">
                <div className={`${bar} h-4 w-8`} />
                <div className={`${bar} h-5 ${i % 2 ? "w-2/3" : "w-full"}`} />
              </div>
            ))}
          </div>
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className={`${bar} h-5 w-full`} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
