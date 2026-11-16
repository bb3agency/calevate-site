"use client";

import { ListPlus } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { StatusPill } from "@/components/console/statusPill";
import { ProblemNotice, formatCount } from "@/components/ui";
import { useAddContacts } from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";

import { ContactEditor } from "./ContactEditor";
import { FoldSection } from "./FoldSection";
import { ContactResults } from "./ContactResults";
import { useCampaignForm } from "./campaignForm";

const STOPPED = "It is stopped. People saved here are called when you start it again.";

/** The people section's element id, so "Add people" in the launch checklist can go to it. */
export function peopleSectionId(campaignId: string): string {
  return `people-${campaignId}`;
}

/**
 * WHO A DRAFT WILL CALL, in one section (founder, 16 Nov 2026): "Add people", always open,
 * with an Excel, CSV, pasted or typed list, and under it the people already added. Both go to
 * the server, which dedupes, keeps India numbers only, and refuses once the campaign started.
 */
export function DraftPeople({
  slug,
  campaignId,
  maxAttempts,
  canWrite,
  refusal,
  total,
  stopped = false,
}: {
  slug: string;
  campaignId: string;
  maxAttempts: number;
  canWrite: boolean;
  refusal: string | undefined;
  /** People already on the draft. People to call is left out while there are none. */
  total: number;
  /** Stopped: people are still saved, and the note says they are not called. */
  stopped?: boolean;
}) {
  return (
    <FoldSection title="Add people" tone="add" id={peopleSectionId(campaignId)}>
        {/* The same panel in every state (founder, 16 Nov 2026), saving people to a stopped
            campaign too; it never dials again, which the note says. */}
        {stopped && <p className="mb-3 text-meta text-ink-muted">{STOPPED}</p>}
        <AddPeoplePanel campaignId={campaignId} canWrite={canWrite} refusal={refusal} />
        {/* The people already added, under the ways to add more: one section, not two
            (founder, 16 Nov 2026: "I don't see the point of having both"). */}
        {total > 0 && (
          <div className="mt-8 border-t border-line pt-6">
            <ContactResults
              slug={slug}
              campaignId={campaignId}
              maxAttempts={maxAttempts}
              live={false}
              editable
              canWrite={canWrite}
              refusal={refusal}
            />
          </div>
        )}
      </FoldSection>
  );
}

function AddPeoplePanel({
  campaignId,
  canWrite,
  refusal,
}: {
  campaignId: string;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  const { session } = useClientRealm();
  const form = useCampaignForm();
  const addContacts = useAddContacts(session, campaignId);
  // Inline: a refusal sits above the list it refused. The count sentence below says what
  // was added, so success needs no toast.
  const contactsFeedback = useActionFeedback(addContacts, { errorDisplay: "inline" });
  const { checked } = form;
  const result = addContacts.data;
  return (
    <div className="space-y-8">
      <div className="space-y-3">
        {addContacts.error && <ProblemNotice error={addContacts.error} />}
        <ContactEditor entries={form.contacts} onChange={form.setContacts} label="People to add" />
        {/* Only once there is someone to add: an empty list has nothing to save. */}
        {checked.ready.length > 0 && (
        <ActionButton
          variant="primary"
          title={refusal}
          disabled={!canWrite || checked.refusal !== null}
          status={contactsFeedback.status}
          pendingLabel="Adding"
          successLabel="Added"
          onClick={() => addContacts.mutate(checked.ready, { onSuccess: () => form.setContacts([]) })}
        >
          <ListPlus aria-hidden className="h-4 w-4" />
          {checked.ready.length === 1 ? "Add 1 person to the campaign" : `Add ${formatCount(checked.ready.length)} people to the campaign`}
        </ActionButton>
        )}
      </div>
      {result && (
        <div role="status">
          <ul aria-label="What was added" className="flex flex-wrap gap-x-4 gap-y-1">
            <li>
              <StatusPill tone="ok">{`${formatCount(result.added)} added`}</StatusPill>
            </li>
            {result.duplicate > 0 && (
              <li>
                <StatusPill>{`${formatCount(result.duplicate)} already on the list`}</StatusPill>
              </li>
            )}
            {result.malformed > 0 && (
              <li>
                <StatusPill tone="warn">{`${formatCount(result.malformed)} unreadable, skipped`}</StatusPill>
              </li>
            )}
            {(result.foreign ?? 0) > 0 && (
              <li>
                <StatusPill tone="warn">{`${formatCount(result.foreign ?? 0)} outside India, skipped`}</StatusPill>
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
