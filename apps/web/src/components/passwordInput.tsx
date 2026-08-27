"use client";

/**
 * The ONE password input in this product, and the ONE show/hide control on it.
 *
 * Every `type="password"` in `src/` renders through this file — the two sign-in realms,
 * the three set-password flows (invitation, bootstrap, reset), the saved integration
 * secret and the two Meta app-secret fields. Written once for CLAUDE.md's
 * one-way-per-problem rule, and because a reveal control is the kind of thing that is
 * subtly wrong in three different ways when it is written three times: the copy that
 * bolts an icon on typically loses the caret, loses the accessible state, or — the
 * expensive one — loses a protection the hidden field had (see "What reveal costs").
 *
 * ## Why it exists at all
 *
 * `authn/policy.py::MIN_CHARS_BY_REALM` requires FIFTEEN characters on the client realm,
 * because that password is single-factor (NIST SP 800-63B-4 §3.1.1.2). A person typing
 * fifteen characters on a phone keyboard into a field they cannot read has no way to find
 * the one wrong character, and their only recovery is the whole string again. We wrote
 * the floor; the reveal is the other half of it.
 *
 * ## The a11y decision: a STATIC accessible name plus a toggling `aria-pressed`
 *
 * The two candidate patterns are (a) one button whose `aria-label` swaps between "Show
 * password" and "Hide password", and (b) one button with a fixed name and `aria-pressed`
 * carrying the state. **(b), deliberately.** `aria-pressed` is a state attribute, so
 * assistive technology is built to watch it and announce the change on the control the
 * user just operated ("Show password, button, pressed"); an ACCESSIBLE NAME is not — a
 * name that changes under a screen reader is announced late, not at all, or paired with
 * the previous state, depending on the pairing. That failure mode is the one documented
 * across the current guidance for this exact widget: "State attributes such as
 * aria-pressed are meant to be dynamic … screen readers really do not like dynamic
 * accessible names" (Stefany Newman, "Dos and don'ts of accessible show password
 * buttons", medium.com/@web-accessibility-education/dos-and-donts-of-accessible-show-
 * password-buttons-9a5fbc2c566b, read 27 Aug 2026) — the same conclusion reached by
 * testparty.ai/blog/accessible-toggle-buttons-modern-web-apps-complete-guide (read
 * 27 Aug 2026), which notes the browser notifies AT of an `aria-pressed` change and it is
 * announced as "button, pressed". Swapping BOTH is explicitly named as the bad practice.
 *
 * The name is therefore "Show <noun>" in both states and never moves. `reveals` is what
 * makes it unique per field: a form with two password fields (set-password has "New
 * password" and "Type it again") would otherwise present two controls with one name, and
 * a screen-reader user listing the buttons could not tell which is which.
 *
 * The icon is `aria-hidden`: it is a second rendering of a state the button already
 * carries, and announcing it would say the same thing twice.
 *
 * ## What reveal COSTS, and what is done about it
 *
 * `type="text"` is not a cosmetic change to a password field — it moves the value into
 * the class of text browsers are willing to process:
 *
 * - **Spell check.** A password input is not spell-checked: MDN's `spellcheck` reference
 *   lists the spell-checkable content as "Text values in input elements (not password)"
 *   (developer.mozilla.org/en-US/docs/Web/HTML/Reference/Global_attributes/spellcheck —
 *   `developer.mozilla.org` is EGRESS-BLOCKED from this machine, so this was read
 *   27 Aug 2026 from the search excerpt, not the page). A revealed field is a text input,
 *   so it is. That is not theoretical: otto-js' September 2022 "spell-jacking" finding was
 *   that Chrome's Enhanced Spellcheck and Edge's MS Editor send form-field contents to
 *   Google and Microsoft, and that **the password is included once the page's own "show
 *   password" control is used** — the mitigation they name is `spellcheck=false` on the
 *   field (reported by bleepingcomputer.com/news/security/google-microsoft-can-get-your-
 *   passwords-via-web-browsers-spellcheck/ and darkreading.com/application-security/
 *   spellchecking-google-chrome-microsoft-edge-browsers-leaks-passwords; both hosts are
 *   egress-blocked here, read 27 Aug 2026 from search excerpts — REPORTED, not read at the
 *   primary source, and it is the reason `spellCheck={false}` is set UNCONDITIONALLY
 *   below rather than only on the revealed branch).
 * - **Autocorrect and autocapitalisation.** A soft keyboard capitalises and corrects text
 *   fields and does neither for a password field; both would silently rewrite a
 *   credential, and autocorrect feeds a predictive dictionary. `autoCorrect="off"` and
 *   `autoCapitalize="off"` are set unconditionally for the same reason as above.
 * - **Autofill classification.** What tells a browser or a password manager that this
 *   field is a credential is the `autocomplete` token, not the type — so the caller's
 *   `current-password` / `new-password` is passed through UNCHANGED in both states and is
 *   never dropped or rewritten on reveal. Nothing here adds a `data-1p-ignore`-style
 *   opt-out: these fields WANT a password manager, and the two Meta app-secret fields
 *   pass no token at all, which is the same answer they had before this component.
 *
 * The result: the revealed field keeps every protection the hidden field had. The one
 * thing reveal genuinely costs — the value is on the screen — is the thing the person
 * asked for, and it is off by default and never persisted anywhere.
 */

import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type InputHTMLAttributes,
  type Ref,
} from "react";

import clsx from "clsx";
import { Eye, EyeOff } from "lucide-react";

import { FIELD } from "@/components/ui";

/**
 * The toggle's class string.
 *
 * `touch:min-h-11` for the same reason every control in `components/ui.tsx` carries it —
 * `tests/responsive.test.ts` enforces it on the shared button constants and this is one
 * more control a thumb has to hit. `text-ink-muted` resting and `text-ink` on hover: both
 * are palette tokens `tests/contrast.test.ts` already checks at 4.5:1 against `--surface`,
 * which is what `FIELD` paints behind this button. A Tailwind literal (`text-slate-400`,
 * the usual choice for a field affordance) would be outside that check — and outside it
 * is where the last contrast failure in this repo lived.
 *
 * `bottom-0 top-1` rather than `inset-y-0`: `FIELD` carries `mt-1`, so the input's box
 * starts 0.25rem below the top of the wrapper. `inset-y-0` plus a correcting `top-1`
 * would be two utilities setting `top`, and which one wins is Tailwind's emission order,
 * not the order they are written in.
 */
const TOGGLE =
  "absolute bottom-0 right-0 top-1 flex items-center rounded-r-md px-3 text-ink-muted " +
  "outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-brand-strong " +
  "touch:min-h-11";

export interface PasswordInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "spellCheck"> {
  /**
   * The noun the toggle names — "Show <reveals>". Defaults to "password".
   *
   * Distinct per field on any form with more than one, so the buttons do not present one
   * name twice; see the a11y note in the file docstring.
   */
  reveals?: string;
  /** For deliberate focus management from a parent, as `AuthField` documents it. */
  inputRef?: Ref<HTMLInputElement>;
  /** Extra classes for the positioning wrapper — a width the input inherits, usually. */
  wrapperClassName?: string;
}

export function PasswordInput({
  reveals = "password",
  inputRef,
  wrapperClassName,
  className,
  ...input
}: PasswordInputProps) {
  /**
   * HIDDEN, and it is `useState` in this component rather than anything durable.
   *
   * There is no `localStorage`, no URL parameter and no context: a reveal lasts exactly
   * as long as this component instance. A navigation remounts it hidden, and so does a
   * failed submit that re-renders the form — the set-password form's refusal path leaves
   * the typed password in place, and a person who revealed it to read a rejection would
   * otherwise walk away from a screen still showing it.
   */
  const [revealed, setRevealed] = useState(false);

  const field = useRef<HTMLInputElement | null>(null);
  /** What to put back after the type change, set only by the toggle. */
  const restore = useRef<{ start: number; end: number; focused: boolean } | null>(null);

  /** Merge the parent's ref with ours; the parent's is the documented focus escape hatch. */
  const attach = useCallback(
    (node: HTMLInputElement | null) => {
      field.current = node;
      if (typeof inputRef === "function") inputRef(node);
      else if (inputRef) (inputRef as { current: HTMLInputElement | null }).current = node;
    },
    [inputRef],
  );

  /**
   * Put the caret (and focus) back, in the same frame the type changed in.
   *
   * `useLayoutEffect` rather than `useEffect` so this runs before paint: a caret that
   * jumps to the end and then jumps back is visible. It is a no-op on mount and on every
   * render that is not a toggle, because `restore` is only ever set by the handler below.
   *
   * Written defensively rather than on a claim about any engine: this component does not
   * depend on every browser preserving selection and focus across a `type` mutation, and
   * where they are preserved this restores the values they already hold. The cost of
   * being wrong the other way is a person losing their place in the middle of a fifteen-
   * character credential.
   */
  useLayoutEffect(() => {
    const at = restore.current;
    restore.current = null;
    const node = field.current;
    if (at === null || node === null) return;
    if (at.focused && document.activeElement !== node) node.focus();
    node.setSelectionRange(at.start, at.end);
  }, [revealed]);

  const toggle = useCallback(() => {
    const node = field.current;
    if (node !== null) {
      restore.current = {
        start: node.selectionStart ?? node.value.length,
        end: node.selectionEnd ?? node.value.length,
        focused: document.activeElement === node,
      };
    }
    setRevealed((shown) => !shown);
  }, []);

  return (
    <div className={clsx("relative", wrapperClassName)}>
      <input
        ref={attach}
        type={revealed ? "text" : "password"}
        // Unconditional, not `revealed &&`: see "What reveal COSTS" in the docstring.
        // A password field ignores all three; a revealed one must not be offered them,
        // and setting them once means no state in which they are momentarily absent.
        spellCheck={false}
        autoCorrect="off"
        autoCapitalize="off"
        // `pr-11` so a long password runs under the label of the toggle rather than
        // under the toggle itself. Last, so a caller's own padding cannot undo it.
        className={clsx(className ?? FIELD, "pr-11")}
        {...input}
      />
      <button
        type="button"
        // Static name + toggling state. The file docstring argues this at length; the
        // one-line version is that screen readers announce a changed `aria-pressed`
        // reliably and a changed accessible name unreliably.
        aria-label={`Show ${reveals}`}
        aria-pressed={revealed}
        className={TOGGLE}
        // THE CARET SURVIVES A MOUSE OR THUMB BECAUSE OF THIS LINE. A mousedown on a
        // button moves focus off the input before the click ever fires; refusing its
        // default keeps focus, and therefore the caret, exactly where the person left
        // it. Keyboard activation is untouched — a Tab to this button and Enter leaves
        // focus here, which is where a keyboard user expects it and where the
        // `aria-pressed` change gets announced.
        onMouseDown={(event) => event.preventDefault()}
        onClick={toggle}
      >
        {revealed ? (
          <EyeOff aria-hidden className="h-4 w-4" />
        ) : (
          <Eye aria-hidden className="h-4 w-4" />
        )}
      </button>
    </div>
  );
}
