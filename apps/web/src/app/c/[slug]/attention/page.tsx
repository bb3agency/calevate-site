"use client";

import Link from "next/link";
import { use, type ComponentType } from "react";
import { ArrowRight, BookOpen, Megaphone, Share2, ShieldAlert } from "lucide-react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import { useAttention, type AttentionKind } from "@/lib/api/attention";
import { useMe } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

/**
 * Per-kind copy, colour and icon. Plain words, not system nouns: the reader is a
 * business owner, so "Call blocked" beats "lead_blocked". Colours follow the same
 * temperature scale as the rest of the app — rose for things broken on their side, amber
 * for things the rules stopped, sky for things merely stuck, and the neutral ink tokens
 * for a review outcome, which is news rather than trouble.
 *
 * `Record<AttentionKind, …>` over the GENERATED union, so a fifth kind on the server is a
 * type error here rather than an unstyled chip nobody notices.
 */
const KIND_COPY: Record<
  AttentionKind,
  { label: string; tone: string; medallion: string; icon: ComponentType<{ className?: string }> }
> = {
  lead_blocked: {
    label: "Call blocked",
    tone: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
    medallion: "bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-400",
    icon: ShieldAlert,
  },
  delivery_failed: {
    label: "Delivery failed",
    tone: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
    medallion: "bg-rose-50 text-rose-600 dark:bg-rose-950 dark:text-rose-400",
    icon: Share2,
  },
  campaign_stalled: {
    label: "Campaign stalled",
    tone: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
    medallion: "bg-sky-50 text-sky-600 dark:bg-sky-950 dark:text-sky-400",
    icon: Megaphone,
  },
  kb_rejected: {
    label: "Knowledge not accepted",
    tone: "bg-black/5 text-ink-muted dark:bg-white/10",
    medallion: "bg-black/5 text-ink-muted dark:bg-white/10",
    icon: BookOpen,
  },
};

/** The neutral fallbacks, once: a kind this build has never heard of still gets a row. */
const UNKNOWN_TONE = "bg-black/5 text-ink-muted dark:bg-white/10";

/**
 * The "needs attention" queue (SURFACES §2b).
 *
 * The platform blocks calls, campaigns and knowledge on purpose — compliance gate, DNC,
 * review — and each block is correct behaviour that still leaves the owner with something
 * to decide. This screen is the promise that none of that happens silently: if we stopped
 * it, it is listed here with the reason and the fix.
 *
 * Restyled onto the design tokens and the shared primitives. Three claims the screen was
 * making that it should not have been:
 *
 * - **Its own `<h1>Needs attention</h1>`**, beside the shell's title from the nav list.
 * - **A failed request rendered an empty Card** — no rows, no empty state, just a blank
 *   panel under the notice. "Nothing needs you right now" and "we could not read your
 *   queue" are opposite facts, and a blank box is read as the first one. The empty state
 *   now requires the server to have SAID zero (`total === 0`), and when there is no data
 *   at all there is no panel, only the refusal.
 * - **The list is capped and the counts are not.** `/v1/attention` merges four sources
 *   and slices to `limit` (50), newest first, while `counts`/`total` are counted
 *   separately from the rows and cover everything that EXISTS — so a busy account is
 *   shown 50 rows under a badge reading 78 with nothing to explain the gap. The gap is
 *   now stated, along with which end of the queue is missing.
 *
 *   This screen prints the server's numbers as fact, which is right — inventing a "25+"
 *   is not a screen's job — and the server has to earn it. It did not until
 *   crm/attention.py stopped counting its own capped page; both numbers in "showing the
 *   N most recent of M" are now true, M included, and each source is fetched to the
 *   merged limit so "most recent" means most recent across all four.
 *
 * Hard rule 6 holds at the row and it holds SERVER-side: `title` names a blocked lead by
 * its captured name, falling back to a MASKED number (crm/attention.py::blocked_leads),
 * and this screen renders what it is given without reconstructing anything from it.
 */
export default function AttentionPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const queue = useAttention(session);
  const me = useMe(session);

  /**
   * `GET /v1/attention` requires `leads:read` — staff work this queue, so it is
   * deliberately NOT gated on an owner permission (crm/routes.py says so at the
   * decorator). Read off `/v1/me` all the same: a session that lacks it should be told,
   * once and quietly, rather than shown a red alert that reads like an outage.
   *
   * Nothing is refused while `/v1/me` is in flight, and nothing is refused if it failed —
   * we do not know, so the request goes out and the API's own answer renders.
   */
  const refused = me.data !== undefined && !me.data.permissions.includes("leads:read");
  if (refused) {
    return (
      <RestrictionNote reason="This queue needs permission to read leads, which this account does not have. Ask your account owner for access." />
    );
  }

  const data = queue.data;
  // `lookup`, not `counts[kind]`: `counts` is parsed from JSON and therefore inherits
  // Object.prototype (src/lib/lookup.ts). The API omits a kind it found nothing for, so
  // absent genuinely means zero here — which is the one place `?? 0` is the truth and
  // not a guess.
  const counts: Record<string, number> = data?.counts ?? {};
  const countOf = (kind: AttentionKind): number => lookup(counts, kind) ?? 0;
  const kinds = (Object.keys(KIND_COPY) as AttentionKind[]).filter((kind) => countOf(kind) > 0);

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Everything the platform stopped, and why. When a call is blocked, a delivery fails
        or a campaign stalls, it never happens silently — it shows up here with what to do
        next.
      </p>

      {queue.error && <ProblemNotice error={queue.error} onRetry={() => void queue.refetch()} />}

      {/* Summary chips: a fast read of WHERE the trouble is before scanning the list.
          Kinds with zero items are omitted — an all-zeros row would just be noise. */}
      {kinds.length > 0 && (
        // Named as a group so a screen reader — and a test — can ask for the summary
        // rather than for "the first element that happens to say Call blocked", which is
        // also the badge on every matching row below.
        <div role="group" aria-label="Queue summary" className="flex flex-wrap gap-2">
          {kinds.map((kind) => {
            const copy = KIND_COPY[kind];
            const Icon = copy.icon;
            return (
              <span
                key={kind}
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${copy.tone}`}
              >
                <Icon className="h-3.5 w-3.5" />
                {copy.label}
                <span className="font-semibold tabular-nums">{formatCount(countOf(kind))}</span>
              </span>
            );
          })}
        </div>
      )}

      {/* No data means no panel. A Card with nothing in it under an error notice reads as
          "nothing needs you", which is the single sentence this screen must never say by
          accident. */}
      {!data ? (
        queue.isLoading ? (
          <Card>
            <Skeleton rows={5} />
          </Card>
        ) : null
      ) : data.total === 0 ? (
        <Card>
          <EmptyState
            title="Nothing needs you right now."
            hint="Blocked calls, failed deliveries and stalled campaigns will appear here."
          />
        </Card>
      ) : (
        <Card bodyClassName="p-2">
          <ul className="divide-y divide-line">
            {data.items.map((item) => {
              // `kind` is a generated union, but the union is a compile-time claim about a
              // runtime string — the API can add a kind without this build knowing. Fails
              // VISIBLE: an unnameable kind still lists its item, badged with its own name
              // in neutral ink, because "needs attention" hiding an item is the one
              // failure this screen exists to prevent.
              const copy = lookup(KIND_COPY, item.kind);
              const Icon = copy?.icon ?? ShieldAlert;
              return (
                <li
                  key={`${item.kind}-${item.id}-${item.occurred_at}`}
                  className="flex items-start gap-4 px-4 py-3.5"
                >
                  <span
                    className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
                      copy?.medallion ?? UNKNOWN_TONE
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                  </span>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                          copy?.tone ?? UNKNOWN_TONE
                        }`}
                      >
                        {copy?.label ?? item.kind.replace(/_/g, " ")}
                      </span>
                      {/* The server's own sentence. A blocked lead is named by its
                          captured name or a MASKED number and never a raw one (hard rule
                          6) — this screen renders it and builds nothing from it. */}
                      {/* `min-w-0 break-words`: the title carries a MASKED E.164 number
                          (`+9198765•••10`), which has no space to wrap at, and a flex item
                          defaults to `min-width: auto` — so at 320px the sentence painted
                          17px outside the row instead of wrapping onto a second line. */}
                      <span className="min-w-0 break-words text-sm font-semibold text-ink">
                        {item.title}
                      </span>
                    </div>
                    {/* The detail line is the point of the screen: the title only names
                        the subject, the detail is the remedy — what happened and what the
                        owner should do. Its own full-width line so it is never crushed
                        between badge and timestamp. */}
                    <p className="mt-1 text-[13px] text-ink-muted">{item.detail}</p>
                    {item.href && (
                      <Link
                        href={href(`/c/${slug}${item.href}`)}
                        className="mt-2 inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 text-xs font-semibold text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
                      >
                        Open
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    )}
                  </div>

                  <span className="shrink-0 whitespace-nowrap text-xs text-ink-faint">
                    {formatIST(item.occurred_at)}
                  </span>
                </li>
              );
            })}
          </ul>

          {/* The queue is capped at `limit` while `total` is not, and the API sorts newest
              first before it slices — so the rows that fall off are the OLDEST. Saying
              which end is missing is the difference between a list a client can trust and
              one they quietly stop believing when the badge disagrees with it.

              `total` is the server's count of the whole set, never `items.length` under
              another name, so this sentence's denominator is a real number and this
              condition is a real question rather than one that answers itself. */}
          {data.total > data.items.length && (
            <p className="border-t border-line px-4 py-3 text-xs text-ink-faint">
              Showing the {formatCount(data.items.length)} most recent of{" "}
              {formatCount(data.total)}. Older items are not listed.
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
