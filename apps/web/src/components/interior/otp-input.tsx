"use client";

// Adapted from interior.dev (github.com/ddoemonn/interior @3148000), MIT License,
// Copyright (c) 2026 ozzy. Full notice: ./LICENSE.

/**
 * A one-time-code field drawn as boxes, built on ONE real `<input>`.
 *
 * The upstream component rendered one input per character. We use a single input laid
 * over the boxes instead, for three reasons that each matter on a sign-in screen:
 *
 * - **Autofill.** iOS and Android offer the code from the email or SMS above the keyboard
 *   and fill ONE field with all of it; a password manager does the same. One input with
 *   `autocomplete="one-time-code"` is exactly what they target.
 * - **Screen readers.** One labelled field announced once ("Six-digit code, 3 of 6
 *   characters") rather than six fields to tab through.
 * - **Editing comes from the platform.** Typing advances, Backspace steps back, paste and
 *   select-all work, because they are the input's own behaviour rather than ours.
 *
 * The caret is held at the end, so the box that looks active is always the one the next
 * digit lands in. The component is controlled: the parent owns the value, which is what
 * lets a refused code be cleared and the field kept focused for the next try.
 *
 * `onComplete` fires once per transition to a full code — not on every render while
 * full, and not when a full value is set again unchanged — so a parent that submits from
 * it cannot double-submit from a re-render.
 */

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type Ref,
} from "react";
import { AnimatePresence, motion, useAnimate, useReducedMotion } from "motion/react";

const EASE_OUT = [0.23, 1, 0.32, 1] as const;

export type OtpMode = "numeric" | "alphanumeric";
export type OtpStatus = "idle" | "error" | "success";

const NOT_ALLOWED: Record<OtpMode, RegExp> = {
  numeric: /[^0-9]/g,
  alphanumeric: /[^0-9a-zA-Z]/g,
};

/** Only the characters a code can hold, at most `length` of them. */
export function sanitizeOtp(raw: string, length: number, mode: OtpMode = "numeric"): string {
  return raw.replace(NOT_ALLOWED[mode], "").slice(0, length);
}

export type OtpInputProps = {
  value: string;
  onChange: (value: string) => void;
  /** Called once each time the value BECOMES a full code. */
  onComplete?: (value: string) => void;
  /** The field's accessible name, e.g. "Six-digit code". Rendered as a visible label. */
  label: string;
  length?: number;
  mode?: OtpMode;
  status?: OtpStatus;
  /**
   * Change this to shake the boxes — a counter bumped on each refused code, so a second
   * wrong code shakes again. Ignored under reduced motion; the error message carries it.
   */
  shakeKey?: number;
  /** Ids of elements that describe the field (its hint, its error). */
  describedBy?: string;
  /** Keeps focus and the typed code, but takes no input (a check is in flight). */
  readOnly?: boolean;
  disabled?: boolean;
  inputRef?: Ref<HTMLInputElement>;
  className?: string;
};

export function OtpInput({
  value,
  onChange,
  onComplete,
  label,
  length = 6,
  mode = "numeric",
  status = "idle",
  shakeKey = 0,
  describedBy,
  readOnly = false,
  disabled = false,
  inputRef,
  className = "",
}: OtpInputProps) {
  const reduced = useReducedMotion();
  const id = useId();
  const [focused, setFocused] = useState(false);
  const [scope, animate] = useAnimate<HTMLDivElement>();
  const ownRef = useRef<HTMLInputElement | null>(null);

  const setRefs = useCallback(
    (el: HTMLInputElement | null) => {
      ownRef.current = el;
      if (typeof inputRef === "function") inputRef(el);
      else if (inputRef) (inputRef as { current: HTMLInputElement | null }).current = el;
    },
    [inputRef],
  );

  // Shake on a refused code: horizontal translate only, under 300ms, ease-out, and only
  // when motion is welcome. A real-world "no" — the boxes refuse the code — rather than a
  // decorative effect, and it plays once per refusal.
  useEffect(() => {
    if (shakeKey === 0 || reduced || !scope.current) return;
    void animate(
      scope.current,
      {
        transform: [
          "translateX(0px)",
          "translateX(-6px)",
          "translateX(5px)",
          "translateX(-3px)",
          "translateX(0px)",
        ],
      },
      { duration: 0.28, ease: EASE_OUT },
    );
  }, [shakeKey, reduced, animate, scope]);

  const keepCaretAtEnd = useCallback(() => {
    const el = ownRef.current;
    if (!el) return;
    const end = el.value.length;
    const start = el.selectionStart ?? end;
    const stop = el.selectionEnd ?? end;
    // Select-all is left alone, so typing or Backspace replaces the whole code.
    const all = start === 0 && stop === end && end > 0;
    if (!all && (start !== end || stop !== end)) {
      try {
        el.setSelectionRange(end, end);
      } catch {
        // Some input types refuse selection APIs; ours is text, but never let a cosmetic
        // caret rule throw inside an event handler.
      }
    }
  }, []);

  const commit = useCallback(
    (next: string) => {
      if (next === value) return;
      onChange(next);
      if (next.length === length && onComplete) onComplete(next);
    },
    [length, onChange, onComplete, value],
  );

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    commit(sanitizeOtp(event.currentTarget.value, length, mode));
  };

  // Paste is handled so a full code always REPLACES what is there: the native insert would
  // append it after the caret and the overflow would be cut, keeping stale digits.
  const handlePaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const pasted = sanitizeOtp(event.clipboardData.getData("text"), length, mode);
    event.preventDefault();
    if (pasted.length === 0 || readOnly) return;
    commit(pasted.length >= length ? pasted : sanitizeOtp(value + pasted, length, mode));
  };

  const error = status === "error";
  const success = status === "success";
  const activeIndex = Math.min(value.length, length - 1);

  return (
    <div className={`w-full ${className}`}>
      <label htmlFor={id} className="block text-sm font-medium text-ink">
        {label}
      </label>
      <div ref={scope} className="relative mt-2 w-full max-w-[22rem]">
        <div aria-hidden className="grid gap-2 sm:gap-2.5" style={{ gridTemplateColumns: `repeat(${length}, minmax(0, 1fr))` }}>
          {Array.from({ length }, (_, i) => {
            const char = value[i] ?? "";
            const active = focused && !readOnly && i === activeIndex;
            return (
              <div
                key={i}
                className={`relative grid h-12 place-items-center rounded-xl border bg-surface transition-[border-color,box-shadow] duration-150 ease-out sm:h-14 ${
                  error
                    ? "border-rose-500 dark:border-rose-400"
                    : success
                      ? "border-brand-strong dark:border-brand-bright"
                      : active
                        ? "border-brand-strong shadow-[0_0_0_3px_color-mix(in_srgb,var(--brand)_22%,transparent)] dark:border-brand-bright"
                        : char
                          ? "border-ink/25"
                          : "border-line"
                } ${disabled ? "opacity-50" : ""}`}
              >
                <AnimatePresence initial={false}>
                  {char ? (
                    <motion.span
                      key={`${i}-${char}`}
                      initial={reduced ? false : { opacity: 0, transform: "translateY(4px)" }}
                      animate={{ opacity: 1, transform: "translateY(0px)" }}
                      exit={{ opacity: 0, transition: { duration: 0.08 } }}
                      transition={{ duration: 0.14, ease: EASE_OUT }}
                      className="col-start-1 row-start-1 font-mono text-xl font-medium tabular-nums text-ink"
                    >
                      {char}
                    </motion.span>
                  ) : null}
                </AnimatePresence>
                {active && !char ? (
                  <motion.span
                    className="col-start-1 row-start-1 block h-6 w-px rounded-full bg-ink"
                    initial={{ opacity: 1 }}
                    animate={reduced ? { opacity: 1 } : { opacity: [1, 1, 0, 0] }}
                    transition={
                      reduced
                        ? { duration: 0 }
                        : { duration: 1.06, times: [0, 0.5, 0.5, 1], repeat: Infinity, ease: "linear" }
                    }
                  />
                ) : null}
              </div>
            );
          })}
        </div>
        <input
          ref={setRefs}
          id={id}
          name="one-time-code"
          type="text"
          inputMode={mode === "numeric" ? "numeric" : "text"}
          pattern={mode === "numeric" ? "[0-9]*" : undefined}
          autoComplete="one-time-code"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="done"
          value={value}
          readOnly={readOnly}
          disabled={disabled}
          aria-invalid={error || undefined}
          aria-describedby={describedBy}
          onChange={handleChange}
          onPaste={handlePaste}
          onFocus={() => {
            setFocused(true);
            keepCaretAtEnd();
          }}
          onBlur={() => setFocused(false)}
          onSelect={keepCaretAtEnd}
          onClick={keepCaretAtEnd}
          // 16px so iOS does not zoom the page on focus; the text itself is transparent,
          // the boxes underneath draw it.
          className="absolute inset-0 h-full w-full cursor-text appearance-none rounded-xl border-0 bg-transparent text-base text-transparent caret-transparent outline-none selection:bg-transparent disabled:cursor-not-allowed"
        />
      </div>
    </div>
  );
}
