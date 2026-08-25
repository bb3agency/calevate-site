"use client";

/**
 * WHAT CALLERS HEAR RIGHT NOW — the staged-versus-live surface, and the cost guard.
 *
 * Split out of the 1,185-line `agents/panels.tsx`, which had grown into four unrelated
 * subjects behind one filename (UX-DOCTRINE §6: a module is bounded by ONE subject, and a
 * route module past ~400 lines is a smell whose remedy is extract / route-split /
 * disclose). This file is the first subject: publishing state.
 *
 * EVERY number and label here is the server's or is absent: the call cap, its bounds, the
 * worst-case cost, the version numbers and the voice all come from
 * `GET /v1/agents/{id}/pending`. Loading is a `Skeleton`, failure is a `ProblemNotice`,
 * and neither is ever a zero.
 */

import { Hourglass, IndianRupee, Timer, Volume2 } from "lucide-react";

import {
  Fact,
  NOTICE_TONES,
  ProblemNotice,
  Skeleton,
  formatCallCap,
  formatINR,
  formatIST,
} from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import {
  usePendingChanges,
  type PendingChange,
  type PendingState,
} from "@/lib/api/publishing";
import { useClientSession } from "@/lib/api/session";

/**
 * The unsaved-changes banner (§2b) and the cost-runaway guard, from the client's side of
 * the fence.
 *
 * `headline` and `why` are rendered as sent. The server composes them from version NUMBERS
 * (a prompt body carries the client's prices and staff names — hard rule 6), and restating
 * them here would be a second source for one sentence.
 *
 * Takes the whole `agent` rather than an id: `PendingOut` carries `published` and
 * `agent_status` too, and reading THOSE here would give one screen two sources for one
 * fact — the badge above says "Being set up" from the roster read while this paragraph
 * could say the opposite from a response that landed a second later. The agent row is the
 * screen's single source; the pending read supplies only what it does not have.
 */
export function PublishingPanel({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const pending = usePendingChanges(session, agent.id);

  if (pending.isLoading) return <Skeleton rows={2} />;
  if (pending.error) {
    return <ProblemNotice error={pending.error} onRetry={() => void pending.refetch()} />;
  }
  if (!pending.data) return null;

  const state = pending.data;

  return (
    <div className="space-y-3">
      {state.has_pending ? (
        <div role="status" className={`rounded-card border p-4 text-sm ${NOTICE_TONES.warn}`}>
          <p className="flex items-center gap-2 font-semibold">
            <Hourglass aria-hidden className="h-4 w-4 shrink-0" />
            Changes waiting to go live
          </p>
          <ul className="mt-3 space-y-3">
            {state.pending.map((change) => (
              <PendingRow key={change.field} change={change} />
            ))}
          </ul>
          <p className="mt-3 text-xs">
            {/* NOT "the version above": the line above is the WAITING one. Which pointer is
                which is rendered as data in `PendingRow`; this sentence only says who
                moves it. */}
            Callers keep hearing the live version until your account manager applies the
            change — nothing goes live silently. Ask them to apply it, or to discard it if
            it was not meant to happen.
          </p>
        </div>
      ) : (
        /* The reassuring case is worth a line: an owner who has been told an edit was made
           needs to be able to see that it HAS landed, not just infer it from the absence
           of a warning. It says something different for an agent no caller can reach yet —
           "what callers hear right now" is not a true sentence about an agent that is not
           on the calling system. */
        <p className="text-sm text-ink-muted">
          {agent.published
            ? "Nothing is waiting to go live — what is described on this page is what callers hear right now."
            : "Nothing is waiting to go live. This agent is not on the calling system yet, so no caller hears it at all."}
        </p>
      )}

      {/* The cost-runaway guard, as the question it actually answers: what is the worst one
          call can do to my bill — plus the voice, which is a cost question too. */}
      <dl className="grid gap-5 rounded-card border border-line bg-app p-4 sm:grid-cols-2">
        <VoiceFacts state={state.voice} published={agent.published} />
        <Fact
          label="Longest one call may run"
          icon={<Timer className="h-3.5 w-3.5" />}
          hint={
            state.call_cap_is_platform_default
              ? "The standard limit we put on every agent."
              : "Set specifically for this agent."
          }
        >
          {formatCallCap(state.effective_call_cap_s)}
        </Fact>
        <Fact
          label="Most one call can cost you"
          icon={<IndianRupee className="h-3.5 w-3.5" />}
          hint={
            state.worst_case_call_cost_inr === null
              ? "Your plan does not quote a per-minute rate, so we cannot put a number on it. Your account manager can."
              : "A call that runs the full limit, at your plan's per-minute rate. Almost every call ends long before this."
          }
        >
          {/* Null is "we cannot say", NOT zero — quoting ₹0.00 for a ten-minute call is the
              one answer that is actively wrong (`publishing.py::_overage_rate`). The figure
              is an exact NUMERIC and stays a STRING all the way here: `formatINR` formats
              the digits and never parses them, because `Number("10159.00")` is how
              ₹10,159.00 becomes ₹10,158.999999999998 (hard rule 7). */}
          {state.worst_case_call_cost_inr === null
            ? "We cannot say yet"
            : formatINR(state.worst_case_call_cost_inr)}
        </Fact>
      </dl>
    </div>
  );
}

/**
 * The voice the caller hears — and, only when they differ, the one waiting for us.
 *
 * **Why a client sees this at all.** There is one voice quality now (the single-tier voice
 * decision) at one per-minute rate, so the voice is no longer a price lever — but a client
 * is still entitled to know which persona their agent speaks in, exactly as they read its
 * disclosure line. Changing it is still ours (D-21), which is why there is no control here,
 * only a fact and who moves it.
 *
 * **One box when there is one answer, two when there are two.** A configured voice the
 * calling system is already holding is a single fact. A voice chosen and not yet published
 * is TWO facts, and collapsing them would say the caller hears something they do not — the
 * same inversion `PendingRow` exists to prevent for the script. The server decides which
 * case this is (`voice.republish_required`); this component does not compare the two ids
 * itself, because an unpublished agent has two different values and no problem at all.
 */
function VoiceFacts({
  state,
  published,
}: {
  state: PendingState["voice"] | undefined;
  published: boolean;
}) {
  // The field is absent on an older API build; a missing fact is honest, an invented one
  // is not. Nothing else on this card depends on it.
  if (!state) return null;
  const heard = state.live
    ? clientVoiceName(state.live)
    : published
      ? "We cannot say from here"
      : "Nothing yet";
  return (
    <>
      <Fact
        label="Voice callers hear"
        icon={<Volume2 className="h-3.5 w-3.5" />}
        hint={
          state.live
            ? "The voice the calling system is speaking in right now."
            : published
              ? "The calling system has a voice for this agent; we have no record of which one. Your account manager can confirm it."
              : "Nothing is on the calling system yet, so no caller hears a voice at all."
        }
      >
        {heard}
      </Fact>
      {state.republish_required && state.configured && (
        <Fact
          label="New voice waiting"
          icon={<Hourglass className="h-3.5 w-3.5" />}
          hint="Chosen for this agent and not switched on yet. Your account manager publishes the agent to make callers hear it."
        >
          {clientVoiceName(state.configured)}
        </Fact>
      )}
    </>
  );
}

/** A voice in words a client recognises. Unknown to the catalogue is still named by its
 *  id — an owner can quote an id to their account manager, and "unknown" reads as a fault
 *  rather than as a voice we simply no longer list. */
function clientVoiceName(voice: NonNullable<PendingState["voice"]["configured"]>): string {
  return voice.catalog?.label ?? voice.voice_id;
}

/**
 * One staged change, with BOTH pointers named.
 *
 * The two-speed model has exactly one way to be catastrophically misread — showing the
 * staged script as the one callers hear — and `agents/publishing.py` opens by recording
 * that the backend shipped that inversion once already. So the pointers are rendered as
 * labelled DATA (`live_version`, `staged_version`) rather than left to the prose: a
 * sentence can be read the wrong way round, a two-item list under "Callers hear now" and
 * "Waiting to be applied" cannot. It also covers what the server's headline leaves out —
 * `live_version` is null for an agent whose script has never been applied.
 */
function PendingRow({ change }: { change: PendingChange }) {
  return (
    <li className="border-l-2 border-amber-400 pl-3">
      <p className="font-medium">{change.headline}</p>
      <dl className="mt-2 flex flex-wrap gap-x-8 gap-y-2">
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-wide opacity-70">
            Callers hear now
          </dt>
          <dd className="text-sm font-semibold tabular-nums">
            {change.live_version === null ? "Nothing live yet" : `v${change.live_version}`}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-wide opacity-70">
            Waiting to be applied
          </dt>
          <dd className="text-sm font-semibold tabular-nums">v{change.staged_version}</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs">{change.why}</p>
      <p className="mt-1 text-xs opacity-80">Waiting since {formatIST(change.staged_at)}</p>
    </li>
  );
}
