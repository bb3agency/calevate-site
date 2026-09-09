"use client";

import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { canDialOut } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber, DltTemplate } from "@/lib/api/campaigns";

import { CLASSIFICATIONS, CONSENT_SOURCES } from "./choices";
import type { CampaignFormState, ScheduleFormState } from "./campaignForm";

/**
 * WHAT THE SCREEN ASSISTANT IS TOLD ABOUT THIS SCREEN.
 *
 * Extracted from `CampaignsScreen.tsx` (UX-DOCTRINE §6). One subject, and it is a
 * REDACTION boundary as much as a declaration: the contact list leaves as a single
 * «PRIVATE_1» placeholder and the number picker's labels carry no E.164 (hard rule 6 /
 * D-127 G-2). Keeping it in one file is what makes that boundary reviewable.
 *
 * A screen gets exactly ONE surface (`lib/copilot/registry.ts` makes the innermost
 * registration the live one), so this hook is called once, by the screen.
 */
export function useCampaignsCopilotSurface({
  form,
  scheduleForm,
  agentOptions,
  selectedAgentId,
  numbers,
  templates,
}: {
  form: CampaignFormState;
  scheduleForm: ScheduleFormState;
  agentOptions: Agent[];
  selectedAgentId: string;
  numbers: { data: CampaignNumber[] | undefined };
  templates: { data: DltTemplate[] | undefined };
}): void {
  const {
    name, classification, numberId, templateId, concurrency, csv,
    consentSource, consentDate, restrictHours, windowStart, windowEnd, parsed,
  } = form;
  const { startDate, startTime, repeatTime, repeatEnds } = scheduleForm;

  /*
   * THE CAMPAIGN BUILD FORM, DECLARED TO THE SCREEN ASSISTANT.
   *
   * Loose `useState` scalars, so `apply` is a run of typed setter calls — no DOM. Three
   * of this screen's controls are choice-cards over `sr-only` radios (classification,
   * consent source) or a `ToggleSwitch`-shaped checkbox (calling window), which is
   * exactly the family `lib/copilot/dom.ts` warns cannot be driven by writing `.value`;
   * none of them is driven that way here, because the state is right in this component.
   *
   * ## THE CONTACT LIST IS READ-ONLY AND REDACTED, AND BOTH HALVES ARE DELIBERATE
   *
   * The CSV is a list of named people's phone numbers — the densest personal data in this
   * console — so it leaves as a single «PRIVATE_1» placeholder (hard rule 6 / D-127 G-2)
   * and the assistant is told how many rows parsed rather than what is in them. It is
   * `writable: false` because a machine-authored call list is a set of strangers nobody
   * chose to ring, and the compliance gate downstream checks CONSENT for numbers a human
   * supplied, not the provenance of the text box.
   *
   * The consent SOURCE is fillable and its date is fillable, because they are a statement
   * the client is making and the form's job is to capture it — but note what is being
   * captured: `consentSource` opens EMPTY on purpose ("there is no sensible default for
   * where five thousand numbers came from"), and nothing here changes that. The
   * assistant can transcribe an answer a person gave; it has no way to invent one,
   * because it cannot see the list.
   *
   * `repeatDays` is absent: it is a set of weekday toggles rather than a value, and a
   * half-registered control is worse than an unregistered one.
   */
  useCopilotSurface({
    route: "/c/{slug}/campaigns",
    title: "Build a calling campaign",
    realm: "client",
    fields: [
      {
        id: "campaign-name",
        label: "Campaign name",
        type: "text",
        value: name,
        help: "Only the client sees it. e.g. Diwali service reminder.",
      },
      {
        id: "campaign-agent",
        label: "Which agent makes these calls",
        type: "select",
        value: selectedAgentId,
        options: agentOptions.map((agent) => ({
          value: agent.id,
          label: `${agent.name}${canDialOut(agent) ? "" : " — not able to call out yet"}`,
        })),
      },
      {
        id: "campaign-classification",
        label: "What kind of calls are these?",
        type: "select",
        value: classification,
        options: CLASSIFICATIONS.map((option) => ({
          value: option.value,
          label: option.label,
        })),
        help: "Decides which number series may dial (DATA-MODEL §6). Promotional needs a 140-series number.",
      },
      {
        id: "campaign-number",
        label: "Calling from",
        type: "select",
        value: numberId,
        options: (numbers.data ?? []).map((number) => ({
          value: number.id,
          // NO E.164 HERE, and the on-screen <option> at line ~1359 deliberately still
          // shows one. This list is the COPILOT's copy of the screen, and it goes to a US
          // model provider — D-127 G-2 says the console never volunteers a personal value
          // on the user's behalf, and a phone number is the first thing that rule names.
          // `copilot/routes.py` now refuses the whole request when anything in the
          // rendered screen still looks personal, so this label was breaking the
          // assistant on this screen as well as leaking; the last two digits are the same
          // discriminator `workers/redaction.py` keeps for staff, and the series is what
          // the person actually asks by ("use the 140 number").
          label: `…${number.e164.slice(-2)} (${number.series} series)`,
        })),
      },
      {
        id: "campaign-template",
        label: "DLT template",
        type: "select",
        value: templateId,
        options: (templates.data ?? []).map((template) => ({
          value: template.id,
          label: `${template.classification} — ${template.status}`,
        })),
      },
      {
        id: "campaign-concurrency",
        label: "Calls at once",
        type: "number",
        value: String(concurrency),
      },
      {
        id: "campaign-csv",
        label: "Contact list (CSV)",
        type: "textarea",
        value: csv,
        writable: false,
        personal: "text",
        help: `A human-supplied list. ${parsed.length} row(s) parsed so far.`,
      },
      {
        id: "campaign-consent-source",
        label: "Where these numbers came from",
        type: "select",
        value: consentSource,
        options: CONSENT_SOURCES.map((option) => ({
          value: option.value,
          label: `${option.label} — ${option.hint}`,
        })),
      },
      {
        id: "campaign-consent-date",
        label: "When consent was collected",
        type: "date",
        value: consentDate,
        help: "YYYY-MM-DD. Cannot be in the future.",
      },
      {
        id: "campaign-restrict-hours",
        label: "Narrow the calling window for this campaign",
        type: "bool",
        value: restrictHours ? "true" : "false",
        help: 'Off means the platform window applies. "true" or "false".',
      },
      { id: "campaign-window-start", label: "Window opens", type: "text", value: windowStart },
      { id: "campaign-window-end", label: "Window closes", type: "text", value: windowEnd },
      { id: "campaign-start-date", label: "Scheduled start date", type: "date", value: startDate },
      { id: "campaign-start-time", label: "Scheduled start time", type: "text", value: startTime },
      { id: "campaign-repeat-time", label: "Repeat at", type: "text", value: repeatTime },
      { id: "campaign-repeat-ends", label: "Repeat until", type: "date", value: repeatEnds },
    ],
    facts: [
      { key: "contacts_parsed", label: "Contacts parsed from the list", value: String(parsed.length) },
    ],
    apply: (items) => {
      for (const item of items) {
        // ONE COERCION AT THE TOP of the switch rather than eighteen at the call sites.
        // Every control on this screen holds text — the two that do not (`concurrency`
        // parses an int, `restrictHours` a boolean) narrow from it below, and the boolean
        // accepts the real `true` the server sends for a `bool` field as well as the
        // string a model might answer a text field with.
        const text = asText(item.value);
        switch (item.field_id) {
          case "campaign-name":
            form.setName(text);
            break;
          case "campaign-agent":
            if (agentOptions.some((agent) => agent.id === text)) form.setAgentId(text);
            break;
          case "campaign-classification": {
            const option = CLASSIFICATIONS.find((row) => row.value === text);
            if (option) form.setClassification(option.value);
            break;
          }
          case "campaign-number":
            if ((numbers.data ?? []).some((number) => number.id === text)) {
              form.setNumberId(text);
            }
            break;
          case "campaign-template":
            if ((templates.data ?? []).some((template) => template.id === text)) {
              form.setTemplateId(text);
            }
            break;
          case "campaign-concurrency": {
            // A dialling rate is a real number in this component's state, and
            // `Number("")` is 0 — a campaign that places no calls. Only a positive
            // integer is accepted; anything else leaves the control alone.
            const parsedConcurrency =
              typeof item.value === "number" ? item.value : Number.parseInt(text, 10);
            if (Number.isFinite(parsedConcurrency) && parsedConcurrency > 0) {
              form.setConcurrency(parsedConcurrency);
            }
            break;
          }
          case "campaign-consent-source": {
            const option = CONSENT_SOURCES.find((row) => row.value === text);
            if (option) form.setConsentSource(option.value);
            break;
          }
          case "campaign-consent-date":
            form.setConsentDate(text);
            break;
          case "campaign-restrict-hours":
            form.setRestrictHours(item.value === true || text === "true");
            break;
          case "campaign-window-start":
            form.setWindowStart(text);
            break;
          case "campaign-window-end":
            form.setWindowEnd(text);
            break;
          case "campaign-start-date":
            scheduleForm.setStartDate(text);
            break;
          case "campaign-start-time":
            scheduleForm.setStartTime(text);
            break;
          case "campaign-repeat-time":
            scheduleForm.setRepeatTime(text);
            break;
          case "campaign-repeat-ends":
            scheduleForm.setRepeatEnds(text);
            break;
          default:
            break;
        }
      }
    },
  });
}
