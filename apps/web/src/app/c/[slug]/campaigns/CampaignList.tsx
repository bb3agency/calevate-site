"use client";

import { Card, ProblemNotice, Skeleton, formatCount, formatIST } from "@/components/ui";
import { type CampaignSummary } from "@/lib/api/campaigns";
import { lookup } from "@/lib/lookup";

import { LIST_PROVENANCE_COPY } from "./blockerCopy";

/**
 * "YOUR CAMPAIGNS" — the landing list, and its three surface states.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6). One subject: which campaigns exist, what
 * state each is in, and which of them cannot be launched at all. §52 is handled here as
 * three mutually exclusive branches — a skeleton while the read is in flight, a refusal
 * when it failed or was PAUSED, and the list only from a response that arrived.
 */
export function CampaignList({
  campaigns,
  onOpen,
}: {
  campaigns: {
    data: CampaignSummary[] | undefined;
    isLoading: boolean;
    error: unknown;
    refetch: () => void;
  };
  onOpen: (campaignId: string) => void;
}) {
  return (
    <>

      {/* A skeleton, not an empty list: "you have no campaigns" is a claim about this
          business, and the request had not answered yet. */}
      {campaigns.isLoading && (
        <Card title="Your campaigns">
          <Skeleton rows={3} />
        </Card>
      )}

      {/* The third state the skeleton above does not cover. `isLoading` is
          `isPending && isFetching`, so it is FALSE for a query TanStack has PAUSED rather
          than started — which is what it does while the browser is offline. A paused
          query also has `error === null`, so the notice at the top of this screen renders
          nothing, and the list card below is simply absent: a client with ten campaigns
          saw a screen offering to create their first. */}
      {!campaigns.isLoading &&
        !campaigns.error &&
        !campaigns.data && (
          <Card title="Your campaigns">
            <ProblemNotice
              error={new Error("Your campaigns did not load.")}
              onRetry={() => campaigns.refetch()}
            />
          </Card>
        )}

      {(campaigns.data?.length ?? 0) > 0 && (
        <Card title="Your campaigns" bodyClassName="px-4 py-2 sm:px-6">
          {/* SYMPTOM this fixed: a draft built before the provenance rule existed is
              now blocked, and nothing on the landing view said so — the client saw a
              normal-looking draft, opened it, and met a refusal with no hint it was
              answerable. This used to be one general notice above the list, because the
              summary carried no consent field and the list genuinely could not tell
              WHICH drafts were affected. It can now: `consent_provenance_blocker` names
              the exact rule per row, so the warning moved onto the rows it is about and
              the rows it is not about say nothing. */}
          <ul className="divide-y divide-line">
            {(campaigns.data ?? []).map((campaign) => {
              const blocker = campaign.consent_provenance_blocker ?? null;
              // The worst-behaved of the copy tables, because `note` is tested for
              // TRUTH rather than for a property: `LIST_PROVENANCE_COPY["constructor"]`
              // is the `Object` function, which is truthy, so the row rendered a badge
              // with no text, a paragraph with no text, and a CLICKABLE BUTTON with no
              // label — an empty control on a compliance row. `lookup` returns
              // `undefined` for anything the table does not own (lib/lookup.ts).
              const note = lookup(LIST_PROVENANCE_COPY, blocker);
              return (
                <li key={campaign.id} className="py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => onOpen(campaign.id)}
                      className="text-sm font-semibold text-ink underline-offset-2 hover:underline"
                    >
                      {campaign.name}
                    </button>
                    <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs font-medium capitalize text-ink-muted dark:bg-white/10">
                      {campaign.status}
                    </span>
                    <span className="text-xs capitalize text-ink-faint">
                      {campaign.classification}
                    </span>
                    {/* The badge is the rule in the client's words. The enum name itself
                        is never rendered — it is the launch gate's vocabulary, not a
                        sentence anyone reading this list can act on. */}
                    {note && (
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${note.badgeClass}`}
                      >
                        {note.badge}
                      </span>
                    )}
                    <span className="ml-auto text-xs tabular-nums text-ink-faint">
                      {formatCount(campaign.connected)}/
                      {formatCount(campaign.contacts)} reached ·{" "}
                      {campaign.launched_at
                        ? formatIST(campaign.launched_at)
                        : "not launched"}
                    </span>
                  </div>
                  {note && (
                    <p className="mt-1 max-w-2xl text-xs text-ink-muted">
                      {note.text}{" "}
                      <button
                        type="button"
                        onClick={() => onOpen(campaign.id)}
                        className="font-semibold text-ink underline underline-offset-2"
                      >
                        {note.action}
                      </button>
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </>
  );
}
