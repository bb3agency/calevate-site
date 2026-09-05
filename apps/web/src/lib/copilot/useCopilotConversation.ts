"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiProblem, type Session } from "@/lib/api/client";

import { clearConversation, loadConversation } from "./conversation";
import { clearFilled, markFilled } from "./highlight";
import { redactForWire } from "./redaction";
import { askCopilot, type CopilotAskBody } from "./stream";
import type {
  CopilotAction,
  CopilotFillItem,
  CopilotNavigation,
  CopilotProposal,
  CopilotStep,
} from "./types";
import type { SurfaceHolder } from "./registry";

/**
 * One conversation with the screen assistant: what has been said, what is streaming, what
 * it filled in, and how to put that back.
 *
 * All of the panel's behaviour lives here rather than in the component, for the ordinary
 * reason (the rules are testable without a DOM) and one specific one: the UNDO CONTRACT is
 * the part most easily broken by a refactor, and it is three lines that have to stay
 * beside each other — capture the prior value BEFORE applying, capture it only ONCE per
 * field per batch, and restore through the screen's own `apply` rather than by any second
 * mechanism.
 *
 * ## Undo, exactly
 *
 * "One batch, one undo" means the batch is the whole EXCHANGE, not one `fill` event: a
 * model that answers with two `fill` events has still answered one question, and two
 * undos for one answer is a person clicking until something looks right. So the priors
 * accumulate across the exchange into one map, first-write-wins — if the model fills
 * `terms-monthly` twice, the prior we restore is what was there before the ANSWER, not
 * what its own first fill put there.
 *
 * A prior of `""` is a real prior. "Was empty" is the most common state of a field an
 * assistant fills, and an undo that skipped empties would leave exactly the values a
 * person most wants removed.
 */

/**
 * One thing said, in BOTH forms.
 *
 * `content` is what the person reads — placeholders restored to the real digits.
 * `wire` is what may be sent back as history, with the placeholders still in place.
 *
 * TWO FIELDS BECAUSE ONE WAS A LEAK. Restoring the assistant's answer for display and
 * then replaying that same restored string as `history` on the next question would hand
 * the server the exact digits the field redaction had just withheld — G-2 defeated on
 * the second turn of every conversation, and invisibly, because the first request looks
 * perfect. The panel renders `content`; `stream.ts` is only ever given `wire`.
 *
 * The placeholder numbering is per-exchange, so `«PHONE_1»` in an older turn is only
 * still the same number if the screen's field list has not been reordered since. It has
 * not been, in practice — a screen's declaration is static for its lifetime — and the
 * failure mode if it ever were is a model confusing two of its own placeholders, never a
 * value escaping.
 */
export type CopilotTurn = { role: "user" | "assistant"; content: string; wire: string };

export interface CopilotBatch {
  /** What to send back through `apply` to undo. Includes the `""` priors. */
  priors: CopilotFillItem[];
  /** Field labels, in fill order — what the panel names in "filled 6 fields". */
  labels: string[];
  /** The ids to outline. Same order, same length as `labels`. */
  ids: string[];
}

export interface CopilotConversation {
  turns: CopilotTurn[];
  /** The answer currently arriving, or `null` when nothing is in flight. */
  streaming: string | null;
  asking: boolean;
  error: unknown;
  /** The server's sentence, rendered VERBATIM when present (D-127 G-6). */
  disclosure: string | null;
  batch: CopilotBatch | null;
  /**
   * The change the assistant is OFFERING to make, or `null`.
   *
   * Held here rather than in the panel for the reason the batch is: it belongs to the
   * EXCHANGE. A new question replaces it, exactly as a new question ends the previous
   * batch's Undo — a card left over from two answers ago is an offer about a screen state
   * nobody is looking at any more, and its token is minutes from expiring regardless.
   *
   * At most one is held. The server sends at most one per response, and a second would
   * REPLACE the first rather than stacking: two open proposals is a person choosing which
   * of two sentences they are agreeing to, which is the shape this whole design exists to
   * avoid.
   */
  proposal: CopilotProposal | null;
  /**
   * TIER 1 actions this exchange has already performed, oldest first. D-500.
   *
   * A LIST where `proposal` is a single value, and the difference is the promise. At most
   * one offer can be open at a time — two would be a person choosing which of two sentences
   * they are agreeing to — but an answer may genuinely DO more than one thing ("make an
   * inbound and an outbound agent"), and each of those is a receipt for something that has
   * already happened. Dropping the first to show the second would hide a change from the
   * person it was made for.
   */
  actions: CopilotAction[];
  /**
   * THE SCREEN THIS ANSWER ASKED TO OPEN, or `null`. D-524.
   *
   * A single value like `proposal` and not a list like `actions`, because one answer opens
   * at most one screen (the server caps it) and two destinations would be a flicker through
   * a screen nobody read.
   *
   * **HOLDING IT IS NOT PERFORMING IT.** Nothing in this hook moves anybody: the panel
   * decides, once the answer has finished arriving, whether the screen being left may hold
   * unsaved work, asks if it may, and only then calls the router. Navigating from inside the
   * stream handler would abort the answer mid-sentence — the dock closes the panel when the
   * surface changes, which aborts the in-flight request — so the person would lose the
   * sentence telling them where they were going.
   */
  navigation: CopilotNavigation | null;
  /**
   * Take the destination off the table without moving. The panel calls it after it has
   * navigated (so a re-render cannot navigate twice) and when the person answers "stay".
   */
  clearNavigation: () => void;
  /**
   * Every tool call this exchange has made, in the order they started, each carrying its
   * latest state. Live, and cleared by the next question.
   *
   * KEYED BY `id` AND REPLACED IN PLACE: the server sends two frames per call, and appending
   * both would render one lookup as two rows. Purely observational — the panel may render
   * none of it and lose no outcome.
   */
  steps: CopilotStep[];
  /** True when the refusal on screen is the AI allowance ceiling (G-5, client realm). */
  atCeiling: boolean;
  ask: (question: string) => void;
  undo: () => void;
  /**
   * Take the card off the screen. SENDS NOTHING — a proposal is a JWT the server never
   * stored, so there is no server-side state to release and nothing to tell it. Doing
   * nothing is a valid answer to a suggestion, and the token simply stops verifying.
   */
  dismissProposal: () => void;
  /**
   * Forget the conversation — the panel's "Start again", and the ONLY way a person
   * removes one now that it is durable (D-540).
   *
   * IT REACHES THE SERVER. Before the transcript was stored this cleared React state and
   * nothing else, and it had no caller at all: the dock unmounts the panel when the
   * surface changes, so there was never anything to reset. A local-only clear now would
   * be worse than no button — the conversation would be back on the next load, on the
   * same device, with no explanation.
   *
   * The delete is fired and NOT awaited, and the local clear happens in the same tick:
   * the click is answered immediately, and a failed delete surfaces afterwards as `error`
   * rather than as a button that appeared to do nothing.
   */
  reset: () => void;
  /**
   * True while the stored conversation is being fetched on mount.
   *
   * Separate from `asking`, which is a question in flight: this is the panel's own
   * loading state, and rendering an empty transcript during it would show "no
   * conversation" to somebody who has one.
   */
  loading: boolean;
}

/** The one code the server uses for the allowance ceiling; `AssistCard` reads the same. */
/**
 * `CopilotAskIn.history`'s ceiling, from `apps/api/copilot/schemas.py::MAX_HISTORY`.
 *
 * Retyped rather than generated because the OpenAPI schema carries `maxItems` on the
 * ARRAY and the generated client does not surface it as a value — so this is the one
 * place the number is written on this side, and `copilotHistory.test.ts` reads the
 * Python constant and fails if the two drift.
 */
export const MAX_HISTORY = 10;

/**
 * The last whole EXCHANGES that fit under the ceiling, oldest first.
 *
 * Pairs, not turns. A plain `slice(-MAX_HISTORY)` can start the window on an assistant
 * turn whose question fell off the front, and a model given an answer with no question
 * reads it as its own earlier assertion — which is how an assistant starts defending a
 * claim nobody made. Dropping the orphan costs one turn of context and removes that
 * failure entirely.
 *
 * Not a conversation summary and deliberately not: nothing here is persisted, and
 * summarising would mean a second model call on the latency path of every question.
 */
export function recentTurns(turns: readonly CopilotTurn[]): CopilotTurn[] {
  const window = turns.slice(-MAX_HISTORY);
  return window.length > 0 && window[0].role === "assistant" ? window.slice(1) : window;
}

export const AI_CEILING_CODE = "ai_quota_exceeded";

export function useCopilotConversation(
  session: Session,
  holder: SurfaceHolder | null,
): CopilotConversation {
  const [turns, setTurns] = useState<CopilotTurn[]>([]);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [disclosure, setDisclosure] = useState<string | null>(null);
  const [batch, setBatch] = useState<CopilotBatch | null>(null);
  const [proposal, setProposal] = useState<CopilotProposal | null>(null);
  const [actions, setActions] = useState<CopilotAction[]>([]);
  const [navigation, setNavigation] = useState<CopilotNavigation | null>(null);
  const [steps, setSteps] = useState<CopilotStep[]>([]);
  const [loading, setLoading] = useState(true);

  // The in-flight request, so a second question cancels the first rather than
  // interleaving two answers into one bubble.
  const inFlight = useRef<AbortController | null>(null);

  // THE REALM, read once per render from the surface. It is what chooses the endpoint
  // (`conversationPath`), and it is the same value `stream.ts` sends, so a conversation
  // cannot be written on one realm and read on the other.
  const realm = holder?.read().realm ?? null;

  /*
   * LOAD ON MOUNT (D-540). The panel is mounted when the launcher is opened and unmounted
   * when the surface changes, so this runs once per opening — which is exactly when a
   * person wants to see what they were saying.
   *
   * NOT a TanStack query, and the departure is worth one sentence because this console
   * uses one for every other read. Those cache across mounts, which is precisely wrong
   * here: the panel appends turns to LOCAL state as they stream, so a cached page would
   * be a second, staler copy of a list that is already being mutated in place, and the
   * two would fight on every re-open. One fetch per mount into the state that owns the
   * list is one source of truth.
   *
   * A FAILURE IS SILENT, and that is not swallowing an error. The person still has a
   * working assistant — they simply start from an empty panel — and an error banner
   * above an empty chat explains nothing they can act on. What an OPERATOR can act on is
   * the request itself, which is already in the API's own logs with its status.
   */
  useEffect(() => {
    if (realm === null) return;
    let live = true;
    setLoading(true);
    loadConversation(session, realm)
      .then((stored) => {
        // Only when nothing has been said yet: a person who typed a question before the
        // load returned must not have it replaced by a page that predates it.
        if (live) setTurns((previous) => (previous.length === 0 ? stored : previous));
      })
      .catch(() => undefined)
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [session, realm]);

  useEffect(
    () => () => {
      inFlight.current?.abort();
      clearFilled();
    },
    [],
  );

  const reset = useCallback(() => {
    inFlight.current?.abort();
    inFlight.current = null;
    // The server copy goes too (D-540). Fired before the local clear so an abort of the
    // in-flight ask cannot race it, and its failure is reported: a person who was told
    // their conversation was forgotten and finds it back tomorrow has been lied to.
    if (realm !== null) {
      void clearConversation(session, realm).catch((cause: unknown) => setError(cause));
    }
    setTurns([]);
    setStreaming(null);
    setAsking(false);
    setError(null);
    setDisclosure(null);
    setBatch(null);
    setProposal(null);
    setActions([]);
    setNavigation(null);
    setSteps([]);
    clearFilled();
  }, [realm, session]);

  const dismissProposal = useCallback(() => setProposal(null), []);
  const clearNavigation = useCallback(() => setNavigation(null), []);

  const undo = useCallback(() => {
    if (batch === null) return;
    holder?.read().apply(batch.priors);
    setBatch(null);
    clearFilled();
  }, [batch, holder]);

  const ask = useCallback(
    (question: string) => {
      const asked = question.trim();
      if (asked === "" || holder === null) return;
      const surface = holder.read();

      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;

      // A new question starts a new batch, so the previous one is no longer undoable —
      // and the marks come off with it. Leaving them would show an "Undo" that restores
      // values from two answers ago.
      setBatch(null);
      // …and the previous OFFER goes with it, for the same reason and one more: the card
      // may be sitting in its confirmed state, and a record of what the last answer did
      // must not be left standing beside a new one as if it were about that.
      setProposal(null);
      // AND THE PREVIOUS ANSWER'S RECEIPTS AND STEPS. Both belong to the EXCHANGE, exactly
      // as the batch and the offer do. Leaving a receipt standing beside a new answer says
      // "this is what I just did" about something that happened two questions ago — and it
      // is a receipt for a change that is still real, which is why it goes rather than
      // being greyed out: the record of it is in the audit log and on the object's own
      // screen, not in a chat panel.
      setActions([]);
      // …and any destination the previous answer named. A move nobody made by the time the
      // next question was typed is a move the person did not want; carrying it forward would
      // navigate them out of the conversation they just started.
      setNavigation(null);
      setSteps([]);
      clearFilled();
      setError(null);
      setDisclosure(null);
      setStreaming("");
      setAsking(true);
      // A question is what the person chose to type, so its two forms are the same
      // string: this module redacts what the CONSOLE volunteers, never what a person
      // deliberately writes (`redaction.ts` argues that boundary).
      setTurns((previous) => [...previous, { role: "user", content: asked, wire: asked }]);

      const pass = redactForWire(surface.fields, surface.facts ?? []);
      const body: CopilotAskBody = {
        screen: { route: surface.route, title: surface.title, realm: surface.realm },
        question: asked,
        fields: pass.fields,
        facts: pass.facts,
        // The REDACTED half of what has already been said. See `CopilotTurn`.
        //
        // TRIMMED TO THE SERVER'S CEILING, and this used to send the whole conversation.
        // `CopilotAskIn.history` is `max_length=MAX_HISTORY`, so the sixth exchange in one
        // open panel was a 422 that read "history: List should have at most 10 items" —
        // shown to the person as a validation error about a field they cannot see, in the
        // middle of a conversation that was working a moment earlier. The bound is not the
        // bug: nothing is persisted, this list IS the conversation's whole memory, and
        // replaying an unbounded one would grow every request until the model's context
        // decided where to truncate instead of us.
        //
        // The LAST turns, not the first: the recent exchange is what a follow-up question
        // refers to. Sliced on PAIRS so the window never opens on an assistant turn whose
        // question was dropped — a model handed an answer with no question treats it as
        // its own prior assertion, which is how a copilot starts insisting on something
        // nobody asked.
        history: recentTurns(turns).map((turn) => ({ role: turn.role, content: turn.wire })),
      };

      // Both halves of the answer, built in step: `answer` is what is shown, `answerWire`
      // is what may be replayed as history.
      let answer = "";
      let answerWire = "";
      // Priors for THIS exchange. A ref-free local: the closure lives exactly as long as
      // the request does, which is precisely the batch's lifetime.
      const priors = new Map<string, string>();
      const labels: string[] = [];
      const ids: string[] = [];

      void askCopilot(
        session,
        body,
        {
          onText: (delta) => {
            answerWire += delta;
            answer += pass.restore(delta);
            setStreaming(answer);
          },
          onFill: (items) => {
            // Read the surface AGAIN: an earlier fill in this same exchange has already
            // been applied, and the screen may have re-rendered since the question was
            // asked. Filling from the snapshot taken at ask-time would apply against a
            // form that has moved.
            const live = holder.read();
            const known = new Map(live.fields.map((field) => [field.id, field]));
            const applicable: CopilotFillItem[] = [];
            for (const item of items) {
              const field = known.get(item.field_id);
              // Unknown ids and read-only fields are dropped HERE, once, so no screen's
              // `apply` has to defend itself and no read-only value can be written by a
              // model that misread the flag.
              if (field === undefined || field.writable === false) continue;
              if (!priors.has(field.id)) {
                priors.set(field.id, field.value);
                labels.push(field.label);
                ids.push(field.id);
              }
              applicable.push({ field_id: field.id, value: pass.restore(item.value) });
            }
            if (applicable.length === 0) return;
            live.apply(applicable);
            setBatch({
              priors: Array.from(priors, ([field_id, value]) => ({ field_id, value })),
              labels: [...labels],
              ids: [...ids],
            });
          },
          onProposal: (offered) => {
            // Straight through, unedited. The token is the whole state of the offer and
            // the prose beside it is the server's; there is nothing for this layer to
            // restore, merge or normalise — `pass.restore` is deliberately NOT applied,
            // because a proposal names its target by id and carries no placeholder by
            // construction (`_plan_dnc_add`: the number never enters the prompt).
            setProposal(offered);
          },
          onAction: (performed) => {
            // APPENDED, never replaced — see `actions`. Straight through and unedited for
            // `onProposal`'s reason: every string is the server's own account of something
            // it has already done, and an action names its object by id, so there is no
            // placeholder to restore.
            setActions((previous) => [...previous, performed]);
          },
          onNavigate: (destination) => {
            // HELD, NOT PERFORMED. The panel moves once the answer has finished arriving —
            // see `navigation` on the interface for why navigating from inside the stream
            // would abort the sentence that explains the move.
            setNavigation(destination);
          },
          onStep: (step) => {
            // UPSERT BY `id`. The terminal frame REPLACES its own `running` one rather than
            // following it, so one call is one row that changes state — which is the whole
            // point of showing them.
            setSteps((previous) => {
              const at = previous.findIndex((existing) => existing.id === step.id);
              if (at === -1) return [...previous, step];
              const next = [...previous];
              next[at] = step;
              return next;
            });
          },
          onDone: (done) => {
            setDisclosure(done.disclosure);
          },
        },
        { signal: controller.signal },
      )
        .then(() => {
          if (controller.signal.aborted) return;
          setTurns((previous) => [
            ...previous,
            { role: "assistant", content: answer, wire: answerWire },
          ]);
          setStreaming(null);
          setAsking(false);
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted) return;
          // Whatever DID arrive stays in the transcript. A dropped stream that erased
          // the half-answer would also erase the only explanation of the fields it had
          // already applied.
          if (answer !== "") {
            setTurns((previous) => [
              ...previous,
              { role: "assistant", content: answer, wire: answerWire },
            ]);
          }
          setStreaming(null);
          setAsking(false);
          setError(cause);
        })
        .finally(() => {
          if (inFlight.current === controller) inFlight.current = null;
        });
    },
    [holder, session, turns],
  );

  const atCeiling = error instanceof ApiProblem && error.code === AI_CEILING_CODE;

  // The marks are drawn from an effect rather than inside `onFill`, because the value has
  // to be in the DOM before it is outlined — `apply` schedules a React state update, and
  // the control does not exist in its new form until that has committed.
  useEffect(() => {
    if (batch === null) return;
    markFilled(batch.ids);
  }, [batch]);

  return {
    turns,
    streaming,
    asking,
    error,
    disclosure,
    batch,
    proposal,
    actions,
    navigation,
    clearNavigation,
    steps,
    atCeiling,
    loading,
    ask,
    undo,
    dismissProposal,
    reset,
  };
}
