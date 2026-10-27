"use client";

/**
 * THE FOUR FOLLOW-UP ACTIONS on a call or a lead (founder, 24 Oct 2026; D-869): call them
 * now, mark it, call them back later, send a WhatsApp follow-up. One hook builds them, so
 * the phone swipe (`SwipeActions`), the desktop ⋯ menu (`RowMenu`) and a record's header
 * (`ButtonGroup`) all run the same code with the same checks and the same feedback.
 *
 * Which one is primary (swipe right): calling them. On both lists the reason a person opens
 * a row from a phone is to get back to the caller, so the one-swipe action is the call; it
 * still asks first, because it rings somebody's phone. Everything else is swipe left.
 *
 * What each action answers with:
 * - Call now: a confirmation naming who rings whom, then "Calling now" or the server's
 *   refusal (a `blocked` result is an answer, shown in the dialog, never an error toast).
 * - Mark: a short choice. The change is undone from its toast by sending the previous value
 *   with the new one as the expected value, so a colleague's later change is never
 *   overwritten; a 409 says exactly that and the list refreshes.
 * - Call back later: a day and a time between 9am and 9pm India time. Undo cancels it.
 * - WhatsApp: the server says first whether a message may be sent and which approved
 *   messages there are; when it may not, its reason is the whole answer.
 * Calls and messages are never offered an Undo: they have already left.
 */

import { useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Clock, MessageCircle, PhoneOutgoing, Tag } from "lucide-react";

import { ActionButton, problemToast, useActionFeedback } from "@/components/arc/feedback";
import type { GroupAction } from "@/components/arc/button-group";
import type { MenuItem } from "@/components/arc/menu";
import type { SwipeAction } from "@/components/arc/swipe-actions";
import { useToast } from "@/components/arc/toast";
import { Field } from "@/components/arc/field";
import { DatePicker } from "@/components/arc/calendar";
import { RadioGroup } from "@/components/arc/radio-group";
import { addDays, todayIST, type ISODate } from "@/components/arc/ist-dates";
import { ConfirmDialog } from "@/components/confirmDialog";
import { ModalDialog } from "@/components/modalDialog";
import {
  FIELD,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
  formatIST,
  formatPhone,
} from "@/components/ui";
import { ApiProblem, type CallLeadResult, type Session } from "@/lib/api/client";
import { useCancelCallback } from "@/lib/api/callbacks";
import { useCallLead, useWriteAccess } from "@/lib/api/hooks";
import {
  SWIPE_LEAD_STATUS,
  useMarkCallFollowUp,
  useMarkLeadStatus,
  useScheduleCallback,
  useSendWhatsApp,
  useWhatsAppOptions,
  type CallFollowUpState,
  type LeadStatus,
} from "@/lib/api/swipe";

/** One row or record the actions are about. */
export type FollowUpTarget = {
  /** The row's own id: the call's on the call log, the lead's on the leads list. */
  key: string;
  /** Who, as the row shows them: a name, or the number. */
  name: string;
  phone?: string | null;
  /** Calls, call-backs and messages are about a lead; a call with none cannot have them. */
  leadId: string | null;
  /** Present on a call: "Mark" then sets the call's follow-up mark. */
  callId?: string;
  followUpState?: CallFollowUpState | null;
  /** Present on a lead: "Mark" then sets the lead's stage. */
  leadStatus?: string;
  /** The agent that handled the call, preferred for calling back when it places calls. */
  agentId?: string | null;
};

export type Dialer = { id: string; name: string };

/** The swipe's three lead outcomes, in the order offered. Follow-up is stored as `interested`. */
const LEAD_MARKS: { status: LeadStatus; label: string; hint: string }[] = [
  { status: SWIPE_LEAD_STATUS.won, label: "Won", hint: "They bought or booked." },
  { status: SWIPE_LEAD_STATUS.lost, label: "Lost", hint: "They are not going ahead." },
  { status: SWIPE_LEAD_STATUS.followUp, label: "Follow up", hint: "Still interested. Shown as Interested in the list." },
];

const CALL_MARKS: { state: CallFollowUpState | null; label: string; hint: string }[] = [
  { state: "resolved", label: "Done", hint: "Nothing more to do on this call." },
  { state: "needs_you", label: "Needs you", hint: "Someone should look at this call." },
  { state: null, label: "No mark", hint: "Take the mark off." },
];

export function followUpWords(state: string | null | undefined): string | null {
  if (state === "resolved") return "Marked done";
  if (state === "needs_you") return "Marked: needs you";
  return null;
}

function leadMarkWords(status: string): string {
  return LEAD_MARKS.find((m) => m.status === status)?.label ?? status.charAt(0).toUpperCase() + status.slice(1);
}

function callMarkWords(state: CallFollowUpState | null): string {
  return CALL_MARKS.find((m) => m.state === state)?.label ?? "No mark";
}

// --- the time a call-back may be booked for -----------------------------------------------

/** The window and step the server accepts (`crm/swipe.check_schedule_time`): 09:00 to 21:00 IST. */
const OPENS_MIN = 9 * 60;
const CLOSES_MIN = 21 * 60;
const STEP_MIN = 15;
/** The server wants at least two minutes; a slot this close is gone before the form is sent. */
const SOONEST_MIN = 10;
const MAX_DAYS_AHEAD = 30;

/** Minutes since midnight India time, now. IST has no daylight saving, so a fixed offset is exact. */
function istMinutesNow(): number {
  const ist = new Date(Date.now() + 330 * 60_000);
  return ist.getUTCHours() * 60 + ist.getUTCMinutes();
}

function hhmm(minutes: number): string {
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

function slotLabel(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  const suffix = h < 12 ? "am" : "pm";
  const twelve = h % 12 === 0 ? 12 : h % 12;
  return `${twelve}:${String(m).padStart(2, "0")} ${suffix}`;
}

/** Every bookable slot on `day`, India time; today's start a little after now. */
export function callbackSlots(day: ISODate, today: ISODate = todayIST(), nowMin: number = istMinutesNow()): number[] {
  const out: number[] = [];
  const earliest = day === today ? nowMin + SOONEST_MIN : OPENS_MIN;
  for (let m = OPENS_MIN; m < CLOSES_MIN; m += STEP_MIN) if (m >= earliest) out.push(m);
  return out;
}

/** The first sensible choice: a slot later today, or 10am tomorrow once today has closed. */
export function defaultCallbackSlot(today: ISODate = todayIST(), nowMin: number = istMinutesNow()) {
  const later = callbackSlots(today, today, nowMin);
  if (later.length > 0) return { day: today, minutes: later[0] };
  return { day: addDays(today, 1), minutes: 10 * 60 };
}

/**
 * The day and time of a call-back, offering only the slots the server accepts. `check()`
 * shows what is missing and returns the instant (`…+05:30`) or null; `fields` is the pair
 * of controls, side by side from `sm`. Shared by "Call back later" and the Call-backs
 * screen's Move, so both offer the same times.
 */
export function useCallbackWhen(): { fields: ReactNode; check: () => string | null } {
  const today = todayIST();
  const [initial] = useState(() => defaultCallbackSlot(today));
  const [day, setDay] = useState<ISODate | null>(initial.day);
  const [minutes, setMinutes] = useState<number>(initial.minutes);
  const [tried, setTried] = useState(false);
  const slots = day ? callbackSlots(day, today) : [];
  const chosen = slots.includes(minutes) ? minutes : (slots[0] ?? null);
  const dayError =
    tried && !day
      ? "Choose the day to call back."
      : tried && day && chosen === null
        ? "There is no time left today between 9am and 9pm. Choose another day."
        : null;
  const fields = (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <DatePicker
        label="Day"
        value={day}
        onChange={setDay}
        min={today}
        max={addDays(today, MAX_DAYS_AHEAD)}
        error={dayError}
      />
      <Field label="Time (India time)">
        {(control) => (
          <select
            {...control}
            value={chosen ?? ""}
            disabled={slots.length === 0}
            onChange={(event) => setMinutes(Number(event.target.value))}
            className={FIELD}
          >
            {slots.length === 0 ? <option value="">No time left that day</option> : null}
            {slots.map((slot) => (
              <option key={slot} value={slot}>
                {slotLabel(slot)}
              </option>
            ))}
          </select>
        )}
      </Field>
    </div>
  );
  return {
    fields,
    check: () => {
      setTried(true);
      return day && chosen !== null ? `${day}T${hhmm(chosen)}:00+05:30` : null;
    },
  };
}

// --- the hook -----------------------------------------------------------------------------

type Dialog =
  | { kind: "call"; target: FollowUpTarget; dialer: Dialer }
  | { kind: "mark"; target: FollowUpTarget }
  | { kind: "later"; target: FollowUpTarget }
  | { kind: "whatsapp"; target: FollowUpTarget };

type ActionSet = { primary: SwipeAction; secondary: SwipeAction[] };

export type FollowUpActions = {
  /** The swipe's actions for one row: right = primary, left = the rest. */
  actionsFor: (target: FollowUpTarget) => ActionSet;
  /** The same actions as ⋯ menu items, for a row on a desktop. */
  menuItems: (target: FollowUpTarget) => MenuItem[];
  /** The same actions for a record's header `ButtonGroup`, primary first. */
  groupActions: (target: FollowUpTarget) => GroupAction[];
  /** The last answer to "call now" for a lead on this screen, kept per lead. */
  callResult: (leadId: string) => CallLeadResult | undefined;
  /** Opens the call confirmation directly (a row's own Call button). */
  startCall: (target: FollowUpTarget) => void;
  /** Mount once, anywhere on the screen. */
  dialogs: ReactNode;
};

export function useFollowUpActions(
  session: Session,
  {
    dialerFor,
    noDialerReason = "None of your agents places calls yet. Set one up to call out first.",
    scheduleAgentId,
  }: {
    /** The agent that places a call for this row, or null when none can. */
    dialerFor: (target: FollowUpTarget) => Dialer | null;
    noDialerReason?: string;
    /** The agent a call-back is booked with; left out, the server picks the lead's own. */
    scheduleAgentId?: string;
  },
): FollowUpActions {
  const toasts = useToast();
  const client = useQueryClient();
  // The swipe hooks refresh the lists; a lead's own screen and its history are kept apart.
  const refreshLead = (leadId: string) => {
    void client.invalidateQueries({ queryKey: ["lead", session.orgSlug, leadId] });
    void client.invalidateQueries({ queryKey: ["lead-timeline", session.orgSlug, leadId] });
  };
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const close = () => setDialog(null);

  const mayWrite = useWriteAccess(session, "leads:write", "mark calls and leads");
  const mayDispatch = useWriteAccess(session, "leads:dispatch", "call a lead or book a call back");

  // --- call now ---
  const callLead = useCallLead(session);
  const [callResults, setCallResults] = useState<Record<string, CallLeadResult>>({});
  const call = useActionFeedback(callLead, {
    errorTitle: "Could not place the call",
    successToast: (result) => (result.status === "queued" ? "Calling now" : null),
    successDescription: "It shows in your call log in a moment.",
  });

  // --- mark (and its undo, kept apart so an undo's toast does not offer another undo) ---
  const conflict = (error: unknown, fallback: string, retry: () => void) => {
    if (error instanceof ApiProblem && error.status === 409) {
      // The hooks refresh the lists on settle, so the row already shows what it is now.
      toasts.toast({
        kind: "warning",
        title: "A colleague changed this first",
        description: "Nothing was changed. The list now shows what it is set to.",
      });
      return;
    }
    toasts.toast({ kind: "error", ...problemToast(error, fallback), action: { label: "Try again", onClick: retry } });
  };
  const previousLead = useRef(new Map<string, string>());

  const markLead = useMarkLeadStatus(session);
  const undoLeadMutation = useMarkLeadStatus(session);
  const leadMark = useActionFeedback(markLead, {
    errorDisplay: "inline",
    successToast: (_lead, vars) => `Marked as ${leadMarkWords(vars.status)}`,
    undo: (_lead, vars) => {
      const before = previousLead.current.get(vars.leadId);
      if (!before) return;
      runUndoLead({ leadId: vars.leadId, status: before as LeadStatus, expectedStatus: vars.status });
    },
  });
  // An undo answers in its toast alone; there is no control of its own to show it on.
  useActionFeedback(undoLeadMutation, {
    errorDisplay: "inline",
    successToast: (_lead, vars) => `Changed back to ${leadMarkWords(vars.status)}`,
  });
  const runUndoLead = (vars: { leadId: string; status: LeadStatus; expectedStatus: LeadStatus }) =>
    undoLeadMutation.mutate(vars, {
      onSettled: () => refreshLead(vars.leadId),
      onError: (error) => conflict(error, "Could not change it back", () => runUndoLead(vars)),
    });

  const markCall = useMarkCallFollowUp(session);
  const undoCallMutation = useMarkCallFollowUp(session);
  const callMark = useActionFeedback(markCall, {
    errorDisplay: "inline",
    successToast: (out) => (out.changed ? (out.state ? `${callMarkWords(out.state)}` : "Mark taken off") : null),
    successDescription: (out) => (out.changed && out.state === "resolved" ? "This call is marked done." : undefined),
    undo: (out) => runUndoCall({ callId: out.call_id, state: out.previous_state, expectedState: out.state }),
  });
  useActionFeedback(undoCallMutation, {
    errorDisplay: "inline",
    successToast: (out) => (out.state ? `Changed back to ${callMarkWords(out.state)}` : "Mark taken off again"),
  });
  const runUndoCall = (vars: { callId: string; state: CallFollowUpState | null; expectedState: CallFollowUpState | null }) =>
    undoCallMutation.mutate(vars, {
      onError: (error) => conflict(error, "Could not change it back", () => runUndoCall(vars)),
    });

  const chooseLeadMark = (target: FollowUpTarget, status: LeadStatus) => {
    if (!target.leadId) return;
    const leadId = target.leadId;
    if (target.leadStatus) previousLead.current.set(leadId, target.leadStatus);
    close();
    const vars = { leadId, status };
    markLead.mutate(vars, {
      onSettled: () => refreshLead(leadId),
      onError: (error) => conflict(error, "Could not mark this lead", () => chooseLeadMark(target, status)),
    });
  };
  const chooseCallMark = (target: FollowUpTarget, state: CallFollowUpState | null) => {
    if (!target.callId) return;
    close();
    const vars = { callId: target.callId, state };
    markCall.mutate(vars, { onError: (error) => conflict(error, "Could not mark this call", () => chooseCallMark(target, state)) });
  };

  // --- call back later; its undo cancels the booking ---
  const schedule = useScheduleCallback(session);
  const cancelMutation = useCancelCallback(session);
  const cancel = useActionFeedback(cancelMutation, {
    errorTitle: "Could not cancel the call back",
    successToast: "Call back cancelled",
  });
  const later = useActionFeedback(schedule, {
    errorDisplay: "inline",
    successToast: (out) => (out.status === "scheduled" && out.requested_at ? `Call back booked for ${formatIST(out.requested_at)}` : null),
    successDescription: (out) =>
      out.rescheduled
        ? "This moved the call back you had already booked for this person."
        : "Your agent rings them then. The do-not-call and calling-hours checks still apply at that time.",
    undo: (out) => {
      if (out.callback_id) cancel.run(out.callback_id);
    },
  });

  // --- WhatsApp ---
  const sendMutation = useSendWhatsApp(session);
  const send = useActionFeedback(sendMutation, {
    errorDisplay: "inline",
    successToast: (out) => (out.status === "sent" ? "WhatsApp message sent" : null),
  });

  // --- the actions ---
  const leadless = "No lead was saved from this call, so there is no one to contact.";
  const forTarget = (target: FollowUpTarget) => {
    const dialer = dialerFor(target);
    const callBusy = callLead.isPending && callLead.variables?.leadId === target.leadId;
    const callDisabledHint = !target.leadId
      ? leadless
      : !mayDispatch.allowed
        ? (mayDispatch.reason ?? undefined)
        : !dialer
          ? noDialerReason
          : undefined;
    const callNow: SwipeAction = {
      id: "call",
      label: target.callId ? "Call back" : "Call now",
      icon: <PhoneOutgoing className="h-4 w-4" />,
      disabled: callDisabledHint !== undefined,
      hint: callDisabledHint,
      status: callBusy ? call.status : undefined,
      onSelect: () => {
        if (target.leadId && dialer) setDialog({ kind: "call", target, dialer });
      },
    };
    const markHint = target.callId ? undefined : !target.leadId ? leadless : undefined;
    const markWrite = !mayWrite.allowed ? (mayWrite.reason ?? undefined) : markHint;
    const mark: SwipeAction = {
      id: "mark",
      label: "Mark",
      icon: <Tag className="h-4 w-4" />,
      disabled: markWrite !== undefined,
      hint: markWrite,
      status: target.callId
        ? markCall.variables?.callId === target.callId ? callMark.status : undefined
        : markLead.variables?.leadId === target.leadId ? leadMark.status : undefined,
      onSelect: () => setDialog({ kind: "mark", target }),
    };
    const dispatchHint = !target.leadId ? leadless : !mayDispatch.allowed ? (mayDispatch.reason ?? undefined) : undefined;
    const laterAction: SwipeAction = {
      id: "later",
      label: "Call back later",
      icon: <Clock className="h-4 w-4" />,
      disabled: dispatchHint !== undefined,
      hint: dispatchHint,
      onSelect: () => {
        schedule.reset();
        setDialog({ kind: "later", target });
      },
    };
    const whatsapp: SwipeAction = {
      id: "whatsapp",
      label: "WhatsApp",
      icon: <MessageCircle className="h-4 w-4" />,
      disabled: dispatchHint !== undefined,
      hint: dispatchHint,
      onSelect: () => {
        sendMutation.reset();
        setDialog({ kind: "whatsapp", target });
      },
    };
    return { callNow, mark, laterAction, whatsapp };
  };

  const actionsFor = (target: FollowUpTarget): ActionSet => {
    const a = forTarget(target);
    return { primary: a.callNow, secondary: [a.mark, a.laterAction, a.whatsapp] };
  };
  const menuItems = (target: FollowUpTarget): MenuItem[] => {
    const a = forTarget(target);
    return [a.callNow, { ...a.mark, label: target.callId ? "Mark this call" : "Mark this lead" }, a.laterAction, { ...a.whatsapp, label: "Send a WhatsApp follow-up" }].map(
      (action) => ({
        id: action.id,
        label: action.label,
        icon: action.icon,
        disabled: action.disabled || action.status === "pending",
        hint: action.hint,
        onSelect: action.onSelect,
      }),
    );
  };
  const groupActions = (target: FollowUpTarget): GroupAction[] => {
    const a = forTarget(target);
    return [a.callNow, { ...a.mark, label: target.callId ? "Mark this call" : "Mark" }, a.laterAction, { ...a.whatsapp, label: "Send WhatsApp" }].map(
      (action) => ({
        id: action.id,
        label: action.label,
        icon: action.icon,
        onSelect: action.onSelect,
        status: action.status,
        disabled: action.disabled,
        hint: action.hint,
      }),
    );
  };

  const placeCall = (target: FollowUpTarget, dialer: Dialer) => {
    if (!target.leadId) return;
    const leadId = target.leadId;
    callLead.mutate(
      { leadId, agentId: dialer.id },
      {
        onSuccess: (result) => {
          setCallResults((prev) => ({ ...prev, [leadId]: result }));
          if (result.status === "queued") close();
        },
      },
    );
  };

  const dialogs = dialog ? (
    dialog.kind === "call" ? (
      <CallDialog
        target={dialog.target}
        dialer={dialog.dialer}
        status={call.status}
        result={callLead.variables?.leadId === dialog.target.leadId ? callLead.data : undefined}
        error={callLead.variables?.leadId === dialog.target.leadId ? callLead.error : null}
        onCancel={() => {
          callLead.reset();
          close();
        }}
        onConfirm={() => placeCall(dialog.target, dialog.dialer)}
      />
    ) : dialog.kind === "mark" ? (
      <MarkDialog
        target={dialog.target}
        onClose={close}
        onLead={(status) => chooseLeadMark(dialog.target, status)}
        onCall={(state) => chooseCallMark(dialog.target, state)}
      />
    ) : dialog.kind === "later" ? (
      <LaterDialog
        target={dialog.target}
        status={later.status}
        result={schedule.data}
        error={schedule.error}
        onClose={close}
        onSubmit={(at, note) => {
          if (!dialog.target.leadId) return;
          schedule.mutate(
            { leadId: dialog.target.leadId, at, note: note || undefined, agentId: scheduleAgentId },
            {
              onSuccess: (out) => {
                if (out.status === "scheduled") close();
              },
              onSettled: () => {
                if (dialog.target.leadId) refreshLead(dialog.target.leadId);
              },
            },
          );
        }}
      />
    ) : (
      <WhatsAppDialog
        session={session}
        target={dialog.target}
        status={send.status}
        result={sendMutation.data}
        error={sendMutation.error}
        onClose={close}
        onSend={(templateId, values) => {
          if (!dialog.target.leadId) return;
          sendMutation.mutate(
            { leadId: dialog.target.leadId, templateId, values },
            {
              onSuccess: (out) => {
                if (out.status === "sent") close();
              },
              onSettled: () => {
                if (dialog.target.leadId) refreshLead(dialog.target.leadId);
              },
            },
          );
        }}
      />
    )
  ) : null;

  return {
    actionsFor,
    menuItems,
    groupActions,
    callResult: (leadId) => (Object.hasOwn(callResults, leadId) ? callResults[leadId] : undefined),
    startCall: (target) => {
      const dialer = dialerFor(target);
      if (target.leadId && dialer && mayDispatch.allowed) setDialog({ kind: "call", target, dialer });
    },
    dialogs,
  };
}

// --- the dialogs --------------------------------------------------------------------------

function CallDialog({
  target,
  dialer,
  status,
  result,
  error,
  onCancel,
  onConfirm,
}: {
  target: FollowUpTarget;
  dialer: Dialer;
  status: ReturnType<typeof useActionFeedback>["status"];
  result: CallLeadResult | undefined;
  error: unknown;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const blocked = result?.status === "blocked";
  return (
    <ConfirmDialog
      title={`Call ${target.name} now?`}
      confirmLabel="Call now"
      pendingLabel="Calling…"
      successLabel="Calling"
      cancelLabel={blocked ? "Close" : "Cancel"}
      // A refusal is the answer: the button that would ask again is held, the reason shown.
      status={blocked ? "idle" : status}
      confirmDisabled={blocked}
      error={error}
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <p>
        {dialer.name} rings {target.phone ? <span className="tabular-nums text-ink">{formatPhone(target.phone)}</span> : "them"} straight
        away. The do-not-call, calling-hours and consent checks still apply, and can stop the call.
      </p>
      {blocked ? (
        <NoticeBox tone="warn" role="status">
          {result?.blocked_reason ?? "This call was not allowed."}
        </NoticeBox>
      ) : null}
    </ConfirmDialog>
  );
}

const CHOICE =
  "press flex w-full items-start justify-between gap-3 rounded-md border border-line px-3 py-2.5 text-left hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 aria-[current=true]:border-brand";

function MarkDialog({
  target,
  onClose,
  onLead,
  onCall,
}: {
  target: FollowUpTarget;
  onClose: () => void;
  onLead: (status: LeadStatus) => void;
  onCall: (state: CallFollowUpState | null) => void;
}) {
  const isCall = Boolean(target.callId);
  const current = isCall ? (target.followUpState ?? null) : (target.leadStatus ?? null);
  const choices = isCall
    ? CALL_MARKS.filter((m) => m.state !== null || current !== null).map((m) => ({
        id: m.state ?? "none",
        label: m.label,
        hint: m.hint,
        current: m.state === current,
        pick: () => onCall(m.state),
      }))
    : LEAD_MARKS.map((m) => ({
        id: m.status,
        label: m.label,
        hint: m.hint,
        current: m.status === current,
        pick: () => onLead(m.status),
      }));
  return (
    <ModalDialog
      title={isCall ? "Mark this call" : "Mark this lead"}
      description={
        <>
          <span className="block break-words font-medium text-ink">{target.name}</span>
          {isCall
            ? "A mark is for your team. It does not change how the call ended."
            : "Choose where this lead stands. You can undo it straight after."}
        </>
      }
      onClose={onClose}
      actions={
        <button type="button" className={SECONDARY_BUTTON} onClick={onClose}>
          Cancel
        </button>
      }
    >
      <ul className="mt-4 space-y-2">
        {choices.map((choice) => (
          <li key={choice.id}>
            <button
              type="button"
              aria-current={choice.current || undefined}
              // Choosing what it already is changes nothing, so it is not offered as a change.
              disabled={choice.current}
              onClick={choice.pick}
              className={CHOICE}
            >
              <span>
                <span className="block text-body font-medium text-ink">{choice.label}</span>
                <span className="block text-meta text-ink-muted">{choice.hint}</span>
              </span>
              {choice.current ? <span className="shrink-0 text-meta font-medium text-ink-muted">Now</span> : null}
            </button>
          </li>
        ))}
      </ul>
    </ModalDialog>
  );
}

const NOTE_MAX = 200;

function LaterDialog({
  target,
  status,
  result,
  error,
  onClose,
  onSubmit,
}: {
  target: FollowUpTarget;
  status: ReturnType<typeof useActionFeedback>["status"];
  result: { status: string; blocked_reason?: string | null } | undefined;
  error: unknown;
  onClose: () => void;
  onSubmit: (at: string, note: string) => void;
}) {
  const when = useCallbackWhen();
  const [note, setNote] = useState("");
  const blocked = result?.status === "blocked";

  const submit = () => {
    const at = when.check();
    if (at) onSubmit(at, note.trim());
  };

  return (
    <ModalDialog
      title="Call back later"
      description={
        <>
          <span className="block break-words font-medium text-ink">{target.name}</span>
          Your agent rings them at the time you choose, between 9am and 9pm India time, within the next 30 days.
        </>
      }
      onClose={onClose}
      actions={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={status === "pending"}>
            Cancel
          </button>
          <ActionButton status={blocked ? "idle" : status} successLabel="Booked" pendingLabel="Booking…" onClick={submit} disabled={blocked}>
            Book the call back
          </ActionButton>
        </>
      }
    >
      <form
        className="mt-4 space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {when.fields}
        <Field label="What is it about? (optional)" hint="Your agent hears this before it rings.">
          {(control) => (
            <textarea
              {...control}
              value={note}
              maxLength={NOTE_MAX}
              rows={2}
              onChange={(event) => setNote(event.target.value)}
              className={FIELD}
            />
          )}
        </Field>
        {blocked ? (
          <NoticeBox tone="warn" role="status">
            {result?.blocked_reason ?? "A call back for this person is not allowed."}
          </NoticeBox>
        ) : null}
        <ProblemNotice error={error} />
      </form>
    </ModalDialog>
  );
}

function WhatsAppDialog({
  session,
  target,
  status,
  result,
  error,
  onClose,
  onSend,
}: {
  session: Session;
  target: FollowUpTarget;
  status: ReturnType<typeof useActionFeedback>["status"];
  result: { status: string; reason?: string | null } | undefined;
  error: unknown;
  onClose: () => void;
  onSend: (templateId: string, values: string[]) => void;
}) {
  const options = useWhatsAppOptions(session, target.leadId ?? undefined);
  const templates = options.data?.templates ?? [];
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string[]>>({});
  const [tried, setTried] = useState(false);
  const template = templates.find((t) => t.id === templateId) ?? (templates.length === 1 ? templates[0] : undefined);
  const filled = template ? (values[template.id] ?? template.variables.map(() => "")) : [];
  const missing = template ? template.variables.map((_, i) => !(filled[i] ?? "").trim()) : [];
  const answered = result && result.status !== "sent";
  const canSend = options.data?.available === true && templates.length > 0;

  const submit = () => {
    setTried(true);
    if (!template || missing.some(Boolean)) return;
    onSend(template.id, filled.map((v) => v.trim()));
  };

  let body: ReactNode;
  if (options.isLoading) body = <Skeleton rows={3} label="Checking whether a message can be sent" />;
  else if (options.error) body = <ProblemNotice error={options.error} onRetry={() => void options.refetch()} />;
  else if (!options.data) body = null;
  else if (!options.data.available)
    body = (
      <NoticeBox tone="neutral" role="status">
        {options.data.reason ?? "A WhatsApp message cannot be sent to this person right now."}
      </NoticeBox>
    );
  else if (templates.length === 0)
    body = (
      <NoticeBox tone="neutral" role="status">
        You have no approved WhatsApp messages yet, so there is nothing to send.
      </NoticeBox>
    );
  else
    body = (
      <div className="space-y-4">
        {templates.length > 1 ? (
          <RadioGroup
            label="Message"
            options={templates.map((t) => ({
              value: t.id,
              label: t.name,
              hint: <span className="line-clamp-2">{t.body}</span>,
            }))}
            value={template?.id ?? null}
            onChange={setTemplateId}
            error={tried && !template ? "Choose a message to send." : null}
          />
        ) : null}
        {template ? (
          <>
            <div>
              <p className="text-xs font-medium text-ink-muted">What they receive</p>
              <p className="mt-1 whitespace-pre-line break-words rounded-md bg-ink/[0.03] px-3 py-2 text-body text-ink">
                {template.body}
              </p>
            </div>
            {template.variables.map((variable, index) => (
              <Field
                key={`${template.id}-${index}`}
                label={variable.label ?? `Blank ${index + 1}`}
                error={tried && missing[index] ? "Fill this in before sending." : null}
              >
                {(control) => (
                  <input
                    {...control}
                    value={filled[index] ?? ""}
                    placeholder={variable.example ?? undefined}
                    onChange={(event) =>
                      setValues((prev) => {
                        const next = [...filled];
                        next[index] = event.target.value;
                        return { ...prev, [template.id]: next };
                      })
                    }
                    className={FIELD}
                  />
                )}
              </Field>
            ))}
          </>
        ) : null}
      </div>
    );

  return (
    <ModalDialog
      title="Send a WhatsApp follow-up"
      description={
        <>
          <span className="block break-words font-medium text-ink">{target.name}</span>
          Only your approved messages can be sent, from your own WhatsApp number.
        </>
      }
      onClose={onClose}
      actions={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={status === "pending"}>
            {canSend ? "Cancel" : "Close"}
          </button>
          {canSend ? (
            <ActionButton status={answered ? "idle" : status} successLabel="Sent" pendingLabel="Sending…" onClick={submit}>
              Send
            </ActionButton>
          ) : null}
        </>
      }
    >
      <div className="mt-4 space-y-4">
        {body}
        {answered ? (
          <NoticeBox tone="warn" role="status">
            {result?.reason ?? "The message was not sent."}
          </NoticeBox>
        ) : null}
        <ProblemNotice error={error} />
      </div>
    </ModalDialog>
  );
}
