"use client";

import { useMemo, useState } from "react";

import {
  consentCollectedAt,
  parseContactCsv,
  scheduleStartAt,
  type Classification,
  type ConsentSource,
} from "@/lib/api/campaigns";

/**
 * THE TWO FORMS' STATE, pulled out of the JSX.
 *
 * UX-DOCTRINE §6: "Pull the arithmetic out of the JSX. Key derivation, dirty comparison,
 * validation and wire mapping belong in a plain module beside the component." These two
 * hooks are that half — every `useState` the campaigns screen holds, plus the three
 * derived values (`parsed`, `consentIso`, `provenanceAnswered`, `startIso`) the controls
 * read. The screen keeps them because ONE component must declare the copilot surface
 * (`lib/copilot/registry.ts` makes the innermost registration the live one), and the
 * surface names controls from both forms.
 *
 * Every initial value below carries an argument that is a compliance or safety property,
 * not a preference, and each is kept beside the field it belongs to.
 */
export interface CampaignFormState {
  name: string;
  setName: (value: string) => void;
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
  csv: string;
  setCsv: (value: string) => void;
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
  /** The rows we could read out of the pasted CSV. */
  parsed: ReturnType<typeof parseContactCsv>;
  /** The consent date as the API takes it, or `null` when it is unusable. */
  consentIso: string | null;
  /** Both halves of the declaration, or neither — the API refuses a half-filled one. */
  provenanceAnswered: boolean;
  /** Back to the list with the AUDITED answer cleared — see the comment at the call. */
  reset: () => void;
}

export function useCampaignForm(): CampaignFormState {
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [classification, setClassification] = useState<Classification>("service");
  const [concurrency, setConcurrency] = useState(3);
  const [numberId, setNumberId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [csv, setCsv] = useState("");
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

  const parsed = useMemo(() => parseContactCsv(csv), [csv]);
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
    setName("");
    setCsv("");
    setConsentSource("");
    setConsentDate("");
  };

  return {
    name, setName,
    agentId, setAgentId,
    classification, setClassification,
    concurrency, setConcurrency,
    numberId, setNumberId,
    templateId, setTemplateId,
    csv, setCsv,
    consentSource, setConsentSource,
    consentDate, setConsentDate,
    restrictHours, setRestrictHours,
    windowStart, setWindowStart,
    windowEnd, setWindowEnd,
    parsed, consentIso, provenanceAnswered, reset,
  };
}

export interface ScheduleFormState {
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
    startDate, setStartDate,
    startTime, setStartTime,
    startIso: scheduleStartAt(startDate, startTime),
    repeatDays, setRepeatDays, toggleRepeatDay,
    repeatTime, setRepeatTime,
    repeatEnds, setRepeatEnds,
  };
}
