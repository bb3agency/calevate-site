"use client";

import { useState } from "react";

import { ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import {
  usePlatformState,
  useSetPlatformState,
  useSetTmRegistration,
  type TmRegistration,
  type TmStatus,
} from "@/lib/api/admin";

/**
 * The operations surface — the big red switch, the load-shed mode, and the one legal
 * fact with the same shape as a switch: whether Calevate is a live registered
 * telemarketer.
 *
 * Three properties of this page are deliberate:
 *
 * 1. It shows the CURRENT state prominently, because the failure mode of a global
 *    kill switch is nobody remembering it is still on.
 * 2. Halting requires typing the confirmation, which the API also demands as a
 *    step-up header. Not a second factor and not pretending to be one — it stops the
 *    accidental click, and Clerk re-auth replaces it when admin MFA lands.
 * 3. `tm_registration.is_live` is DISPLAYED, never computed. The launch gate refuses
 *    every tenant's campaign with `tm_registration_missing` from the same property, so
 *    a console that decided for itself whether `submitted` counts would be capable of
 *    showing a green platform while every client's launch was being refused.
 */
export default function OpsPage() {
  const state = usePlatformState();
  const setState = useSetPlatformState();
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  const halted = state.data?.outbound_halted ?? false;
  const confirmWord = halted ? "RESUME" : "HALT";

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Operations</h1>
        <p className="mt-0.5 text-sm text-slate-400">
          Platform-wide switches. Every change is audit-logged with its reason.
        </p>
      </div>

      {state.error && <ProblemNotice error={state.error} onRetry={() => state.refetch()} />}
      {setState.error && <ProblemNotice error={setState.error} />}

      {state.isLoading ? (
        <Skeleton rows={3} />
      ) : (
        <div
          className={
            halted
              ? "rounded-xl border border-rose-800 bg-rose-950 p-4"
              : "rounded-xl border border-slate-800 bg-slate-900 p-4"
          }
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold">
                Outbound calling: {halted ? "HALTED" : "running"}
              </p>
              <p className="mt-0.5 text-xs text-slate-400">
                Load-shed mode: {state.data?.load_shed_mode ?? "unknown"}
              </p>
            </div>
            <span
              className={
                halted
                  ? "h-3 w-3 rounded-full bg-rose-400"
                  : "h-3 w-3 rounded-full bg-emerald-400"
              }
            />
          </div>

          <p className="mt-3 text-xs text-slate-400">
            Halting stops every tenant&apos;s outbound dispatch immediately. Inbound calls
            are unaffected — the caller initiated those, and refusing them would
            silently break the receptionist clients pay for.
          </p>

          <form
            className="mt-4 space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              setState.mutate(
                { outboundHalted: !halted, reason },
                { onSuccess: () => { setReason(""); setConfirm(""); } },
              );
            }}
          >
            <input
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason (recorded in the audit log)"
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm"
            />
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder={`Type ${confirmWord} to confirm`}
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 font-mono text-sm"
            />
            <button
              type="submit"
              disabled={confirm !== confirmWord || !reason || setState.isPending}
              className={
                halted
                  ? "rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 disabled:opacity-40"
                  : "rounded-md bg-rose-500 px-4 py-2 text-sm font-semibold text-rose-950 disabled:opacity-40"
              }
            >
              {halted ? "Resume outbound calling" : "Halt all outbound calling"}
            </button>
          </form>
        </div>
      )}

      {state.isLoading ? null : state.data ? (
        <TmRegistrationPanel registration={state.data.tm_registration} />
      ) : null}

      {/* Admin panels are styled locally rather than with the shared `Card`: that
          component is built for the client realm's light surface and only goes dark
          under `prefers-color-scheme`, so it renders as a white slab inside this
          deliberately dark shell. */}
      <section className="rounded-xl border border-slate-800 bg-slate-900">
        <header className="border-b border-slate-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-100">What is never shed</h2>
        </header>
        <ul className="space-y-1 p-4 text-sm text-slate-400">
          <li>· Health endpoints</li>
          <li>· Engine webhooks — a dropped callback is a call whose lead never appears</li>
          <li>· This ops surface — an operator must not be able to lock themselves out</li>
        </ul>
      </section>
    </div>
  );
}

const TM_STATUSES: { value: TmStatus; label: string }[] = [
  { value: "not_registered", label: "not_registered — no application filed" },
  { value: "submitted", label: "submitted — filed, not yet granted" },
  { value: "active", label: "active — granted and in force" },
  { value: "suspended", label: "suspended — registrar action, e.g. complaints" },
  { value: "revoked", label: "revoked — registration withdrawn" },
];

/** `date-time` ⇄ `<input type="datetime-local">`. The input speaks LOCAL wall-clock
 * (an operator types the IST moment on the registrar's letter) and `Date` converts it
 * to the instant the API stores, so no timezone arithmetic happens by hand. */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(
    at.getHours(),
  )}:${pad(at.getMinutes())}`;
}

/**
 * Calevate's own DLT telemarketer registration — the platform-wide campaign blocker.
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
function TmRegistrationPanel({ registration }: { registration: TmRegistration }) {
  const record = useSetTmRegistration();
  // Seeded from the current registration so re-recording after a re-verification is an
  // edit, not a retype — a blank `tm_id` posted by habit would erase the one we hold.
  // Deliberately NOT re-synced on the 30s refetch: clobbering a half-typed form with a
  // poll result is worse than a stale default an operator can see and change.
  const [status, setStatus] = useState<TmStatus>(
    TM_STATUSES.some((s) => s.value === registration.status)
      ? (registration.status as TmStatus)
      : "not_registered",
  );
  const [tmId, setTmId] = useState(registration.tm_id ?? "");
  const [registeredAt, setRegisteredAt] = useState(toLocalInput(registration.registered_at));
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  // Which write this is, in the operator's words and in the API's. Both derive from the
  // status being SUBMITTED — the direction of this request — and neither is a claim
  // about what counts as live; `ops/routes.py` computes the same thing from the same
  // field and refuses a header that does not match.
  const makingLive = status === "active";
  const confirmWord = makingLive ? "RECORD" : "WITHDRAW";
  const live = registration.is_live;

  return (
    <section
      className={
        live
          ? "rounded-xl border border-slate-800 bg-slate-900"
          : "rounded-xl border border-amber-800 bg-amber-950/40"
      }
    >
      <header className="flex items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">
            Our telemarketer registration (DLT)
          </h2>
          <p className="mt-0.5 text-xs text-slate-400">
            Calevate is the registered Telemarketer; each client is its own Principal
            Entity. One fact for the whole platform.
          </p>
        </div>
        <span
          className={
            live
              ? "whitespace-nowrap rounded-full bg-emerald-500 px-2 py-0.5 text-xs font-semibold text-emerald-950"
              : "whitespace-nowrap rounded-full bg-amber-400 px-2 py-0.5 text-xs font-semibold text-amber-950"
          }
        >
          {live ? "LIVE" : "NOT LIVE"}
        </span>
      </header>

      <div className="space-y-4 p-4">
        {/* The consequence, stated before the fields. An operator reading `submitted`
            and no consequence has to remember the rule; reading it here, they do not. */}
        <p className={live ? "text-xs text-slate-400" : "text-sm text-amber-200"}>
          {live
            ? "Campaign launches are not blocked by this. Every client still needs its own Principal Entity registration and TM link."
            : "While this is not live, NO tenant can launch an outbound campaign, however complete their own registration is. Inbound answering is unaffected — clients' receptionists keep working."}
        </p>

        <dl className="grid gap-3 sm:grid-cols-4">
          <Fact label="Status" value={registration.status} />
          <Fact label="TM id" value={registration.tm_id ?? "—"} mono />
          <Fact label="Registered" value={formatIST(registration.registered_at)} />
          <Fact label="Last verified" value={formatIST(registration.verified_at)} />
        </dl>

        {record.error && <ProblemNotice error={record.error} />}
        {record.data && (
          <p className="text-xs text-slate-400">
            Recorded. The gate now reads{" "}
            <span className="font-medium text-slate-200">
              {record.data.is_live ? "live" : "not live"}
            </span>
            .
          </p>
        )}

        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            record.mutate(
              {
                status,
                tm_id: tmId.trim() || null,
                registered_at: registeredAt ? new Date(registeredAt).toISOString() : null,
                reason,
              },
              { onSuccess: () => setConfirm("") },
            );
          }}
        >
          <div className="flex flex-wrap gap-2">
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as TmStatus);
                // The confirmation word changes with the direction, so a word typed for
                // the other direction must not survive the switch and submit silently.
                setConfirm("");
              }}
              className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm"
            >
              {TM_STATUSES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <input
              value={tmId}
              onChange={(e) => setTmId(e.target.value)}
              placeholder="TM id from the registrar"
              className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-sm"
            />
            <input
              type="datetime-local"
              value={registeredAt}
              onChange={(e) => setRegisteredAt(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm"
            />
          </div>
          <input
            required
            minLength={3}
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (recorded in the audit log — e.g. 'registrar grant letter 2026-08-04')"
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm"
          />
          <input
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder={`Type ${confirmWord} to confirm`}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 font-mono text-sm"
          />
          <p className="text-xs text-slate-500">
            {makingLive
              ? "Recording this as active turns the platform-wide launch gate green for every tenant."
              : "Anything other than active takes the gate away: no tenant can launch an outbound campaign until it is recorded active again."}
          </p>
          <button
            type="submit"
            disabled={confirm !== confirmWord || reason.trim().length < 3 || record.isPending}
            className={
              makingLive
                ? "rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 disabled:opacity-40"
                : "rounded-md bg-amber-400 px-4 py-2 text-sm font-semibold text-amber-950 disabled:opacity-40"
            }
          >
            {record.isPending
              ? "Recording…"
              : makingLive
                ? "Record registration as active"
                : `Record as ${status.replace(/_/g, " ")}`}
          </button>
        </form>
      </div>
    </section>
  );
}

function Fact({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd
        className={
          mono
            ? "mt-0.5 font-mono text-sm text-slate-200"
            : "mt-0.5 text-sm text-slate-200"
        }
      >
        {value}
      </dd>
    </div>
  );
}
