"use client";

import { useState, type ReactNode } from "react";
import {
  BadgeCheck,
  CalendarClock,
  CircleHelp,
  FileSearch,
  MessageSquareOff,
  PhoneOff,
  Search,
  ShieldAlert,
} from "lucide-react";

import {
  Card,
  FIELD_INLINE,
  FIELD_INLINE_ICON,
  MonoValue,
  NOTICE_TONES,
  ProblemNotice,
  RestrictionNote,
  TermGloss,
  formatIST,
  type NoticeTone,
  PRIMARY_BUTTON_SM,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
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
 *
 * ## THIS IS NOT CONSENT TO BE CALLED, and the screen may never blur the two
 *
 * SEC-COMP §4 is explicit: a campaign's `consent_source` provenance and a `callback`
 * ledger row "never satisfy it, and nothing backfills it". They are different purposes
 * under DPDP §6, they are refused by different gates, and a follow-up message still has
 * to pass `check_dispatch` — the do-not-call read — before this record is even consulted.
 * So every sentence here that could be read as clearance for a CALL is either absent or
 * says which gate it belongs to.
 *
 * ## What the design pass changed
 *
 * Tokens from `globals.css` and the shared `NOTICE_TONES` palette replace the hardcoded
 * slate/emerald/amber literals and this file's private copy of that table — two tables
 * describing the same four states is where a design language starts to drift. Three
 * honesty problems fixed on the way through:
 *
 * - **It printed its own `<h1>`**, which the app shell already renders from the nav list.
 * - **A status this build does not know rendered as "nobody has asked them yet".**
 *   `MessagingConsentOut.status` is a bare `string`, so `none` (a real state: nobody ever
 *   asked, and a 200) shared a branch with every member the API might grow. Those are
 *   different sentences — one is a fact about the person, the other is a fact about our
 *   build — and the second one now says so and shows the value, so support can act on it.
 * - **The lookup mutation was named `lookup`**, shadowing the `lookup()` this file
 *   imports for its wire-string reads. The one call site that needed the import was at
 *   module scope, so it worked — and would have stopped working the moment anyone needed
 *   a copy-table read inside the component, in a way that reads as a typo.
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

// Form controls come from ui.tsx's FIELD_INLINE / FIELD_INLINE_ICON (see the note on
// the do-not-call screen — the local trio both screens carried is hoisted, MC-2).

export default function MessagingConsentPage() {
  const session = useClientSession();

  const consentLookup = useLookupMessagingConsent(session);
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
  /* Two forms on this screen, two instances: one refusal must never mark the other's
     field, and the ids the hook mints are per instance. */
  const lookupValid = useFormValidation();
  const recordValid = useFormValidation();

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

  /*
   * THIS SCREEN, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * ## The two phone boxes leave as placeholders, and neither is writable
   *
   * Both hold a customer's number (D-127 G-2), so both are `personal: "phone"`. Neither
   * is fillable, and here that is the compliance rule rather than caution: recording a
   * consent is a statement that a NAMED PERSON said something, and an assistant that
   * could put a number in that box could manufacture an opt-in against somebody who
   * never gave one. The same argument bars the CALL ID, which is the evidence tying the
   * statement to the conversation it was made in.
   *
   * ## What IS fillable is the shape of the answer
   *
   * Yes-or-no, which source, and — on a "no" — which withdrawal status. Those are three
   * enums describing an answer a person in front of the form already has, they are the
   * part people get wrong, and none of them is a record until Save is pressed. The source
   * list offered is `sourceOptions`, the SAME narrowing the form renders from, so the
   * assistant cannot pick a source that cannot carry the answer being given.
   *
   * The EVIDENCE fields are not declared at all: they are per-source free text ("where in
   * the call", "document reference") and are exactly the place a caller's own words would
   * land.
   */
  useCopilotSurface({
    route: "/c/{slug}/messaging-consent",
    title: "Messaging consent",
    realm: "client",
    fields: [
      {
        id: "consent-lookup-phone",
        label: "Number being looked up",
        type: "text",
        value: lookupPhone,
        writable: false,
        personal: "phone",
        help: "Typed by the reader; the assistant is told whether the box is filled in, never what is in it.",
      },
      {
        id: "consent-phone",
        label: "Number the answer is being recorded against",
        type: "text",
        value: phone,
        writable: false,
        personal: "phone",
      },
      {
        id: "consent-answer",
        label: "Did the customer agree to be messaged?",
        type: "select",
        value: answer,
        options: [
          { value: "yes", label: "Yes — they agreed" },
          { value: "no", label: "No — they did not, or they withdrew" },
        ],
      },
      {
        id: "consent-status",
        label: "How the consent ended, when the answer is no",
        type: "select",
        value: status,
        options: NO_STATUSES.map((value) => ({ value, label: STATUS_COPY[value].label })),
        help: "Ignored while the answer is yes — a yes is always recorded as granted.",
      },
      {
        id: "consent-source",
        label: "How they said it",
        type: "select",
        value: source,
        options: sourceOptions.map((value) => ({ value, label: CONSENT_SOURCES[value].label })),
      },
      {
        id: "consent-call-id",
        label: "Call the statement was made on",
        type: "text",
        value: callId,
        writable: false,
        help: "The evidence tying the consent to the conversation. A person supplies it, from the call log.",
      },
    ],
    facts: [
      {
        key: "status_to_be_recorded",
        label: "What pressing Save would record",
        value: effectiveStatus,
      },
      {
        key: "call_id_required",
        label: "Does the chosen source need a call id?",
        value: spec.requiresCallId ? "yes" : "no",
      },
      {
        key: "blocked",
        label: "Is anything stopping this being recorded as a yes?",
        value: blocked ?? "no",
      },
      {
        key: "lookup_answered",
        label: "Is there a lookup verdict on screen?",
        value: consentLookup.data ? "yes — the reader can see it" : "no",
      },
      {
        key: "may_record",
        label: "May this session record what a customer said?",
        value: write.allowed ? "yes" : `no — ${write.reason ?? "no reason given"}`,
      },
    ],
    apply: (items) => {
      for (const item of items) {
        const value = asText(item.value);
        if (item.field_id === "consent-answer" && (value === "yes" || value === "no")) {
          chooseAnswer(value);
        } else if (item.field_id === "consent-source") {
          const next = sourceOptions.find((option) => option === value);
          if (next !== undefined) chooseSource(next);
        } else if (item.field_id === "consent-status") {
          const next = NO_STATUSES.find((option) => option === value);
          if (next !== undefined) setStatus(next);
        }
      }
    },
  });

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
          consentLookup.reset();
        },
      },
    );
  };

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Who has agreed to receive WhatsApp messages from you. Campaign follow-ups are
        only sent to people recorded here — and this is a separate permission from
        calling, which is governed by the do-not-call list.
      </p>

      <RestrictionNote reason={write.reason} />

      {/* The question people actually arrive with, and the one thing everyone with
          access to the account may do. */}
      <Card title="Can we message this number?">
        <p className="text-sm text-ink-muted">
          Asks the same question the system asks itself before it sends a follow-up, so
          the answer cannot disagree with what actually happens.
        </p>
        <form
          className="mt-3 flex flex-wrap items-center gap-2"
          noValidate
          onSubmit={lookupValid.onSubmit(() => {
            consentLookup.mutate(lookupPhone.trim());
          })}
        >
          {/* `min-w-0`: this wrapper is a flex item, and a flex item defaults to
              `min-width: auto` — so it took the search input's intrinsic ~256px width
              and would not shrink into the 254px row at 320px. The input's own
              `max-w-full` can only cap it once the wrapper is allowed to give. */}
          <div className="relative min-w-0">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
            <input
              {...lookupValid.field("lookupPhone", "Enter the number to check.")}
              required
              value={lookupPhone}
              onChange={(e) => {
                setLookupPhone(e.target.value);
                // A stale verdict beside a changed number is worse than no verdict.
                // (TanStack Query v5 `reset()` clears mutation state —
                // tanstack.com/query/v5/docs/framework/react/reference/useMutation)
                consentLookup.reset();
              }}
              minLength={8}
              maxLength={20}
              inputMode="tel"
              autoComplete="off"
              placeholder="9876543210 or +919876543210"
              aria-label="Phone number to check"
              className={`${FIELD_INLINE_ICON} w-64 font-mono`}
            />
            {lookupValid.error("lookupPhone")}
          </div>
          <button
            type="submit"
            /* The length rule is not repeated here — a button that is dead at seven
               digits explains nothing, and pressing it now says what is wrong. */
            disabled={consentLookup.isPending}
            className={PRIMARY_BUTTON_SM}
          >
            {consentLookup.isPending ? "Checking…" : "Check"}
          </button>
        </form>

        {/* A failed lookup is a refusal and nothing else. Every verdict this box can
            render is a claim about a PERSON's wishes; none of them may be printed on the
            strength of a request that never landed. */}
        {consentLookup.error != null && (
          <div className="mt-3">
            <ProblemNotice error={consentLookup.error} />
          </div>
        )}
        {consentLookup.data && (
          <div className="mt-3">
            <Verdict state={consentLookup.data} />
          </div>
        )}
      </Card>

      {write.allowed && (
        <Card title="Record what a customer said">
          <p className="text-sm text-ink-muted">
            Every record is kept — nothing here is edited or deleted. If someone changes
            their mind, record the new answer and it replaces the old one from that
            moment.
          </p>

          <form
            className="mt-4 space-y-4"
            noValidate
            onSubmit={recordValid.onSubmit(submit)}
          >
            <Field label="Their number" htmlFor="consent-phone">
              <input
                {...recordValid.field("phone", "Enter their number.")}
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
                className={`${FIELD_INLINE} w-64 font-mono`}
              />
              {recordValid.error("phone")}
            </Field>

            {/* The answer first: it is what decides which sources may carry it. */}
            <fieldset>
              <legend className="text-sm font-medium text-ink">What did they say?</legend>
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
              <p className="mt-2 text-xs text-ink-muted">
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
                  className={FIELD_INLINE}
                >
                  {NO_STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {STATUS_COPY[value].label}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-ink-muted">{STATUS_COPY[status].hint}</p>
              </Field>
            )}

            <Field label="How do you know?" htmlFor="consent-source">
              <select
                id="consent-source"
                value={source}
                onChange={(e) => chooseSource(e.target.value as ConsentSource)}
                className={`${FIELD_INLINE} w-full max-w-md`}
              >
                {sourceOptions.map((value) => (
                  <option key={value} value={value}>
                    {CONSENT_SOURCES[value].label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-ink-muted">{spec.hint}</p>
              {/* Said once, where someone would otherwise go looking for the missing
                  option: your own staff cannot assert an opt-in on a customer's behalf. */}
              {answer === "yes" && (
                <p className="mt-1 text-xs text-ink-muted">
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
                  className={`${FIELD_INLINE} w-full max-w-md font-mono`}
                />
                <p className="mt-1 text-xs text-ink-muted">
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
                  className={`${FIELD_INLINE} w-full max-w-md`}
                />
                <p className="mt-1 text-xs text-ink-muted">
                  {field.hint}
                  {answer === "no" && " Optional here."}
                </p>
              </Field>
            ))}

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                /* `blocked` stays: it is a rule about WHAT may be recorded, not about
                   an answer this form can point at. The length rule is answered at the
                   field now. */
                disabled={record.isPending || blocked !== null}
                className={PRIMARY_BUTTON_SM}
              >
                <BadgeCheck className="h-4 w-4" />
                {record.isPending
                  ? "Recording…"
                  : answer === "yes"
                    ? "Record their opt-in"
                    : "Record their refusal"}
              </button>
              {/* The refusal, given before the click rather than as a 422 after it. */}
              {blocked && (
                <span className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
                  <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
                  {blocked}
                </span>
              )}
            </div>
          </form>

          {record.error != null && (
            <div className="mt-3">
              <ProblemNotice error={record.error} />
            </div>
          )}
          {record.data && (
            <div className="mt-4">
              <p className="mb-2 text-sm font-medium text-ink">
                Recorded. This is where that number now stands:
              </p>
              <Verdict state={record.data} />
            </div>
          )}
        </Card>
      )}

      <Card title="How this record works">
        <ul className="space-y-3 text-sm text-ink-muted">
          <Rule
            icon={<CalendarClock className="h-4 w-4" />}
            title={`An opt-in lasts ${CONSENT_VALIDITY_DAYS} days.`}
          >
            After that it stops authorising messages and someone has to ask again. A
            check above will say so rather than quietly failing on the day it lapses.
          </Rule>
          <Rule icon={<FileSearch className="h-4 w-4" />} title="Nothing is ever deleted.">
            Recording a refusal adds a new entry that supersedes the earlier one, so the
            history of what someone agreed to — and when — stays intact.
          </Rule>
          <Rule
            icon={<PhoneOff className="h-4 w-4" />}
            title="Agreeing to a call is not agreeing to a message."
          >
            Someone who asked to be called back has not opted in to WhatsApp, and
            nothing here fills that in for them. It is a separate purpose, and nothing
            backfills it from your campaign lists or your call records.
          </Rule>
          <Rule
            icon={<ShieldAlert className="h-4 w-4" />}
            title="This is in addition to do-not-call."
          >
            A follow-up still passes the same do-not-call and calling-hours checks a
            call does; consent never replaces them.
          </Rule>
          {/* SEC-COMP §4, TCCCPR 2018 as amended (Second Amendment, 12 Feb 2025): explicit
              consent under Reg. 2(y) is recorded by the Consent Registrar on DLT through
              Digital Consent Acquisition — a registrar function we cannot perform. What
              is captured here is OUR evidence. Saying so is not a disclaimer: a client
              who believes this screen produces registrar-grade consent will use it to
              answer a regulator, and that is the sentence they will be answering with. */}
          <Rule icon={<CircleHelp className="h-4 w-4" />} title="This is your evidence, not a DLT record.">
            It is what you would produce if a number is challenged — who agreed, when,
            and on what. It is not the consent recorded on{" "}
            <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss>, which
            Indian telecom rules define separately, and it does not stand in for one.
          </Rule>
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
      <Box tone="ok" icon={<BadgeCheck className="h-4 w-4" />}>
        <p className="font-medium">You may send this person WhatsApp messages.</p>
        <p className="mt-1">
          {describeCapture(state)} This stays current until {formatIST(state.expires_at)}.
        </p>
      </Box>
    );
  }

  if (state.status === "granted") {
    return (
      <Box tone="warn" icon={<CalendarClock className="h-4 w-4" />}>
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
      <Box tone="stop" icon={<MessageSquareOff className="h-4 w-4" />}>
        <p className="font-medium">
          {state.status === "withdrawn"
            ? "Not messageable — they asked us to stop."
            : "Not messageable — they were asked and said no."}
        </p>
        <p className="mt-1">{describeCapture(state)}</p>
      </Box>
    );
  }

  // `status: "none"` — nobody has ever asked this person. A 200 and the normal state of
  // the world, not a 404 and not an error (MessagingConsentOut says so in its docstring),
  // so it is neutral in tone and still a no.
  if (state.status === "none") {
    return (
      <Box tone="neutral" icon={<CircleHelp className="h-4 w-4" />}>
        <p className="font-medium">Not messageable — nobody has asked them yet.</p>
        <p className="mt-1">
          Campaign follow-ups will skip this number until someone records what they said.
          Recording it needs the customer&apos;s own answer, not an assumption.
        </p>
      </Box>
    );
  }

  /* Any status this build predates. `MessagingConsentOut.status` is a bare `string`, so
     the API can grow a member without this file changing — and "nobody has asked them
     yet" would then be a confident, wrong sentence about a person whose record we simply
     cannot read. The verdict is unaffected (it comes from `messageable`, which is false
     here); what changes is that the screen stops explaining a record it does not
     understand, and shows the value so support can. */
  return (
    <Box tone="neutral" icon={<CircleHelp className="h-4 w-4" />}>
      <p className="font-medium">Not messageable — this record is one we cannot read.</p>
      <p className="mt-1">
        The system will not message this number. Quote{" "}
        <MonoValue className="text-xs">{state.status}</MonoValue> to us and we will
        explain what it means.
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

/**
 * The verdict box. Palette from `NOTICE_TONES` (ui.tsx) — the four states this product
 * already has words for — rather than a fifth private copy of the same four colours.
 */
function Box({
  tone,
  icon,
  children,
}: {
  tone: NoticeTone;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${NOTICE_TONES[tone]}`}>
      <span className="mt-0.5 shrink-0" aria-hidden>
        {icon}
      </span>
      <div>{children}</div>
    </div>
  );
}

function Rule({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <li className="flex items-start gap-3">
      <span
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
        aria-hidden
      >
        {icon}
      </span>
      <span>
        <span className="font-medium text-ink">{title}</span> {children}
      </span>
    </li>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="text-sm font-medium text-ink">
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
  /*
   * WCAG 2.4.7 Focus Visible (AA), failure technique F78 — the same fix, and the same
   * reasoning, as `components/llmModelPicker.tsx`'s model rows, which is where it is
   * written out in full. The input below is `sr-only`, so the browser's own ring is gone
   * and the label styled only `checked` and `hover`: a keyboard user could not see which
   * of "Agreed" / "Refused" they were on.
   *
   * This one is 🔒 compliance-visible. The record this radio produces is the client's
   * evidence under TCCCPR that a person agreed to be messaged — the screen says so — so a
   * keyboard user unable to see which answer is focused is a keyboard user who can record
   * the wrong one about a real person.
   */
  const FOCUS_RING =
    "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app";
  return (
    <label
      className={
        checked
          ? `cursor-pointer rounded-md border border-brand-strong bg-brand-strong px-3 py-1.5 text-sm font-semibold text-white ${FOCUS_RING}`
          : `cursor-pointer rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5 ${FOCUS_RING}`
      }
    >
      <input type="radio" name={name} checked={checked} onChange={onChange} className="sr-only" />
      {label}
    </label>
  );
}
