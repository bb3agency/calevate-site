import type { CampaignProgress } from "@/lib/api/campaigns";

/**
 * Whether a paused campaign's Resume waits on the owner, for every screen that offers one
 * (the campaign page's Start and the list row's Resume).
 *
 * Only an opt-out review still owed holds it (`complaint_review_required`, the server's own
 * flag). The pause reason alone holds nothing: it stays on the campaign until it is
 * resumed, so a confirmed review, a raised spending limit or a new month would otherwise
 * hold Resume for ever. Whether credit or the limit still stop the campaign is the server's
 * answer to the press (`controls.assert_resumable`), shown where the press was made.
 */
export function reviewHoldsResume(
  progress: Pick<CampaignProgress, "complaint_review_required"> | undefined,
): boolean {
  return progress?.complaint_review_required === true;
}

/**
 * The list row carries no `complaint_review_required`, so a row paused for a complaint
 * spike reads it from the campaign itself. No other pause reason can owe a review.
 */
export function needsReviewRead(campaign: { status: string; pause_reason?: string | null }): boolean {
  return campaign.status === "paused" && campaign.pause_reason === "complaint_spike";
}
