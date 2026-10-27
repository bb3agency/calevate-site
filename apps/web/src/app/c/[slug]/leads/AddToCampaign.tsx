"use client";

import Link from "next/link";
import { useEffect, useId, useState, type ReactNode } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { ConfirmDialog } from "@/components/confirmDialog";
import { TypedConfirmation } from "@/components/typedConfirmation";
import { FIELD_INLINE, FIELD_LABEL, NoticeBox, ProblemNotice, formatCount } from "@/components/ui";
import {
  useAddLeadsToCampaign,
  useCampaigns,
  type AddLeadsResult,
  type CampaignSummary,
} from "@/lib/api/campaigns";
import type { Session } from "@/lib/api/client";
import type { LeadLens } from "@/lib/api/leads";

import { TYPED_CONFIRMATION_FROM, type BulkSelection } from "./BulkActionBar";

/** Only a campaign that has not started calling takes new people. */
const OPEN_STATUSES = new Set(["draft", "scheduled"]);

/**
 * "Add to a campaign" for the leads the table has selected (D-893 lane L3, item 12).
 *
 * Its own row under the bulk bar rather than a third verb inside it: the bulk bar's verbs
 * change a field on each lead and report changed/unchanged, while this one puts the leads
 * on a call list and reports added/left out, and folding both into one confirmation would
 * make its sentence and its result describe two different kinds of act.
 *
 * The scope is the bulk bar's own (`BulkSelection`): the ticked rows, or every lead the
 * filters match. In the second case the TABLE'S LENS is sent with the count the person
 * confirmed, and the server refuses a set that moved; a set larger than one request adds
 * comes back as a plan, shown with its own card.
 */
interface AddToCampaignProps {
  session: Session;
  slug: string;
  href: (path: string) => string;
  selection: BulkSelection;
  lens: LeadLens;
  /** The server's total for the lens; `undefined` while unknown. */
  filteredTotal: number | undefined;
  /** `leads:dispatch`, the campaign buttons' permission. */
  canAdd: boolean;
  addReason: string | null;
  renderPlan: (planId: string, onDismiss: () => void) => ReactNode;
  onAdded: () => void;
}

type Added = { campaign: CampaignSummary; added: AddLeadsResult };

export function AddToCampaign(props: AddToCampaignProps) {
  // The answer outlives the selection, which the screen clears once leads are added.
  const [result, setResult] = useState<Added | null>(null);
  const active = props.selection.wholeQuery || props.selection.ids.length > 0;
  return (
    <>
      {result && (
        <AddedNotice
          {...result}
          slug={props.slug}
          href={props.href}
          onDismiss={() => setResult(null)}
          renderPlan={props.renderPlan}
        />
      )}
      {/* Mounted only with a selection, so the Leads page reads no campaigns until then. */}
      {active && <Chooser {...props} onResult={setResult} />}
    </>
  );
}

function Chooser({
  session,
  slug,
  href,
  selection,
  lens,
  filteredTotal,
  canAdd,
  addReason,
  onAdded,
  onResult,
}: AddToCampaignProps & { onResult: (added: Added) => void }) {
  const campaigns = useCampaigns(session);
  const add = useAddLeadsToCampaign(session);
  const feedback = useActionFeedback(add, { errorDisplay: "inline" });
  const [campaignId, setCampaignId] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");
  const selectId = useId();

  // A changed selection retracts a confirmation in progress, as the bulk bar's does.
  useEffect(() => {
    setConfirming(false);
    setTyped("");
  }, [selection]);

  const open = campaigns.data ? campaigns.data.filter((c) => OPEN_STATUSES.has(c.status)) : [];
  const chosen = open.find((c) => c.id === campaignId) ?? open[0];
  const count = selection.wholeQuery ? filteredTotal : selection.ids.length;

  const needsTyping = count !== undefined && count >= TYPED_CONFIRMATION_FROM;
  const armed = count !== undefined && (!needsTyping || typed.trim() === String(count));
  const noun = count === 1 ? "lead" : "leads";

  const run = () => {
    if (!chosen || count === undefined) return;
    add.mutate(
      selection.wholeQuery
        ? { campaignId: chosen.id, lens, expectedCount: count }
        : { campaignId: chosen.id, leadIds: selection.ids },
      {
        onSuccess: (added) => {
          onResult({ campaign: chosen, added });
          setConfirming(false);
          onAdded();
        },
      },
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 basis-56">
          <label htmlFor={selectId} className={FIELD_LABEL}>
            Add to a campaign
          </label>
          {campaigns.isLoading ? (
            <select id={selectId} disabled className={`${FIELD_INLINE} mt-1 w-full touch:min-h-11`}>
              <option>Loading your campaigns…</option>
            </select>
          ) : campaigns.error || !campaigns.data ? null : open.length === 0 ? (
            <p className="mt-1 text-body text-ink-muted">
              No campaign is waiting to start.{" "}
              <Link href={href(`/c/${slug}/campaigns/new`)} className={TEXT_ACTION}>
                Create a campaign
              </Link>
            </p>
          ) : (
            <select
              id={selectId}
              value={chosen?.id ?? ""}
              onChange={(e) => setCampaignId(e.target.value)}
              className={`${FIELD_INLINE} mt-1 w-full touch:min-h-11`}
            >
              {open.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                  {c.status === "scheduled" ? " (scheduled)" : ""}
                </option>
              ))}
            </select>
          )}
        </div>
        {open.length > 0 && (
          <ActionButton
            variant="secondary-sm"
            disabled={!canAdd || count === undefined || !chosen}
            title={addReason ?? undefined}
            onClick={() => setConfirming(true)}
          >
            {count === undefined ? "Add these leads" : `Add ${formatCount(count)} ${noun}`}
          </ActionButton>
        )}
      </div>
      {campaigns.error != null && (
        <ProblemNotice error={campaigns.error} onRetry={() => campaigns.refetch()} />
      )}

      {confirming && chosen && count !== undefined ? (
        <ConfirmDialog
          title={`Add ${formatCount(count)} ${noun} to “${chosen.name}”?`}
          confirmLabel={`Add ${formatCount(count)}`}
          pendingLabel="Adding…"
          status={feedback.status}
          confirmDisabled={!armed}
          error={add.error}
          onCancel={() => setConfirming(false)}
          onConfirm={run}
        >
          <p className="font-medium text-ink">
            {selection.wholeQuery
              ? "Every lead matching these filters, not only the ones on screen."
              : "The leads you have ticked on this page."}
          </p>
          <p>
            Nobody is called now. They are called when the campaign starts, inside its calling
            hours. Numbers already on it, on the do-not-call list or outside India are left out.
          </p>
          {needsTyping && (
            <TypedConfirmation phrase={String(count)} value={typed} onChange={setTyped} inputMode="numeric" />
          )}
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

function AddedNotice({
  campaign,
  added,
  slug,
  href,
  onDismiss,
  renderPlan,
}: {
  campaign: CampaignSummary;
  added: AddLeadsResult;
  slug: string;
  href: (path: string) => string;
  onDismiss: () => void;
  renderPlan: (planId: string, onDismiss: () => void) => ReactNode;
}) {
  if (added.plan_id) return <div className="mt-1">{renderPlan(added.plan_id, onDismiss)}</div>;
  const left = added.duplicate + added.malformed + (added.foreign ?? 0);
  return (
    <NoticeBox
      tone={added.added > 0 ? "ok" : "warn"}
      role="status"
      action={
        <span className="flex flex-wrap gap-x-3">
          <Link href={href(`/c/${slug}/campaigns/${campaign.id}`)} className={TEXT_ACTION}>
            Open the campaign
          </Link>
          <button type="button" onClick={onDismiss} className={`${TEXT_ACTION} touch:min-h-11`}>
            Dismiss
          </button>
        </span>
      }
    >
      Added {formatCount(added.added)} to “{campaign.name}”
      {left > 0 ? `; ${formatCount(left)} left out (already on it, or a number it cannot call)` : ""}.
    </NoticeBox>
  );
}
