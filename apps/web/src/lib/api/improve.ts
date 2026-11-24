"use client";

/**
 * The Improve readings of a campaign's or Inbound line's calls (`GET …/diagnosis`,
 * `campaigns/diagnose.py`), and the presses its cards make. Every card takes a `Holder`, so a
 * campaign and a line show the same card from the same code.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { useCampaignTestCalls, useRequestCampaignScript } from "./campaignWorkspace";
import { apiRequest, type Session } from "./client";
import { useLineTestCalls, useRequestLineScript, type LineScriptAsk } from "./inboundLines";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Holder = { kind: "campaign" | "inbound_line"; id: string };
export type HolderDiagnosis = Schemas["HolderDiagnosisOut"];
export type DiagnosisStep = Schemas["DiagnosisStepOut"];
export type HolderMistake = Schemas["HolderMistakeOut"];
export type RefusalReason = Schemas["RefusalReasonOut"]["reason"];

export const diagnosisKey = (org: string, holder: Holder) =>
  ["holder-diagnosis", org, holder.kind, holder.id] as const;

function holderPath(holder: Holder): string {
  const root = holder.kind === "campaign" ? "/v1/campaigns" : "/v1/inbound-lines";
  return `${root}/${encodeURIComponent(holder.id)}`;
}

export function useHolderDiagnosis(session: Session, holder: Holder): UseQueryResult<HolderDiagnosis> {
  return useQuery({
    queryKey: diagnosisKey(session.orgSlug, holder),
    queryFn: () => apiRequest<HolderDiagnosis>(session, `${holderPath(holder)}/diagnosis`),
  });
}

export type HolderGiveTime = Schemas["HolderGiveTimeOut"];

export const giveTimeKey = (org: string, holder: Holder) =>
  ["holder-give-time", org, holder.kind, holder.id] as const;

/** "Give callers time" on this holder's calls (`agents/give_callers_time`). */
export function useHolderGiveTime(session: Session, holder: Holder): UseQueryResult<HolderGiveTime> {
  return useQuery({
    queryKey: giveTimeKey(session.orgSlug, holder),
    queryFn: () => apiRequest<HolderGiveTime>(session, `${holderPath(holder)}/give-callers-time`),
  });
}

/** The owner's choice for this holder; the script no longer decides after it. */
export function useSetHolderGiveTime(
  session: Session,
  holder: Holder,
): UseMutationResult<HolderGiveTime, Error, boolean> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (on: boolean) =>
      apiRequest<HolderGiveTime>(session, `${holderPath(holder)}/give-callers-time`, {
        method: "PUT",
        body: { on },
      }),
    onSuccess: (data) => client.setQueryData(giveTimeKey(session.orgSlug, holder), data),
  });
}

/**
 * Ask Pip for a draft of the holder's script with `instruction` (the holder's own
 * `…/proposal` route, as Generate with a note is). The draft waits on the script for the
 * owner to keep or discard; nothing reaches a call before that.
 */
export function useAskPipToRewrite(
  session: Session,
  holder: Holder,
): UseMutationResult<unknown, Error, LineScriptAsk | undefined> {
  // Both hooks are called every render (hooks cannot be conditional); only the holder's own
  // is ever pressed.
  const campaign = useRequestCampaignScript(session, holder.kind === "campaign" ? holder.id : "");
  const line = useRequestLineScript(session, holder.kind === "inbound_line" ? holder.id : "");
  return holder.kind === "campaign" ? campaign : line;
}

/** The holder's test calls, newest first. */
export function useHolderTestCalls(session: Session, holder: Holder) {
  const campaign = useCampaignTestCalls(session, holder.id, holder.kind === "campaign");
  const line = useLineTestCalls(session, holder.id, holder.kind === "inbound_line");
  return holder.kind === "campaign" ? campaign : line;
}

/** What Pip is told for "Fix this step": the step by number and name, and why. */
export function stepFixInstruction(step: DiagnosisStep): string {
  return (
    `Rewrite step ${step.step}${step.name ? `, "${step.name}",` : ""} so more people reach its ` +
    "outcome: many calls stop there. Keep the other steps as they are."
  );
}

/**
 * What Pip is told for "Rewrite the opening". The opening keeps the AI and recording notices:
 * Pip's opening repair writes them into the line it writes (D-971), and until a saved
 * opening says them the engine says the stored sentences beside it.
 */
export function openingFixInstruction(holder: Holder): string {
  const purpose = holder.kind === "campaign" ? "why we are calling" : "how it can help";
  return (
    "Rewrite the opening line so fewer people hang up in the first seconds: shorter, and " +
    `it says early ${purpose}. Keep the AI and recording notices it says. Keep the steps ` +
    "as they are."
  );
}

/** The reasons, in the owner's words. Client-facing: no provider named. */
export const REFUSAL_REASON_WORDS: Record<RefusalReason, string> = {
  price: "The price",
  busy_now: "Busy right now",
  already_has: "Already has it",
  not_interested: "Not interested",
  wants_person: "Wants to talk to a person",
  no_trust: "Does not trust it yet",
  other: "Another reason",
};

/** The question a "Teach an answer" fact answers, per reason. */
export const REFUSAL_REASON_QUESTION: Record<RefusalReason, string> = {
  price: "What do we say when someone says the price is too high?",
  busy_now: "What do we say when someone is busy right now?",
  already_has: "What do we say when someone already has it?",
  not_interested: "What do we say when someone is not interested?",
  wants_person: "What do we say when someone wants to talk to a person?",
  no_trust: "What do we say when someone is not sure they can trust us?",
  other: "What else should the agent say when someone says no?",
};
