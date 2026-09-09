"use client";

import { useState } from "react";

import {
  CONSENT_SOURCES,
  GRANT_CAPABLE_SOURCES,
  collectEvidence,
  grantBlockReason,
  useLookupMessagingConsent,
  useRecordMessagingConsent,
  type ConsentSource,
  type ConsentStatus,
} from "@/lib/api/messagingConsent";
import { type Session } from "@/lib/api/client";

/**
 * Everything the messaging-consent screen HOLDS, in one hook, away from the JSX.
 *
 * Both mutations live here rather than in the two cards, and that is the coupling this
 * module exists to keep: recording an answer makes any verdict already on screen stale,
 * so `submit` resets the lookup — which it can only do if it holds the same mutation
 * instance the lookup card renders. Two `useMutation` calls in two components are two
 * independent states, and the stale verdict would have survived the write.
 *
 * The derived values (`effectiveStatus`, `sourceOptions`, `blocked`) are here for the
 * second reason UX-DOCTRINE §6 gives: they are the rules about what may be recorded, and
 * they are the half a test can drive without a render.
 */
export interface ConsentForm {
  lookup: ReturnType<typeof useLookupMessagingConsent>;
  record: ReturnType<typeof useRecordMessagingConsent>;
  /**
   * The refusal from the last write, surfaced BY the module that fires the write.
   *
   * `submit` below calls `record.mutate`, so this is where a 403, a 409 or a timeout
   * becomes visible or does not — leaving it to whichever component happens to render the
   * form is how a refusal ends up swallowed and the user presses the button again.
   * `tests/surfaceStatesGuard.test.ts` holds exactly this rule.
   */
  recordError: ReturnType<typeof useRecordMessagingConsent>["error"];
  lookupPhone: string;
  setLookupPhone: (next: string) => void;
  phone: string;
  setPhone: (next: string) => void;
  answer: "yes" | "no";
  status: ConsentStatus;
  setStatus: (next: ConsentStatus) => void;
  source: ConsentSource;
  callId: string;
  setCallId: (next: string) => void;
  evidence: Record<string, string>;
  setEvidence: (next: (prev: Record<string, string>) => Record<string, string>) => void;
  /** The chosen source's spec: its hint, whether it needs a call id, its evidence fields. */
  spec: (typeof CONSENT_SOURCES)[ConsentSource];
  /** What pressing Save would record. A yes is always `granted`. */
  effectiveStatus: ConsentStatus;
  /** Only the sources that can carry the answer being given. */
  sourceOptions: ConsentSource[];
  /** Why this cannot be recorded as a yes yet, or `null`. */
  blocked: string | null;
  chooseAnswer: (next: "yes" | "no") => void;
  chooseSource: (next: ConsentSource) => void;
  submit: () => void;
}

export function useConsentForm(session: Session): ConsentForm {
  const lookup = useLookupMessagingConsent(session);
  const record = useRecordMessagingConsent(session);

  const [lookupPhone, setLookupPhone] = useState("");

  // The recording form. `answer` is the first decision and drives everything below it.
  const [phone, setPhone] = useState("");
  const [answer, setAnswer] = useState<"yes" | "no">("yes");
  const [status, setStatus] = useState<ConsentStatus>("withdrawn");
  const [source, setSource] = useState<ConsentSource>("inbound_call_verbal");
  const [callId, setCallId] = useState("");
  const [evidence, setEvidence] = useState<Record<string, string>>({});

  const spec = CONSENT_SOURCES[source];
  const effectiveStatus: ConsentStatus = answer === "yes" ? "granted" : status;
  // A yes never offers `staff_recorded_request`; a no offers everything, including it.
  const sourceOptions =
    answer === "yes"
      ? GRANT_CAPABLE_SOURCES
      : (Object.keys(CONSENT_SOURCES) as ConsentSource[]);

  const blocked = answer === "yes" ? grantBlockReason(source, evidence, callId) : null;

  const chooseAnswer = (next: "yes" | "no") => {
    setAnswer(next);
    record.reset();
    // A source that cannot grant must not survive a switch to "yes" — it would leave
    // the form holding a combination the database refuses.
    if (next === "yes" && !CONSENT_SOURCES[source].canGrant) setSource("inbound_call_verbal");
  };

  const chooseSource = (next: ConsentSource) => {
    setSource(next);
    // Evidence keys belong to the source that asked for them; carrying a transcript
    // span over to a web form would attach a field that evidences nothing.
    setEvidence({});
    record.reset();
  };

  const submit = () => {
    const evidencePayload = collectEvidence(spec, evidence);
    record.mutate(
      {
        // The number goes in the BODY. Never a query string, never the URL — access
        // logs, referrers and browser history (hard rule 6).
        phone: phone.trim(),
        status: effectiveStatus,
        source,
        // Meaningful only for a spoken opt-in; omitted rather than sent empty.
        call_id: spec.requiresCallId && callId.trim() ? callId.trim() : null,
        evidence: evidencePayload,
      },
      {
        onSuccess: () => {
          setEvidence({});
          setCallId("");
          // Any verdict on screen was read before this write and may now be wrong.
          lookup.reset();
        },
      },
    );
  };

  return {
    lookup,
    record,
    recordError: record.error,
    lookupPhone,
    setLookupPhone,
    phone,
    setPhone,
    answer,
    status,
    setStatus,
    source,
    callId,
    setCallId,
    evidence,
    setEvidence,
    spec,
    effectiveStatus,
    sourceOptions,
    blocked,
    chooseAnswer,
    chooseSource,
    submit,
  };
}
