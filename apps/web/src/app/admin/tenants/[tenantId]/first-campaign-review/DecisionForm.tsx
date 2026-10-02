"use client";

import { useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { Card, FIELD, FIELD_HINT, FIELD_LABEL, PRIMARY_BUTTON, RestrictionNote } from "@/components/ui";
import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { InfoTip } from "@/components/console/infoTip";
import type { useAdminAccess } from "@/app/admin/access";
import { useTenantCampaigns, type useFirstCampaignDecision } from "@/lib/api/admin";
import {
  DECISION_COPY,
  DECISION_NOTE_MAX,
  decisionBlockReason,
  type FirstCampaignDecision,
  type FirstCampaignDecisionIn,
} from "@/lib/api/firstCampaign";

const DECISIONS = Object.keys(DECISION_COPY) as FirstCampaignDecision[];

/**
 * The decision itself.
 *
 * Starts EMPTY, the opposite of the KYC form and deliberately: this records a fresh
 * judgement and `decision_note` is assigned outright, so prefilling the last reviewer's
 * words invites re-recording somebody else's sentence under your own name. There is no
 * default decision either — a preselected "release" is a release one stray Enter away.
 *
 * Every rule here is enforced again by the route (problem+json naming the field) and again
 * by `decision_says_what_was_reviewed` underneath it. The form previews the refusal.
 */
export function DecisionForm({
  decide,
  tenantName,
  slug,
  write,
}: {
  decide: ReturnType<typeof useFirstCampaignDecision>;
  tenantName: string;
  slug: string;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [decision, setDecision] = useState<FirstCampaignDecision | null>(null);
  const [note, setNote] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const campaigns = useTenantCampaigns(slug);

  const draft: FirstCampaignDecisionIn | null =
    decision === null
      ? null
      : { decision, note, reviewed_campaign_id: campaignId === "" ? null : campaignId };
  const blocked = draft === null ? "Choose what you are recording." : decisionBlockReason(draft);
  const copy = decision === null ? null : DECISION_COPY[decision];

  return (
    <Card
      title="Record a decision"
      info={
        <p>
          This keeps one decision per account — a release can be withdrawn when complaints
          arrive and granted again afterwards. Each decision writes its own audit entry, so
          the history is the audit log rather than this row.
        </p>
      }
    >
      <form
        className="space-y-5"
        // Our refusals are written beside each control; `noValidate` keeps a rule added
        // later from being answered in the browser's language.
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (draft !== null) decide.mutate(draft);
        }}
      >
        {/* The WRITE is admin-realm, so the question is the role's `admin:tenants`, not
            whether this is a view-as session. */}
        <RestrictionNote reason={write.reason} />

        <fieldset>
          <legend className={FIELD_LABEL}>Decision</legend>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {DECISIONS.map((value) => {
              const on = decision === value;
              return (
                <label
                  key={value}
                  className={`${CHOICE_CARD} ${on ? CHOICE_ON : CHOICE_OFF} ${
                    write.allowed ? "" : "cursor-not-allowed opacity-60"
                  }`}
                >
                  <input
                    type="radio"
                    name="decision"
                    value={value}
                    className="sr-only"
                    checked={on}
                    disabled={!write.allowed}
                    onChange={() => {
                      setDecision(value);
                      decide.reset();
                    }}
                  />
                  {on && (
                    <CheckCircle2
                      aria-hidden
                      className="absolute right-3 top-3 h-4 w-4 text-brand-strong"
                    />
                  )}
                  <span className="block pr-6 text-sm font-medium text-ink">
                    {DECISION_COPY[value].label}
                  </span>
                  <span className="mt-1 block text-xs text-ink-muted">
                    {DECISION_COPY[value].effect}
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        {/* The note's job changes with the decision — audit evidence versus a message the
            client reads — so its label and hint change with it. */}
        <div>
          <label htmlFor="fcr-note" className={FIELD_LABEL}>
            {copy?.noteLabel ?? "Note"}
          </label>
          <textarea
            id="fcr-note"
            rows={4}
            maxLength={DECISION_NOTE_MAX}
            value={note}
            disabled={!write.allowed}
            onChange={(e) => {
              setNote(e.target.value);
              decide.reset();
            }}
            placeholder={
              decision === "rejected"
                ? "What was wrong, and what to change."
                : "What you read: the list and its source, the script, the disclosure line."
            }
            className={FIELD}
          />
          <span className={FIELD_HINT}>
            {copy?.noteHint ??
              "What was reviewed, or what was wrong with it. Choose a decision above and this says which."}
          </span>
          <span className={FIELD_HINT}>
            {note.trim().length}/{DECISION_NOTE_MAX} characters. This is a note about a
            campaign — no phone numbers, no transcript text.
          </span>
        </div>

        <div className="max-w-md">
          <label htmlFor="fcr-campaign" className={FIELD_LABEL}>
            Campaign read (optional)
          </label>
          <select
            id="fcr-campaign"
            value={campaignId}
            disabled={!write.allowed}
            onChange={(e) => {
              setCampaignId(e.target.value);
              decide.reset();
            }}
            className={FIELD}
          >
            <option value="">— not recorded —</option>
            {(campaigns.data ?? []).map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name} · {campaign.status} · {campaign.contacts} contacts
              </option>
            ))}
          </select>
          <span className={FIELD_HINT}>
            Evidence of what you read; the hold is on the account.{" "}
            <InfoTip label="the campaign read">
              <p>
                Evidence, not mechanism: deleting this campaign later cannot change whether
                the account is released.
              </p>
              <p>
                Leaving it blank keeps whatever was recorded before — a reversal that names no
                campaign does not erase what the first reviewer read.
              </p>
            </InfoTip>
          </span>
          {/* Error (or a PAUSED offline read, which carries no error) first: "this account
              has no campaigns yet" said about a read that never landed would invite a
              release on a premise nobody checked. */}
          {campaigns.error != null || !campaigns.data ? (
            <p className="mt-1 text-xs text-ink-muted">
              Their campaigns could not be listed, so this field is empty. It is optional —
              the decision can still be recorded without naming one.
            </p>
          ) : campaigns.data.length === 0 ? (
            <p className="mt-1 text-xs text-warn">
              This account has no campaigns yet. Releasing it now clears the rule before
              anything exists to read — which is a decision, not an accident, so record why
              in the note.
            </p>
          ) : null}
        </div>

        <WillRecord draft={draft} tenantName={tenantName} />

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={decide.isPending || blocked !== null || !write.allowed}
            className={`${PRIMARY_BUTTON} max-sm:w-full max-sm:justify-center`}
          >
            {decide.isPending ? "Recording…" : "Record decision"}
          </button>
          {blocked && <span className="text-xs text-warn">{blocked}</span>}
        </div>
      </form>
    </Card>
  );
}

/**
 * What this write will put in the record, said before it is made — including the two
 * facts the operator cannot supply (who, from the session; when, from the database), which
 * is why there is no "decided on" date picker here.
 */
function WillRecord({
  draft,
  tenantName,
}: {
  draft: FirstCampaignDecisionIn | null;
  tenantName: string;
}) {
  const note = draft?.note.trim() ?? "";
  return (
    <div className="rounded-card border border-line bg-app p-3 text-xs text-ink-muted">
      <p className="font-medium text-ink">This will record, against {tenantName}:</p>
      <ul className="mt-1.5 space-y-1">
        <li>
          <span className="text-ink-faint">Outcome</span> —{" "}
          {draft === null
            ? "nothing yet; choose a decision above."
            : draft.decision === "approved"
              ? "approved. Campaign calling opens and this rule never holds another of their campaigns."
              : "rejected. Every campaign stays blocked, and the client is shown the note."}
        </li>
        <li>
          <span className="text-ink-faint">Note</span> —{" "}
          {note === "" ? (
            "empty; the database refuses a decision that does not say what was reviewed."
          ) : (
            <span className="text-ink">
              “{note}”
              {draft?.decision === "rejected" && " — shown to the client word for word."}
            </span>
          )}
        </li>
        <li>
          <span className="text-ink-faint">Campaign read</span> —{" "}
          {draft?.reviewed_campaign_id
            ? "the one selected above, checked against this tenant before it is stored."
            : "none named; whatever was recorded before is kept."}
        </li>
        <li>
          <span className="text-ink-faint">Decided by</span> — the admin account sending this
          request. Taken from your session, not from this form. The time is stamped by the
          database, and the decision and note go into one new audit-log entry.
        </li>
      </ul>
    </div>
  );
}
