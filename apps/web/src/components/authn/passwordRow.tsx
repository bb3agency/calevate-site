"use client";

/**
 * The Password row of both realms' account pages (`POST /password/change`): a "Change"
 * action that opens the form in place, and closes it on success or Cancel.
 *
 * Presentation plus one mutation, with NO session logic: the realm hands it a
 * `changePassword` function. That keeps D-177's line (the realms never share session
 * logic): the admin realm's function wraps its step-up prompt, the client realm's is the
 * bare call (`service.MFA_REQUIRED_REALMS` is `{"admin"}`), and nothing here knows which.
 *
 * The rules it keeps:
 * - Every OTHER session ends, so the warning is visible before the submit: the cost lands
 *   on a device that is not in the room. It is one line above the button.
 * - A refusal renders at the field it is about (`invalid_current_password` under Current,
 *   `password_unchanged` / `password_unacceptable` under New); only a refusal with no
 *   field (a 429, a dropped connection) goes to the notice. One refusal is never shown
 *   twice.
 * - A mistyped NEW password is unrecoverable without a reset link, hence the repeat. It is
 *   compared locally and only decides whether the button is enabled.
 * - The three passwords are cleared as soon as the request no longer needs them.
 */

import { useEffect, useRef, useState, type FormEvent } from "react";

import { useMutation } from "@tanstack/react-query";
import { Check } from "lucide-react";

import { AuthField, AuthProblemNotice } from "@/components/authn/fields";
import { TEXT_ACTION } from "@/components/console/section";
import { SettingRow } from "@/components/console/settingRow";
import { PRIMARY_BUTTON } from "@/components/ui";
import {
  MAX_PASSWORD_CHARS,
  MIN_PASSWORD_CHARS_BY_REALM,
  passwordProblem,
  type AuthnRealm,
} from "@/lib/authn/password";
import { AUTHN_CODES, codeOf, passwordFieldMessage, signInMessage } from "@/lib/authn/problems";

/** "signed you out of N other devices", said correctly at 0 and at 1. */
export function revokedSentence(revoked: number): string {
  if (revoked === 0) return "There were no other sessions to sign out.";
  if (revoked === 1) return "We signed you out of 1 other device.";
  return `We signed you out of ${revoked} other devices.`;
}

/**
 * The live length line under New password. NIST SP 800-63B-4 §3.1.1.2 asks the verifier to
 * guide the choice, not only state the floor, so the empty state names the easy way there.
 */
function lengthHint(length: number, floor: number): { text: string; met: boolean } {
  if (length === 0) {
    return {
      text: `At least ${floor} characters. Three or four unrelated words work well.`,
      met: false,
    };
  }
  if (length < floor) return { text: `At least ${floor} characters · ${length} so far`, met: false };
  if (length > MAX_PASSWORD_CHARS) {
    return { text: `At most ${MAX_PASSWORD_CHARS} characters · ${length} so far`, met: false };
  }
  return { text: "Long enough", met: true };
}

export interface PasswordRowProps {
  /**
   * Which realm's floor to show: 15 characters on the client realm, 12 on the admin one
   * (`lib/authn/password.ts`). A form advertising the wrong one refuses what the server
   * would take, or takes what it will refuse.
   */
  realm: AuthnRealm;
  /** The realm's own call. Answers how many OTHER sessions it ended. */
  changePassword: (input: { currentPassword: string; newPassword: string }) => Promise<number>;
}

export function PasswordRow({ realm, changePassword }: PasswordRowProps) {
  const floor = MIN_PASSWORD_CHARS_BY_REALM[realm];
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmation, setConfirmation] = useState("");
  /** Shown only after a submit attempt, so a field is not red before it is touched. */
  const [attempted, setAttempted] = useState(false);
  const changeButton = useRef<HTMLButtonElement>(null);
  const firstField = useRef<HTMLInputElement>(null);

  // Opening the form moves focus into it; the "Change" control that had focus is gone.
  useEffect(() => {
    if (open) firstField.current?.focus();
  }, [open]);

  const clear = (): void => {
    setCurrent("");
    setNext("");
    setConfirmation("");
    setAttempted(false);
  };

  const submit = useMutation({
    mutationFn: () => changePassword({ currentPassword: current, newPassword: next }),
    onSuccess: () => {
      clear();
      close();
    },
  });

  /** Close the form and hand focus back to the control that opened it. */
  function close(): void {
    setOpen(false);
    window.requestAnimationFrame(() => changeButton.current?.focus());
  }

  const lengthProblem = passwordProblem(next, realm);
  const mismatch = confirmation !== "" && confirmation !== next;
  const canSend = current !== "" && lengthProblem === null && !mismatch && confirmation !== "";

  const refusalCode = codeOf(submit.error);
  const currentProblem =
    refusalCode === AUTHN_CODES.invalidCurrentPassword ? signInMessage(submit.error) : null;
  const unchangedProblem =
    refusalCode === AUTHN_CODES.passwordUnchanged ? signInMessage(submit.error) : null;
  const newProblem = unchangedProblem ?? passwordFieldMessage(submit.error);
  const noticeError = currentProblem === null && newProblem === null ? submit.error : null;

  /** Editing any field makes the last refusal describe a string that is no longer here. */
  const clearRefusal = (): void => {
    if (submit.isError) submit.reset();
  };

  const hint = lengthHint(next.length, floor);

  return (
    <div>
      <SettingRow
        label="Password"
        hint={
          submit.isSuccess && !open ? (
            // Persistent rather than a fading tick: how many devices were signed out is
            // the one thing the person may need to act on (sign back in on their phone).
            <span role="status" className="inline-flex items-start gap-1 text-brand-strong dark:text-brand-bright">
              <Check aria-hidden className="mt-1 h-3.5 w-3.5 shrink-0" />
              <span>Password changed. {revokedSentence(submit.data)}</span>
            </span>
          ) : undefined
        }
        action={
          open ? undefined : (
            <button
              ref={changeButton}
              type="button"
              className={TEXT_ACTION}
              aria-label="Change your password"
              onClick={() => {
                submit.reset();
                setOpen(true);
              }}
            >
              Change
            </button>
          )
        }
      />

      {open && (
        <form
          aria-label="Change your password"
          className="max-w-sm space-y-4 pb-5"
          noValidate
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            setAttempted(true);
            if (submit.isPending || !canSend) return;
            submit.mutate();
          }}
        >
          <AuthField
            label="Current password"
            type="password"
            reveals="current password"
            autoComplete="current-password"
            maxLength={MAX_PASSWORD_CHARS}
            value={current}
            inputRef={firstField}
            onChange={(event) => {
              setCurrent(event.target.value);
              clearRefusal();
            }}
            error={currentProblem}
          />

          <AuthField
            label="New password"
            type="password"
            reveals="new password"
            autoComplete="new-password"
            minLength={floor}
            maxLength={MAX_PASSWORD_CHARS}
            value={next}
            onChange={(event) => {
              setNext(event.target.value);
              clearRefusal();
            }}
            hint={
              <span className={`inline-flex items-center gap-1 ${hint.met ? "text-brand-strong dark:text-brand-bright" : ""}`}>
                {hint.met && <Check aria-hidden className="h-3 w-3" />}
                {hint.text}
              </span>
            }
            error={attempted ? (lengthProblem ?? newProblem) : newProblem}
          />

          <AuthField
            label="Type it again"
            type="password"
            reveals="the repeated password"
            autoComplete="new-password"
            maxLength={MAX_PASSWORD_CHARS}
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            error={mismatch ? "These two do not match." : null}
          />

          <AuthProblemNotice error={noticeError} />

          {/* Before the button, not after the click: the cost lands on other devices. */}
          <p className="text-meta text-ink-muted">
            Saving ends every other session on this account. This browser stays signed in.
          </p>

          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <button type="submit" className={PRIMARY_BUTTON} disabled={submit.isPending || !canSend}>
              {submit.isPending ? "Saving…" : "Save new password"}
            </button>
            <button
              type="button"
              className={TEXT_ACTION}
              disabled={submit.isPending}
              onClick={() => {
                clear();
                submit.reset();
                close();
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
