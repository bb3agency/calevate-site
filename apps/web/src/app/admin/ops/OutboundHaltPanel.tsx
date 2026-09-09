"use client";

import { useState } from "react";
import { Lock, PhoneCall, PhoneOff, TriangleAlert } from "lucide-react";

import { WriteFailure } from "@/app/admin/writeFailure";
import {
  Card,
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { useSetPlatformState, type PlatformState } from "@/lib/api/admin";

import type { OpsAccess } from "./opsAccess";

/**
 * The big red switch, with its current position and its reason.
 *
 * The confirmation is the screen's existing pattern kept intact: a typed word plus a
 * reason, mirroring the `X-Confirm-Action` header the API demands (BACKEND-PATTERNS §7).
 * The reason is trimmed before it is measured, because the server strips it and refuses
 * anything under three characters — a form that enables its button on `"   "` teaches the
 * operator the API is flaky.
 */
export function OutboundHaltPanel({ state, access }: { state: PlatformState; access: OpsAccess }) {
  const setState = useSetPlatformState();
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  const halted = state.outbound_halted;
  const confirmWord = halted ? "RESUME" : "HALT";
  const valid = useFormValidation();
  // The reason is answered at its own control now — pressing the button with an
  // empty reason says so rather than doing nothing. The typed word stays in `ready`:
  // it is a gate on the act, not an answer on the form.
  const ready = confirm === confirmWord;

  return (
    <Card>
      <div className="space-y-4">
        <NoticeBox
          tone={halted ? "stop" : "ok"}
          icon={
            halted ? (
              <PhoneOff aria-hidden className="h-5 w-5" />
            ) : (
              <PhoneCall aria-hidden className="h-5 w-5" />
            )
          }
          title={
            halted
              ? "Outbound calling is HALTED for every client"
              : "Outbound calling is running"
          }
        >
          {halted ? (
            <>
              <p className="mt-1">
                No outbound call is being placed for any client. Inbound calls are
                unaffected — clients&apos; receptionists keep answering.
              </p>
              {/* The one question whoever finds the platform halted asks first. It is on
                  the wire and was on no screen until this pass. */}
              <p className="mt-2">
                <span className="font-semibold">Reason on the record:</span>{" "}
                {state.halt_reason ?? "none was recorded with this halt."}
              </p>
            </>
          ) : (
            <p className="mt-1">
              Campaigns dial normally, subject to each one&apos;s own compliance gate.
            </p>
          )}
        </NoticeBox>

        <form
          className="space-y-3"
          noValidate
          onSubmit={valid.onSubmit(() => {
            setState.mutate(
              { outboundHalted: !halted, reason: reason.trim() },
              {
                onSuccess: () => {
                  setReason("");
                  setConfirm("");
                },
              },
            );
          })}
        >
          {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON. Blast radius first, then what is
              NOT affected, then the fact that it is recorded — in that order, because
              an operator who reads only the first line has read the part that matters. */}
          <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
            <TriangleAlert
              aria-hidden
              className={`mt-0.5 h-4 w-4 shrink-0 ${halted ? "text-ink-faint" : "text-rose-600"}`}
            />
            <div className="min-w-0">
              <p className="font-semibold text-ink">
                {halted
                  ? "Resuming lets every client's outbound dialling start again"
                  : "Halting stops every client's outbound dialling immediately"}
              </p>
              <p className="mt-1 text-ink-muted">
                {halted
                  ? "Paused campaigns pick up again within a minute or so. Every campaign's own compliance gate still applies — this only releases the platform-wide stop, nothing else."
                  : "Running campaigns stop within a minute or so and no new outbound call is placed for any client. Inbound calls are unaffected — the caller started those, and refusing them would silently break the receptionist your clients pay for."}
              </p>
              <p className="mt-1 text-xs text-ink-faint">
                Recorded in the activity log against your admin account, with the reason
                you type below.
              </p>
            </div>
          </div>

          {setState.error && (
            <WriteFailure
              error={setState.error}
              actionLabel={halted ? "Resume outbound calling" : "Halt all outbound calling"}
            />
          )}

          <label className="block">
            <span className={FIELD_LABEL}>Reason</span>
            <input
              {...valid.field("reason", "Say why you are making this change.")}
              required
              minLength={3}
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={!access.allowed}
              placeholder={
                halted
                  ? "e.g. 'registrar confirmed the suspension was lifted'"
                  : "e.g. 'spike in complaints — stopping until we've read the logs'"
              }
              className={FIELD}
            />
            {valid.error("reason")}
            <span className={FIELD_HINT}>
              Whoever finds outbound calling stopped at 3am reads this to decide whether the
              reason still holds. It stays on record here, not only in the activity log.
            </span>
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>Type {confirmWord} to confirm</span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={!access.allowed}
              placeholder={confirmWord}
              className={`${FIELD} font-mono`}
            />
          </label>

          <button
            type="submit"
            title={access.reason ?? undefined}
            disabled={!access.allowed || !ready || setState.isPending}
            className={halted ? PRIMARY_BUTTON : DANGER_BUTTON}
          >
            {halted ? (
              <PhoneCall aria-hidden className="h-4 w-4" />
            ) : (
              <PhoneOff aria-hidden className="h-4 w-4" />
            )}
            {setState.isPending
              ? "Sending…"
              : halted
                ? "Resume outbound calling"
                : "Halt all outbound calling"}
          </button>

          {/* A dead switch with no explanation is worse than a refusal after the click:
              the operator cannot tell it apart from a broken page. */}
          {!access.allowed && access.reason && (
            <p className="flex items-start gap-2 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {access.reason}
            </p>
          )}
        </form>
      </div>
    </Card>
  );
}
