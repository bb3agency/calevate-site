/**
 * What a screen shows from the moment it is opened until its code has arrived.
 *
 * Rendered by the `loading.tsx` files under `app/c/[slug]`. Without one, Next keeps the
 * screen being LEFT on view while the next route's JavaScript downloads, because the
 * navigation runs in a transition with no Suspense boundary to fall back to. On a phone
 * network a screen's own code can take seconds, and a tap that changes nothing for that
 * long reads as a broken page.
 *
 * A server component with no client imports, so the fallback is part of the prefetched
 * route payload and costs no download of its own. The shapes follow the screen that is
 * on its way, so the page does not jump when it arrives.
 */

export type RouteLoadingShape = "page" | "list" | "detail" | "steps";

const BAR = "animate-pulse rounded bg-black/5 motion-reduce:animate-none dark:bg-white/10";

function Bar({ className }: { className: string }) {
  return <div className={`${BAR} ${className}`} />;
}

export function RouteLoading({ shape = "page", label }: { shape?: RouteLoadingShape; label: string }) {
  return (
    <div role="status" aria-live="polite" className="pb-12">
      <span className="sr-only">{label}</span>
      <div aria-hidden>
        {shape === "list" && <ListShape />}
        {shape === "detail" && <DetailShape />}
        {shape === "steps" && <StepsShape />}
        {shape === "page" && <PageShape />}
      </div>
    </div>
  );
}

/** A page header with its button, then rows. */
function ListShape() {
  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center justify-end gap-2">
        <Bar className="h-11 w-32" />
        <Bar className="h-11 w-32" />
      </div>
      <div className="divide-y divide-line border-y border-line">
        {[0, 1, 2].map((row) => (
          <div key={row} className="flex items-center gap-3 px-4 py-3.5">
            <div className="min-w-0 flex-1 space-y-2">
              <Bar className="h-4 w-40 max-w-full" />
              <Bar className="h-3 w-56 max-w-full" />
            </div>
            <Bar className="h-6 w-16 shrink-0" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** One record: the way back, its name, its switches, its tabs, then the first tab. */
function DetailShape() {
  return (
    <div className="space-y-6">
      <Bar className="h-4 w-24" />
      <div className="space-y-3">
        <Bar className="h-7 w-48 max-w-full" />
        <Bar className="h-4 w-64 max-w-full" />
      </div>
      <div className="flex flex-wrap gap-2">
        <Bar className="h-11 w-28" />
        <Bar className="h-11 w-28" />
      </div>
      <div className="flex gap-2 border-b border-line pb-2">
        {[0, 1, 2, 3].map((tab) => (
          <Bar key={tab} className="h-9 w-20" />
        ))}
      </div>
      <div className="space-y-2">
        {[0, 1, 2, 3, 4].map((row) => (
          <Bar key={row} className="h-8" />
        ))}
      </div>
    </div>
  );
}

/** A guided flow: where you are, a heading, a sentence, two fields and the next button. */
function StepsShape() {
  return (
    <div className="max-w-2xl space-y-5">
      <Bar className="h-3 w-28" />
      <Bar className="h-7 w-56 max-w-full" />
      <Bar className="h-4 w-72 max-w-full" />
      <Bar className="h-11" />
      <Bar className="h-11" />
      <Bar className="h-11 w-32" />
    </div>
  );
}

function PageShape() {
  return (
    <div className="space-y-4">
      <Bar className="h-7 w-48 max-w-full" />
      {[0, 1, 2, 3].map((row) => (
        <Bar key={row} className="h-8" />
      ))}
    </div>
  );
}
