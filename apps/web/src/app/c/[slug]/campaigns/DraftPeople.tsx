"use client";

import { useState } from "react";
import { ListPlus } from "lucide-react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice, formatCount } from "@/components/ui";
import { useAddContacts, useAddLeads, useLeadPool, type LeadFilter } from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";

import { ContactEditor } from "./ContactEditor";
import { ContactResults } from "./ContactResults";
import { LeadPicker, leadPoolFits } from "./LeadPicker";
import { useCampaignForm } from "./campaignForm";

/**
 * WHO A DRAFT WILL CALL, and the way to add more: "Add people" beside the heading opens
 * the two ways in (a pasted, uploaded or typed list; people from your leads) above the
 * list, in place, and closes again with Done. Both go to the server, which dedupes, keeps
 * India numbers only, and refuses once the campaign has started.
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
  const [adding, setAdding] = useState(false);
  return (
    <Section
      title="Who will be called"
      action={
        <button
          type="button"
          className={TEXT_ACTION}
          aria-expanded={adding}
          title={refusal}
          disabled={!canWrite}
          onClick={() => setAdding((open) => !open)}
        >
          {adding ? "Done adding" : "Add people"}
        </button>
      }
    >
      <div className="space-y-6">
        {adding && <AddPeoplePanel campaignId={campaignId} canWrite={canWrite} refusal={refusal} />}
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
    </Section>
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
  const addLeads = useAddLeads(session, campaignId);
  // Inline: each refusal sits above the list it refused. The count sentence below says
  // what was added, so success needs no toast.
  const contactsFeedback = useActionFeedback(addContacts, { errorDisplay: "inline" });
  const leadsFeedback = useActionFeedback(addLeads, { errorDisplay: "inline" });
  const [filter, setFilter] = useState<LeadFilter>({ statuses: [], sources: [] });
  const pool = useLeadPool(session, filter, true);
  const { checked } = form;
  const result = addContacts.data ?? addLeads.data;
  return (
    <div className="settings-enter space-y-8 border-y border-line py-6">
      <div className="space-y-3">
        {addContacts.error && <ProblemNotice error={addContacts.error} />}
        <ContactEditor entries={form.contacts} onChange={form.setContacts} label="People to add" />
        <ActionButton
          variant="secondary"
          title={refusal}
          disabled={!canWrite || checked.ready.length === 0 || checked.refusal !== null}
          status={contactsFeedback.status}
          pendingLabel="Adding"
          successLabel="Added"
          onClick={() => addContacts.mutate(checked.ready, { onSuccess: () => form.setContacts([]) })}
        >
          <ListPlus aria-hidden className="h-4 w-4" />
          Add these people
        </ActionButton>
      </div>
      <div className="space-y-3 border-t border-line pt-6">
        <h3 className="text-body font-semibold text-ink">From your leads</h3>
        {addLeads.error && <ProblemNotice error={addLeads.error} />}
        <LeadPicker value={filter} onChange={setFilter} />
        <ActionButton
          variant="secondary"
          title={refusal}
          disabled={!canWrite || !leadPoolFits(pool.data?.matching, pool.data?.limit)}
          status={leadsFeedback.status}
          pendingLabel="Adding"
          successLabel="Added"
          onClick={() => leadsFeedback.run({ filter })}
        >
          {pool.data
            ? `Add ${formatCount(pool.data.matching)} ${pool.data.matching === 1 ? "lead" : "leads"}`
            : "Add leads"}
        </ActionButton>
      </div>
      {result && (
        <p role="status" className="text-meta text-ink-muted">
          Added {formatCount(result.added)}.
          {result.duplicate > 0 && ` ${formatCount(result.duplicate)} were already on the list.`}
          {result.malformed > 0 && ` ${formatCount(result.malformed)} numbers couldn't be read and were skipped.`}
          {(result.foreign ?? 0) > 0 && ` ${formatCount(result.foreign ?? 0)} numbers outside India were skipped.`}
        </p>
      )}
    </div>
  );
}
