"use client";

import { useState } from "react";
import { CheckCircle2, CircleAlert, Landmark, Lock, TriangleAlert } from "lucide-react";

import { WriteFailure } from "@/app/admin/writeFailure";
import {
  Card,
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  formatIST,
  formatISTInput,
  istInputToInstant,
} from "@/components/ui";
import { TypedConfirmation } from "@/components/typedConfirmation";
import { useFormValidation } from "@/components/formValidation";
import {
  useSetTmRegistration,
  type TmRegistration,
  type TmStatus,
} from "@/lib/api/admin";
import { Term } from "@/lib/glossary";
import { tmStatusCopy } from "@/app/admin/ops/opsLanguage";

import type { OpsAccess } from "./opsAccess";

// The five statuses in the order they are offered. The human label and one-line
// explanation for each come from `tmStatusCopy` (opsLanguage), so the select, the status
// banner and the facts grid all read the registration in one voice.
const TM_STATUSES: TmStatus[] = [
  "not_registered",
  "submitted",
  "active",
  "suspended",
  "revoked",
];

/**
 * `toLocalInput` WAS HERE AND IS GONE. It read `at.getHours()` — the BROWSER's wall clock
 * — while its own comment said the field held "the IST moment on the registrar's letter".
 * Those are the same number only on a machine set to India, and this is the admin console:
 * an operator reading it from another zone was shown, and would have posted back, a
 * different instant than the letter states. `formatISTInput`/`istInputToInstant`
 * (`components/ui.tsx`) are the pair that names the zone instead of assuming it, beside
 * the `formatIST` this screen already renders every other time through.
 */

/**
 * Calevate's own DLT telemarketer registration. Under D-692 no outbound gate reads it.
 *
 * The symptom this fixes: the registration became a launch-gate input, and no surface
 * showed it. Every client's campaign could be refused with `tm_registration_missing`
 * while the ops console reported a healthy platform — outbound not halted, load-shed
 * normal, and nothing anywhere saying that Calevate itself may not lawfully dial.
 *
 * `is_live` comes from the server and is rendered as-is. The status is shown BESIDE it
 * rather than instead of it, because the two answer different questions: `submitted`
 * is real progress to report to a colleague, and it is still not live.
 */
export function TmRegistrationPanel({
  registration,
  access,
}: {
  registration: TmRegistration;
  access: OpsAccess;
}) {
  const record = useSetTmRegistration();
  // Seeded from the current registration so re-recording after a re-verification is an
  // edit, not a retype — a blank `tm_id` posted by habit would erase the one we hold.
  // Deliberately NOT re-synced on the 30s refetch: clobbering a half-typed form with a
  // poll result is worse than a stale default an operator can see and change.
  const [status, setStatus] = useState<TmStatus>(
    TM_STATUSES.includes(registration.status as TmStatus)
      ? (registration.status as TmStatus)
      : "not_registered",
  );
  const [tmId, setTmId] = useState(registration.tm_id ?? "");
  const [registeredAt, setRegisteredAt] = useState(formatISTInput(registration.registered_at));
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  // The form is rare and the verdict is not: LIVE / NOT LIVE and the facts stay on screen,
  // and the fields open on request. The consequence still sits above the button once open.
  const [editing, setEditing] = useState(false);

  // Which write this is, in the operator's words and in the API's. Both derive from the
  // status being ACTIVE — the direction of this request — and neither is a claim about
  // what counts as live; `ops/routes.py` computes the same thing from the same field and
  // refuses a header that does not match.
  const makingLive = status === "active";
  const confirmWord = makingLive ? "RECORD" : "WITHDRAW";
  const live = registration.is_live;
  const valid = useFormValidation();
  // The reason is answered at its own control now — pressing the button with an
  // empty reason says so rather than doing nothing. The typed word stays in `ready`:
  // it is a gate on the act, not an answer on the form.
  const ready = confirm === confirmWord;

  return (
    <Card
      title="Our telemarketer registration"
      action={
        editing ? undefined : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            disabled={!access.allowed}
            title={access.reason ?? undefined}
            className={SECONDARY_BUTTON_SM}
          >
            Record a change
          </button>
        )
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          Calevate is the registered{" "}
          <Term id="tm" term="telemarketer (TM)" audience="operator" />
          ; each client is its own{" "}
          <Term id="pe" term="principal entity (PE)" audience="operator" />.
        </p>

        {/* The consequence, stated before the fields. An operator reading `submitted`
            and no consequence has to remember the rule; reading it here, they do not. */}
        <NoticeBox
          tone={live ? "ok" : "warn"}
          icon={
            live ? (
              <Landmark aria-hidden className="h-5 w-5" />
            ) : (
              <CircleAlert aria-hidden className="h-5 w-5" />
            )
          }
          title={live ? "LIVE — on record" : "Not required for outbound"}
        >
          <p className="mt-1">
            {live
              ? "Kept on record. No outbound gate asks for this registration."
              : "Calevate does not register as a telemarketer and no outbound gate asks for this. Outbound needs each client's verified KYC and accepted no-cold-calls pledge instead."}
          </p>
        </NoticeBox>

        <dl className="grid gap-3 sm:grid-cols-4">
          <Fact label="Status" value={tmStatusCopy(registration.status).label} />
          <Fact label="TM ID" value={registration.tm_id ?? "—"} mono />
          <Fact label="Registered" value={formatIST(registration.registered_at)} />
          <Fact label="Last verified" value={formatIST(registration.verified_at)} />
        </dl>

        {record.error && (
          <WriteFailure
            error={record.error}
            actionLabel={
              makingLive
                ? "Record registration as active"
                : `Record as “${tmStatusCopy(status).label}”`
            }
          />
        )}
        {/* The SERVER's `is_live` after the write, never this form's opinion of it. */}
        {record.data && (
          <p className="flex items-start gap-2 text-sm text-ink-muted">
            <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
            {/* One span around the whole sentence: a flex container lays out EVERY child
                as its own item, so leaving the text loose beside the <span> below made
                the verdict a column of its own with a `gap-2` either side of it. */}
            <span>
              Recorded. The launch gate now reads{" "}
              <span className="font-semibold text-ink">
                {record.data.is_live ? "live" : "not live"}
              </span>
              .
            </span>
          </p>
        )}

        {!editing && !access.allowed && access.reason && (
          <p className="flex items-start gap-2 text-xs text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {access.reason}
          </p>
        )}

        {editing && (
        <form
          className="space-y-3 border-t border-line pt-4"
          noValidate
          onSubmit={valid.onSubmit(() => {
            record.mutate(
              {
                status,
                tm_id: tmId.trim() || null,
                registered_at: istInputToInstant(registeredAt),
                reason: reason.trim(),
              },
              { onSuccess: () => setConfirm("") },
            );
          })}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block">
              <span className={FIELD_LABEL}>Registration status</span>
              <select
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value as TmStatus);
                  // The confirmation word changes with the direction, so a word typed for
                  // the other direction must not survive the switch and submit silently.
                  setConfirm("");
                }}
                disabled={!access.allowed}
                className={FIELD}
              >
                {TM_STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {tmStatusCopy(value).label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className={FIELD_LABEL}>TM id from the registrar</span>
              <input
                value={tmId}
                onChange={(e) => setTmId(e.target.value)}
                disabled={!access.allowed}
                className={`${FIELD} font-mono`}
              />
            </label>
            <label className="block">
              {/* THE ZONE IS ON SCREEN, and it is not decoration. A `datetime-local`
                  carries no zone, so an unlabelled one means "this machine's clock" to
                  every reader — and this field does not: it holds the moment printed on
                  the registrar's letter, which is IST wherever the operator is sitting.
                  Saying so is what lets someone in another zone type the letter's digits
                  rather than converting them, which is the whole correction here. */}
              <span className={FIELD_LABEL}>Registered on (IST)</span>
              <input
                type="datetime-local"
                value={registeredAt}
                onChange={(e) => setRegisteredAt(e.target.value)}
                disabled={!access.allowed}
                className={FIELD}
              />
              <span className={FIELD_HINT}>
                The date and time on the registrar&apos;s letter, in IST — type it as
                printed, wherever you are.
              </span>
            </label>
          </div>

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
              placeholder="e.g. 'registrar grant letter 2026-08-04'"
              className={FIELD}
            />
            {valid.error("reason")}
            <span className={FIELD_HINT}>Recorded in the activity log with this change.</span>
          </label>

          <TypedConfirmation
            match="exact"
            phrase={confirmWord}
            value={confirm}
            onChange={setConfirm}
            disabled={!access.allowed}
          />

          {/* What this write does to every tenant, before it is sent. */}
          <div className="flex gap-3 rounded-card border border-line bg-app p-4 text-sm">
            <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <p className="text-ink-muted">
              Recording this changes no outbound gate; it is kept for the record.
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              title={access.reason ?? undefined}
              disabled={!access.allowed || !ready || record.isPending}
              className={makingLive ? PRIMARY_BUTTON : DANGER_BUTTON}
            >
              {record.isPending
                ? "Recording…"
                : makingLive
                  ? "Record registration as active"
                  : `Record as “${tmStatusCopy(status).label}”`}
            </button>
            <button
              type="button"
              disabled={record.isPending}
              onClick={() => {
                setEditing(false);
                setConfirm("");
              }}
              className={SECONDARY_BUTTON}
            >
              Cancel
            </button>
          </div>

          {!access.allowed && access.reason && (
            <p className="flex items-start gap-2 text-xs text-ink-muted">
              <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {access.reason}
            </p>
          )}
        </form>
        )}
      </div>
    </Card>
  );
}

function Fact({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs font-medium text-ink-faint">{label}</dt>
      <dd className={mono ? "mt-0.5 font-mono text-sm text-ink" : "mt-0.5 text-sm text-ink"}>
        {value}
      </dd>
    </div>
  );
}
