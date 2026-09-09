"use client";

import { CheckCircle2, Plus } from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { Term } from "@/lib/glossary";
import { canDialOut } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import type {
  CampaignNumber,
  DltTemplate,
  useCreateCampaign,
} from "@/lib/api/campaigns";

import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON, CLASSIFICATIONS } from "./choices";
import { ConsentProvenanceFields } from "./ConsentProvenance";
import type { CampaignFormState } from "./campaignForm";

/** A read this form is BUILT from — its failure is a dead picker, not an empty one. */
interface ListQuery<T> {
  data: T[] | undefined;
  isLoading: boolean;
}

/**
 * BUILD A CALLING CAMPAIGN — the create form.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6). One subject: everything a client answers
 * before a campaign exists. Its state lives in `useCampaignForm` and is owned by the
 * screen, because one component has to declare the copilot surface; the validation is
 * this form's own.
 *
 * Nothing here was reworded in the move. The consent-provenance block is a compliance
 * artefact (SEC-COMP §3) and is required to submit, because a campaign created without it
 * is a campaign that cannot launch — and finding that out at the launch check, after the
 * list is uploaded, is a worse place to learn it.
 */
export function NewCampaignForm({
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
  refusal,
  onCreated,
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
  refusal: string | undefined;
  onCreated: (campaignId: string) => void;
}) {
  const {
    name, setName,
    classification, setClassification,
    concurrency, setConcurrency,
    numberId, setNumberId,
    templateId, setTemplateId,
    consentSource, setConsentSource,
    consentDate, setConsentDate,
    restrictHours, setRestrictHours,
    windowStart, setWindowStart,
    windowEnd, setWindowEnd,
    consentIso, provenanceAnswered,
  } = form;
  const setAgentId = form.setAgentId;
  const valid = useFormValidation();

  return (
        <Card title="New campaign">
          <form
            className="space-y-5"
            noValidate
            onSubmit={valid.onSubmit(() => {
              if (!selectedAgentId) return;
              create.mutate(
                {
                  agent_id: selectedAgentId,
                  name,
                  classification,
                  concurrency,
                  number_id: numberId || null,
                  dlt_template_id: templateId || null,
                  calling_hours: restrictHours
                    ? { start: windowStart, end: windowEnd }
                    : null,
                  consent_provenance:
                    consentSource && consentIso
                      ? { source: consentSource, collected_at: consentIso }
                      : null,
                },
                { onSuccess: (data) => onCreated(data.id) },
              );
            })}
          >
            {/* Outside the wrapping label, so the sentence describes the field instead
                of becoming part of its name. */}
            <div className="max-w-sm">
              <label className="block">
                <span className={FIELD_LABEL}>Name</span>
                <input
                  {...valid.field("name", "Give this campaign a name.")}
                  required
                  minLength={2}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Diwali service reminder"
                  className={FIELD}
                />
              </label>
              {valid.error("name")}
            </div>

            {/* Rendered whenever the server has ANSWERED with at least one assignable
                agent — never off a list that is empty because the read is in flight or
                failed, which is the same `Boolean(agents.data)` test `hasNoAgents` uses
                four lines up. */}
            {Boolean(agents.data) && agentOptions.length > 0 && (
              <label className="block max-w-sm">
                <span className={FIELD_LABEL}>
                  Which agent makes these calls
                </span>
                <select
                  value={selectedAgentId}
                  onChange={(e) => setAgentId(e.target.value)}
                  className={FIELD}
                >
                  {agentOptions.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {/* The state travels WITH the name. An agent that cannot dial yet
                          is a legal choice here and an `agent_not_live` blocker at
                          launch; saying so at the point of choosing turns a refusal
                          nobody expected into a wait somebody planned. */}
                      {agent.name}
                      {canDialOut(agent) ? "" : " — not able to call out yet"}
                    </option>
                  ))}
                </select>
                <span className={FIELD_HINT}>
                  Its script and voice are what your customers will hear.
                  {selectedAgent &&
                    !canDialOut(selectedAgent) &&
                    " This one cannot make calls yet — you can still build the campaign, but it will not launch until the agent is switched on and able to dial out."}
                </span>
              </label>
            )}

            <fieldset>
              <legend className={FIELD_LABEL}>
                What kind of calls are these?
              </legend>
              {/* Not a cosmetic choice: the category decides which number series may
                  dial (DATA-MODEL §6), so it is asked in plain language up front
                  rather than discovered as a launch blocker. */}
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                {CLASSIFICATIONS.map((option) => (
                  <label
                    key={option.value}
                    className={`${CHOICE_CARD} ${
                      classification === option.value ? CHOICE_ON : CHOICE_OFF
                    }`}
                  >
                    <input
                      type="radio"
                      name="classification"
                      className="sr-only"
                      checked={classification === option.value}
                      onChange={() => setClassification(option.value)}
                    />
                    {classification === option.value && (
                      <CheckCircle2
                        aria-hidden
                        className="absolute right-2 top-2 h-4 w-4 text-brand"
                      />
                    )}
                    <span className="block pr-6 text-sm font-semibold text-ink">
                      {option.label}
                    </span>
                    <span className="mt-0.5 block text-xs text-ink-faint">
                      {option.hint}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className={FIELD_LABEL}>Calling from</span>
                <select
                  value={numberId}
                  onChange={(e) => setNumberId(e.target.value)}
                  className={FIELD}
                >
                  <option value="">Choose a number…</option>
                  {(numbers.data ?? []).map((number) => (
                    <option key={number.id} value={number.id}>
                      {number.e164} ({number.series} series)
                    </option>
                  ))}
                </select>
                {/* "No numbers yet" is a claim about this account, so it is only made
                    from a list the server actually sent: `numbers.data?.length === 0` is
                    false while the answer is missing, which left an empty picker with no
                    explanation under a paused or failed read. */}
                {!numbers.data ? (
                  !numbers.isLoading && (
                    <span className={FIELD_HINT}>
                      Your numbers could not be read, so this picker is empty.
                      That is not &ldquo;you have none&rdquo;.
                    </span>
                  )
                ) : numbers.data.length === 0 ? (
                  <span className={FIELD_HINT}>
                    No numbers yet — your account manager sets these up.
                  </span>
                ) : null}
              </label>

              <label className="block">
                <span className={FIELD_LABEL}>
                  <Term id="dlt" /> template
                </span>
                <select
                  value={templateId}
                  onChange={(e) => setTemplateId(e.target.value)}
                  className={FIELD}
                >
                  <option value="">Choose a template…</option>
                  {(templates.data ?? []).map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.classification} —{" "}
                      {template.status === "approved"
                        ? "approved"
                        : template.status}
                    </option>
                  ))}
                </select>
                {/* Same rule as the number picker beside it: "none registered" is a
                    compliance claim about this client's DLT position, and only a list the
                    server sent is evidence for it. */}
                {!templates.data ? (
                  !templates.isLoading && (
                    <span className={FIELD_HINT}>
                      Your{" "}
                      <Term id="dlt" />{" "}
                      templates could not be read, so this picker is empty. That is not
                      &ldquo;you have none&rdquo;.
                    </span>
                  )
                ) : templates.data.length === 0 ? (
                  <span className={FIELD_HINT}>
                    None registered yet. Calls can&apos;t go out without one.
                  </span>
                ) : null}
              </label>
            </div>

            <div className="max-w-xs">
              <label className="block">
                <span className={FIELD_LABEL}>Calls at the same time</span>
                <input
                  {...valid.field("concurrency", "Enter how many calls may run at once.")}
                  type="number"
                  min={1}
                  max={10}
                  value={concurrency}
                  onChange={(e) => setConcurrency(Number(e.target.value))}
                  className={FIELD}
                />
                <span className={FIELD_HINT}>
                  Lower means the list takes longer. Lines are always kept free
                  for people calling you.
                </span>
              </label>
              {valid.error("concurrency")}
            </div>

            {/* The calling window NARROWS a bound that already exists; it does not set
                one. 9am-9pm is TRAI law applied to every dial (hard rule 5), so the
                caption says "never … before 9am or after 9pm" first and offers the
                narrowing second. Copy that read "choose your calling hours" would
                imply the client is picking the outer limit, and the first client who
                typed 08:00 would learn otherwise from a server rejection instead of
                from the form. */}
            <fieldset>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={restrictHours}
                  onChange={(e) => setRestrictHours(e.target.checked)}
                  className="h-4 w-4 rounded border-line accent-brand"
                />
                <span className="text-sm text-ink">
                  Only call during specific hours
                </span>
              </label>
              <p className="mt-1 text-xs text-ink-faint">
                Calls never go out before 9am or after 9pm — this narrows that
                further.
              </p>

              {restrictHours && (
                <div className="mt-2 grid max-w-xs gap-3 sm:grid-cols-2">
                  <div>
                    <label className="block">
                      <span className={FIELD_LABEL}>From</span>
                      <input
                        {...valid.field("windowStart", "Choose a start time.")}
                        type="time"
                        required
                        value={windowStart}
                        onChange={(e) => setWindowStart(e.target.value)}
                        className={FIELD}
                      />
                    </label>
                    {valid.error("windowStart")}
                  </div>
                  <div>
                    <label className="block">
                      <span className={FIELD_LABEL}>Until</span>
                      <input
                        {...valid.field("windowEnd", "Choose an end time.")}
                        type="time"
                        required
                        value={windowEnd}
                        onChange={(e) => setWindowEnd(e.target.value)}
                        className={FIELD}
                      />
                    </label>
                    {valid.error("windowEnd")}
                  </div>
                </div>
              )}
            </fieldset>

            {/* Consent provenance (SEC-COMP §3) — a compliance artefact, not a form
                field: the client is stating on the record where this list came from,
                and the statement is what a complaint would later be answered with.
                Required to submit, because a campaign created without it is a campaign
                that cannot launch, and finding that out at the launch check — after the
                list is uploaded — is a worse place to learn it. */}
            <ConsentProvenanceFields
              validation={valid}
              idPrefix="new"
              source={consentSource}
              collectedAt={consentDate}
              onSource={setConsentSource}
              onCollectedAt={setConsentDate}
            />

            {/* Kept next to the button that causes it: a window the server refuses
                (too wide, or start after end) comes back as a problem+json with copy
                that explains the law, and ProblemNotice already renders it. Repeating
                that rule as client-side validation would let the two drift. */}
            {create.error && <ProblemNotice error={create.error} />}

            <div className="space-y-2">
              <button
                type="submit"
                title={refusal}
                disabled={
                  !canWrite ||
                  create.isPending ||
                  !selectedAgentId ||
                  name.length < 2 ||
                  !provenanceAnswered
                }
                className={PRIMARY_BUTTON}
              >
                <Plus aria-hidden className="h-4 w-4" />
                {create.isPending ? "Creating…" : "Create campaign"}
              </button>
              {/* A dead button needs a reason next to it — including this one, which is
                  dead until the provenance question is answered. */}
              {!provenanceAnswered && (
                <p className="text-xs text-ink-faint">
                  Answer both questions about your list above — a campaign
                  without them can&apos;t be launched.
                </p>
              )}
              {hasNoAgents && (
                <p className="text-xs text-ink-faint">
                  No agent is set up yet — your account manager builds one
                  before campaigns can run.
                </p>
              )}
            </div>
          </form>
        </Card>
  );
}
