"use client";

/**
 * HOW THE AGENT SOUNDS, AND HOW LONG ONE CALL MAY RUN — the two settings D-586 put in the
 * account's own hands, as controls rather than as facts.
 *
 * ## What this panel is, and what the panel above it stays
 *
 * `panels/publishing.tsx` answers "what callers hear RIGHT NOW": the staged-versus-live
 * banner, the voice in force, the worst-case cost. It is a READ, it is the first thing on
 * the screen, and it stays one — a control belongs beside the thing it changes, and that
 * panel's subject is the state, not the decision (UX-DOCTRINE §6: one subject per module).
 * This one is the decision.
 *
 * ## Both of these apply to the NEXT call, and the copy says so rather than implying it
 *
 * The server writes the row and re-publishes a live agent in the SAME transaction
 * (`agents/publishing.py`), so there is no Apply step and no "waiting to go live" state for
 * either — which is exactly what `GET /v1/agents/lanes` publishes as the `live` lane and
 * what the lane guide renders. What a client has to be told is the one thing a transaction
 * cannot decide: a call that is already in progress finishes as it started. Saying "applies
 * immediately" without that sentence is how somebody comes to believe a shorter cap cuts
 * off the call they are listening to.
 *
 * ## Nothing here composes a refusal of its own
 *
 * A voice that cannot be chosen on this account carries the server's own sentence, in the
 * CLIENT's language — the tier's name and the one action they have, never a vendor and
 * never one of our settings (`agents/voice_offer.py::client_unofferable_reason`). The
 * picker prints it verbatim. A cap outside the allowed range is refused server-side with
 * `call_cap_out_of_range`; the bounds come from `GET /v1/agents/lanes`, so this form hints
 * them and never hardcodes a second copy. A vendor refusal on the re-publish arrives as a
 * `dependency` problem and NOTHING was saved — the row and the phone line still agree, and
 * `ProblemNotice` says so in the server's words.
 *
 * ## Why there is no permission gate in this file
 *
 * `agents:write` is held by `owner` and `staff`, which is every role that can open this
 * screen at all, so a disabled control here could only ever be disabled for a population
 * that does not exist. If that changes, the refusal is a 403 problem+json rendered by
 * `ProblemNotice` — the server is the enforcement, and a second copy of the rule in
 * TypeScript is the one that goes stale.
 */

import { Timer, Volume2 } from "lucide-react";
import { useState } from "react";

import { FieldMessage, useFormValidation } from "@/components/formValidation";
import {
  FIELD,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SectionHeading,
  Skeleton,
  formatCallCap,
} from "@/components/ui";
import { VoicePicker } from "@/components/voicePicker";
import type { Agent } from "@/lib/api/agents";
import {
  useLanes,
  usePendingChanges,
  useSetMyCallCap,
  type PendingState,
} from "@/lib/api/publishing";
import { useClientSession } from "@/lib/api/session";
import { useSetMyAgentVoice, useVoiceCatalogue } from "@/lib/api/voices";

/** One sentence, shared by both controls, because it is one promise. */
const NEXT_CALL_NOTE =
  "Saved changes reach the calling system straight away and apply from the next call. " +
  "A call already in progress finishes exactly as it started.";

export function DeliverySettings({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const pending = usePendingChanges(session, agent.id);

  if (pending.isLoading) return <Skeleton rows={3} />;
  if (pending.error || !pending.data) {
    // ONE ALERT PER FAILED READ, ON A SCREEN WHERE TWO PANELS SHARE ONE REQUEST. The panel
    // above this one is built on the same `/pending` read and already renders the refusal
    // with its retry; a second `ProblemNotice` here would be the same server message in
    // two cards, and the reader would have to work out whether two things had failed.
    // `tests/agentDetail.test.tsx` asserts the single alert, and it says why: the case was
    // written after a duplicate won a race and made the assertion flaky.
    //
    // Not silence either. A control section that vanished when a read failed would read as
    // "this account cannot change these", which is a claim about permissions rather than
    // about a request — so the section states what it is, in plain text, and offers nothing
    // to press. There is nothing safe to press: the current voice and the current cap are
    // both in the response that did not arrive, so every control here would start from a
    // value nobody has.
    return (
      <p className="text-sm text-ink-muted">
        This agent&apos;s current voice and call limit could not be read just now, so there
        is nothing to change here until they load.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <VoiceChoice agentId={agent.id} state={pending.data} />
      <CallCapChoice agentId={agent.id} state={pending.data} />
    </div>
  );
}

/**
 * The picker, with every voice this deployment knows about and the reason on the ones that
 * cannot be chosen.
 *
 * `choice` is `null` until the client touches the control, so the radio group shows the
 * CONFIGURED voice from the server rather than an empty selection — the same shape, and the
 * same reason, as the cap field below: an explicit choice and "not edited on this visit"
 * are different states and collapsing them makes a re-render look like an edit.
 */
function VoiceChoice({ agentId, state }: { agentId: string; state: PendingState }) {
  const session = useClientSession();
  const catalogue = useVoiceCatalogue(session);
  const save = useSetMyAgentVoice(session, agentId);
  const [choice, setChoice] = useState<string | null>(null);
  const selected = choice ?? state.voice.configured?.voice_id ?? "";

  return (
    <section>
      <SectionHeading icon={<Volume2 className="h-3.5 w-3.5" />}>
        The voice it speaks in
      </SectionHeading>
      <div className="mt-3 space-y-3">
        {save.error && <ProblemNotice error={save.error} />}

        {/* A read like any other: a skeleton while it is in flight and a refusal when it
            failed — never an empty list, which reads as "this agent has no voices
            available" and is a claim about the product rather than about a request. */}
        {catalogue.isLoading ? (
          <Skeleton rows={2} />
        ) : catalogue.error || !catalogue.data ? (
          <ProblemNotice
            error={
              catalogue.error ??
              new Error("The voices did not load, so there is nothing to choose from.")
            }
            onRetry={() => void catalogue.refetch()}
          />
        ) : !catalogue.data.selectable ? (
          /* THE CALLING SYSTEM SUPPLIES ITS OWN VOICES (D-93). A product fact, not a
             fault, so it is stated in the server's own words and NOT through
             `ProblemNotice` — an error card here would send a client to support about a
             deployment working exactly as intended. The picker is not rendered at all
             rather than rendered-and-disabled: a greyed list of personas still tells the
             reader those are the voices this agent might speak, and they are not. */
          <p className="text-sm text-ink-muted">{catalogue.data.note}</p>
        ) : (
          <form
            className="space-y-3"
            // A radio group always has a value chosen, so there is no rule to word.
            // `noValidate` so a rule added later cannot be answered by the browser in its
            // own language instead of ours.
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              save.mutate(selected);
            }}
          >
            <VoicePicker
              name="my-agent-voice"
              legend="Voice"
              hint={catalogue.data.note}
              voices={catalogue.data.voices}
              value={selected}
              rates={state.voice_tier_rates}
              onChange={setChoice}
            />
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={save.isPending || selected === ""}
                className={PRIMARY_BUTTON_SM}
              >
                {save.isPending ? "Saving…" : "Use this voice"}
              </button>
              <span className="text-xs text-ink-muted">{NEXT_CALL_NOTE}</span>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}

/**
 * The cost-runaway guard, as the question it answers: what is the worst one call can do.
 *
 * The bounds and the default are the SERVER's (`GET /v1/agents/lanes`) — a second copy in
 * TypeScript is how a form comes to accept what the API refuses. When that read fails the
 * field stays usable and says the range is unknown rather than being withdrawn: the server
 * is the enforcement, and blocking the input would stop work the client can still do.
 */
function CallCapChoice({ agentId, state }: { agentId: string; state: PendingState }) {
  const session = useClientSession();
  const lanes = useLanes(session);
  const save = useSetMyCallCap(session, agentId);
  const valid = useFormValidation();
  // `null` = untouched on this visit, so the box shows the agent's own override and an
  // account on the platform default starts EMPTY — which is what clearing it means.
  const [seconds, setSeconds] = useState<string | null>(null);
  const field =
    seconds ??
    (state.call_cap_is_platform_default ? "" : String(state.effective_call_cap_s));
  const trimmed = field.trim();
  // Empty is a real choice — "go back to the standard limit" — and is NOT the same as 0.
  const parsed = trimmed === "" ? null : Number(trimmed);

  return (
    <section>
      {/* NOT "Longest one call may run", which is the FACT's label one panel up
          (`panels/publishing.tsx`). One screen, one phrase per thing: the panel above
          reports the limit in force, this one is where it is decided, and two headings
          reading identically make a reader think one of them is stale. */}
      <SectionHeading icon={<Timer className="h-3.5 w-3.5" />}>
        How long one call may run
      </SectionHeading>
      <p className="mt-2 text-sm text-ink-muted">
        A limit on how long a single call may go on — the guard against one call that never
        ends. It cannot change a word the agent says. Leave it empty to use the standard
        limit we put on every agent
        {lanes.data ? ` (${formatCallCap(lanes.data.call_cap_default_s)})` : ""}; there is
        no way to make a call unlimited, deliberately.
      </p>
      <div className="mt-3 space-y-3">
        {save.error && <ProblemNotice error={save.error} />}
        <form
          className="flex flex-wrap items-end gap-3"
          noValidate
          onSubmit={valid.onSubmit(() => {
            save.mutate({ max_call_duration_s: parsed });
          })}
        >
          <div className="flex flex-col gap-1">
            <label htmlFor="my-call-cap" className="text-xs text-ink-muted">
              Seconds
            </label>
            <input
              id="my-call-cap"
              {...valid.track("seconds", "Enter how many seconds a call may run.")}
              type="number"
              inputMode="numeric"
              value={field}
              min={lanes.data?.call_cap_min_s}
              max={lanes.data?.call_cap_max_s}
              onChange={(event) => setSeconds(event.target.value)}
              placeholder={
                lanes.data ? String(lanes.data.call_cap_default_s) : "standard limit"
              }
              className={`w-32 tabular-nums ${FIELD}`}
              aria-invalid={valid.message("seconds") ? true : undefined}
              aria-describedby={valid.message("seconds") ? "my-call-cap-error" : undefined}
            />
            {valid.message("seconds") ? (
              <FieldMessage id="my-call-cap-error">{valid.message("seconds")}</FieldMessage>
            ) : null}
          </div>
          <button type="submit" disabled={save.isPending} className={PRIMARY_BUTTON_SM}>
            {save.isPending ? "Saving…" : "Set limit"}
          </button>
          <span className="text-xs text-ink-muted">
            {parsed === null
              ? "Empty — the standard limit applies."
              : `${formatCallCap(parsed)} per call.`}
            {/* Three states, not two. `lanes` supplies this input's `min`/`max`, so a
                FAILED read silently removes the bounds from a control that is still
                pressable: the client types a value, the server refuses it, and nothing on
                the screen ever said the range was unknown. */}
            {lanes.isError
              ? " The allowed range could not be read, so this box is unbounded here; the" +
                " server will still refuse a value outside it."
              : ""}{" "}
            {NEXT_CALL_NOTE}
          </span>
        </form>
      </div>
    </section>
  );
}
