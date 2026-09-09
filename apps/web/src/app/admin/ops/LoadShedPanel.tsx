"use client";

import { useState } from "react";
import { Gauge, Lock, TriangleAlert } from "lucide-react";

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
import {
  useSetPlatformState,
  type LoadShedMode,
  type PlatformState,
} from "@/lib/api/admin";
import { hasKey, lookup } from "@/lib/lookup";
import { loadShedModeCopy } from "@/app/admin/ops/opsLanguage";

import type { OpsAccess } from "./opsAccess";

/** Two sentences per mode: what it is doing now, and what choosing it would do. */
interface LoadShedNote {
  /** Printed for the mode the platform IS in. Present tense, a statement of fact. */
  now: string;
  /** Printed above the button for the mode being CHOSEN, before the click. */
  blast: string;
}

/**
 * What each load-shed mode actually sheds, in one place — and the copy was rewritten
 * against `core/loadshed.py` rather than carried over, because the old wording was wrong
 * in the direction that matters when someone is choosing a mode mid-incident.
 *
 * `is_shed()` is four lines: never shed the always-allowed prefixes; shed EVERYTHING in
 * `maintenance`; otherwise shed non-GET in `reduced`, `emergency` and `maintenance`. So
 * `emergency` does NOT stop reads (the old copy said "Reads only"), `reduced` does not
 * shed only "expensive" writes (it sheds all of them), and — the fact an operator most
 * needs before picking one — **`reduced` and `emergency` shed exactly the same set
 * today.** Saying that out loud is the point: an operator who picks `emergency` believing
 * it does more has spent the escalation and bought nothing.
 *
 * `lookup()` rather than `LOAD_SHED[mode]` at the READ site: `load_shed_mode` is a bare
 * `string` on the wire, so a mode named after an `Object.prototype` member would resolve
 * to the `Object` FUNCTION and render as `function Object() { [native code] }` under a
 * heading an operator is reading mid-incident. Missing fails VISIBLE — the mode is still
 * printed, because a mode this build has no copy for is exactly the one worth reading.
 *
 * `Record<LoadShedMode, …>` over the GENERATED union (not `Record<string, …>`) so that a
 * fifth mode added server-side fails `tsc` here instead of arriving as a mode the console
 * can display but never offer.
 */
const LOAD_SHED: Record<LoadShedMode, LoadShedNote> = {
  normal: {
    now: "Everything is working normally.",
    blast:
      "Takes the platform out of its protective slowdown: clients can make changes again, and new self-serve sign-ups reopen.",
  },
  reduced: {
    now: "Clients can’t make changes right now — launching campaigns, saving agents and adding leads are paused. They can still view everything.",
    blast:
      "Clients stop being able to make changes — launching a campaign, saving an agent, adding a lead. They can still view everything, and a campaign that is already running keeps dialling (a running campaign doesn’t depend on the website). New self-serve sign-ups are turned away.",
  },
  emergency: {
    now: "Clients can’t make changes right now — launching campaigns, saving agents and adding leads are paused. They can still view everything.",
    blast:
      "Pauses exactly what “Reduced” pauses. Today this is a louder label for the same thing, not a stricter one — choose it to signal how serious the situation is, not because it stops more.",
  },
  maintenance: {
    now: "Planned downtime: clients can’t view or change anything. Only calls, sign-in and this operations console keep working.",
    blast:
      "Client screens go dark — a client opening their dashboard sees a “temporarily unavailable” message. Live calls are unaffected, so no lead is lost. This operations console keeps working, so you can always bring the platform back.",
  },
};

/** Offered in this order on purpose: least to most shed. */
const LOAD_SHED_MODES = Object.keys(LOAD_SHED) as LoadShedMode[];

/**
 * The load-shed mode — the second switch on the global row, and until now the one this
 * console could READ and not move.
 *
 * That gap is why `runbooks/calls-stopped.md` §2 sent an operator to a hand-written curl
 * with a step-up header in it, mid-incident, against production. Everything that makes the
 * halt switch safe applies here unchanged and for the same reasons, so none of it is
 * re-argued below — but two properties are this control's own:
 *
 * 1. **The form opens on NO CHANGE.** `target` is seeded from the mode the platform is
 *    actually in, so the button is dead until the operator has chosen a different one.
 *    A screen that preselected `normal` would make "click the obvious button" a release
 *    of a shed somebody imposed twenty minutes ago for a reason nobody has read yet.
 * 2. **The confirmation carries the TARGET MODE**, in the typed word and in the header
 *    (`set_load_shed:<mode>`, `platformConfirmation`). The API binds it that way because
 *    consent to `reduced` is not consent to `maintenance`; the typed word says the same
 *    thing to the human, so the two cannot drift apart in an operator's habits.
 *
 * The mode the platform is IN is printed from the server's string even when this build
 * has no copy for it — see `LOAD_SHED` on why that fails visible rather than silent.
 */
export function LoadShedPanel({ state, access }: { state: PlatformState; access: OpsAccess }) {
  const setState = useSetPlatformState();
  const current = state.load_shed_mode;
  // A mode this build cannot name seeds `normal`: it is the only direction that is
  // meaningful to offer out of a state this console cannot describe, and it is still a
  // deliberate choice the operator has to type a word for.
  const [target, setTarget] = useState<LoadShedMode>(
    hasKey(LOAD_SHED, current) ? current : "normal",
  );
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");

  const note = lookup(LOAD_SHED, current);
  const confirmWord = target.toUpperCase();
  // The server would accept a request that re-asserts the current mode and would write an
  // audit row for it — a recorded platform change nobody made. `platform_confirmation`
  // refuses the empty transition for that exact reason; this is the same objection one
  // step earlier, where the operator can still see it.
  const unchanged = target === current;
  const valid = useFormValidation();
  // The reason is answered at its own control now — pressing the button with an
  // empty reason says so rather than doing nothing. The typed word stays in `ready`:
  // it is a gate on the act, not an answer on the form.
  const ready = !unchanged && confirm === confirmWord;

  return (
    <Card title="Protective slowdown">
      <div className="space-y-4">
        <NoticeBox
          tone={current === "normal" ? "ok" : "warn"}
          icon={<Gauge aria-hidden className="h-5 w-5" />}
          title={loadShedModeCopy(current).label}
        >
          <p className="mt-1">
            {note?.now ?? (
              <>
                This console has no description for that mode, so treat it as unknown until
                someone can confirm what it does.
              </>
            )}
          </p>
        </NoticeBox>

        {setState.error && (
          <WriteFailure
            error={setState.error}
            actionLabel={`Switch to “${loadShedModeCopy(target).label}”`}
          />
        )}

        <form
          className="space-y-3"
          noValidate
          onSubmit={valid.onSubmit(() => {
            setState.mutate(
              { loadShedMode: target, reason: reason.trim() },
              {
                onSuccess: () => {
                  setReason("");
                  setConfirm("");
                },
              },
            );
          })}
        >
          <label className="block">
            <span className={FIELD_LABEL}>Change the mode to</span>
            <select
              value={target}
              onChange={(e) => {
                setTarget(e.target.value as LoadShedMode);
                // The confirmation word IS the target mode, so a word typed for a
                // different target must not survive the change and submit silently.
                setConfirm("");
              }}
              disabled={!access.allowed}
              className={FIELD}
            >
              {LOAD_SHED_MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {loadShedModeCopy(mode).label}
                  {mode === current ? " — in force now" : ""}
                </option>
              ))}
            </select>
          </label>

          {/* WHAT THE BUTTON DOES, ABOVE THE BUTTON — for the mode being chosen, not for
              the one in force. Every mode here refuses requests for every client at once. */}
          <div className="flex gap-3 rounded-card border border-line bg-surface p-4 text-sm">
            <TriangleAlert
              aria-hidden
              className={`mt-0.5 h-4 w-4 shrink-0 ${
                target === "normal" ? "text-ink-faint" : "text-rose-600"
              }`}
            />
            <div className="min-w-0">
              <p className="font-semibold text-ink">
                {unchanged
                  ? `The platform is already in “${loadShedModeCopy(current).label}”`
                  : `Switching to “${loadShedModeCopy(target).label}” applies to every client at once`}
              </p>
              <p className="mt-1 text-ink-muted">{LOAD_SHED[target].blast}</p>
              <p className="mt-1 text-xs text-ink-faint">
                Recorded in the activity log against your admin account, with the reason
                you type below. This does not stop a campaign that is already running, and
                it never affects inbound calls.
              </p>
            </div>
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
              placeholder="e.g. 'database under heavy load — pausing changes until it recovers'"
              className={FIELD}
            />
            {valid.error("reason")}
            <span className={FIELD_HINT}>
              Whoever finds the platform slowed reads this to decide whether the condition
              still holds.
            </span>
          </label>

          <label className="block">
            <span className={FIELD_LABEL}>Type {confirmWord} to confirm</span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={!access.allowed || unchanged}
              placeholder={confirmWord}
              className={`${FIELD} font-mono`}
            />
          </label>

          <button
            type="submit"
            title={access.reason ?? undefined}
            disabled={!access.allowed || !ready || setState.isPending}
            className={target === "normal" ? PRIMARY_BUTTON : DANGER_BUTTON}
          >
            <Gauge aria-hidden className="h-4 w-4" />
            {setState.isPending ? "Sending…" : `Switch to “${loadShedModeCopy(target).label}”`}
          </button>

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
