import { lookup } from "@/lib/lookup";

/**
 * A campaign's status as a pill, and the slim progress bar its row carries.
 *
 * The status words are the server's own (`campaigns.status`), only capitalised. An unknown
 * value prints as it came rather than vanishing (`lookup`), because a status this build has
 * not heard of is still a fact about the campaign.
 */
const TONE: Record<string, string> = {
  draft: "border border-line bg-surface text-ink-muted",
  scheduled: "bg-ink/[0.06] text-ink",
  running: "bg-brand-soft text-brand-strong",
  paused: "border border-warn-line bg-warn-soft text-warn",
  completed: "bg-ink/[0.06] text-ink-muted",
  cancelled: "bg-ink/[0.06] text-ink-muted",
};

export function CampaignStatusPill({ status }: { status: string }) {
  const label = status.replace(/_/g, " ");
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${
        lookup(TONE, status) ?? TONE.draft
      }`}
    >
      {label.charAt(0).toUpperCase() + label.slice(1)}
    </span>
  );
}

/**
 * "12 of 120 reached" with a hairline bar. `scaleX` rather than `width`, so a poll that
 * moves it repaints without layout. A campaign with no contacts shows the words only.
 */
export function ReachBar({ reached, total }: { reached: number; total: number }) {
  const fraction = total > 0 ? Math.min(1, reached / total) : 0;
  return (
    <div className="space-y-1 sm:min-w-[7rem]">
      <p className="text-xs tabular-nums text-ink-muted">
        {reached.toLocaleString("en-IN")} of {total.toLocaleString("en-IN")} reached
      </p>
      {total > 0 && (
        <div aria-hidden className="h-1 overflow-hidden rounded-full bg-ink/[0.07]">
          <div
            className="h-full origin-left rounded-full bg-brand transition-transform duration-(--duration-slow) ease-(--ease-out-strong) motion-reduce:transition-none"
            style={{ transform: `scaleX(${fraction})` }}
          />
        </div>
      )}
    </div>
  );
}
