"use client";

/**
 * THE CALL-BACKS YOUR AGENTS PROMISED (D-510).
 *
 * A caller said "ring me back Tuesday at four" and the agent said yes. This is the screen
 * where the client can see that a promise exists, that it went out, or exactly why it did
 * not — and stop one before it does.
 *
 * ## Every row says WHY, and never in our vocabulary
 *
 * The API sends `explanation` already resolved: the compliance gate's own client-facing
 * sentence when a call-back was refused ("This number is on the do-not-call list."), and a
 * plain reading of the ending otherwise. This screen prints it and does not compose one —
 * a second implementation of "what does `missed` mean" is where the drift starts, and the
 * gate's sentence is more specific than anything a status word could be mapped to here.
 *
 * ## Cancelling is a confirmation, not a click
 *
 * Somebody is expecting this call. `ConfirmDialog` states the CONSEQUENCE rather than
 * restating the command, the same standard the do-not-call screen holds itself to, and it
 * closes only on success — a failed cancel leaves the promise live, and closing would
 * imply it did not.
 *
 * ## Loading, failure and empty are three states and never two
 *
 * "No call-backs" under a failed request reads as "nobody asked to be rung back", which is
 * a claim about this client's calls made on no evidence. The empty state is reached only
 * through rows the server actually sent.
 */

import { PhoneForwarded } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import {
  Card,
  EmptyState,
  MonoValue,
  ProblemNotice,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useCallbacks, useCancelCallback, type ScheduledCallback } from "@/lib/api/callbacks";
import { lookup } from "@/lib/lookup";
import { useClientSession } from "@/lib/api/session";

/** Which promises are still live, and therefore still stoppable. */
const LIVE = new Set(["scheduled", "dialing"]);

/**
 * The heading a row sits under. Our status words never reach the screen; these do.
 *
 * `dialing` and `scheduled` are separated because the difference is what the client can
 * DO: one can still be called off and the other cannot, and a single "upcoming" label
 * would make the missing cancel button look like a bug.
 */
const HEADINGS: Record<string, string> = {
  scheduled: "Waiting",
  dialing: "Calling now",
  completed: "Called",
  cancelled: "Called off",
  refused: "Not allowed",
  missed: "Ran out of time",
  failed: "Could not be placed",
};

export default function CallbacksPage() {
  const session = useClientSession();
  const [openOnly, setOpenOnly] = useState(false);
  const callbacks = useCallbacks(session, openOnly);
  const cancel = useCancelCallback(session);
  const [stopping, setStopping] = useState<ScheduledCallback | null>(null);

  const rows = callbacks.data;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-ink">Call-backs</h1>
        <p className="mt-1 text-sm text-ink-muted">
          When a caller asks one of your agents to ring them back at a particular time,
          that call is booked here and goes out at the time they asked for. It goes through
          the same checks as every other call — the do-not-call list, permitted calling
          hours, and your account&apos;s credit — so a promise that cannot lawfully be kept
          is stopped and says why.
        </p>
      </div>

      <Card
        title={openOnly ? "Still to come" : "Every call-back"}
        action={
          <button
            type="button"
            className="text-sm font-medium text-ink-muted underline underline-offset-2 hover:text-ink"
            onClick={() => setOpenOnly((current) => !current)}
          >
            {openOnly ? "Show all" : "Show only the ones still to come"}
          </button>
        }
      >
        {callbacks.error && (
          <div className="p-4">
            <ProblemNotice error={callbacks.error} onRetry={() => callbacks.refetch()} />
          </div>
        )}

        {callbacks.isLoading ? (
          <div className="p-4">
            <Skeleton rows={5} />
          </div>
        ) : !rows ? null : rows.length ? (
          <ul className="divide-y divide-line">
            {rows.map((row) => (
              <CallbackRow
                key={row.id}
                callback={row}
                stopping={cancel.isPending && cancel.variables === row.id}
                onStop={() => setStopping(row)}
              />
            ))}
          </ul>
        ) : (
          <EmptyState
            title={openOnly ? "Nothing booked" : "No call-backs yet"}
            hint={
              openOnly
                ? "Nobody is waiting for a call right now."
                : "Your agents book one whenever a caller asks to be rung back at a particular time. It has to be switched on for the agent first — you will find it on the agent, under Remembering callers."
            }
          />
        )}
      </Card>

      {stopping && (
        <ConfirmDialog
          title="Call this off?"
          confirmLabel="Do not ring them"
          pendingLabel="Calling it off…"
          cancelLabel="Keep it"
          pending={cancel.isPending}
          error={cancel.error}
          onCancel={() => {
            cancel.reset();
            setStopping(null);
          }}
          onConfirm={() =>
            cancel.mutate(stopping.id, { onSuccess: () => setStopping(null) })
          }
        >
          <p>
            <MonoValue className="tabular-nums text-ink">{stopping.phone_e164}</MonoValue>{" "}
            asked to be rung back on{" "}
            <strong className="font-semibold text-ink">
              {formatIST(stopping.requested_at)}
            </strong>
            .
          </p>
          <p>
            They will not be called.{" "}
            <strong className="font-semibold text-ink">
              Nobody tells them the call is off
            </strong>{" "}
            — if it matters, ring them yourself.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}

function CallbackRow({
  callback,
  stopping,
  onStop,
}: {
  callback: ScheduledCallback;
  stopping: boolean;
  onStop: () => void;
}) {
  // `lookup`, never a bare index (src/lib/lookup.ts): `status` is a WIRE string, and
  // indexing a plain object with one resolves `constructor` to a function, which
  // React then tries to render.
  const heading = lookup(HEADINGS, callback.status) ?? callback.status;
  return (
    <li className="flex items-start gap-3 p-4">
      <PhoneForwarded aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-ink">
          <MonoValue className="tabular-nums text-ink">{callback.phone_e164}</MonoValue>{" "}
          <span className="text-ink-muted">·</span> {formatIST(callback.requested_at)}
        </p>
        <p className="mt-0.5 text-xs font-medium text-ink-muted">{heading}</p>
        {callback.explanation && (
          <p className="mt-1 text-xs text-ink-muted">{callback.explanation}</p>
        )}
        {callback.note && (
          <p className="mt-1 text-xs italic text-ink-muted">
            They said: {callback.note}
          </p>
        )}
      </div>
      {/* Only where there is something to stop. `dialing` is deliberately excluded — that
          phone may be ringing as this renders, and a button that reported success while
          somebody answered would be the screen lying about a call that happened. */}
      {callback.status === "scheduled" && (
        <button
          type="button"
          className="shrink-0 text-sm font-medium text-ink-muted underline underline-offset-2 hover:text-ink disabled:opacity-50"
          disabled={stopping}
          onClick={onStop}
        >
          {stopping ? "Calling it off…" : "Call it off"}
        </button>
      )}
      {callback.status === "dialing" && (
        <span className="shrink-0 text-xs text-ink-faint">Too late to stop</span>
      )}
      {!LIVE.has(callback.status) && callback.settled_at && (
        <span className="shrink-0 text-xs text-ink-faint">
          {formatIST(callback.settled_at)}
        </span>
      )}
    </li>
  );
}
