"use client";

/**
 * CALLS AT ONCE (F7): how many calls this client may have in progress together.
 *
 * Calevate's default is two for a paying client and one on a free trial; an operator may set
 * another. A paying client's own voice workspace is capped at the value (sent on save and
 * repaired by the daily sweep); a free trial's calls are counted by our dial gate. A failed
 * read offers no control, so an operator never saves over a value they could not see.
 *
 * When the client has asked for more, the request sits beside the control: who asked, how
 * many, their note. Saving a higher number answers it: at once on a free trial, and once the
 * client's own workspace reads it back otherwise (`engine_state`); until then the panel says
 * the voice platform does not hold it yet. Decline closes it with a reason the client reads.
 * The account-wide ceiling sits beside the limit, so a grant past it is visible. The console bell and the operators'
 * email link here with `?focus=call-lines`, which opens the control at the number asked for.
 */

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Field } from "@/components/arc/field";
import { NumberField } from "@/components/arc/number-field";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { ModalDialog } from "@/components/modalDialog";
import { FIELD, NoticeBox, ProblemNotice, SECONDARY_BUTTON, Skeleton, formatIST } from "@/components/ui";
import {
  callsAtOnce,
  useCallLines,
  useDeclineCallLinesRequest,
  useSetCallLines,
  type CallLines,
} from "@/lib/api/callLines";
import { resetIfSettled } from "@/app/admin/resetIfSettled";

/** The query the bell's and the email's link carry (`core/console_links.CALL_LINES_FOCUS_QUERY`). */
const FOCUS = "call-lines";

export function CallLinesPanel({ tenantId, canWrite }: { tenantId: string; canWrite: boolean }) {
  const state = useCallLines(tenantId);
  const save = useSetCallLines(tenantId);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const [editing, setEditing] = useState(false);
  // `null` is "no choice of this client's own", sent as null so the default applies. The
  // field holds the value inside min..max itself, so there is no out-of-range draft to refuse.
  const [value, setValue] = useState<number | null>(null);
  const [declining, setDeclining] = useState(false);
  const anchor = useRef<HTMLDivElement>(null);
  const focused = useSearchParams().get("focus") === FOCUS;
  const opened = useRef(false);

  const data = state.data;
  const asked = data?.open_request ?? null;

  // Arriving from the bell or the email: open the control once, at the number asked for.
  useEffect(() => {
    if (!focused || opened.current || !data) return;
    opened.current = true;
    anchor.current?.scrollIntoView?.({ block: "start" });
    if (!canWrite) return;
    setValue(data.open_request?.wanted_lines ?? data.call_lines_chosen ?? data.call_lines + 1);
    setEditing(true);
  }, [focused, data, canWrite]);

  return (
    <div id={FOCUS} ref={anchor} className="scroll-mt-24">
      <Section title="Calls at once">
        {state.error ? (
          <ProblemNotice error={state.error} onRetry={() => void state.refetch()} />
        ) : state.isLoading || !data ? (
          <Skeleton rows={1} />
        ) : (
          <div className="space-y-3">
            {asked && (
              <NoticeBox
                tone="info"
                title={`Asked for ${asked.wanted_lines ?? "more"} (has ${asked.lines_at_request})`}
                role="status"
                action={
                  canWrite ? (
                    <button type="button" className={SECONDARY_BUTTON} onClick={() => setDeclining(true)}>
                      Decline
                    </button>
                  ) : undefined
                }
              >
                {asked.requested_by ?? "Someone at the account"}, {formatIST(asked.created_at)}.
                {asked.note ? ` “${asked.note}”` : ""}{" "}
                {data.engine_state === "applying"
                  ? "Answered once the voice platform holds the new number."
                  : "Saving a higher number answers it."}
              </NoticeBox>
            )}
            {data.engine_state === "applying" && (
              <NoticeBox tone="warn" title="Not on the voice platform yet" role="status">
                {data.applied_lines === null
                  ? "Sent, not confirmed yet. "
                  : `It still holds ${callsAtOnce(data.applied_lines)}. `}
                If this stays, check{" "}
                <a className={TEXT_ACTION} href="/admin/ops#stuck">
                  stuck messages
                </a>
                .
              </NoticeBox>
            )}
            <SettingRows className="border-y border-line">
              <SettingRow
                label="Limit"
                hint={
                  data.source === "organization"
                    ? "Set for this client"
                    : `Calevate default (${data.on_trial ? "free trial" : "paying client"})`
                }
                info={
                  <p>
                    How many calls this client can have in progress together. The default is{" "}
                    {data.paid_default} for a paying client and {data.trial_default} on a free trial.
                    A call over the limit is refused until one ends.
                  </p>
                }
                value={
                  data.engine_state === "applied"
                    ? `${callsAtOnce(data.call_lines)}, confirmed`
                    : callsAtOnce(data.call_lines)
                }
                action={
                  editing || !canWrite ? undefined : (
                    <button
                      type="button"
                      className={TEXT_ACTION}
                      onClick={() => {
                        setValue(data.call_lines_chosen);
                        resetIfSettled(save);
                        setEditing(true);
                      }}
                    >
                      Change
                    </button>
                  )
                }
              />
              {data.account_ceiling !== null && (
                <SettingRow
                  label="Account ceiling"
                  hint="Shared by every client on the voice platform"
                  value={accountLine(data.account_ceiling, data.lines_elsewhere_at_most)}
                />
              )}
            </SettingRows>
            {save.error && <ProblemNotice error={save.error} />}
            {editing && (
              <form
                className="space-y-2"
                noValidate
                onSubmit={(event) => {
                  event.preventDefault();
                  if (save.isPending) return;
                  save.mutate({ call_lines: value }, { onSuccess: () => setEditing(false) });
                }}
              >
                <NumberField
                  label="Calls at once"
                  hint={limitHint(data)}
                  value={value}
                  onChange={setValue}
                  min={data.min_lines}
                  max={data.max_lines}
                  optional
                />
                <div className="flex items-center gap-3">
                  <ActionButton type="submit" status={saveFeedback.status} successLabel="Saved">
                    Save
                  </ActionButton>
                  <button
                    type="button"
                    className={TEXT_ACTION}
                    onClick={() => {
                      // A refusal belongs to the attempt it answered, not to the next one.
                      resetIfSettled(save);
                      setEditing(false);
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
            {declining && asked && (
              <DeclineDialog tenantId={tenantId} data={data} requestId={asked.id} onClose={() => setDeclining(false)} />
            )}
          </div>
        )}
      </Section>
    </div>
  );
}

/** "20 at once; other clients hold up to 14". Exported for the test. */
export function accountLine(ceiling: number, elsewhere: number): string {
  return `${ceiling} at once; other clients hold up to ${elsewhere}`;
}

/** The field's hint: its range, and the room left on the account when it is known. */
export function limitHint(data: CallLines): string {
  const range = `${data.min_lines} to ${data.max_lines}. Leave empty for the default.`;
  if (data.account_ceiling === null) return range;
  const room = data.account_ceiling - data.lines_elsewhere_at_most;
  return room > 0
    ? `${range} At least ${room} free on the account.`
    : `${range} Other clients may already use the whole account.`;
}

function DeclineDialog({
  tenantId,
  data,
  requestId,
  onClose,
}: {
  tenantId: string;
  data: CallLines;
  requestId: string;
  onClose: () => void;
}) {
  const decline = useDeclineCallLinesRequest(tenantId);
  const feedback = useActionFeedback(decline, { errorDisplay: "inline", successToast: "Declined. The client is told." });
  const [reason, setReason] = useState("");
  const pending = decline.isPending;
  const blank = reason.trim() === "";

  return (
    <ModalDialog
      title="Decline the request"
      description={`They keep ${callsAtOnce(data.call_lines)}. They read your reason on their bell.`}
      onClose={() => {
        if (!pending) onClose();
      }}
      actions={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={pending}>
            Cancel
          </button>
          <ActionButton
            variant="danger"
            status={feedback.status}
            pendingLabel="Declining…"
            successLabel="Declined"
            disabled={blank}
            onClick={() => {
              if (pending || blank) return;
              decline.mutate({ requestId, reason: reason.trim() }, { onSuccess: onClose });
            }}
          >
            Decline
          </ActionButton>
        </>
      }
    >
      <div className="mt-4 space-y-3">
        <Field label="Why" hint="One sentence, written to the client.">
          {(control) => (
            <textarea
              {...control}
              className={FIELD}
              rows={3}
              maxLength={280}
              value={reason}
              disabled={pending}
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </Field>
        {decline.error != null && <ProblemNotice error={decline.error} />}
      </div>
    </ModalDialog>
  );
}
