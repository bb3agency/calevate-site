"use client";

/**
 * The client's one business profile (D-695): what every agent of the business knows.
 *
 * `GET | PATCH /v1/business-profile` and `POST /v1/business-profile/setup` in the client
 * realm (a view-as session uses the same routes), `GET /v1/admin/tenants/{id}/business-profile`
 * in the operator console. A PATCH names the sections it replaces; the server updates every
 * agent in the same request, so nothing here republishes anything.
 *
 * The draft is the form's own state: the wire model with `""` for every `null`, because a
 * controlled input cannot hold `null`. `toPatch` is the one place that difference is
 * resolved, per section, so a step that saves only its own topic sends only that topic.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { LANGUAGE_CHOICES, LANGUAGE_NAMES } from "@/lib/agentState";
import { lookup } from "@/lib/lookup";

import { adminSession } from "./admin";
import { agentKeys } from "./agents";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type BusinessProfile = Schemas["BusinessProfileOut"];
export type AdminBusinessProfile = Schemas["AdminBusinessProfileOut"];
export type ProfilePatch = Schemas["ProfilePatch"];
export type ProfileSetupIn = Schemas["ProfileSetupIn"];
export type StepId = Schemas["ProfileSetupStepOut"]["id"];
export type StepState = Schemas["ProfileSetupStepOut"]["state"];
export type DayHours = Schemas["DayHours"];
export type Weekday = DayHours["day"];
export type BusinessContact = Schemas["BusinessContactOut"];

/** The week in the order the agent reads it out. `Weekday` is the generated union. */
export const DAYS: readonly Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export const DAY_LABELS: Record<Weekday, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

/* ------------------------------------------------------------------------ the steps */

export interface StepCopy {
  id: StepId;
  /** The step's question, as a heading. */
  title: string;
  /** One line under the title. */
  hint: string;
  /** The checklist row's label. */
  short: string;
}

/** One topic per step, in the order the wizard asks them. Business facts only: what each
 *  agent says, its voice and its language live on the agent's own screens. */
export const STEPS: readonly StepCopy[] = [
  { id: "hours", title: "When are you open?", hint: "Callers ask this first. Mark the days you are closed.", short: "Opening hours" },
  { id: "branches", title: "Where are you?", hint: "Add each branch callers can visit.", short: "Address" },
  { id: "services", title: "What do you offer?", hint: "Services and prices your agents can quote.", short: "Services and prices" },
  { id: "faqs", title: "What do callers often ask?", hint: "Short questions with the answer you want given.", short: "Common questions" },
  { id: "staff", title: "Who works with you?", hint: "Names your agents may mention, and how to say them.", short: "Staff names" },
  { id: "booking", title: "How do bookings work?", hint: "Slots, notice, deposits — anything a caller should know.", short: "Booking rules" },
  { id: "contacts", title: "Who can take a call?", hint: "People your agents can put a caller through to. Indian mobiles only.", short: "People who take calls" },
  { id: "languages", title: "Which languages do you serve?", hint: "Your agents answer in these besides their own language.", short: "Languages" },
];

export function stepCopy(id: StepId): StepCopy {
  return STEPS.find((step) => step.id === id) ?? STEPS[0];
}

/** Where a step is answered, in the wizard. */
export function setupHref(href: (path: string) => string, step?: StepId): string {
  return href(step ? `/setup?step=${step}` : "/setup");
}

/* ------------------------------------------------------------------------ the draft */

export interface DayDraft {
  day: Weekday;
  /** `""` while unanswered. `<input type="time">` gives HH:MM or `""`. */
  opens: string;
  closes: string;
  closed: boolean;
}

export interface BranchDraft {
  label: string;
  address: string;
}

export interface ServiceDraft {
  name: string;
  /** A STRING all the way down: the agent reads out exactly the digits typed. */
  price_inr: string;
  notes: string;
}

export interface FaqDraft {
  question: string;
  answer: string;
}

export interface StaffDraft {
  name: string;
  pronunciation: string;
  role: string;
}

export interface ContactDraft {
  /** The stored contact this row edits, or `null` for a new person. Kept so every agent's
   *  handover list keeps pointing at the same person after a rename. */
  id: string | null;
  name: string;
  phone_e164: string;
  /** When they can be reached, in the client's words. */
  hours: string;
}

export interface ProfileDraft {
  /** Always all seven days, in `DAYS` order. */
  business_hours: DayDraft[];
  branches: BranchDraft[];
  services: ServiceDraft[];
  faqs: FaqDraft[];
  staff: StaffDraft[];
  booking_rules: string;
  escalation_contacts: ContactDraft[];
  languages: NonNullable<ProfilePatch["languages"]>;
}

export const blankBranch = (): BranchDraft => ({ label: "", address: "" });
export const blankService = (): ServiceDraft => ({ name: "", price_inr: "", notes: "" });
export const blankFaq = (): FaqDraft => ({ question: "", answer: "" });
export const blankStaff = (): StaffDraft => ({ name: "", pronunciation: "", role: "" });
export const blankContact = (): ContactDraft => ({ id: null, name: "", phone_e164: "", hours: "" });

const text = (value: string | null | undefined): string => value ?? "";

export function draftFromProfile(profile: BusinessProfile): ProfileDraft {
  const byDay = new Map(profile.hours.map((row) => [row.day, row]));
  return {
    business_hours: DAYS.map((day) => {
      const row = byDay.get(day);
      if (!row) return { day, opens: "", closes: "", closed: false };
      return { day, opens: text(row.opens), closes: text(row.closes), closed: Boolean(row.closed) };
    }),
    branches: profile.branches.map((row) => ({ label: row.label, address: row.address })),
    services: profile.services.map((row) => ({
      name: row.name,
      price_inr: text(row.price_inr),
      notes: text(row.notes),
    })),
    faqs: profile.faqs.map((row) => ({ question: row.question, answer: row.answer })),
    staff: profile.staff.map((row) => ({
      name: row.name,
      pronunciation: text(row.pronunciation),
      role: text(row.role),
    })),
    booking_rules: text(profile.booking_rules),
    escalation_contacts: profile.contacts.map((row) => ({
      id: row.id,
      name: row.label,
      phone_e164: row.phone_e164,
      hours: text(row.note),
    })),
    languages: [...profile.languages],
  };
}

const trimmed = (value: string): string | null => {
  const clean = value.trim();
  return clean === "" ? null : clean;
};

const filled = (...values: string[]): boolean => values.some((value) => value.trim() !== "");

/** Drop the rows nobody typed in, so what is on screen and what is sent share indices. */
export function pruneDraft(draft: ProfileDraft): ProfileDraft {
  return {
    ...draft,
    branches: draft.branches.filter((row) => filled(row.label, row.address)),
    services: draft.services.filter((row) => filled(row.name, row.price_inr, row.notes)),
    faqs: draft.faqs.filter((row) => filled(row.question, row.answer)),
    staff: draft.staff.filter((row) => filled(row.name, row.pronunciation, row.role)),
    escalation_contacts: draft.escalation_contacts.filter((row) =>
      filled(row.name, row.phone_e164, row.hours),
    ),
  };
}

/** The PATCH body for ONE step: only that topic is sent, so it replaces only that topic. */
export function toPatch(draft: ProfileDraft, step: StepId): ProfilePatch {
  const pruned = pruneDraft(draft);
  switch (step) {
    case "hours":
      return {
        hours: pruned.business_hours
          .filter((day) => day.closed || day.opens !== "" || day.closes !== "")
          .map((day) => ({
            day: day.day,
            closed: day.closed,
            opens: day.closed ? null : trimmed(day.opens),
            closes: day.closed ? null : trimmed(day.closes),
          })),
      };
    case "branches":
      return { branches: pruned.branches.map((row) => ({ label: row.label.trim(), address: row.address.trim() })) };
    case "services":
      return {
        services: pruned.services.map((row) => ({
          name: row.name.trim(),
          price_inr: trimmed(row.price_inr),
          notes: trimmed(row.notes),
        })),
      };
    case "faqs":
      return { faqs: pruned.faqs.map((row) => ({ question: row.question.trim(), answer: row.answer.trim() })) };
    case "staff":
      return {
        staff: pruned.staff.map((row) => ({
          name: row.name.trim(),
          pronunciation: trimmed(row.pronunciation),
          role: trimmed(row.role),
        })),
      };
    case "booking":
      return { booking_rules: trimmed(draft.booking_rules) };
    case "contacts":
      return {
        contacts: pruned.escalation_contacts.map((row) => ({
          id: row.id,
          label: row.name.trim(),
          phone_e164: row.phone_e164.trim(),
          note: trimmed(row.hours),
        })),
      };
    case "languages":
      return { languages: draft.languages };
  }
}

/** The DOM id a control carries, derived from the wire path it edits — so a field error
 *  and the control it is about cannot have two names. */
export function profileFieldId(path: string): string {
  return `profile-${path.replace(/\./g, "-")}`;
}

/** The server's message for a field of the section just sent, or nothing. */
export function fieldMessage(
  fields: { field: string; message: string }[] | undefined,
  path: string,
): string | undefined {
  return fields?.find((f) => f.field === path || f.field.startsWith(`${path}.`))?.message;
}

/* ------------------------------------------------------------------------ the hooks */

export const BUSINESS_PROFILE_PATH = "/v1/business-profile";

export const businessProfileKeys = {
  mine: (org: string) => ["business-profile", org] as const,
  tenant: (tenantId: string) => ["admin", "business-profile", tenantId] as const,
};

export function useBusinessProfile(session: Session): UseQueryResult<BusinessProfile> {
  return useQuery({
    queryKey: businessProfileKeys.mine(session.orgSlug),
    queryFn: () => apiRequest<BusinessProfile>(session, BUSINESS_PROFILE_PATH),
  });
}

/**
 * Save one or more sections. The response IS the new profile, so it is written straight
 * into the cache; the agents' caches go stale because their facts just changed.
 */
export function useSaveBusinessProfile(
  session: Session,
): UseMutationResult<BusinessProfile, Error, ProfilePatch> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (patch: ProfilePatch) =>
      apiRequest<BusinessProfile>(session, BUSINESS_PROFILE_PATH, { method: "PATCH", body: patch }),
    onSuccess: (profile) => {
      client.setQueryData(businessProfileKeys.mine(session.orgSlug), profile);
      const org = session.orgSlug;
      for (const queryKey of [
        agentKeys.all(org),
        ["agent", org],
        ["agent-handoff", org],
        ["agent-pending", org],
      ]) {
        void client.invalidateQueries({ queryKey });
      }
    },
  });
}

export function useSetupAction(
  session: Session,
): UseMutationResult<BusinessProfile, Error, ProfileSetupIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: ProfileSetupIn) =>
      apiRequest<BusinessProfile>(session, `${BUSINESS_PROFILE_PATH}/setup`, {
        method: "POST",
        body: action,
      }),
    onSuccess: (profile) => client.setQueryData(businessProfileKeys.mine(session.orgSlug), profile),
  });
}

export function useAdminBusinessProfile(tenantId: string): UseQueryResult<AdminBusinessProfile> {
  return useQuery({
    queryKey: businessProfileKeys.tenant(tenantId),
    queryFn: () =>
      apiRequest<AdminBusinessProfile>(
        adminSession(),
        `/v1/admin/tenants/${encodeURIComponent(tenantId)}/business-profile`,
      ),
    enabled: Boolean(tenantId),
  });
}

/* ------------------------------------------------------------------- small readers */

export function stepStates(profile: BusinessProfile): Record<StepId, StepState> {
  const out = {} as Record<StepId, StepState>;
  for (const step of profile.setup.steps) out[step.id] = step.state;
  return out;
}

/** The first step still to do, or `null` when every step is answered or skipped. */
export function nextStep(profile: BusinessProfile): StepId | null {
  return profile.setup.steps.find((step) => step.state === "todo")?.id ?? null;
}

export function languageLabel(tag: string): string {
  return lookup(LANGUAGE_NAMES, tag) ?? tag;
}

/** The languages a business can choose, with their one set of names. */
export { LANGUAGE_CHOICES as PROFILE_LANGUAGES };
