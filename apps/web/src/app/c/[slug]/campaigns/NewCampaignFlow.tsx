"use client";

import { CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";

import { StepFlow } from "@/components/console/stepFlow";
import { useFormValidation } from "@/components/formValidation";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  ProblemNotice,
  formatCount,
  formatPhone,
} from "@/components/ui";
import { canDialOut } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber, DltTemplate, useCreateCampaign } from "@/lib/api/campaigns";
import { Term } from "@/lib/glossary";

import { ConsentProvenanceFields } from "./ConsentProvenance";
import type { CampaignFormState } from "./campaignForm";
import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON, CLASSIFICATIONS, CONSENT_SOURCES } from "./choices";

/** A read this flow is BUILT from: its failure is a dead picker, not an empty one. */
interface ListQuery<T> {
  data: T[] | undefined;
  isLoading: boolean;
}

/**
 * NEW CAMPAIGN, one question at a time: who to call, what they hear, when, then review.
 *
 * PRIMARY JOB: get a list of people into a draft campaign with its consent answer on record.
 *
 * The provenance question is asked in the FIRST step, beside the list it describes,
 * because the client is holding that list at this moment and it is the one moment they
 * can answer it cheaply. A draft created without it cannot launch, and learning that at the
 * launch check is a worse place to learn it. Its wording is a compliance artefact
 * (SEC-COMP §3) and is unchanged (`ConsentProvenance.tsx`).
 *
 * Submit is two calls: create the draft, then add the contacts (`CampaignsScreen` sequences
 * them through the same hooks the detail view uses). A failed contact upload lands on the
 * draft with the error and the list still in place to retry.
 */
export function NewCampaignFlow({
  form,
  agents,
  agentOptions,
  selectedAgentId,
  selectedAgent,
  hasNoAgents,
  numbers,
  templates,
  create,
  canWrite,
  onSubmit,
  onCancel,
}: {
  form: CampaignFormState;
  agents: { data: Agent[] | undefined };
  agentOptions: Agent[];
  selectedAgentId: string;
  selectedAgent: Agent | undefined;
  hasNoAgents: boolean;
  numbers: ListQuery<CampaignNumber>;
  templates: ListQuery<DltTemplate>;
  create: ReturnType<typeof useCreateCampaign>;
  canWrite: boolean;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const valid = useFormValidation();
  const { parsed } = form;
  const number = (numbers.data ?? []).find((option) => option.id === form.numberId);
  const template = (templates.data ?? []).find((option) => option.id === form.templateId);
  const source = CONSENT_SOURCES.find((option) => option.value === form.consentSource);
  const kind = CLASSIFICATIONS.find((option) => option.value === form.classification);

  return (
    <StepFlow
      label="New campaign"
      onCancel={onCancel}
      submitLabel="Create campaign"
      onSubmit={() => {
        if (canWrite) onSubmit();
      }}
      pending={create.isPending}
      error={create.error ? <ProblemNotice error={create.error} /> : undefined}
      steps={[
        {
          id: "who",
          title: "Who should we call?",
          hint: "Paste your list, then tell us where it came from.",
          validate: () =>
            form.name.trim().length < 2
              ? "Give this campaign a name."
              : parsed.length === 0
                ? "Paste at least one phone number."
                : !form.provenanceAnswered
                  ? "Answer both questions about your list — a campaign without them can't be launched."
                  : null,
          content: (
            <div className="space-y-5">
              <label className="block max-w-sm">
                <span className={FIELD_LABEL}>Name</span>
                <input
                  value={form.name}
                  onChange={(e) => form.setName(e.target.value)}
                  placeholder="e.g. Diwali service reminder"
                  className={FIELD}
                />
              </label>
              <label className="block">
                <span className={FIELD_LABEL}>Contact list</span>
                <textarea
                  rows={5}
                  value={form.csv}
                  onChange={(e) => form.setCsv(e.target.value)}
                  placeholder={"phone,name\n9876543210,Priya\n9876501234,Ravi"}
                  className={`${FIELD} font-mono text-xs`}
                />
                <span className={FIELD_HINT}>
                  {parsed.length > 0
                    ? `${formatCount(parsed.length)} rows ready. Numbers we can't read are counted and skipped — never guessed.`
                    : "Paste your CSV, or one number per line."}
                </span>
              </label>
              <ConsentProvenanceFields
                validation={valid}
                idPrefix="new"
                source={form.consentSource}
                collectedAt={form.consentDate}
                onSource={form.setConsentSource}
                onCollectedAt={form.setConsentDate}
              />
            </div>
          ),
        },
        {
          id: "what",
          title: "What will they hear?",
          validate: () =>
            selectedAgentId ? null : "Choose the agent that makes these calls.",
          content: (
            <div className="space-y-5">
              {hasNoAgents && (
                <p className="text-sm text-ink-muted">
                  No agent is set up yet — your account manager builds one before
                  campaigns can run.
                </p>
              )}
              {/* Only from a list the server sent: an empty picker over a read in flight
                  or failed would read as "you have no agent". */}
              {Boolean(agents.data) && agentOptions.length > 0 && (
                <label className="block max-w-sm">
                  <span className={FIELD_LABEL}>Which agent makes these calls</span>
                  <select
                    value={selectedAgentId}
                    onChange={(e) => form.setAgentId(e.target.value)}
                    className={FIELD}
                  >
                    {agentOptions.map((agent) => (
                      <option key={agent.id} value={agent.id}>
                        {agent.name}
                        {canDialOut(agent) ? "" : " — not able to call out yet"}
                      </option>
                    ))}
                  </select>
                  <span className={FIELD_HINT}>
                    {selectedAgent && !canDialOut(selectedAgent)
                      ? "You can build the campaign now, but it will not launch until the agent is switched on and able to dial out."
                      : "Its script and voice are what your customers will hear."}
                  </span>
                </label>
              )}

              <fieldset>
                <legend className={FIELD_LABEL}>What kind of calls are these?</legend>
                {/* The category decides which number series may dial (DATA-MODEL §6). */}
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  {CLASSIFICATIONS.map((option) => (
                    <label
                      key={option.value}
                      className={`${CHOICE_CARD} ${
                        form.classification === option.value ? CHOICE_ON : CHOICE_OFF
                      }`}
                    >
                      <input
                        type="radio"
                        name="classification"
                        className="sr-only"
                        checked={form.classification === option.value}
                        onChange={() => form.setClassification(option.value)}
                      />
                      {form.classification === option.value && (
                        <CheckCircle2
                          aria-hidden
                          className="absolute right-2 top-2 h-4 w-4 text-brand-strong"
                        />
                      )}
                      <span className="block pr-6 text-sm font-semibold text-ink">
                        {option.label}
                      </span>
                      <span className="mt-0.5 block text-xs text-ink-faint">{option.hint}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block min-w-0">
                  <span className={FIELD_LABEL}>Calling from</span>
                  <select
                    value={form.numberId}
                    onChange={(e) => form.setNumberId(e.target.value)}
                    className={FIELD}
                  >
                    <option value="">Choose a number…</option>
                    {(numbers.data ?? []).map((option) => (
                      <option key={option.id} value={option.id}>
                        {formatPhone(option.e164)} ({option.series} series)
                      </option>
                    ))}
                  </select>
                  {/* "None" only from a list the server sent; a failed read is refused at
                      the top of the screen. */}
                  {numbers.data?.length === 0 && (
                    <span className={FIELD_HINT}>
                      No numbers yet — your account manager sets these up.
                    </span>
                  )}
                </label>
                <label className="block min-w-0">
                  <span className={FIELD_LABEL}>
                    <Term id="dlt" /> template
                  </span>
                  <select
                    value={form.templateId}
                    onChange={(e) => form.setTemplateId(e.target.value)}
                    className={FIELD}
                  >
                    <option value="">Choose a template…</option>
                    {(templates.data ?? []).map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.classification} — {option.status}
                      </option>
                    ))}
                  </select>
                  {templates.data?.length === 0 && (
                    <span className={FIELD_HINT}>
                      None registered yet. Calls can&apos;t go out without one.
                    </span>
                  )}
                </label>
              </div>
            </div>
          ),
        },
        {
          id: "when",
          title: "When should we call?",
          validate: () =>
            form.concurrency < 1 || form.concurrency > 10
              ? "Choose between 1 and 10 calls at the same time."
              : form.restrictHours && (!form.windowStart || !form.windowEnd)
                ? "Choose both a start and an end time."
                : null,
          content: (
            <div className="space-y-5">
              {/* The window NARROWS the 9am–9pm bound every dial already has; it never
                  sets one. Saying the bound first is what stops a client typing 08:00. */}
              <fieldset>
                <label className="flex items-center gap-2 touch:min-h-11">
                  <input
                    type="checkbox"
                    checked={form.restrictHours}
                    onChange={(e) => form.setRestrictHours(e.target.checked)}
                    className="h-4 w-4 rounded border-line accent-brand"
                  />
                  <span className="text-sm text-ink">Only call during specific hours</span>
                </label>
                <p className="mt-1 text-xs text-ink-faint">
                  Calls never go out before 9am or after 9pm — this narrows that further.
                </p>
                {form.restrictHours && (
                  <div className="settings-enter mt-3 grid max-w-xs grid-cols-2 gap-3">
                    <label className="block">
                      <span className={FIELD_LABEL}>From</span>
                      <input
                        type="time"
                        value={form.windowStart}
                        onChange={(e) => form.setWindowStart(e.target.value)}
                        className={FIELD}
                      />
                    </label>
                    <label className="block">
                      <span className={FIELD_LABEL}>Until</span>
                      <input
                        type="time"
                        value={form.windowEnd}
                        onChange={(e) => form.setWindowEnd(e.target.value)}
                        className={FIELD}
                      />
                    </label>
                  </div>
                )}
              </fieldset>
              <label className="block max-w-xs">
                <span className={FIELD_LABEL}>Calls at the same time</span>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={form.concurrency}
                  onChange={(e) => form.setConcurrency(Number(e.target.value))}
                  className={FIELD}
                />
                <span className={FIELD_HINT}>
                  Lower is slower. Lines are always kept free for people calling you.
                </span>
              </label>
            </div>
          ),
        },
      ]}
      review={{
        title: "Check and create",
        content: (
          <dl className="divide-y divide-line text-sm">
            <ReviewRow label="Name">{form.name}</ReviewRow>
            <ReviewRow label="Contacts">{formatCount(parsed.length)} rows</ReviewRow>
            <ReviewRow label="Where the list came from">
              {source?.label ?? "Not answered"}
              {form.consentDate ? ` · agreed ${form.consentDate}` : ""}
            </ReviewRow>
            <ReviewRow label="Agent">{selectedAgent?.name ?? "None chosen"}</ReviewRow>
            <ReviewRow label="Kind of call">{kind?.label}</ReviewRow>
            <ReviewRow label="Calling from">
              {number ? formatPhone(number.e164) : "No number chosen"}
            </ReviewRow>
            <ReviewRow label="Template">
              {template
                ? `${template.classification} — ${template.status}`
                : "No template chosen"}
            </ReviewRow>
            <ReviewRow label="Hours">
              {form.restrictHours
                ? `${form.windowStart}–${form.windowEnd} IST`
                : "9am–9pm IST"}
            </ReviewRow>
            <ReviewRow label="Calls at once">{form.concurrency}</ReviewRow>
          </dl>
        ),
      }}
    />
  );
}

function ReviewRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-4 gap-y-0.5 py-2">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="min-w-0 font-medium text-ink">{children}</dd>
    </div>
  );
}
