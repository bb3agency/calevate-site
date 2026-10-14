"use client";

import Link from "next/link";
import { useState } from "react";

import {
  NOTICE_BAR,
  NOTICE_BASE,
  PRIMARY_BUTTON,
  ProblemNotice,
  Skeleton,
  formatIST,
} from "@/components/ui";
import {
  useComplaintReview,
  useOptOuts,
  type CampaignProgress,
} from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { BLOCKER_COPY, PAUSE_COPY, blockerDestination } from "./blockerCopy";

/**
 * WHY THIS CAMPAIGN IS NOT CALLING, when that is the case — one quiet left-rule notice.
 *
 * - A paused campaign names its pause (`pause_reason`) with the way out: add credit, raise
 *   the limit, or (a complaint spike) read the opt-outs and confirm, which the server
 *   requires before Resume works.
 * - A running campaign the gate would refuse says "Not calling" with each reason and its
 *   fix (`not_calling`, the dispatcher's own rules), instead of claiming to run.
 * - A running campaign outside its hours says it is waiting for them.
 */
export function CampaignStateNotice({
  slug,
  campaignId,
  progress,
  canWrite,
  refusal,
}: {
  slug: string;
  campaignId: string;
  progress: CampaignProgress;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  const { href } = useClientRealm();
  const at = (path: string) => href(`/c/${slug}${path}`);

  if (progress.status === "paused" && progress.pause_reason) {
    const copy = lookup(PAUSE_COPY, progress.pause_reason);
    const fix =
      progress.pause_reason === "out_of_credit"
        ? { href: at("/billing?tab=credits"), label: "Add credit" }
        : progress.pause_reason === "spend_cap"
          ? { href: at("/billing?tab=usage"), label: "See your monthly spending limit" }
          : undefined;
    return (
      <div role="status" className={`${NOTICE_BASE} ${NOTICE_BAR.warn}`}>
        <p className="font-semibold">{copy?.title ?? "Paused"}</p>
        <p className="text-ink-muted">{copy?.text}</p>
        {fix && (
          <Link href={fix.href} className="inline-block font-medium text-ink underline underline-offset-2">
            {fix.label}
          </Link>
        )}
        {progress.pause_reason === "complaint_spike" && (
          <ComplaintReview
            campaignId={campaignId}
            reviewedAt={progress.complaint_reviewed_at ?? null}
            required={progress.complaint_review_required}
            canWrite={canWrite}
            refusal={refusal}
          />
        )}
      </div>
    );
  }

  if (progress.status === "running" && progress.not_calling.length > 0) {
    return (
      <div role="status" className={`${NOTICE_BASE} ${NOTICE_BAR.stop}`}>
        <p className="font-semibold">Not calling anyone right now</p>
        <ul className="space-y-2">
          {progress.not_calling.map((blocker) => {
            const fix = blockerDestination(blocker.rule, at, campaignId);
            return (
              <li key={blocker.rule} className="text-ink-muted">
                {lookup(BLOCKER_COPY, blocker.rule)?.text ?? blocker.reason}
                {fix && (
                  <>
                    {" "}
                    <Link href={fix.href} className="font-medium text-ink underline underline-offset-2">
                      {fix.label}
                    </Link>
                  </>
                )}
              </li>
            );
          })}
        </ul>
        <p className="text-meta text-ink-muted">It starts calling again by itself once this is cleared.</p>
      </div>
    );
  }

  if (progress.status === "running" && progress.waiting_for_calling_hours) {
    const hours = progress.calling_hours;
    return (
      <div role="status" className={`${NOTICE_BASE} ${NOTICE_BAR.neutral}`}>
        <p>
          Waiting for calling hours. Calls go out {hours ? `${hours.start}–${hours.end}` : "9am–9pm"} IST.
        </p>
      </div>
    );
  }
  return null;
}

/**
 * The opt-outs behind a complaint-spike pause, in the callers' own words as the consent
 * ledger stored them (redacted when captured: a number said aloud is masked), and the
 * confirmation the server needs before Resume works. The checkbox is the client saying
 * they read them; the button records it (audited).
 */
function ComplaintReview({
  campaignId,
  reviewedAt,
  required,
  canWrite,
  refusal,
}: {
  campaignId: string;
  reviewedAt: string | null;
  required: boolean;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  const { session, href } = useClientRealm();
  const optOuts = useOptOuts(session, campaignId, true);
  const review = useComplaintReview(session, campaignId);
  const [read, setRead] = useState(false);
  const slug = session.orgSlug;

  return (
    <div className="mt-2 space-y-3">
      {optOuts.isLoading ? (
        <Skeleton rows={2} />
      ) : optOuts.error || !optOuts.data ? (
        <ProblemNotice
          error={optOuts.error ?? new Error("The opt-outs did not load.")}
          onRetry={() => optOuts.refetch()}
        />
      ) : (
        <ul className="divide-y divide-line border-y border-line">
          {optOuts.data.map((item, index) => (
            <li key={`${item.call_id}-${index}`} className="space-y-0.5 py-2">
              <p className="text-ink">
                {item.words_redacted ? <q>{item.words_redacted}</q> : "Asked not to be called"}
              </p>
              <p className="text-meta text-ink-muted">
                {item.contact_name?.trim() || "Someone on the list"} · {formatIST(item.at)}
                {item.call_id && (
                  <>
                    {" · "}
                    <Link href={href(`/c/${slug}/calls/${item.call_id}`)} className="underline underline-offset-2">
                      Open call
                    </Link>
                  </>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}
      {required ? (
        <div className="space-y-2">
          <label className="flex items-start gap-2 touch:min-h-11">
            <input
              type="checkbox"
              checked={read}
              onChange={(e) => setRead(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-line accent-brand"
            />
            <span>
              I have read what these people said, and I am sure the rest of this list agreed to be called.
            </span>
          </label>
          {review.error ? <ProblemNotice error={review.error} /> : null}
          <button
            type="button"
            title={refusal}
            disabled={!read || !canWrite || review.isPending}
            onClick={() => review.mutate()}
            className={PRIMARY_BUTTON}
          >
            {review.isPending ? "Saving…" : "Confirm I've reviewed them"}
          </button>
        </div>
      ) : (
        <p className="text-meta text-ink-muted">
          Reviewed {reviewedAt ? formatIST(reviewedAt) : ""}. You can resume the campaign.
        </p>
      )}
    </div>
  );
}
