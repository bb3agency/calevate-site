"use client";

import { useState } from "react";
import { CheckCircle2, CircleHelp, Info } from "lucide-react";

import {
  Card,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";
import { Drawer } from "@/components/console/drawer";
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
 * Since D-551 an empty wallet stops a client's agents ANSWERING as well as dialling, so "this
 * new client has no credit and their phone has gone quiet" is a wallet question whose two
 * answers are "record their payment" and "put them on a trial" (D-577).
 *
 * The state is foreground (on us until when, and what it has cost us — there is no spend
 * ceiling, so that figure is the visibility that makes the choice survivable); the forms open
 * in a drawer, where each keeps its blast radius above its button. A trial is a BILLING state
 * and nothing else: the start form says what it does NOT suspend.
 *
 * Three exclusive branches: loading is a `Skeleton`; a failed read is a `ProblemNotice` and
 * offers no control (a failed read is not "they never had one", and the difference decides
 * whether an operator opens a second trial over a live one); "never given a trial" is stated
 * only because the server answered `null`.
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
  // `admin:tenants`, with its own sentence: a restriction note names the control it is under.
  const write = useAdminAccess("admin:tenants", "put this client on a trial");
  // Fixed when the drawer opens, so a trial that starts inside it keeps showing its own
  // receipt rather than swapping to the end form the moment the re-read lands.
  const [mode, setMode] = useState<"start" | "end" | null>(null);

  if (trial.isLoading) {
    return (
      <Card title="Trial period" density="compact">
        <Skeleton rows={2} />
      </Card>
    );
  }

  if (trial.isError) {
    return (
      <Card title="Trial period" density="compact">
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
  const active = state?.active === true;

  return (
    <Card
      title="Trial period"
      density="compact"
      action={
        <button type="button" className={SECONDARY_BUTTON} onClick={() => setMode(active ? "end" : "start")}>
          {active ? "End trial" : "Start trial"}
        </button>
      }
    >
      <p className="text-xs text-ink-muted">
        Days on us. While a trial runs, this client&apos;s wallet is not debited and an
        empty one stops neither their outgoing calls nor their agents answering incoming
        ones. Every minute is still metered and we still pay for it.
      </p>

      {state === null ? (
        <p className="mt-3 text-sm text-ink-muted">{clientName} has never been given a trial.</p>
      ) : (
        <TrialFacts state={state} />
      )}

      <Drawer
        open={mode !== null}
        onClose={() => setMode(null)}
        title={mode === "end" ? "End this trial" : "Start a trial"}
        description={clientName}
        width="lg"
      >
        {mode === "end" ? (
          <EndTrialForm clientName={clientName} end={end} write={write} />
        ) : (
          <StartTrialForm clientName={clientName} start={start} write={write} />
        )}
      </Drawer>
    </Card>
  );
}

/** The trial as the SERVER reports it — `active` is its verdict, never `status ===
 * "active"`: the sweep that expires a row runs daily, so a row can read `active` for up
 * to a day past its end date and `TrialState.is_active` reads the clock as well. */
function TrialFacts({ state }: { state: TrialStatus }) {
  return (
    <NoticeBox
      className="mt-3"
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
      {/* OUR SUPPLIER COST: there is no spend ceiling on a trial by explicit choice, so this
          figure is the visibility that makes that choice survivable. Operator-only — no
          client surface has ever shown `unit_cost_paid`. */}
      <p className="mt-2 text-xs">
        Cost to Calevate so far:{" "}
        <span className="font-semibold tabular-nums">{formatINR(state.cost_to_us_inr)}</span>{" "}
        at our supplier rates. This figure is ours and is never shown to the client.
      </p>
      {state.erase_after && !state.active && (
        <p className="mt-2 text-xs">
          They did not convert, so their leads, calls and transcripts become erasable on{" "}
          {formatIST(state.erase_after)}.
        </p>
      )}
    </NoticeBox>
  );
}
