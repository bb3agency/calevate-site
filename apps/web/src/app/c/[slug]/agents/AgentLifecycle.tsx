"use client";

/**
 * Putting an agent on the phone, taking it off, and retiring it (D-440).
 *
 * ## What each button actually does on the server, because the copy has to match
 *
 * These are not column writes and the screen must not describe them as if they were:
 *
 * - **Switch on** is a PUBLISH. "Active" is a claim about the voice platform — that it is
 *   holding this agent's script, its voice and the truthful-answer directive — and D-64
 *   made `publish_agent` prove that by reading the agent back before any column says
 *   `live`. So switching on can legitimately FAIL, and the two ways it commonly does are
 *   worth a client understanding rather than being surprised by: an agent with no script
 *   yet (`agent_has_no_script`) and a voice platform that did not answer. Both arrive as
 *   problem+json with a remediation, which is what `ProblemNotice` renders.
 * - **Switch off** and **Archive** reach the engine too. `phone_numbers.agent_id` is our
 *   record of which numbers this agent answers, and both movers RELEASE them (D-420) —
 *   because a switched-off agent whose numbers still answer is a client's line still being
 *   picked up by an AI they switched off.
 * - **Restore** lands in the INACTIVE state, never straight back on the phone. The engine
 *   may have been reconfigured or drifted while the agent sat retired, and the only thing
 *   that can establish what it is holding is a publish with its read-back — so the owner
 *   switches it on deliberately, which runs that proof.
 *
 * ## Why archive gets a second step and the others do not
 *
 * `LaunchConfirm`'s shape, one rung down: consequences ABOVE the control, decision made
 * before the click. Archiving takes an agent off the roster and stops its numbers
 * answering, which is a change a client's customers feel — but unlike a campaign launch it
 * is REVERSIBLE (restore is one button away) and it dials nobody, so it earns a restated
 * panel and does not earn typing a word. Two ways of confirming one class of thing is a
 * defect even when both work; this is deliberately the same three beats with the ceremony
 * scaled to the blast radius.
 */

import { useState } from "react";
import { Archive, Power, PowerOff, Undo2 } from "lucide-react";

import {
  DANGER_BUTTON,
  NOTICE_TONES,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
} from "@/components/ui";
import { movesFor } from "@/lib/agentState";
import { useAgentLifecycle, type Agent, type LifecycleMove } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

interface MoveCopy {
  /** What the button says. */
  label: string;
  /** What it says while the request is in flight. */
  busy: string;
  /** The sentence beside it — what pressing it does, not what it is called. */
  hint: string;
  icon: typeof Power;
  danger?: boolean;
  /** Restated consequences, shown before the press. Absent = no second step. */
  confirm?: { title: string; points: string[]; go: string };
}

const MOVE_COPY: Record<LifecycleMove, MoveCopy> = {
  activate: {
    label: "Switch on",
    busy: "Switching on…",
    hint: "Puts it on the calling system and starts it taking calls. We check the platform is really running your script and voice before it goes live, so this can take a moment — and it is refused if the script has not been written yet.",
    icon: Power,
  },
  deactivate: {
    label: "Switch off",
    busy: "Switching off…",
    hint: "Stops it answering and dialling straight away. The numbers it answers are released, so they stop being picked up by this agent. Everything else is kept and switching it back on is one button.",
    icon: PowerOff,
  },
  archive: {
    label: "Archive",
    busy: "Archiving…",
    hint: "Retires it. Use this when you are finished with an agent rather than leaving it switched off forever.",
    icon: Archive,
    danger: true,
    confirm: {
      title: "Archiving this agent",
      points: [
        "It stops answering and dialling, and the numbers it answers are released.",
        "It can no longer be put on a campaign.",
        "Nothing is deleted. Its calls, recordings and everything it captured stay in your call log and your leads exactly as they are.",
        "You can bring it back at any time. It comes back switched off, and you switch it on again yourself.",
      ],
      go: "Archive this agent",
    },
  },
  restore: {
    label: "Bring it back",
    busy: "Restoring…",
    hint: "Takes it out of the archive. It comes back switched OFF — we do not put an agent straight back on the phone after it has been retired, because the calling system may have moved on while it was away. Switch it on when you are ready.",
    icon: Undo2,
  },
};

/**
 * The moves available on this agent, from `movesFor` — which mirrors the server's
 * transition table and fails closed on a status this build has never seen.
 */
export function AgentLifecycle({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const move = useAgentLifecycle(session, agent.id);
  /* `org:manage`, the OWNER's own permission — NOT `agents:write`, which is admin-only and
     which neither client role holds. See the header of `lib/api/agents.ts`. */
  const write = useWriteAccess(session, "org:manage", "change whether this agent is working");
  const [confirming, setConfirming] = useState<LifecycleMove | null>(null);

  const moves = movesFor(agent.status);
  if (moves.length === 0) {
    /* Not an empty panel: a status we cannot place is a fact worth stating, because the
       alternative is a client staring at an agent with no controls and no explanation. */
    return (
      <p className="text-sm text-ink-muted">
        We cannot tell from here what can be done with this agent. Your account manager can.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <RestrictionNote reason={write.reason} />
      {move.error && <ProblemNotice error={move.error} />}

      {moves.map((key) => {
        const copy = MOVE_COPY[key];
        const Icon = copy.icon;
        const open = confirming === key;
        return (
          <div key={key} className="rounded-card border border-line bg-app p-4">
            <p className="text-sm font-semibold text-ink">{copy.label}</p>
            <p className="mt-1 text-xs text-ink-muted">{copy.hint}</p>

            {copy.confirm && open && (
              /* `role="status"` because this panel APPEARS in response to something the
                 person did, and a consequence that exists only as newly-painted pixels is
                 a consequence a screen-reader user is asked to confirm without having been
                 told. Polite rather than `alert`: they asked for it, so it does not need to
                 interrupt — the same call `RowFailure` and `panels.tsx` already make.

                 FOCUS IS NOT MOVED and does not need to be: the trigger and the confirm
                 button are one `<button>` in one slot of one parent, so React reuses the
                 DOM node and the keyboard stays exactly where it was, on a control whose
                 name has become "Archive this agent". `agentDetail.test.tsx` pins
                 that — it is a property of the reconciliation, which a later refactor into
                 two sibling buttons would silently take away. */
              <div role="status" className={`mt-3 rounded-lg border p-3 text-xs ${NOTICE_TONES.warn}`}>
                <p className="font-semibold">{copy.confirm.title}</p>
                <ul className="mt-2 list-inside list-disc space-y-1">
                  {copy.confirm.points.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-3 flex flex-wrap gap-2">
              {copy.confirm && !open ? (
                <button
                  type="button"
                  onClick={() => setConfirming(key)}
                  disabled={!write.allowed}
                  title={write.reason ?? undefined}
                  className={SECONDARY_BUTTON}
                >
                  <Icon aria-hidden className="h-4 w-4" />
                  {copy.label}…
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setConfirming(null);
                    move.mutate(key);
                  }}
                  disabled={!write.allowed || move.isPending}
                  title={write.reason ?? undefined}
                  className={copy.danger ? DANGER_BUTTON : PRIMARY_BUTTON}
                >
                  <Icon aria-hidden className="h-4 w-4" />
                  {move.isPending && move.variables === key
                    ? copy.busy
                    : (copy.confirm?.go ?? copy.label)}
                </button>
              )}
              {copy.confirm && open && (
                <button
                  type="button"
                  onClick={() => setConfirming(null)}
                  className={SECONDARY_BUTTON}
                >
                  Keep it
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
