"use client";

import { CheckCircle2, CircleHelp, Info } from "lucide-react";

import {
  Card,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import { adminSession } from "@/lib/api/admin";
import {
  useEndTrial,
  useStartTrial,
  useTenantTrial,
  type TrialStatus,
} from "@/lib/api/trials";

import { EndTrialForm } from "./EndTrialForm";
import { StartTrialForm } from "./StartTrialForm";

/**
 * TRIAL PERIODS, on the screen an operator is already on when the question comes up.
 *
 * `POST /v1/admin/tenants/{id}/trial` shipped with D-536 and had no caller: starting a
 * trial meant hand-assembling a `curl` with an `X-Confirm-Action` header against
 * production. It sits HERE rather than on its own route because of what a trial now
 * answers: since D-551 an empty wallet stops a client's agents ANSWERING as well as
 * dialling, so "this brand-new client has no credit and their phone has gone quiet" is a
 * wallet question whose two answers are "record their payment" and "put them on a trial",
 * and an operator holding that question is looking at this screen.
 *
 * ## WHAT THE CONTROL HAS TO SAY BEFORE IT IS PRESSED
 *
 * A trial is money-adjacent with NO SPEND CEILING — the founder was shown the
 * unbounded-liability argument and chose days only (`billing/trials.py` §4). So the days
 * are the entire bound on what this act can cost, and three things follow, none of them
 * decoration:
 *
 * - the blast radius is stated above the button in the ops order — what it does, for how
 *   long, what it does NOT suspend, and that it is recorded;
 * - the number of days is DOUBLE-KEYED and travels in the confirmation header, exactly as
 *   the amount does on the correction and restatement panels above. `useStartTrial`
 *   builds the header; this screen is where a human confirms the figure, because a
 *   confirm dialog in a browser is absent from `curl`;
 * - what the trial has cost us so far is on the read and is shown while it runs, because
 *   "no ceiling" and "no visibility" together is how this becomes expensive silently.
 *
 * ## WHAT IT MUST NOT IMPLY
 *
 * A trial is a BILLING state and nothing else. KYC, the agreements, the spend cap,
 * calling hours, DNC, consent, the AI disclosure and the DLT chain all still bite, and
 * the panel says so where an operator would otherwise assume "everything is on us" means
 * "everything is allowed". There is no reading of a commercial gift that reaches TRAI.
 *
 * §52 as three exclusive branches: loading is a `Skeleton`, a failed read is a
 * `ProblemNotice` with a retry AND withholds the form, and "this client has never been
 * given a trial" is stated only because the server answered `null` — never because a read
 * came back empty.
 */
export function TrialPanel({
  tenantId,
  clientName,
}: {
  tenantId: string;
  clientName: string;
}) {
  const trial = useTenantTrial(adminSession(), tenantId);
  const start = useStartTrial(adminSession(), tenantId);
  const end = useEndTrial(adminSession(), tenantId);
  // `admin:tenants`, the same permission as every other write on this screen, with its
  // own sentence: a restriction note has to name the control it sits under.
  const write = useAdminAccess("admin:tenants", "put this client on a trial");

  if (trial.isLoading) {
    return (
      <Card title="Trial period">
        <Skeleton rows={3} />
      </Card>
    );
  }

  // A read that FAILED is not "they have never had a trial" — and the difference decides
  // whether an operator opens a second one over a live one, which the API would refuse
  // but only after the operator has told a client on the phone that it is done.
  if (trial.isError) {
    return (
      <Card title="Trial period">
        <ProblemNotice error={trial.error} onRetry={() => trial.refetch()} />
        <NoticeBox
          className="mt-4"
          tone="warn"
          icon={<CircleHelp aria-hidden className="h-5 w-5" />}
          title="We could not read this client's trial, so none can be started here"
        >
          <p className="mt-1 text-xs">
            This screen will not tell you they have never had one — it does not know. Retry
            the read and the control comes back with it.
          </p>
        </NoticeBox>
      </Card>
    );
  }

  const state = trial.data ?? null;

  return (
    <Card title="Trial period">
      <p className="-mt-2 text-xs text-ink-muted">
        Days on us. While a trial runs, this client&apos;s wallet is not debited and an
        empty one stops neither their outgoing calls nor their agents answering incoming
        ones. Every minute is still metered and we still pay for it.
      </p>

      {state === null ? (
        <p className="mt-4 text-sm text-ink-muted">
          {clientName} has never been given a trial.
        </p>
      ) : (
        <TrialFacts state={state} />
      )}

      {state?.active ? (
        <EndTrialForm clientName={clientName} end={end} write={write} />
      ) : (
        <StartTrialForm clientName={clientName} start={start} write={write} />
      )}
    </Card>
  );
}

/** The trial as the SERVER reports it — `active` is its verdict, never `status ===
 * "active"`: the sweep that expires a row runs daily, so a row can read `active` for up
 * to a day past its end date and `TrialState.is_active` reads the clock as well. */
function TrialFacts({ state }: { state: TrialStatus }) {
  return (
    <div className="mt-4 space-y-3">
      <NoticeBox
        tone={state.active ? "ok" : "neutral"}
        icon={
          state.active ? (
            <CheckCircle2 aria-hidden className="h-5 w-5" />
          ) : (
            <Info aria-hidden className="h-5 w-5" />
          )
        }
        title={
          state.active
            ? `On us for ${state.days_remaining ?? 0} more day(s) — until ${formatIST(state.ends_at)}`
            : `Their trial ended ${state.ended_at ? formatIST(state.ended_at) : ""} (${state.status})`
        }
      >
        <p className="mt-1 text-xs">
          {state.days} day(s) from {formatIST(state.started_at)}.
          {state.ended_reason ? ` “${state.ended_reason}”` : ""}
        </p>
        {/* OUR SUPPLIER COST, and the whole reason the read exists: there is no spend
            ceiling on a trial by explicit choice, so this figure is the visibility that
            makes that choice survivable. Operator-only — no client surface has ever shown
            `unit_cost_paid` and none starts here. */}
        <p className="mt-2 text-xs">
          Cost to Calevate so far:{" "}
          <span className="font-semibold tabular-nums">
            {formatINR(state.cost_to_us_inr)}
          </span>{" "}
          at our supplier rates. This figure is ours and is never shown to the client.
        </p>
        {state.erase_after && !state.active && (
          <p className="mt-2 text-xs">
            They did not convert, so their leads, calls and transcripts become erasable on{" "}
            {formatIST(state.erase_after)}.
          </p>
        )}
      </NoticeBox>
    </div>
  );
}
