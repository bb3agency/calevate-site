"use client";

import { useState } from "react";

import { ProblemNotice, Skeleton } from "@/components/ui";
import { usePlatformState, useSetPlatformState } from "@/lib/api/admin";

/**
 * The operations surface — the big red switch and the load-shed mode.
 *
 * Two properties of this page are deliberate:
 *
 * 1. It shows the CURRENT state prominently, because the failure mode of a global
 *    kill switch is nobody remembering it is still on.
 * 2. Halting requires typing the confirmation, which the API also demands as a
 *    step-up header. Not a second factor and not pretending to be one — it stops the
 *    accidental click, and Clerk re-auth replaces it when admin MFA lands.
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
