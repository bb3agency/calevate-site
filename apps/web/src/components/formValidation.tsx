"use client";

/**
 * Our own words when a form is submitted with something missing — both realms.
 *
 * ## What this replaces
 *
 * Twenty-odd client forms carried `required` / `minLength` / `type="email"` with no
 * `noValidate`, so an empty submit was refused by the BROWSER: a bubble reading "Please
 * fill out this field." Three things are wrong with that, and the first is the one that
 * matters for a Telugu-first product sold to Indian SMBs:
 *
 * - **It is written in the browser's UI language, not ours.** A shop owner running Chrome
 *   in English gets English however the rest of the product is set, and there is no API
 *   that lets us translate it. `setCustomValidity` changes the STRING but not the
 *   language of anything else in that bubble, and it still leaves the other two problems.
 * - **It does not sound like us.** The same form then speaks in two voices depending on
 *   whether the browser or the server did the refusing, and the browser's voice names
 *   "fields" and "formats".
 * - **It is placed and styled by the browser**, so it ignores the error surface every
 *   other refusal on the screen lands in, and it disappears on the next click.
 *
 * ## Why the constraint ATTRIBUTES stay on the controls
 *
 * `noValidate` suppresses the browser's automatic UI; it does not remove the attributes.
 * They are kept, deliberately, and this is the safest half of the change: `required`
 * still reaches assistive technology (a screen reader announces the field as required
 * before anything is typed), `type="email"` still picks the phone keyboard, and — the
 * point — the RULE still lives on the control it belongs to, in one place, where a reader
 * can see it. This module reads those same attributes back off the DOM at submit time and
 * says in our words what the browser would have said in its own. Nothing here is a second
 * copy of a rule, so no form can drift from its own validation.
 *
 * ## Why not one `attempted` flag and a hand-written sentence per rule, per form
 *
 * That was the estimate this work started from (~1000 lines). It produces twenty-two
 * slightly different vocabularies, and the twenty-third form gets a twenty-third. The
 * only sentence a form knows better than this module is the one naming WHAT is missing
 * ("Enter a name for this agent."), because that is about the field and not about the
 * rule. So that one is passed in and everything else — the length rule, the email rule,
 * the number range — is worded here, once.
 *
 * ## The ADMIN realm was converted second, and it needed MORE than `noValidate`
 *
 * The client realm's defect was the browser speaking. The admin console's thirty-three
 * forms mostly had a different one wearing the same clothes: the rule lived in a `ready`
 * boolean that deadened the submit button, so an operator with an empty reason box got a
 * button that did nothing and no sentence anywhere on the screen. That is not a gentler
 * refusal than Chrome's bubble — it is a refusal with no words in it at all.
 *
 * So a converted admin form moves the ANSWER rules onto the controls (`required`,
 * `minLength`, `type`) and leaves only the GATES in `ready`: a typed confirmation, a
 * permission, a stale-precondition conflict. The distinction is worth stating because it
 * is the one a reader has to make on the next form: a gate is not about a value the
 * person can supply in a box, so there is nothing for this module to word.
 *
 * ## What a converted form gets, and what it must keep
 *
 * `aria-invalid` on the control, the message associated through `aria-describedby`, and
 * focus moved to the first invalid control on submit. The browser bubble did announce
 * itself, so a message that did not would be a REGRESSION rather than an improvement —
 * `tests/formValidation.test.tsx` asserts each of those three on a real form rather than
 * on this module in isolation — one from each realm, plus a source sweep over both.
 */

import { useCallback, useId, useRef, useState, type FormEvent, type ReactNode } from "react";

/** The controls this module can read a rule off. */
type Control = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

/**
 * A plausible email address, checked loosely on purpose.
 *
 * The SERVER is the authority (`EmailStr`, RFC 5322 by way of `email-validator`), and a
 * client that tried to match it would refuse addresses the server accepts — the failure
 * direction that cannot be worked around from the screen. This catches the mistakes a
 * person actually makes (no `@`, no domain, a stray space) and lets everything else
 * through to be judged where it can be judged properly.
 */
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Is this control one whose value a person types, so that trimming makes sense? */
function isTextual(el: Control): boolean {
  if (el instanceof HTMLTextAreaElement) return true;
  if (el instanceof HTMLSelectElement) return false;
  return !["checkbox", "radio", "file", "number", "range", "date", "time"].includes(el.type);
}

/**
 * What is wrong with this control, in our words — or `null` when nothing is.
 *
 * `ask` is the form's own sentence for "there is nothing here yet"; every other sentence
 * is this module's, so that "at least 2 characters" reads the same on every screen.
 *
 * Order matters: emptiness is reported before shape. Telling somebody their empty field
 * is not a valid email address is technically true and useless.
 */
export function fieldProblem(el: Control, ask: string): string | null {
  const textual = isTextual(el);
  const raw = el.value;
  const value = textual ? raw.trim() : raw;

  if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) {
    return el.required && !el.checked ? ask : null;
  }

  // Whitespace only counts as empty here where the browser counts it as filled. The
  // server strips before it validates, so the browser's reading would let a form submit
  // a space and meet a refusal it could have made sense of on screen.
  if (value === "") return el.required ? ask : null;

  if (el instanceof HTMLSelectElement) return null;

  if (el.minLength > 0 && value.length < el.minLength) {
    return `Use at least ${el.minLength} characters.`;
  }
  if (el.maxLength > 0 && value.length > el.maxLength) {
    return `Use ${el.maxLength} characters or fewer.`;
  }

  if (el instanceof HTMLInputElement) {
    if (el.type === "email" && !EMAIL_SHAPE.test(value)) {
      return "Enter an email address, like name@example.com.";
    }
    if (el.type === "url" && !/^https?:\/\/[^\s]+$/i.test(value)) {
      return "Enter a web address that starts with https://.";
    }
    // A date or time picker compares as a STRING because both are ISO-ordered
    // (`2026-09-02`, `21:30`), which is the same comparison the browser makes and needs
    // no parsing that could disagree with it across time zones.
    if (["date", "month", "week", "time", "datetime-local"].includes(el.type)) {
      const noun = el.type === "time" ? "time" : "date";
      if (el.min !== "" && value < el.min) return `Choose a ${noun} on or after ${el.min}.`;
      if (el.max !== "" && value > el.max) return `Choose a ${noun} on or before ${el.max}.`;
      return null;
    }
    if (el.type === "number") {
      const n = Number(value);
      if (Number.isNaN(n)) return "Enter a number.";
      const min = el.min === "" ? null : Number(el.min);
      const max = el.max === "" ? null : Number(el.max);
      if (min !== null && max !== null && (n < min || n > max)) {
        return `Enter a number between ${min} and ${max}.`;
      }
      if (min !== null && n < min) return `Enter ${min} or more.`;
      if (max !== null && n > max) return `Enter ${max} or less.`;
    }
  }
  return null;
}

/** Props for a control this module both labels the error of and watches. */
export interface FieldProps {
  id: string;
  ref: (el: Control | null) => void;
  onInput: () => void;
  "aria-invalid"?: true;
  "aria-describedby"?: string;
}

/** Props for a control whose own component already owns its id and aria wiring. */
export type TrackedProps = Pick<FieldProps, "ref" | "onInput">;

export interface FormValidation {
  /**
   * Wrap the form's submit. Nothing is sent while a control is refused, and the first
   * refused control — first in DOM order, not in registration order — takes focus.
   */
  onSubmit: (run: () => void) => (event: FormEvent<HTMLFormElement>) => void;
  /**
   * Everything a bare control needs: spread onto the `<input>`/`<select>`/`<textarea>`.
   *
   * `describedBy` is for a control that already HAS a description — a hint span with its
   * own id. `aria-describedby` takes a list and the last spread wins, so a caller writing
   * its own attribute after this one would silently drop the message from the control's
   * description; passing the hint's id here keeps both.
   */
  field: (name: string, ask: string, describedBy?: string) => FieldProps;
  /** For a control inside a component that renders its own label, hint and error. */
  track: (name: string, ask: string) => TrackedProps;
  /** This field's message, for a component that renders errors itself. */
  message: (name: string) => string | undefined;
  /** The rendered message for a bare control. Put it directly after the control. */
  error: (name: string) => ReactNode;
  /** Drop every message — for a form that closes or resets without unmounting. */
  reset: () => void;
}

/**
 * One form's worth of validation state.
 *
 * Registration is by NAME rather than by index so that a form whose fields appear and
 * disappear (the campaign form's schedule half, the credential form's provider-specific
 * secret) cannot shift another field's message onto the wrong control.
 */
export function useFormValidation(): FormValidation {
  // Ids are per-INSTANCE. Two of these forms can be on one screen (the lead-source
  // screen renders a create form and an edit form together), and a fixed id prefix would
  // give both fields the same id and point one form's `aria-describedby` at the other's
  // message.
  const uid = useId();
  const controls = useRef(new Map<string, { el: Control | null; ask: string }>());
  const refs = useRef(new Map<string, (el: Control | null) => void>());
  const [messages, setMessages] = useState<Record<string, string>>({});
  // Read inside callbacks that must not be re-created when a message changes: a ref
  // callback whose identity churned would detach and re-attach every control on every
  // keystroke.
  const attempted = useRef(false);

  const entry = useCallback((name: string, ask: string) => {
    const existing = controls.current.get(name);
    if (existing) existing.ask = ask;
    else controls.current.set(name, { el: null, ask });
  }, []);

  const refFor = useCallback((name: string) => {
    const cached = refs.current.get(name);
    if (cached) return cached;
    const set = (el: Control | null) => {
      const held = controls.current.get(name);
      if (held) held.el = el;
    };
    refs.current.set(name, set);
    return set;
  }, []);

  /** Re-check one control, but only once the person has actually tried to submit. */
  const recheck = useCallback((name: string) => {
    if (!attempted.current) return;
    const held = controls.current.get(name);
    if (!held?.el) return;
    const problem = fieldProblem(held.el, held.ask);
    setMessages((prev) => {
      if (problem === (prev[name] ?? null)) return prev;
      const next = { ...prev };
      if (problem === null) delete next[name];
      else next[name] = problem;
      return next;
    });
  }, []);

  const field = useCallback(
    (name: string, ask: string, describedBy?: string): FieldProps => {
      entry(name, ask);
      const message = messages[name];
      const described = [describedBy, message ? `${uid}${name}-error` : null]
        .filter(Boolean)
        .join(" ");
      return {
        id: `${uid}${name}`,
        ref: refFor(name),
        onInput: () => recheck(name),
        ...(message ? { "aria-invalid": true as const } : {}),
        ...(described ? { "aria-describedby": described } : {}),
      };
    },
    [entry, messages, recheck, refFor, uid],
  );

  const track = useCallback(
    (name: string, ask: string): TrackedProps => {
      entry(name, ask);
      return { ref: refFor(name), onInput: () => recheck(name) };
    },
    [entry, recheck, refFor],
  );

  const onSubmit = useCallback(
    (run: () => void) => (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      attempted.current = true;
      const found: Record<string, string> = {};
      const refused: Control[] = [];
      for (const [name, held] of controls.current) {
        // A control that is not on screen right now has no answer to give and no place to
        // put a message. Its rule is the server's until it is rendered again.
        if (!held.el || !held.el.isConnected) continue;
        const problem = fieldProblem(held.el, held.ask);
        if (problem === null) continue;
        found[name] = problem;
        refused.push(held.el);
      }
      setMessages(found);
      if (refused.length > 0) {
        // DOM order, not registration order: a form whose fields mount in a different
        // order than they are read (a conditional block, a re-render) would otherwise
        // send focus backwards past answers that are fine.
        refused.sort((a, b) =>
          a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1,
        );
        refused[0].focus();
        return;
      }
      run();
    },
    [],
  );

  const message = useCallback((name: string) => messages[name], [messages]);

  const error = useCallback(
    (name: string): ReactNode => {
      const text = messages[name];
      if (!text) return null;
      return <FieldMessage id={`${uid}${name}-error`}>{text}</FieldMessage>;
    },
    [messages, uid],
  );

  const reset = useCallback(() => {
    attempted.current = false;
    setMessages({});
  }, []);

  return { onSubmit, field, track, message, error, reset };
}

/**
 * The one way a field-level refusal is drawn.
 *
 * `role="alert"` because it appears in response to a press rather than being on screen
 * already: without it, a screen-reader user who submits an empty form hears nothing at
 * all, which is worse than the browser bubble this replaces. Focus lands on the control
 * the message describes, so the message is also read as part of that control.
 */
export function FieldMessage({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} role="alert" className="mt-1 text-xs font-medium text-rose-700 dark:text-rose-400">
      {children}
    </p>
  );
}
