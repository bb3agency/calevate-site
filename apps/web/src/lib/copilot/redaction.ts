/**
 * D-127 G-2, at the last point the browser still owns the data: personal values are
 * replaced with placeholders BEFORE the request leaves, and put back locally afterwards.
 *
 * The model can still reason about the field and can still fill it — "put the escalation
 * number in the after-hours contact" works, because the placeholder is a stable, readable
 * token it can name — it just never learns the digits. Nothing about the mapping is sent,
 * and nothing about it is persisted: it lives for one exchange, in one closure.
 *
 * ## Why the tokens look like «PHONE_1» and not [REDACTED]
 *
 * Three properties, all load-bearing:
 *
 * - **Distinguishable.** Two phone numbers on one screen are two different facts, and a
 *   model told both are `[REDACTED]` will happily put the branch's number in the
 *   escalation field. The counter is per KIND, so the numbering is stable and readable.
 * - **Reversible by exact match.** The guillemets are not in any value this console can
 *   produce (no field on any registered screen accepts them) and they are not markdown,
 *   so a token cannot be produced by accident and cannot be mangled into something that
 *   still matches. `RESTORE` is a plain global replace of a literal, not a regex over
 *   user data.
 * - **Idempotent.** Restoring text that contains no token returns it unchanged, so the
 *   same function runs over every streamed delta and every filled value without a caller
 *   having to know which of them could contain one.
 *
 * ## What this deliberately does NOT do
 *
 * It does not redact the QUESTION. A person typing a phone number into the ask box is
 * choosing to send it, the same way they choose what to type into any field; inventing a
 * detector over free text would be a guess that both misses real numbers and mangles
 * order references that merely look like them. G-2 is about what the CONSOLE volunteers
 * on the user's behalf, and this module is exactly that boundary.
 */

import type { CopilotFact, CopilotField, PersonalKind } from "./types";

/** The wire shape of one field. Deliberately snake_case: this IS the request body. */
export interface WireField {
  id: string;
  label: string;
  type: CopilotField["type"];
  value: string;
  options: { value: string; label: string }[] | null;
  writable: boolean;
  help: string | null;
  redacted: boolean;
}

export interface WireFact {
  key: string;
  label: string;
  value: string;
}

const TOKEN_PREFIX: Record<PersonalKind, string> = {
  phone: "PHONE",
  email: "EMAIL",
  name: "NAME",
  text: "PRIVATE",
};

/**
 * One exchange's redaction: the values that went out, and the way back.
 *
 * `restore` is handed to the panel and run over EVERY string that comes back — each
 * streamed delta and each filled value — because a model asked to "copy the branch number
 * into the escalation field" answers with the token, and a token reaching a form field is
 * a form field holding `«PHONE_1»` instead of a number.
 */
export interface RedactionPass {
  fields: WireField[];
  facts: WireFact[];
  /** Identity on anything that is not a string — see the implementation. */
  restore: <T>(text: T) => T;
}

/**
 * Build the request's field list, swapping personal values for tokens.
 *
 * An EMPTY personal field is not redacted, and that is not an oversight: `""` carries no
 * personal data, and sending `«PHONE_2»` for a blank control would tell the model the
 * field is already answered — which is the one thing a fill assistant must not believe.
 */
export function redactForWire(fields: CopilotField[], facts: CopilotFact[]): RedactionPass {
  const counters = new Map<PersonalKind, number>();
  // Token -> real value. Insertion-ordered, which `restore` relies on only for
  // determinism in tests; correctness comes from the tokens being mutually exclusive.
  const mapping = new Map<string, string>();

  const tokenFor = (kind: PersonalKind, value: string): string => {
    const next = (counters.get(kind) ?? 0) + 1;
    counters.set(kind, next);
    const token = `«${TOKEN_PREFIX[kind]}_${next}»`;
    mapping.set(token, value);
    return token;
  };

  const wireFields: WireField[] = fields.map((field) => {
    const personal = field.personal !== undefined && field.value !== "";
    return {
      id: field.id,
      label: field.label,
      type: field.type,
      value: personal ? tokenFor(field.personal as PersonalKind, field.value) : field.value,
      options: field.options ?? null,
      writable: field.writable ?? true,
      help: field.help ?? null,
      redacted: personal,
    };
  });

  const wireFacts: WireFact[] = facts.map((fact) => ({
    key: fact.key,
    label: fact.label,
    value:
      fact.personal !== undefined && fact.value !== ""
        ? tokenFor(fact.personal, fact.value)
        : fact.value,
  }));

  return {
    fields: wireFields,
    facts: wireFacts,
    restore: <T,>(text: T): T => {
      // NON-STRINGS PASS THROUGH UNTOUCHED rather than being coerced. A `fill` value can
      // be a boolean or a number (see `CopilotFillItem`), and there is no placeholder in
      // either — a token is a string a model wrote. `String(value)` here would turn
      // `false` into `"false"` and hand a checkbox a truthy string.
      if (typeof text !== "string") return text;
      let out: string = text;
      for (const [token, real] of mapping) out = out.split(token).join(real);
      return out as unknown as T;
    },
  };
}

/** A pass that redacts nothing — what a screen with no personal fields gets, and the
 *  identity `restore` a caller can hold before the first question is asked. */
export function noRedaction(): RedactionPass {
  return { fields: [], facts: [], restore: <T,>(text: T): T => text };
}
