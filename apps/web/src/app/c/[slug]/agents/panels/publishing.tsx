"use client";

/**
 * WHAT CALLERS HEAR RIGHT NOW — the staged-versus-live state, the voice in force, and the
 * cost guard, as three pieces the workspace's sections place where each is read.
 *
 * Every number and label here is the server's or is absent: the call cap, the worst-case
 * cost, the version numbers and the voice all come from `GET /v1/agents/{id}/pending`, which
 * the caller reads once and hands down. Loading and failure are the caller's branches.
 */

import { Hourglass } from "lucide-react";

import { formatCallCap, formatINR, formatIST, formatRupeeRate } from "@/components/ui";
import { SettingRow } from "@/components/console/settingRow";
import type { PendingChange, PendingState } from "@/lib/api/publishing";
import { voiceTierRate } from "@/lib/api/voices";

/** The field name the server gives a staged script in `PendingOut.pending`. */
export const SCRIPT_FIELD = "script";

/** The staged script, if one is waiting — the only staged change the owner applies. */
export function stagedScript(state: PendingState): PendingChange | undefined {
  return state.pending.find((change) => change.field === SCRIPT_FIELD);
}

/**
 * The unsaved-changes banner (§2b). `headline` and `why` are rendered as sent: the server
 * composes them from version NUMBERS (a prompt body carries the client's prices and staff
 * names — hard rule 6), and restating them here would be a second source for one sentence.
 *
 * Renders nothing when nothing is waiting; the "Live" line in the header says the rest.
 */
export function PendingBanner({ state }: { state: PendingState }) {
  if (!state.has_pending) return null;
  return (
    <div role="status" className="rounded-md border border-warn-line bg-warn-soft px-4 py-3 text-sm text-ink">
      <p className="flex items-center gap-2 font-semibold">
        <Hourglass aria-hidden className="h-4 w-4 shrink-0 text-warn" />
        Changes waiting to go live
      </p>
      <ul className="mt-3 space-y-3">
        {state.pending.map((change) => (
          <PendingRow key={change.field} change={change} />
        ))}
      </ul>
      <p className="mt-3 text-xs text-ink-muted">
        Callers keep hearing the live version until the change is applied — nothing goes
        live silently.
        {stagedScript(state) ? " Apply it from the top of this page, or undo it in the script builder." : ""}
      </p>
    </div>
  );
}

/**
 * One staged change, with BOTH pointers named as labelled data. Showing the staged script
 * as the one callers hear is the one catastrophic misreading of the two-speed model, and a
 * sentence can be read the wrong way round where a "Callers hear now" / "Waiting to be
 * applied" pair cannot.
 */
function PendingRow({ change }: { change: PendingChange }) {
  return (
    <li className="border-l-2 border-warn-line pl-3">
      <p className="font-medium">{change.headline}</p>
      <dl className="mt-2 flex flex-wrap gap-x-8 gap-y-2">
        <div>
          <dt className="text-xs text-ink-muted">Callers hear now</dt>
          <dd className="text-sm font-semibold tabular-nums">
            {change.live_version === null ? "Nothing live yet" : `v${change.live_version}`}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-ink-muted">Waiting to be applied</dt>
          <dd className="text-sm font-semibold tabular-nums">v{change.staged_version}</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs">{change.why}</p>
      <p className="mt-1 text-xs text-ink-muted">Waiting since {formatIST(change.staged_at)}</p>
    </li>
  );
}

/**
 * The voice callers hear, its quality and this account's rate for it, and — only when the
 * server says they differ — the voice chosen and not yet on the calling system.
 *
 * The quality is named and the vendor never is: "Clear" and "Studio" are the API's words.
 * The rate is the account's next minute (oldest open credit lot, D-547) and is simply not
 * printed when absent — quoting a rate a client is not on is the money defect hard rule 7
 * exists for. The tier priced is the LIVE voice's, because that is the one being billed.
 */
export function VoiceNow({ state, published }: { state: PendingState; published: boolean }) {
  const voice = state.voice;
  // Absent on an older API build; a missing fact is honest, an invented one is not.
  if (!voice) return null;
  // No voice configured at all is its own answer, and the server's headline says it ("No
  // voice has been set on this agent."): an agent published with none speaks in the
  // calling system's default, which is not a voice we can name — but it is not "unknown".
  const noneSet = voice.live === null && voice.configured === null;
  // A voice the calling platform supplies itself carries no provider and no entry in our
  // catalogue; the server's headline names it ("Callers hear Anika."), shown instead of its id.
  const shown = voice.live ?? voice.configured;
  const engineVoice = shown != null && shown.provider === null && shown.catalog === null;
  const heard = engineVoice
    ? published
      ? "Chosen"
      : "Chosen, used once switched on"
    : voice.live
    ? clientVoiceName(voice.live)
    : noneSet
      ? "None chosen"
      : published
        ? "We cannot say from here"
        : "Nothing yet";
  const tier = voiceTierRate(state.voice_tier_rates, voice.live?.voice_tier);
  return (
    <>
      <SettingRow
        label="Voice callers hear"
        hint={
          engineVoice
            ? voice.headline
            : voice.live
            ? "The voice the calling system is speaking in right now."
            : noneSet
              ? voice.headline
              : published
              ? "The calling system has a voice for this agent; we have no record of which one. Choosing one below will settle it."
              : "Nothing is on the calling system yet, so no caller hears a voice at all."
        }
        value={heard}
      />
      {voice.unnamed_note && (
        /* The server's sentence for a voice shown as a stored code rather than a name (D-617). */
        <p className="py-2 text-xs text-ink-muted">{voice.unnamed_note}</p>
      )}
      {tier && (
        <SettingRow
          label={tier.inr_per_min === null ? "Voice quality" : "Voice quality and rate"}
          hint={
            /* No rate means no open credit lot — an empty or overdrawn wallet — so the
               action is the owner's own, never a person's. */
            tier.inr_per_min === null
              ? "You have no credit left, so nothing sets a per-minute price for this voice yet. The credit pack you buy fixes the rate you pay on it."
              : tier.further_open_lots === 0
                ? "What a minute on this voice costs against your current credit."
                : `What a minute on this voice costs against your oldest unspent credit. You have ${tier.further_open_lots} later purchase${tier.further_open_lots === 1 ? "" : "s"} behind it, each at the rates it was bought at.`
          }
          value={
            <>
              {tier.label}
              {tier.inr_per_min === null ? "" : ` — ${formatRupeeRate(tier.inr_per_min)} / min`}
            </>
          }
        />
      )}
      {voice.republish_required && voice.configured && (
        <SettingRow
          label="New voice waiting"
          hint="Chosen for this agent and not on the calling system yet."
          value={clientVoiceName(voice.configured)}
        />
      )}
    </>
  );
}

/** The cost-runaway guard, as the question it answers: what is the worst one call can do. */
export function WorstCaseCost({ state }: { state: PendingState }) {
  return (
    <SettingRow
      label="Most one call can cost you"
      hint={
        /* Struck from the dearest minute the account can be charged — the plan's overage
           rate, or the rate on a prepaid account's own credit (`publishing.py::worst_case_rate`),
           so neither sentence names "your plan". */
        state.worst_case_call_cost_inr === null
          ? "Nothing on your account prices a minute yet, so we cannot put a number on it. The credit pack you buy sets that rate."
          : "A call that runs the full limit, at the dearest per-minute rate your account can be charged. Almost every call ends long before this."
      }
      /* Null is "we cannot say", NOT zero. The figure stays a string: `formatINR` formats
         the digits and never parses them (hard rule 7). */
      value={
        state.worst_case_call_cost_inr === null
          ? "We cannot say yet"
          : formatINR(state.worst_case_call_cost_inr)
      }
    />
  );
}

/** The limit in force, for the read-only view of a deleted agent. */
export function CallCapFact({ state }: { state: PendingState }) {
  return (
    <SettingRow
      label="Longest one call may run"
      hint={
        state.call_cap_is_platform_default
          ? "The standard limit we put on every agent."
          : "Set specifically for this agent."
      }
      value={formatCallCap(state.effective_call_cap_s)}
    />
  );
}

/** A voice in words a client recognises; an id the catalogue no longer lists is shown as
 *  itself, because an owner can quote an id and "unknown" reads as a fault. */
export function clientVoiceName(voice: NonNullable<PendingState["voice"]["configured"]>): string {
  return voice.catalog?.label ?? voice.voice_id;
}
