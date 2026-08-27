"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiProblem, type Session } from "@/lib/api/client";

import { clearFilled, markFilled } from "./highlight";
import { redactForWire } from "./redaction";
import { askCopilot, type CopilotAskBody } from "./stream";
import type { CopilotFillItem } from "./types";
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
  /** True when the refusal on screen is the AI allowance ceiling (G-5, client realm). */
  atCeiling: boolean;
  ask: (question: string) => void;
  undo: () => void;
  /** Forget the conversation — used when the surface underneath changes. */
  reset: () => void;
}

/** The one code the server uses for the allowance ceiling; `AssistCard` reads the same. */
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

  // The in-flight request, so a second question cancels the first rather than
  // interleaving two answers into one bubble.
  const inFlight = useRef<AbortController | null>(null);

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
    setTurns([]);
    setStreaming(null);
    setAsking(false);
    setError(null);
    setDisclosure(null);
    setBatch(null);
    clearFilled();
  }, []);

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
        history: turns.map((turn) => ({ role: turn.role, content: turn.wire })),
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
    atCeiling,
    ask,
    undo,
    reset,
  };
}
