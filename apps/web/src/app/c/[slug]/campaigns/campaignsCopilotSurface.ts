"use client";

import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { canDialOut } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import { istDateStamp } from "@/components/ui";
import { RETRY_GAP_CHOICES, type CampaignNumber, type DltTemplate } from "@/lib/api/campaigns";

import { STATUSES } from "../leads/StatusSelect";

import { CLASSIFICATIONS, CONSENT_SOURCES, WEEKDAYS } from "./choices";
import type { CampaignFormState, ScheduleFormState, StartMode } from "./campaignForm";

const START_MODE_VALUES: StartMode[] = ["review", "later", "weekly"];
const START_MODE_WORDS: Record<StartMode, string> = {
  review: "The client launches it from its checklist",
  later: "Once, at a set date and time",
  weekly: "Every week, on chosen days",
};

/**
 * WHAT THE SCREEN ASSISTANT IS TOLD ABOUT THIS SCREEN.
 *
 * The create page's surface (UX-DOCTRINE §6). One subject, and it is a
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
    name, classification, numberId, templateId, concurrency,
    consentSource, consentDate, restrictHours, windowStart, windowEnd, checked,
  } = form;
  const { startDate, startTime, repeatTime, repeatEnds, startMode, repeatDays } = scheduleForm;

  /*
   * THE CAMPAIGN BUILD FORM, DECLARED TO THE SCREEN ASSISTANT.
   *
   * Loose `useState` scalars, so `apply` is a run of typed setter calls — no DOM. Three
   * of this screen's controls are choice-cards over `sr-only` radios (classification,
   * consent source) or a `ToggleSwitch`-shaped checkbox (calling window), which is
   * exactly the family `lib/copilot/dom.ts` warns cannot be driven by writing `.value`;
   * none of them is driven that way here, because the state is right in this component.
   *
   * ## THE CONTACT LIST IS NOT DECLARED AT ALL, ONLY ITS COUNTS
   *
   * The list is named people's phone numbers — the densest personal data in this console
   * (hard rule 6 / D-127 G-2) — so the assistant is told how many rows are ready, left out
   * and duplicated, and never what is in them. It is not fillable because a machine-authored call list is a set of strangers nobody
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
   * The repeat days are declared as a comma list of ISO weekday numbers, the vocabulary the
   * server stores, and the start mode as a select, so a sentence like "every Tuesday at 11"
   * can be filled. Calls at once are accepted only from 1 to 10, the server's bound.
   */
  useCopilotSurface({
    route: "/c/{slug}/campaigns/new",
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
        help: "promotional = offers and marketing; service = reminders and updates to the client's own customers.",
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
      {
        id: "campaign-start-mode",
        label: "How it starts",
        type: "select",
        value: startMode,
        options: START_MODE_VALUES.map((value) => ({ value, label: START_MODE_WORDS[value] })),
        help: "review = the client launches it after checking; later = once at the start date and time; weekly = on the repeat days.",
      },
      {
        id: "campaign-repeat-days",
        label: "Repeat on which days",
        type: "text",
        value: repeatDays.join(","),
        help: "ISO weekday numbers, 1 = Monday, comma-separated. e.g. 2,4 for Tuesday and Thursday.",
      },
      {
        id: "campaign-retry-attempts",
        label: "Tries per person",
        type: "number",
        value: String(form.retry.max_attempts),
        help: "1 to 5.",
      },
      {
        id: "campaign-retry-gaps",
        label: "Minutes to wait before each retry",
        type: "text",
        value: (form.retry.gaps_minutes ?? []).join(","),
        help: `One per retry, each one of ${RETRY_GAP_CHOICES.join(", ")}.`,
      },
      {
        id: "campaign-leads-stage",
        label: "Also call leads at this stage",
        type: "text",
        value: form.fromLeads ? (form.leads.status ?? "any") : "",
        help: `One of ${STATUSES.join(", ")}, or "any" for every stage. Empty means no leads are added.`,
      },
      {
        id: "campaign-leads-since",
        label: "Only leads that came in on or after",
        type: "date",
        value: form.fromLeads ? (form.leads.created?.start ?? "") : "",
        help: "YYYY-MM-DD, India time. Needs a stage above.",
      },
    ],
    facts: [
      { key: "contacts_ready", label: "Contacts ready to call", value: String(checked.counts.ready) },
      { key: "contacts_invalid", label: "Rows that can't be called", value: String(checked.counts.invalid) },
      { key: "contacts_duplicate", label: "Duplicate rows", value: String(checked.counts.duplicate) },
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
            if (Number.isFinite(parsedConcurrency) && parsedConcurrency >= 1 && parsedConcurrency <= 10) {
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
          case "campaign-start-mode":
            if (START_MODE_VALUES.includes(text as StartMode)) scheduleForm.setStartMode(text as StartMode);
            break;
          case "campaign-repeat-days": {
            // "2,4" or "Tue, Thu": ISO weekday numbers (1 = Monday) or the short names.
            const days = text
              .split(/[\s,]+/)
              .map((part) => WEEKDAYS.find((d) => String(d.value) === part || d.short.toLowerCase() === part.toLowerCase().slice(0, 3))?.value)
              .filter((day): day is number => day !== undefined);
            scheduleForm.setRepeatDays([...new Set(days)].sort());
            break;
          }
          case "campaign-retry-attempts": {
            const attempts = Number.parseInt(text, 10);
            if (attempts >= 1 && attempts <= 5) {
              const gaps = (form.retry.gaps_minutes ?? []).slice(0, attempts - 1);
              while (gaps.length < attempts - 1) gaps.push(gaps[gaps.length - 1] ?? 30);
              form.setRetry({ max_attempts: attempts, gaps_minutes: gaps });
            }
            break;
          }
          case "campaign-retry-gaps": {
            const gaps = text.split(/[\s,]+/).map((part) => Number.parseInt(part, 10));
            const wanted = form.retry.max_attempts - 1;
            if (gaps.length === wanted && gaps.every((gap) => (RETRY_GAP_CHOICES as readonly number[]).includes(gap))) {
              form.setRetry({ ...form.retry, gaps_minutes: gaps });
            }
            break;
          }
          case "campaign-leads-stage": {
            const stage = text.trim().toLowerCase();
            if (stage === "") form.setFromLeads(false);
            else if (stage === "any" || (STATUSES as string[]).includes(stage)) {
              form.setFromLeads(true);
              form.leads.setStatus(stage === "any" ? undefined : stage);
            }
            break;
          }
          case "campaign-leads-since":
            // Not gated on `fromLeads`: the stage in the same batch has not re-rendered yet,
            // and a date with leads off is simply never sent.
            if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
              form.leads.setCreated({ start: text, end: istDateStamp() });
            }
            break;
          default:
            break;
        }
      }
    },
  });
}
