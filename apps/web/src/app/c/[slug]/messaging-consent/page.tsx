"use client";

import { useState } from "react";

import { Card, ProblemNotice, RestrictionNote, formatIST } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import {
  CONSENT_SOURCES,
  CONSENT_VALIDITY_DAYS,
  GRANT_CAPABLE_SOURCES,
  collectEvidence,
  grantBlockReason,
  useLookupMessagingConsent,
  useRecordMessagingConsent,
  type ConsentSource,
  type ConsentStatus,
  type MessagingConsent,
} from "@/lib/api/messagingConsent";

/**
 * Messaging consent (SEC-COMP §4) — the record of who said we may message them.
 *
 * `POST /v1/compliance/messaging-consent` shipped with no screen, so nobody could
 * record an opt-in and every campaign WhatsApp follow-up was refused
 * `recipient_not_opted_in`. This is the way in, and it is shaped by the four things
 * the schema encodes that a generic form would quietly break:
 *
 * 1. **The answer comes first, and it decides the rest of the form.** "They said yes"
 *    and "They said no" are not two values of one dropdown here, because they have
 *    different rules: a yes must be evidenced and cannot come from your own staff, a
 *    no needs nothing at all and may come from anywhere. Asking the question first is
 *    what lets the form offer only the sources that can carry the answer given.
 * 2. **Evidence changes shape with the source**, because each source evidences itself
 *    differently (call → the call and the moment in it; web form → the form and the
 *    wording version; paper → the document; WhatsApp → the message id). One free-text
 *    "notes" box would satisfy the CHECK constraint and evidence nothing.
 * 3. **There is no "assumed" and no "implied".** Not in the source list, and not
 *    reachable by submitting a yes with the evidence fields left empty — the submit
 *    button says why it is disabled instead (`grantBlockReason`).
 * 4. **Expired is not green.** A year-old opt-in still has `status: "granted"`, so the
 *    verdict below renders `messageable` — the server's own "granted AND not stale" —
 *    and an expired grant reads as not messageable with the date it lapsed.
 *
 * No delete control exists anywhere on this page: the ledger is append-only (hard rule
 * 4) and a withdrawal is a new record that supersedes the grant before it.
 */

/** The three answers, as the person on the phone would put them. */
const STATUS_COPY: Record<ConsentStatus, { label: string; hint: string }> = {
  granted: {
    label: "Yes — they agreed to be messaged",
    hint: "An opt-in. It has to record what it rests on, and it stops being current after a year.",
  },
  declined: {
    label: "No — they were asked and said no",
    hint: "Recorded so nobody asks again, and so an audit can show they were asked.",
  },
  withdrawn: {
    label: "Stop — they asked us not to message them",
    hint: "Takes effect from now. The earlier record is kept; this one supersedes it.",
  },
};

const NO_STATUSES: ConsentStatus[] = ["declined", "withdrawn"];

export default function MessagingConsentPage() {
  const session = useClientSession();

  const lookup = useLookupMessagingConsent(session);
  const record = useRecordMessagingConsent(session);

  /**
   * Recording is `leads:dispatch` — the same authority that lets someone cause a
   * person to be contacted, because an opt-in is exactly that decision: it is what
   * turns an exhausted campaign contact into a message. The LOOKUP is `leads:read`
   * and is deliberately not gated here: reading whether somebody may be messaged is
   * not changing it, and it stays available inside a read-only "view as client"
   * session (D-22), which is the whole reason the API put it on a read permission.
   */
  const write = useWriteAccess(
    session,
    "leads:dispatch",
    "record what a customer said about being messaged",
  );

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
  // Only the sources that can carry the answer being given. A yes never offers
  // `staff_recorded_request`; a no offers everything, including it.
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

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">
          Messaging consent
        </h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Who has agreed to receive WhatsApp messages from you. Campaign follow-ups are
          only sent to people recorded here — and this is separate from calling, which
          is governed by the do-not-call list.
        </p>
      </div>

      <RestrictionNote reason={write.reason} />

      {/* The question people actually arrive with, and the one thing everyone with
          access to the account may do. */}
      <Card title="Can we message this number?">
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Asks the same question the system asks itself before it sends a follow-up, so
          the answer cannot disagree with what actually happens.
        </p>
        <form
          className="mt-3 flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            lookup.mutate(lookupPhone.trim());
          }}
        >
          <input
            required
            value={lookupPhone}
            onChange={(e) => {
              setLookupPhone(e.target.value);
              // A stale verdict beside a changed number is worse than no verdict.
              // (TanStack Query v5 `reset()` clears mutation state —
              // tanstack.com/query/v5/docs/framework/react/reference/useMutation)
              lookup.reset();
            }}
            minLength={8}
            maxLength={20}
            inputMode="tel"
            autoComplete="off"
            placeholder="9876543210 or +919876543210"
            aria-label="Phone number to check"
            className="w-64 rounded-md border border-slate-200 px-3 py-1.5 font-mono text-sm dark:border-slate-700 dark:bg-slate-950"
          />
          <button
            type="submit"
            disabled={lookup.isPending || lookupPhone.trim().length < 8}
            className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
          >
            {lookup.isPending ? "Checking…" : "Check"}
          </button>
        </form>

        {lookup.error != null && (
          <div className="mt-3">
            <ProblemNotice error={lookup.error} />
          </div>
        )}
        {lookup.data && (
          <div className="mt-3">
            <Verdict state={lookup.data} />
          </div>
        )}
      </Card>

      {write.allowed && (
        <Card title="Record what a customer said">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Every record is kept — nothing here is edited or deleted. If someone changes
            their mind, record the new answer and it replaces the old one from that
            moment.
          </p>

          <form
            className="mt-4 space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <Field label="Their number" htmlFor="consent-phone">
              <input
                id="consent-phone"
                required
                value={phone}
                onChange={(e) => {
                  setPhone(e.target.value);
                  record.reset();
                }}
                minLength={8}
                maxLength={20}
                inputMode="tel"
                autoComplete="off"
                placeholder="9876543210 or +919876543210"
                className="w-64 rounded-md border border-slate-200 px-3 py-1.5 font-mono text-sm dark:border-slate-700 dark:bg-slate-950"
              />
            </Field>

            {/* The answer first: it is what decides which sources may carry it. */}
            <fieldset>
              <legend className="text-sm font-medium text-slate-700 dark:text-slate-300">
                What did they say?
              </legend>
              <div className="mt-2 flex flex-wrap gap-2">
                <Choice
                  name="answer"
                  checked={answer === "yes"}
                  onChange={() => chooseAnswer("yes")}
                  label="They agreed to be messaged"
                />
                <Choice
                  name="answer"
                  checked={answer === "no"}
                  onChange={() => chooseAnswer("no")}
                  label="They do not want messages"
                />
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {answer === "yes"
                  ? STATUS_COPY.granted.hint
                  : "A refusal is never held up: it needs no evidence and can be recorded by anyone here."}
              </p>
            </fieldset>

            {answer === "no" && (
              <Field label="Which kind of no?" htmlFor="consent-status">
                <select
                  id="consent-status"
                  value={status}
                  onChange={(e) => setStatus(e.target.value as ConsentStatus)}
                  className="rounded-md border border-slate-200 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
                >
                  {NO_STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {STATUS_COPY[value].label}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-slate-500">{STATUS_COPY[status].hint}</p>
              </Field>
            )}

            <Field label="How do you know?" htmlFor="consent-source">
              <select
                id="consent-source"
                value={source}
                onChange={(e) => chooseSource(e.target.value as ConsentSource)}
                className="w-full max-w-md rounded-md border border-slate-200 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
              >
                {sourceOptions.map((value) => (
                  <option key={value} value={value}>
                    {CONSENT_SOURCES[value].label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-slate-500">{spec.hint}</p>
              {/* Said once, where someone would otherwise go looking for the missing
                  option: your own staff cannot assert an opt-in on a customer's behalf. */}
              {answer === "yes" && (
                <p className="mt-1 text-xs text-slate-500">
                  Recording it on a customer&apos;s behalf is not on this list — an
                  opt-in has to come from the customer.
                </p>
              )}
            </Field>

            {spec.requiresCallId && (
              <Field label="Which call?" htmlFor="consent-call">
                <input
                  id="consent-call"
                  value={callId}
                  onChange={(e) => setCallId(e.target.value)}
                  placeholder="Call ID from the Calls page"
                  className="w-full max-w-md rounded-md border border-slate-200 px-3 py-1.5 font-mono text-sm dark:border-slate-700 dark:bg-slate-950"
                />
                <p className="mt-1 text-xs text-slate-500">
                  {answer === "yes"
                    ? "Required: a spoken opt-in has to name the call it was spoken on."
                    : "Optional for a refusal."}
                </p>
              </Field>
            )}

            {spec.evidence.map((field) => (
              <Field key={field.key} label={field.label} htmlFor={`evidence-${field.key}`}>
                <input
                  id={`evidence-${field.key}`}
                  value={evidence[field.key] ?? ""}
                  onChange={(e) =>
                    setEvidence((prev) => ({ ...prev, [field.key]: e.target.value }))
                  }
                  placeholder={field.placeholder}
                  className="w-full max-w-md rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
                />
                <p className="mt-1 text-xs text-slate-500">
                  {field.hint}
                  {answer === "no" && " Optional here."}
                </p>
              </Field>
            ))}

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={record.isPending || phone.trim().length < 8 || blocked !== null}
                className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
              >
                {record.isPending
                  ? "Recording…"
                  : answer === "yes"
                    ? "Record their opt-in"
                    : "Record their refusal"}
              </button>
              {/* The refusal, given before the click rather than as a 422 after it. */}
              {blocked && <span className="text-xs text-amber-700 dark:text-amber-400">{blocked}</span>}
            </div>
          </form>

          {record.error != null && (
            <div className="mt-3">
              <ProblemNotice error={record.error} />
            </div>
          )}
          {record.data && (
            <div className="mt-4">
              <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                Recorded. This is where that number now stands:
              </p>
              <Verdict state={record.data} />
            </div>
          )}
        </Card>
      )}

      <Card title="How this record works">
        <ul className="space-y-2 text-sm text-slate-600 dark:text-slate-400">
          <li>
            <span className="font-medium text-slate-800 dark:text-slate-200">
              An opt-in lasts {CONSENT_VALIDITY_DAYS} days.
            </span>{" "}
            After that it stops authorising messages and someone has to ask again. A
            check above will say so rather than quietly failing on the day it lapses.
          </li>
          <li>
            <span className="font-medium text-slate-800 dark:text-slate-200">
              Nothing is ever deleted.
            </span>{" "}
            Recording a refusal adds a new entry that supersedes the earlier one, so the
            history of what someone agreed to — and when — stays intact.
          </li>
          <li>
            <span className="font-medium text-slate-800 dark:text-slate-200">
              Agreeing to a call is not agreeing to a message.
            </span>{" "}
            Someone who asked to be called back has not opted in to WhatsApp, and
            nothing here fills that in for them.
          </li>
          <li>
            <span className="font-medium text-slate-800 dark:text-slate-200">
              This is in addition to do-not-call.
            </span>{" "}
            A follow-up still passes the same do-not-call and calling-hours checks a
            call does; consent never replaces them.
          </li>
        </ul>
      </Card>
    </div>
  );
}

/**
 * The verdict, rendered from `messageable` and never recomputed from `status`.
 *
 * The distinction that matters: a `granted` row that has gone stale is NOT a green
 * tick. It gets the amber treatment and the date it lapsed, because the campaign
 * worker will refuse it and the client needs to know why before they wonder where
 * their follow-ups went.
 */
function Verdict({ state }: { state: MessagingConsent }) {
  if (state.messageable) {
    return (
      <Box tone="ok">
        <p className="font-medium">You may send this person WhatsApp messages.</p>
        <p className="mt-1">
          {describeCapture(state)} This stays current until {formatIST(state.expires_at)}.
        </p>
      </Box>
    );
  }

  if (state.status === "granted") {
    return (
      <Box tone="warn">
        <p className="font-medium">Not messageable — their opt-in has expired.</p>
        <p className="mt-1">
          {describeCapture(state)} An opt-in stays current for {CONSENT_VALIDITY_DAYS}{" "}
          days, and this one lapsed on {formatIST(state.expires_at)}. Ask again before
          messaging them.
        </p>
      </Box>
    );
  }

  if (state.status === "declined" || state.status === "withdrawn") {
    return (
      <Box tone="stop">
        <p className="font-medium">
          {state.status === "withdrawn"
            ? "Not messageable — they asked us to stop."
            : "Not messageable — they were asked and said no."}
        </p>
        <p className="mt-1">{describeCapture(state)}</p>
      </Box>
    );
  }

  // `status: "none"` — and any status a future API grows that this build predates.
  // Neutral on purpose: nobody having asked yet is the normal state of the world,
  // not a fault, and it is still a no.
  return (
    <Box tone="neutral">
      <p className="font-medium">Not messageable — nobody has asked them yet.</p>
      <p className="mt-1">
        Campaign follow-ups will skip this number until someone records what they said.
      </p>
    </Box>
  );
}

function describeCapture(state: MessagingConsent): string {
  // `source` is `string | null` on the wire — a `consent_ledger` column, never narrowed
  // by the schema — so this is a lookup that must tolerate a member this build predates.
  // It used to be a `value in CONSENT_SOURCES` guard, which walks the prototype chain:
  // a source of "constructor" passed the guard, the table handed back `Object`, and
  // `.label.toLowerCase()` threw during render. The whole verdict box — the one thing on
  // this screen that answers "may we message them?" — went blank. `lookup` (lib/lookup.ts)
  // is the one way this codebase reads a wire string out of a copy table.
  // Fail direction: an unnameable source is OMITTED, not printed. The sentence is about
  // where the consent came from, and rendering a raw enum name to a client says nothing;
  // the verdict itself comes from `messageable` and is unaffected either way.
  const source = lookup(CONSENT_SOURCES, state.source);
  const when = state.captured_at ? formatIST(state.captured_at) : null;
  if (source && when) return `Recorded ${when} — ${source.label.toLowerCase()}.`;
  if (when) return `Recorded ${when}.`;
  return "";
}

const TONES = {
  ok: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  warn: "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200",
  stop: "border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200",
  neutral:
    "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300",
} as const;

function Box({ tone, children }: { tone: keyof typeof TONES; children: React.ReactNode }) {
  return <div className={`rounded-lg border p-3 text-sm ${TONES[tone]}`}>{children}</div>;
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={htmlFor}
        className="text-sm font-medium text-slate-700 dark:text-slate-300"
      >
        {label}
      </label>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function Choice({
  name,
  checked,
  onChange,
  label,
}: {
  name: string;
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <label
      className={
        checked
          ? "cursor-pointer rounded-md border border-slate-900 bg-slate-900 px-3 py-1.5 text-sm font-medium text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900"
          : "cursor-pointer rounded-md border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
      }
    >
      <input
        type="radio"
        name={name}
        checked={checked}
        onChange={onChange}
        className="sr-only"
      />
      {label}
    </label>
  );
}
