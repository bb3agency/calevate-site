"use client";

/**
 * A client's campaigns, and the three things an operator may do to one (F-10): archive it
 * with a reason, restore it, or delete a draft that never dialled. The rules are the
 * service's (`apps/api/campaigns/archive.py`), the same as the client's own buttons and Pip;
 * this screen adds the reason the client reads and says whether the client was told.
 */

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import { FIELD, FIELD_HINT, FIELD_LABEL, ProblemNotice, RestrictionNote, Skeleton, formatIST } from "@/components/ui";
import { HAIRLINE_LIST, StatusPill, sentenceCase } from "@/components/admin/kit";
import { useAdminAccess } from "@/app/admin/access";
import {
  type AdminCampaignAct,
  useAdminArchiveCampaign,
  useAdminDeleteCampaign,
  useAdminRestoreCampaign,
  useTenant,
  useTenantCampaignPage,
} from "@/lib/api/admin";
import type { CampaignSummary } from "@/lib/api/campaigns";

/** `archive.MIN_REASON_CHARS` / `MAX_REASON_CHARS`; the server refuses outside them. */
export const MIN_REASON = 3;
export const MAX_REASON = 280;

type Act = "archive" | "delete";

/** What happened, in one line, including whether the client was told. */
export function actOutcome(act: "archive" | "restore" | "delete", result: AdminCampaignAct): string {
  if (!result.changed) {
    return act === "restore" ? "It was not archived. Nothing changed." : "Already archived. Nothing changed.";
  }
  const told = result.client_notified ? " The client was told." : " The client was not sent a notice.";
  if (act === "delete") return `Deleted.${told}`;
  if (act === "restore") return `Restored as ${sentenceCase(result.status).toLowerCase()}.${told}`;
  return `Archived.${told}`;
}

export function CampaignsScreen({ tenantId }: { tenantId: string }) {
  const tenant = useTenant(tenantId).data;
  const slug = tenant?.slug ?? "";
  const [archived, setArchived] = useState(false);
  const page = useTenantCampaignPage(slug, archived);
  const write = useAdminAccess("admin:tenants", "archive or delete this client's campaigns");

  const archive = useAdminArchiveCampaign(tenantId);
  const remove = useAdminDeleteCampaign(tenantId);
  const restore = useAdminRestoreCampaign(tenantId);
  const archiveFeedback = useActionFeedback(archive, { errorDisplay: "inline" });
  const removeFeedback = useActionFeedback(remove, { errorDisplay: "inline" });
  const restoreFeedback = useActionFeedback(restore, { errorDisplay: "inline" });

  const [confirming, setConfirming] = useState<{ act: Act; campaign: CampaignSummary } | null>(null);
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState<{ name: string; line: string } | null>(null);

  if (!tenant) return null;

  const reasonOk = reason.trim().length >= MIN_REASON && reason.trim().length <= MAX_REASON;
  const open = (act: Act, campaign: CampaignSummary) => {
    archive.reset();
    remove.reset();
    setReason("");
    setConfirming({ act, campaign });
  };
  const confirm = () => {
    if (!confirming) return;
    const { act, campaign } = confirming;
    const vars = { campaignId: campaign.id, reason: reason.trim() };
    const done = (result: AdminCampaignAct) => {
      setOutcome({ name: campaign.name, line: actOutcome(act, result) });
      setConfirming(null);
    };
    if (act === "archive") archive.mutate(vars, { onSuccess: done });
    else remove.mutate(vars, { onSuccess: done });
  };

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader
        title="Campaigns"
        description="Archive a campaign, restore it, or delete a draft that never called. The client is told why."
      />
      <RestrictionNote reason={write.reason} />

      <div className="flex gap-4" role="group" aria-label="Which campaigns">
        <button
          type="button"
          className={`${TEXT_ACTION} aria-pressed:underline`}
          aria-pressed={!archived}
          onClick={() => setArchived(false)}
        >
          Live
        </button>
        <button
          type="button"
          className={`${TEXT_ACTION} aria-pressed:underline`}
          aria-pressed={archived}
          onClick={() => setArchived(true)}
        >
          Archived{page.data && !archived ? ` (${page.data.archived_total})` : ""}
        </button>
      </div>

      {/* Above the list, not on the row: the row leaves this list once the act lands. */}
      {outcome && (
        <p role="status" className="text-body text-ink">
          <span className="font-medium">{outcome.name}</span> <span>{outcome.line}</span>
        </p>
      )}
      {restore.error && <ProblemNotice error={restore.error} />}
      {page.error ? (
        <ProblemNotice error={page.error} onRetry={() => page.refetch()} />
      ) : page.isLoading || !page.data ? (
        <Skeleton rows={3} />
      ) : page.data.items.length === 0 ? (
        <EmptyState message={archived ? "No archived campaigns." : "No campaigns yet."} />
      ) : (
        <ul className={HAIRLINE_LIST}>
          {page.data.items.map((campaign) => (
            <li key={campaign.id} className="space-y-1 py-3 text-body sm:px-2">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="min-w-0 break-words font-medium text-ink">{campaign.name}</span>
                <StatusPill tone="neutral">{sentenceCase(campaign.status)}</StatusPill>
                <span className="text-meta text-ink-muted">
                  {campaign.archived_at
                    ? `Archived ${formatIST(campaign.archived_at)}`
                    : `Created ${formatIST(campaign.created_at)}`}
                </span>
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {archived ? (
                  <ActionButton
                    variant="secondary-sm"
                    status={restore.variables === campaign.id ? restoreFeedback.status : "idle"}
                    pendingLabel="Restoring…"
                    successLabel="Restored"
                    disabled={!write.allowed || restore.isPending}
                    onClick={() =>
                      restore.mutate(campaign.id, {
                        onSuccess: (result) =>
                          setOutcome({ name: campaign.name, line: actOutcome("restore", result) }),
                      })
                    }
                  >
                    Restore
                  </ActionButton>
                ) : (
                  <button
                    type="button"
                    className={TEXT_ACTION}
                    disabled={!write.allowed}
                    onClick={() => open("archive", campaign)}
                  >
                    Archive
                  </button>
                )}
                {campaign.status === "draft" && !campaign.launched_at && (
                  <button
                    type="button"
                    className={TEXT_ACTION_DANGER}
                    disabled={!write.allowed}
                    onClick={() => open("delete", campaign)}
                  >
                    Delete
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {confirming && (
        <ConfirmDialog
          title={
            confirming.act === "archive"
              ? `Archive ${confirming.campaign.name}`
              : `Delete ${confirming.campaign.name}`
          }
          confirmLabel={confirming.act === "archive" ? "Archive it" : "Delete it"}
          pendingLabel={confirming.act === "archive" ? "Archiving…" : "Deleting…"}
          status={confirming.act === "archive" ? archiveFeedback.status : removeFeedback.status}
          error={confirming.act === "archive" ? archive.error : remove.error}
          confirmDisabled={!reasonOk}
          onCancel={() => setConfirming(null)}
          onConfirm={confirm}
        >
          <p>
            {confirming.act === "archive"
              ? "A running campaign is paused first. Its calls, leads and charges are kept."
              : "This draft is removed for good. It never made a call."}
          </p>
          <label className="mt-3 block">
            <span className={FIELD_LABEL}>Reason the client will read</span>
            <textarea
              className={FIELD}
              rows={3}
              maxLength={MAX_REASON}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <span className={FIELD_HINT}>
              The client is told in the app and by email, with this reason.
            </span>
          </label>
        </ConfirmDialog>
      )}
    </div>
  );
}
