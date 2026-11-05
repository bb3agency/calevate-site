"use client";

import Link from "next/link";
import { useState, type FormEvent, type ReactNode } from "react";
import { CalendarClock, PhoneForwarded, PhoneOutgoing, Wallet } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Field } from "@/components/arc/field";
import { useCallbackWhen } from "@/components/calls/followUpActions";
import { PageHeader } from "@/components/console/pageHeader";
import { TEXT_ACTION } from "@/components/console/section";
import { SegmentedControl } from "@/components/interior/segmented-control";
import {
  FIELD,
  FIELD_HINT,
  MonoValue,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
  formatPhone,
} from "@/components/ui";
import { canDialOut } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import { useBusinessCopy } from "@/lib/api/businessCopy";
import { useCancelCallback } from "@/lib/api/callbacks";
import { ApiProblem } from "@/lib/api/client";
import { useCall, useCallbackEligibility } from "@/lib/api/hooks";
import { useLead } from "@/lib/api/leads";
import {
  DETAILS_MAX,
  NAME_MAX,
  REASON_MAX,
  useMakeCall,
  type OneCallInput,
  type OneCallResult,
} from "@/lib/api/oneCall";
import { useClientRealm } from "@/lib/api/session";

import { CallStatusCard } from "./CallStatusCard";
import { RecentOneCalls } from "./RecentOneCalls";

/**
 * MAKE A CALL — the one form for one call to one person (founder, 5 Nov 2026).
 *
 * PRIMARY JOB: have an agent ring one person, now or at a time, and watch it happen.
 *
 * - Who, which agent, why, when; one column, labels above, the primary button names the act
 *   ("Call now" / "Book the call"). A lead's or a call's Call button arrives pre-filled and
 *   shows the person instead of the number field.
 * - Only agents that can place calls are offered (`canDialOut`), the first chosen.
 * - Every refusal is the server's own sentence (the dial gate), never a paraphrase, plus the
 *   one thing it cannot say: where to fix a money refusal, and the next allowed time as a
 *   button when calling hours are the reason.
 * - After "Call now", the live card follows the call to its end and links to it.
 */

type When = "now" | "later";

const WHEN_OPTIONS = [
  { value: "now", label: "Now" },
  { value: "later", label: "At a time" },
];

/** The refusals whose fix is on the billing screen; every other carries its own remedy. */
const MONEY_RULES = new Set(["no_credits", "spend_cap"]);

export function MakeCallScreen({
  leadId,
  callId,
  agentId,
  later = false,
}: {
  leadId?: string;
  callId?: string;
  agentId?: string;
  later?: boolean;
}) {
  const { session, href } = useClientRealm();
  const agents = useAgents(session);
  const lead = useLead(session, callId ? "" : (leadId ?? ""));
  const call = useCall(session, callId ?? "");
  const eligibility = useCallbackEligibility(session, callId ?? "");
  const copy = useBusinessCopy(session);
  const make = useMakeCall(session);
  const feedback = useActionFeedback(make, { errorDisplay: "inline" });
  const when = useCallbackWhen();

  const dialers = agents.data?.filter(canDialOut) ?? [];
  const [chosenAgent, setChosenAgent] = useState(agentId ?? "");
  const agent = dialers.find((a) => a.id === chosenAgent) ?? dialers[0];
  const [mode, setMode] = useState<When>(later ? "later" : "now");
  const [byNumber, setByNumber] = useState(!leadId && !callId);
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [details, setDetails] = useState("");
  const [tried, setTried] = useState(false);
  const [result, setResult] = useState<OneCallResult | null>(null);

  const fromCall = Boolean(callId) && !byNumber;
  const fromLead = Boolean(leadId) && !callId && !byNumber;
  const example = copy.data?.placeholders?.outbound_purpose?.trim() || null;

  const phoneError = tried && byNumber && !phone.trim() ? "Enter the number to call." : null;
  const reasonError = tried && !fromCall && !reason.trim() ? "Say why you are calling, in one line." : null;
  const serverFieldError = (field: string): string | null => {
    const problem = make.error instanceof ApiProblem ? make.error : null;
    // The server names the field; its sentence (`message`, the problem's `detail`) is shown there.
    return problem?.fields?.some((f) => f.field === field) ? problem.message : null;
  };

  const input = (at?: string): OneCallInput | null => {
    const base: OneCallInput = fromCall
      ? { call_id: callId }
      : {
          ...(fromLead ? { lead_id: leadId } : { phone: phone.trim(), name: name.trim() || null }),
          agent_id: agent?.id ?? null,
          reason: reason.trim(),
          details: details.trim() || null,
        };
    return at ? { ...base, at } : base;
  };

  const send = (body: OneCallInput) => {
    setResult(null);
    make.mutate(body, { onSuccess: (out) => setResult(out) });
  };

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    setTried(true);
    if ((byNumber && !phone.trim()) || (!fromCall && !reason.trim()) || (!fromCall && !agent)) return;
    if (mode === "later") {
      const at = when.check();
      if (!at) return;
      const body = input(at);
      if (body) send(body);
      return;
    }
    const body = input();
    if (body) send(body);
  };

  const startOver = () => {
    make.reset();
    setResult(null);
    setTried(false);
    setPhone("");
    setName("");
    setReason("");
    setDetails("");
    setByNumber(true);
    setMode("now");
  };

  const cantCallBack = fromCall && mode === "now" && eligibility.data && !eligibility.data.eligible;
  const noDialer = !fromCall && agents.data !== undefined && dialers.length === 0;
  const busy = make.isPending;
  const placed = result?.status === "queued" && result.call_id ? result.call_id : null;

  return (
    <div className="space-y-6">
      <PageHeader description="Have an agent call one person, now or at a time you pick." />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,34rem)_minmax(0,1fr)] lg:items-start">
        {placed ? (
          // The call just placed takes the form's place: one thing to watch, where the
          // press was, and the way to the next call under it.
          <CallStatusCard callId={placed} followUpNumber={result?.follow_up_number} onAnother={startOver} />
        ) : (
        <section aria-labelledby="make-call-form" className="rounded-lg border border-line bg-surface p-4 sm:p-6">
          <h2 id="make-call-form" className="sr-only">
            Call details
          </h2>
          {result?.status === "scheduled" ? (
            <Booked result={result} onAnother={startOver} />
          ) : (
            <form noValidate onSubmit={submit} className="space-y-5">
              <Who
                fromCall={fromCall}
                fromLead={fromLead}
                lead={lead}
                call={call}
                onChange={() => {
                  setByNumber(true);
                  make.reset();
                  setResult(null);
                }}
                numberFields={
                  <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                    <Field
                      label="Phone number"
                      hint="10-digit mobile, or start with +"
                      error={phoneError ?? serverFieldError("phone")}
                    >
                      {(control) => (
                        <div className="relative">
                          <span
                            aria-hidden
                            className="pointer-events-none absolute inset-y-0 left-3 mt-1 flex items-center text-sm text-ink-muted"
                          >
                            +91
                          </span>
                          <input
                            {...control}
                            type="tel"
                            inputMode="tel"
                            autoComplete="tel-national"
                            value={phone}
                            maxLength={20}
                            onChange={(event) => setPhone(event.target.value)}
                            className={`${FIELD} pl-11 tabular-nums`}
                          />
                        </div>
                      )}
                    </Field>
                    <Field label="Name (optional)" hint="Your agent greets them by it.">
                      {(control) => (
                        <input
                          {...control}
                          value={name}
                          maxLength={NAME_MAX}
                          autoComplete="off"
                          onChange={(event) => setName(event.target.value)}
                          className={FIELD}
                        />
                      )}
                    </Field>
                  </div>
                }
              />

              {fromCall ? null : agents.isLoading ? (
                <Skeleton rows={1} label="Loading your agents" />
              ) : agents.error != null ? (
                <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} />
              ) : noDialer ? (
                <NoticeBox tone="warn">
                  No agent can place calls yet.{" "}
                  <Link href={href(`/c/${session.orgSlug}/agents`)} className={TEXT_ACTION}>
                    Set one up
                  </Link>
                </NoticeBox>
              ) : (
                <Field label="Agent" hint={dialers.length === 1 ? "Your agent that places calls." : undefined}>
                  {(control) => (
                    <select
                      {...control}
                      value={agent?.id ?? ""}
                      onChange={(event) => setChosenAgent(event.target.value)}
                      className={FIELD}
                    >
                      {dialers.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
              )}

              {fromCall ? (
                <p className="text-body text-ink-muted">Your agent picks up where the last call stopped.</p>
              ) : (
                <>
                  <Field
                    label="Why are you calling?"
                    hint={example ? `Your agent tells them. For example: ${example}` : "Your agent tells them. One line."}
                    error={reasonError ?? serverFieldError("reason")}
                  >
                    {(control) => (
                      <input
                        {...control}
                        value={reason}
                        maxLength={REASON_MAX}
                        onChange={(event) => setReason(event.target.value)}
                        className={FIELD}
                      />
                    )}
                  </Field>
                  <Field label="Anything else your agent should know? (optional)">
                    {(control) => (
                      <textarea
                        {...control}
                        value={details}
                        rows={2}
                        maxLength={DETAILS_MAX}
                        onChange={(event) => setDetails(event.target.value)}
                        className={FIELD}
                      />
                    )}
                  </Field>
                </>
              )}

              <div className="space-y-3">
                <SegmentedControl
                  label="When to call"
                  options={WHEN_OPTIONS}
                  value={mode}
                  onValueChange={(value) => setMode(value === "later" ? "later" : "now")}
                />
                {mode === "later" ? (
                  <>
                    {when.fields}
                    <span className={FIELD_HINT}>9 am to 9 pm India time, within 30 days.</span>
                  </>
                ) : null}
              </div>

              {cantCallBack && eligibility.data?.reason ? (
                <NoticeBox tone="warn" role="status">
                  {eligibility.data.reason}
                </NoticeBox>
              ) : null}

              {result?.status === "blocked" ? (
                <Refusal
                  result={result}
                  busy={busy}
                  onBookAt={(at) => {
                    const body = input(at);
                    if (body) send(body);
                  }}
                />
              ) : null}
              <ProblemNotice error={make.error} shownAtField={["phone", "reason"]} />

              <div className="flex flex-col gap-2 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-meta text-ink-muted">Do-not-call, calling hours and credit are checked first.</p>
                <ActionButton
                  type="submit"
                  status={result?.status === "blocked" ? "idle" : feedback.status}
                  pendingLabel={mode === "now" ? "Calling…" : "Booking…"}
                  successLabel={mode === "now" ? "Calling" : "Booked"}
                  disabled={busy || noDialer || Boolean(cantCallBack)}
                  className="justify-center max-sm:w-full"
                >
                  {mode === "now" ? (
                    <PhoneOutgoing aria-hidden className="h-4 w-4" />
                  ) : (
                    <CalendarClock aria-hidden className="h-4 w-4" />
                  )}
                  {mode === "now" ? "Call now" : "Book the call"}
                </ActionButton>
              </div>
            </form>
          )}
        </section>
        )}

        <RecentOneCalls />
      </div>
    </div>
  );
}

/** Who the call is to: the number fields, or the person a lead or a call named. */
function Who({
  fromCall,
  fromLead,
  lead,
  call,
  onChange,
  numberFields,
}: {
  fromCall: boolean;
  fromLead: boolean;
  lead: ReturnType<typeof useLead>;
  call: ReturnType<typeof useCall>;
  onChange: () => void;
  numberFields: ReactNode;
}) {
  if (!fromCall && !fromLead) return <>{numberFields}</>;
  const read = fromCall ? call : lead;
  if (read.isLoading) return <Skeleton rows={1} label="Loading who to call" />;
  if (read.error != null || !read.data) {
    return (
      <div className="space-y-2">
        <ProblemNotice error={read.error ?? new Error("We could not find this person.")} onRetry={() => void read.refetch()} />
        <button type="button" onClick={onChange} className={SECONDARY_BUTTON_SM}>
          Enter a number instead
        </button>
      </div>
    );
  }
  const who = fromCall
    ? { name: call.data?.lead_name ?? null, phone: call.data?.caller_e164 ?? null }
    : { name: lead.data?.name ?? null, phone: lead.data?.phone_e164 ?? null };
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border border-line px-3 py-2.5">
      <div className="min-w-0">
        <p className="text-meta text-ink-muted">{fromCall ? "Calling back" : "Calling"}</p>
        <p className="break-words text-body font-medium text-ink">{who.name?.trim() || formatPhone(who.phone)}</p>
        {who.name?.trim() && who.phone ? (
          <MonoValue className="text-meta tabular-nums text-ink-muted">{formatPhone(who.phone)}</MonoValue>
        ) : null}
      </div>
      <button type="button" onClick={onChange} className={`${SECONDARY_BUTTON_SM} shrink-0`}>
        Someone else
      </button>
    </div>
  );
}

/** The gate's refusal in its own words, plus the one thing it cannot say: where to act. */
function Refusal({
  result,
  busy,
  onBookAt,
}: {
  result: OneCallResult;
  busy: boolean;
  onBookAt: (at: string) => void;
}) {
  const { session, href } = useClientRealm();
  return (
    <NoticeBox tone="warn" role="status">
      <span className="block">{result.blocked_reason ?? "This call was not allowed."}</span>
      {result.opens_at ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => result.opens_at && onBookAt(result.opens_at)}
          className={`${SECONDARY_BUTTON_SM} mt-2`}
        >
          <CalendarClock aria-hidden className="h-3.5 w-3.5" />
          Book it for {formatIST(result.opens_at)}
        </button>
      ) : null}
      {result.blocked_rule && MONEY_RULES.has(result.blocked_rule) ? (
        <Link href={href(`/c/${session.orgSlug}/billing`)} className={`${SECONDARY_BUTTON_SM} mt-2`}>
          <Wallet aria-hidden className="h-3.5 w-3.5" />
          {result.blocked_rule === "no_credits" ? "Add credit" : "See your limit"}
        </Link>
      ) : null}
    </NoticeBox>
  );
}

/** A call booked for later, with the way to call it off (its undo) and to the next call. */
function Booked({ result, onAnother }: { result: OneCallResult; onAnother: () => void }) {
  const { session } = useClientRealm();
  const cancel = useCancelCallback(session);
  const cancelled = cancel.isSuccess;
  return (
    <div className="space-y-4" role="status">
      <NoticeBox tone={cancelled ? "neutral" : "ok"}>
        {cancelled
          ? "Called off. Nobody will ring them for it."
          : `${result.rescheduled ? "Moved to" : "Booked for"} ${formatIST(result.requested_at)}.`}
      </NoticeBox>
      <ProblemNotice error={cancel.error} />
      <div className="flex flex-wrap gap-2">
        {!cancelled && result.callback_id ? (
          <button
            type="button"
            disabled={cancel.isPending}
            onClick={() => result.callback_id && cancel.mutate(result.callback_id)}
            className={SECONDARY_BUTTON}
          >
            {cancel.isPending ? "Calling off…" : "Call it off"}
          </button>
        ) : null}
        <button type="button" onClick={onAnother} className={SECONDARY_BUTTON}>
          <PhoneForwarded aria-hidden className="h-4 w-4" />
          Make another call
        </button>
      </div>
    </div>
  );
}
