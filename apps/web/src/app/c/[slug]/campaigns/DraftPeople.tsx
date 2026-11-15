"use client";

import { useState } from "react";
import { ListPlus } from "lucide-react";

import { Section } from "@/components/console/section";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { StatusPill } from "@/components/console/statusPill";
import { ProblemNotice, formatCount } from "@/components/ui";
import { PlanCard } from "@/components/copilot/PlanCard";
import { useAddContacts, useAddLeadsToCampaign } from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";

import { ContactEditor } from "./ContactEditor";
import { ContactResults } from "./ContactResults";
import { LeadPicker, usePickedLeads } from "./LeadPicker";
import { useCampaignForm } from "./campaignForm";

/** The people section's element id, so "Add people" in the launch checklist can go to it. */
export function peopleSectionId(campaignId: string): string {
  return `people-${campaignId}`;
}

/**
 * WHO A DRAFT WILL CALL, as two sections (founder, 15 Nov 2026): "Add people", always open,
 * with the two ways in (an Excel, CSV, pasted or typed list; people from your leads), then
 * "People to call", the list itself. Both go to the server, which dedupes, keeps India
 * numbers only, and refuses once the campaign has started.
 */
export function DraftPeople({
  slug,
  campaignId,
  maxAttempts,
  canWrite,
  refusal,
}: {
  slug: string;
  campaignId: string;
  maxAttempts: number;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  return (
    <>
      <Section title="Add people">
        <div id={peopleSectionId(campaignId)} className="scroll-mt-24">
          <AddPeoplePanel campaignId={campaignId} canWrite={canWrite} refusal={refusal} />
        </div>
      </Section>
      <Section title="People to call">
        <ContactResults
          slug={slug}
          campaignId={campaignId}
          maxAttempts={maxAttempts}
          live={false}
          editable
          canWrite={canWrite}
          refusal={refusal}
        />
      </Section>
    </>
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
  const addLeads = useAddLeadsToCampaign(session);
  // Inline: each refusal sits above the list it refused. The count sentence below says
  // what was added, so success needs no toast.
  const contactsFeedback = useActionFeedback(addContacts, { errorDisplay: "inline" });
  const leadsFeedback = useActionFeedback(addLeads, { errorDisplay: "inline" });
  const { matching } = usePickedLeads(session, form.leads);
  const [planDismissed, setPlanDismissed] = useState(false);
  const { checked } = form;
  // A set added as a plan reports on its own card, not as "Added 0".
  const result = addContacts.data ?? (addLeads.data?.plan_id ? undefined : addLeads.data);
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
      <div className="space-y-3 border-t border-line pt-6">
        <h3 className="text-body font-semibold text-ink">From your leads</h3>
        {addLeads.error && <ProblemNotice error={addLeads.error} />}
        <LeadPicker f={form.leads} />
        <ActionButton
          variant="secondary"
          title={refusal}
          disabled={!canWrite || !matching}
          status={leadsFeedback.status}
          pendingLabel="Adding"
          successLabel="Added"
          onClick={() => {
            if (!matching) return;
            setPlanDismissed(false);
            leadsFeedback.run({ campaignId, lens: form.leads.lens, expectedCount: matching });
          }}
        >
          {matching !== undefined ? `Add ${formatCount(matching)} ${matching === 1 ? "lead" : "leads"}` : "Add leads"}
        </ActionButton>
        {addLeads.data?.plan_id && !planDismissed && (
          <PlanCard session={session} planId={addLeads.data.plan_id} onDismiss={() => setPlanDismissed(true)} />
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
