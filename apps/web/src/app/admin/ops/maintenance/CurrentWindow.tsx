"use client";

import { useState, type ReactNode } from "react";
import { TriangleAlert } from "lucide-react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { InfoTip } from "@/components/console/infoTip";
import { Metric } from "@/components/console/metric";
import {
  DANGER_BUTTON,
  NoticeBox,
  SECONDARY_BUTTON,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  useCancelMaintenance,
  useEndMaintenance,
  type MaintenanceInFlight,
  type MaintenanceWindow,
} from "@/lib/api/maintenance";

import { AmendWindowDrawer } from "./windowForms";
import { CurrentWindowHeading, STATE_COPY, StatePill } from "./windowState";

const ENDING_RESTORES: ReactNode = (
  <>
    Ending restores the portals first, then resumes every campaign this window paused and
    puts every agent back to its own script. That last part is a round trip per agent —
    watch for <code>maintenance_voice_incomplete</code>.
  </>
);

/**
 * The two counts the drain is waiting on, with how old they are. They lead the window
 * because an operator staring at a spinner with no numbers is the one who forces it and
 * breaks a live call.
 */
function InFlightPanel({
  inFlight,
  title,
  hint,
  info,
}: {
  inFlight: MaintenanceInFlight;
  title: string;
  hint: string;
  info?: ReactNode;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1">
        <h3 className="text-body font-semibold text-ink">{title}</h3>
        {info && <InfoTip label={title}>{info}</InfoTip>}
      </div>
      <div className="grid max-w-md grid-cols-2 gap-4">
        <Metric
          label="Calls still up"
          value={formatCount(inFlight.calls)}
          flashValue={String(inFlight.calls)}
        />
        <Metric
          label="Jobs still queued"
          value={formatCount(inFlight.jobs)}
          flashValue={String(inFlight.jobs)}
        />
      </div>
      <p className="text-meta text-ink-muted">
        {hint} Measured {formatIST(inFlight.measured_at)}.
      </p>
      {/* A walk that ran out of time has not asked everybody, so zeros here are not a drain.
          The window will not activate on it, and neither should the operator. */}
      {!inFlight.complete && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="These numbers are a floor, not a total"
        >
          <p className="mt-1">
            The check could not reach {inFlight.tenants_unreached} client
            {inFlight.tenants_unreached === 1 ? "" : "s"} before its time budget ran out, so
            each of them may be holding a call this count does not include. The window will
            not activate on an incomplete check.
          </p>
        </NoticeBox>
      )}
    </div>
  );
}

function WhenFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-meta font-medium text-ink-muted">{label}</dt>
      <dd className="mt-1 text-body font-semibold tabular-nums text-ink">{value}</dd>
    </div>
  );
}

/**
 * The open window. Nothing here reads the browser's clock: `state` is the worker's word,
 * `measured_at` the server's instant and the deadline a column, so a laptop four minutes
 * fast cannot render "active" over a platform that is still draining.
 */
export function CurrentWindow({ window: current }: { window: MaintenanceWindow }) {
  const copy = STATE_COPY[current.state];
  const cancel = useCancelMaintenance();
  const end = useEndMaintenance();
  const [editing, setEditing] = useState(false);
  const [stopping, setStopping] = useState(false);
  // Two verbs because the server treats them as two: a window that has not begun is
  // called off (nothing happened); one draining or active is ENDED, which is what puts the
  // campaigns and agents back. Each is offered only where the server accepts it.
  const scheduled = current.state === "scheduled";
  const stopLabel = scheduled
    ? "Call it off"
    : current.state === "active"
      ? "End now and reopen the portals"
      : "Stop now and put everything back";

  return (
    <section aria-labelledby="maintenance-current" className="space-y-5">
      <CurrentWindowHeading>
        <StatePill tone={copy.tone}>{copy.label}</StatePill>
        {current.forced && (
          <StatePill tone="stop">Activated on the deadline, not on a clean drain</StatePill>
        )}
      </CurrentWindowHeading>
      <p className="max-w-prose text-body text-ink-muted">{copy.what}</p>

      {current.state === "draining" && current.in_flight !== null && (
        <InFlightPanel
          inFlight={current.in_flight}
          title="What the drain is waiting for"
          hint="It activates by itself when both reach zero, or at the drain deadline."
          info="Whichever comes first. Nothing is cancelled either way: a call that is up stays up and still produces its post-call record."
        />
      )}

      <dl className="grid gap-4 sm:grid-cols-3">
        <WhenFact label="Opens" value={formatIST(current.starts_at)} />
        <WhenFact label="Ends" value={formatIST(current.ends_at)} />
        <WhenFact
          label="Drain deadline"
          value={
            current.drain_deadline_at === null
              ? `${current.max_drain_minutes} min once it opens`
              : formatIST(current.drain_deadline_at)
          }
        />
      </dl>

      {current.stragglers !== null && (
        <InFlightPanel
          inFlight={current.stragglers}
          title="What was still running when it activated"
          hint="These are the counts the activation decision was taken on."
        />
      )}

      <div className="border-l-2 border-line pl-3">
        <p className="text-meta font-medium text-ink-muted">What clients are being told</p>
        <p className="mt-1 text-body text-ink">{current.reason}</p>
      </div>

      <div className="space-y-2 border-t border-line pt-4">
        <div className="flex flex-wrap gap-2">
          <button type="button" className={SECONDARY_BUTTON} onClick={() => setEditing(true)}>
            Change window
          </button>
          <button
            type="button"
            className={scheduled ? SECONDARY_BUTTON : DANGER_BUTTON}
            onClick={() => setStopping(true)}
          >
            {stopLabel}
          </button>
        </div>
        {!scheduled && <p className="max-w-prose text-meta text-ink-muted">{ENDING_RESTORES}</p>}
      </div>

      {editing && <AmendWindowDrawer window={current} onClose={() => setEditing(false)} />}

      {stopping && scheduled && (
        <ConfirmDialog
          title="Call off this window?"
          confirmLabel="Call it off"
          pendingLabel="Calling it off…"
          pending={cancel.isPending}
          error={cancel.error}
          onCancel={() => {
            setStopping(false);
            cancel.reset();
          }}
          onConfirm={() => cancel.mutate(current.id, { onSuccess: () => setStopping(false) })}
        >
          <p>
            The window never opens. Nothing has changed yet, so there is nothing to put back,
            and clients stop seeing the maintenance banner.
          </p>
        </ConfirmDialog>
      )}
      {stopping && !scheduled && (
        <ConfirmDialog
          title={
            current.state === "active"
              ? "End the window and reopen the portals?"
              : "Stop the drain and put everything back?"
          }
          confirmLabel={stopLabel}
          pendingLabel="Ending…"
          pending={end.isPending}
          error={end.error}
          onCancel={() => {
            setStopping(false);
            end.reset();
          }}
          onConfirm={() => end.mutate(current.id, { onSuccess: () => setStopping(false) })}
        >
          <p>{copy.what}</p>
          <p>{ENDING_RESTORES}</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
