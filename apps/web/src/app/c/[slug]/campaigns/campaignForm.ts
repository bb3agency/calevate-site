"use client";

import { useMemo, useRef, useState } from "react";

import {
  consentCollectedAt,
  scheduleStartAt,
  DEFAULT_RETRY,
  type Classification,
  type ConsentSource,
  type RetryPolicy,
} from "@/lib/api/campaigns";

import { useLeadsLens, type LeadsLensState } from "../leads/useLeadsLens";

import { checkContacts, type CheckedList, type ContactEntry } from "./contactList";

/**
 * THE TWO FORMS' STATE, pulled out of the JSX.
 *
 * UX-DOCTRINE §6: "Pull the arithmetic out of the JSX. Key derivation, dirty comparison,
 * validation and wire mapping belong in a plain module beside the component." These two
 * hooks are that half — every `useState` the campaigns screen holds, plus the three
 * derived values (`checked`, `consentIso`, `provenanceAnswered`, `startIso`) the controls
 * read. The screen keeps them because ONE component must declare the copilot surface
 * (`lib/copilot/registry.ts` makes the innermost registration the live one), and the
 * surface names controls from both forms.
 *
 * Every initial value below carries an argument that is a compliance or safety property,
 * not a preference, and each is kept beside the field it belongs to.
 */
/**
 * The name a campaign gets from its goal until the owner types one: the goal and the day it
 * was made, "Booked a visit, 5 Nov". An owner rarely knows what to call a list of calls, and
 * a blank name was the one field every draft stopped on; the day tells two runs of the same
 * goal apart in the list.
 */
export function nameFromGoal(goal: string, at: Date = new Date()): string {
  const line = goal.trim().replace(/\s+/g, " ");
  if (line === "") return "";
  const day = at.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  return `${line}, ${day}`;
}

export interface CampaignFormState {
  name: string;
  /** Typed by the owner. A cleared name goes back to following the goal. */
  setName: (value: string) => void;
  /** True while the name is the one made from the goal, not one the owner typed. */
  nameFollowsGoal: boolean;
  /** Why these people are called, in the business's words (`campaigns.purpose`). */
  purpose: string;
  setPurpose: (value: string) => void;
  /** What a good call ends with (`campaigns.goal`). */
  goal: string;
  setGoal: (value: string) => void;
  agentId: string;
  setAgentId: (value: string) => void;
  classification: Classification;
  setClassification: (value: Classification) => void;
  concurrency: number;
  setConcurrency: (value: number) => void;
  numberId: string;
  setNumberId: (value: string) => void;
  templateId: string;
  setTemplateId: (value: string) => void;
  /** The contact list as the editor holds it, before upload. */
  contacts: ContactEntry[];
  setContacts: (value: ContactEntry[]) => void;
  consentSource: ConsentSource | "";
  setConsentSource: (value: ConsentSource | "") => void;
  consentDate: string;
  setConsentDate: (value: string) => void;
  restrictHours: boolean;
  setRestrictHours: (value: boolean) => void;
  windowStart: string;
  setWindowStart: (value: string) => void;
  windowEnd: string;
  setWindowEnd: (value: string) => void;
  /** How many tries per person and the gaps between them (`RetryPolicyIn`). */
  retry: RetryPolicy;
  setRetry: (value: RetryPolicy) => void;
  /** Whether CRM leads are added once the draft exists, and the lens that chooses them. */
  fromLeads: boolean;
  setFromLeads: (value: boolean) => void;
  leads: LeadsLensState;
  /** Each row's verdict, the counts, and the request the ready rows become. */
  checked: CheckedList;
  /** The consent date as the API takes it, or `null` when it is unusable. */
  consentIso: string | null;
  /** Both halves of the declaration, or neither — the API refuses a half-filled one. */
  provenanceAnswered: boolean;
  /** Back to the list with the AUDITED answer cleared — see the comment at the call. */
  reset: () => void;
}

export function useCampaignForm(): CampaignFormState {
  const [name, setNameValue] = useState("");
  // A ref, not state: the edit page sets the saved name and then the saved goal in one
  // effect, and a state flag read in that same closure would still say "follows the goal"
  // and overwrite the name the draft was saved with.
  const nameFollows = useRef(true);
  const [nameFollowsGoal, setNameFollowsGoal] = useState(true);
  const followGoal = (on: boolean) => {
    nameFollows.current = on;
    setNameFollowsGoal(on);
  };
  const setName = (value: string) => {
    setNameValue(value);
    followGoal(value.trim() === "");
  };
  const [purpose, setPurpose] = useState("");
  const [goal, setGoalValue] = useState("");
  const setGoal = (value: string) => {
    setGoalValue(value);
    if (nameFollows.current) setNameValue(nameFromGoal(value));
  };
  const [agentId, setAgentId] = useState("");
  const [classification, setClassification] = useState<Classification>("service");
  const [concurrency, setConcurrency] = useState(3);
  const [numberId, setNumberId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [contacts, setContacts] = useState<ContactEntry[]>([]);
  const [retry, setRetry] = useState<RetryPolicy>(DEFAULT_RETRY);
  const [fromLeads, setFromLeads] = useState(false);
  const leads = useLeadsLens();
  // Asked at creation, not deferred to the launch check: the client is holding the
  // list in their hand at this moment, which is the only moment they can answer
  // cheaply. Empty string, never a default source — there is no sensible default for
  // "where did these five thousand numbers come from", and a pre-selected one would
  // put an assertion nobody made into an audited record.
  const [consentSource, setConsentSource] = useState<ConsentSource | "">("");
  const [consentDate, setConsentDate] = useState("");
  // Off by default, and "off" means null — not 09:00-21:00 echoed back. The platform
  // window is enforced by the per-dial compliance gate whether or not a campaign
  // carries one of its own, so sending it as a campaign setting would misrepresent
  // a legal bound as something this form chose.
  const [restrictHours, setRestrictHours] = useState(false);
  const [windowStart, setWindowStart] = useState("10:00");
  const [windowEnd, setWindowEnd] = useState("18:00");

  const checked = useMemo(() => checkContacts(contacts), [contacts]);
  // Both or neither, decided here so the two halves cannot be sent apart: the API
  // takes provenance as one nested object and refuses a half-filled one.
  const consentIso = consentCollectedAt(consentDate);
  const provenanceAnswered = Boolean(consentSource) && consentIso !== null;

  /**
   * The bug this closes: `consentSource`/`consentDate` used to survive the reset, so the
   * create form re-opened with the previous campaign's declaration pre-selected and
   * "Create campaign" already live. A client clicking straight through would then have
   * stated, on the record, that a list they have not described yet came from the same
   * place on the same date as the last one — the exact "assertion nobody made" the
   * `consentSource` initialiser above forbids, written into a record whose whole purpose
   * is to answer a complaint later.
   *
   * The number, template, classification and concurrency deliberately DO survive: they
   * are settings the gate re-checks on every launch, not statements about a list, and a
   * client running a second campaign from the same number should not have to say so
   * twice.
   */
  const reset = () => {
    setNameValue("");
    followGoal(true);
    setPurpose("");
    setGoal("");
    setContacts([]);
    setFromLeads(false);
    leads.clearFilters();
    leads.setActiveViewId(undefined);
    setConsentSource("");
    setConsentDate("");
  };

  return {
    name, setName, nameFollowsGoal,
    purpose, setPurpose,
    goal, setGoal,
    agentId, setAgentId,
    classification, setClassification,
    concurrency, setConcurrency,
    numberId, setNumberId,
    templateId, setTemplateId,
    contacts, setContacts,
    retry, setRetry,
    fromLeads, setFromLeads, leads,
    consentSource, setConsentSource,
    consentDate, setConsentDate,
    restrictHours, setRestrictHours,
    windowStart, setWindowStart,
    windowEnd, setWindowEnd,
    checked, consentIso, provenanceAnswered, reset,
  };
}

/**
 * How a new campaign starts. `review`: the owner launches it from its checklist (the
 * default, and the only path with the typed-count confirmation). `later`: one start at a
 * set time. `weekly`: a repeat. Both armed starts run the same launch gate when they fire.
 */
export type StartMode = "review" | "later" | "weekly";

export interface ScheduleFormState {
  startMode: StartMode;
  setStartMode: (value: StartMode) => void;
  startDate: string;
  setStartDate: (value: string) => void;
  startTime: string;
  setStartTime: (value: string) => void;
  /** The armed instant, or `null` while the two halves do not make one. */
  startIso: string | null;
  repeatDays: number[];
  setRepeatDays: (days: number[]) => void;
  toggleRepeatDay: (day: number) => void;
  repeatTime: string;
  setRepeatTime: (value: string) => void;
  repeatEnds: string;
  setRepeatEnds: (value: string) => void;
}

export function useScheduleForm(): ScheduleFormState {
  // Two fields, not one datetime-local: a date picker and a time picker are what a
  // phone renders usefully, and most of these clients are on one. Empty by default —
  // there is no sensible default start, and a pre-filled "tomorrow 10am" is a date
  // nobody chose sitting one click from dialling a list.
  const [startMode, setStartMode] = useState<StartMode>("review");
  const [startDate, setStartDate] = useState("");
  const [startTime, setStartTime] = useState("10:00");

  // The repeat form. Days empty by default and no day pre-ticked: "every Monday" is a
  // standing instruction to call strangers, and a default one is an instruction nobody
  // gave. The time defaults to 10:00 only because the control needs a value at all — it
  // is inside the calling window either way, which is the part the server enforces.
  const [repeatDays, setRepeatDays] = useState<number[]>([]);
  const [repeatTime, setRepeatTime] = useState("10:00");
  const [repeatEnds, setRepeatEnds] = useState("");
  const toggleRepeatDay = (day: number) =>
    setRepeatDays((days) =>
      days.includes(day)
        ? days.filter((value) => value !== day)
        : [...days, day].sort(),
    );

  return {
    startMode, setStartMode,
    startDate, setStartDate,
    startTime, setStartTime,
    startIso: scheduleStartAt(startDate, startTime),
    repeatDays, setRepeatDays, toggleRepeatDay,
    repeatTime, setRepeatTime,
    repeatEnds, setRepeatEnds,
  };
}

/** The most calls at once a campaign may ask for (`campaigns.concurrency_range`). */
export const CONCURRENCY_MAX = 10;

/**
 * The most calls at once this account can really place: its call lines (`GET /v1/call-lines`)
 * under the campaign's own bound. `undefined` while the lines are unknown, so the picker can
 * say it is checking rather than offer ten the account may not have. The dispatcher also
 * holds a campaign to the plan's ceiling (`campaigns/service.effective_concurrency`), which
 * the campaign page reports once the draft exists.
 */
export function concurrencyCap(callLines: number | undefined): number | undefined {
  if (callLines === undefined) return undefined;
  return Math.max(1, Math.min(CONCURRENCY_MAX, callLines));
}

/** A requested pace held to the cap, so the form never shows or sends more than can dial. */
export function clampConcurrency(value: number, cap: number | undefined): number {
  return Math.max(1, Math.min(value, cap ?? CONCURRENCY_MAX));
}
