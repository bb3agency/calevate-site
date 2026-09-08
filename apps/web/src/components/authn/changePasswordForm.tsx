"use client";

/**
 * "Change password", for a person who is already signed in (`POST /password/change`).
 *
 * The browser half of the endpoint `apps/api/authn/service.py::change_password` describes:
 * the CURRENT password proves it is them, the caller's own session is ROTATED rather than
 * spared, and every other session in the realm dies. It is presentational plus one
 * mutation and holds NO session logic of its own — the realm hands it a `changePassword`
 * function and nothing here knows which realm produced it. That split is D-177's line:
 * CLAUDE.md forbids the two realms sharing session logic, and a shared FORM is not that,
 * in exactly the way `EmailVerificationPanel` is not.
 *
 * ## What it says BEFORE the submit, and why that paragraph is not decoration
 *
 * Every other session ends, unconditionally — `change_password` argues the option to keep
 * them is the default that fails the person this endpoint exists for. The consequence
 * lands on a device that is not in front of them: the phone in their pocket is signed out
 * with no explanation, and a person who was not warned reads that as a broken app rather
 * than as the thing they just asked for. So the warning is above the fields, always, and
 * not in a tooltip.
 *
 * ## Where each refusal is rendered
 *
 * At the FIELD it is about, when it is about one: `invalid_current_password` under the
 * current-password box, `password_unchanged` and `password_unacceptable` under the new
 * one. `AuthField` wires `aria-invalid` + `aria-describedby` + `role="alert"` for that,
 * so the message is announced when it appears and is attached to the input a screen
 * reader lands on. Anything else — a 429, a step-up refusal nobody answered, a dropped
 * connection — has no field to sit under and goes to `AuthProblemNotice`, which renders
 * the one code-keyed sentence `lib/authn/problems.ts` holds for it. The notice is
 * suppressed while a field message is showing: one refusal said twice in two places is
 * how a person comes to believe two things went wrong.
 *
 * ## The confirmation field, which the sign-in form does not have
 *
 * A mistyped NEW password here is unrecoverable in the same way the reset form's is. The
 * browser stays signed in, but the credential it would take to change it again is the
 * string that was mistyped and is now nowhere — the only way back is a reset link. It is
 * compared locally on two values the same person just typed, which is the comparison
 * `setPasswordForm.tsx` argues is the legitimate one (§5.7 defect 6 is a credential
 * compared against a SECRET to authenticate; this decides whether a button is enabled).
 */

import { useState, type FormEvent } from "react";

import { useMutation } from "@tanstack/react-query";
import { KeyRound, ShieldCheck } from "lucide-react";

import { AuthField, AuthProblemNotice } from "@/components/authn/fields";
import { NoticeBox, PRIMARY_BUTTON } from "@/components/ui";
import {
  MAX_PASSWORD_CHARS,
  MIN_PASSWORD_CHARS_BY_REALM,
  passwordProblem,
  passwordRule,
  type AuthnRealm,
} from "@/lib/authn/password";
import { AUTHN_CODES, codeOf, passwordFieldMessage, signInMessage } from "@/lib/authn/problems";

export interface ChangePasswordFormProps {
  /**
   * WHICH REALM's floor to show, required for the reason `SetPasswordForm` requires it:
   * 15 characters on the client realm and 12 on the admin one, and a form advertising
   * the wrong one refuses what the server would take or takes what it will refuse.
   */
  realm: AuthnRealm;
  /**
   * The realm's own call, passed in. Answers how many OTHER sessions it ended.
   *
   * A function rather than a `RealmAuthn`, because the admin realm's version is not the
   * bare call: it has a step-up prompt wrapped around it (`adminAuthn.changeAdminPassword`),
   * and that wrapping is admin-only by construction — there is no client-realm step-up to
   * route through. Handing this component a realm instance would put the choice of which
   * realm to talk to inside a shared file, which is the thing D-177 forbids.
   */
  changePassword: (input: { currentPassword: string; newPassword: string }) => Promise<number>;
}

/** "signed you out of N other devices", said correctly at 0 and at 1. */
export function revokedSentence(revoked: number): string {
  if (revoked === 0) return "There were no other sessions to sign out.";
  if (revoked === 1) return "We signed you out of 1 other device.";
  return `We signed you out of ${revoked} other devices.`;
}

export function ChangePasswordForm({ realm, changePassword }: ChangePasswordFormProps) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmation, setConfirmation] = useState("");
  /** Shown only after a submit attempt, so a field is not red before it is touched. */
  const [attempted, setAttempted] = useState(false);

  const submit = useMutation({
    mutationFn: () => changePassword({ currentPassword: current, newPassword: next }),
    onSuccess: () => {
      // Three credentials, held no longer than the request needed them.
      setCurrent("");
      setNext("");
      setConfirmation("");
      setAttempted(false);
    },
  });

  const lengthProblem = passwordProblem(next, realm);
  const mismatch = confirmation !== "" && confirmation !== next;
  const canSend =
    current !== "" && lengthProblem === null && !mismatch && confirmation !== "";

  const refusalCode = codeOf(submit.error);
  const currentPasswordProblem =
    refusalCode === AUTHN_CODES.invalidCurrentPassword ? signInMessage(submit.error) : null;
  const unchangedProblem =
    refusalCode === AUTHN_CODES.passwordUnchanged ? signInMessage(submit.error) : null;
  /** The server's blocklist reason, which depends on the string that was typed. */
  const blocklistProblem = passwordFieldMessage(submit.error);
  const newPasswordProblem = unchangedProblem ?? blocklistProblem;

  /** A refusal shown at a field must not also be shown in the notice. */
  const noticeError =
    currentPasswordProblem === null && newPasswordProblem === null ? submit.error : null;

  /** Editing any field makes the last refusal describe a string that is no longer here. */
  const clearRefusal = (): void => {
    if (submit.isError) submit.reset();
  };

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        setAttempted(true);
        if (submit.isPending || !canSend) return;
        submit.mutate();
      }}
    >
      {/* BEFORE the fields, not after the click. See the docstring: the cost of this
          change lands on a device that is not in the room. */}
      <NoticeBox tone="warn" title="This signs out your other devices">
        <p className="mt-1">
          Changing your password ends every other session on this account — your phone, a
          second browser, a laptop you left somewhere. This browser stays signed in.
        </p>
      </NoticeBox>

      {submit.isSuccess && (
        <NoticeBox
          tone="ok"
          icon={<ShieldCheck aria-hidden className="h-4 w-4" />}
          title="Your password is changed"
        >
          {/* `role="status"` (polite): the change succeeded and focus is still on the
              button the person pressed, so this is news to announce rather than an
              interruption to force. `role="alert"` is for the refusals above. */}
          <p role="status" className="mt-1">
            {revokedSentence(submit.data)} You are still signed in here — use your new
            password everywhere else.
          </p>
        </NoticeBox>
      )}

      <AuthField
        label="Current password"
        type="password"
        reveals="current password"
        autoComplete="current-password"
        maxLength={MAX_PASSWORD_CHARS}
        value={current}
        onChange={(event) => {
          setCurrent(event.target.value);
          clearRefusal();
        }}
        error={currentPasswordProblem}
      />

      <AuthField
        label="New password"
        type="password"
        reveals="new password"
        autoComplete="new-password"
        minLength={MIN_PASSWORD_CHARS_BY_REALM[realm]}
        maxLength={MAX_PASSWORD_CHARS}
        value={next}
        onChange={(event) => {
          setNext(event.target.value);
          clearRefusal();
        }}
        hint={passwordRule(realm)}
        error={attempted ? (lengthProblem ?? newPasswordProblem) : newPasswordProblem}
      />

      <AuthField
        label="Type it again"
        type="password"
        // Distinct from the field above's: two controls named "Show password" on one form
        // are two controls a screen-reader user cannot tell apart.
        reveals="the repeated password"
        autoComplete="new-password"
        maxLength={MAX_PASSWORD_CHARS}
        value={confirmation}
        onChange={(event) => setConfirmation(event.target.value)}
        error={mismatch ? "These two do not match." : null}
      />

      <AuthProblemNotice error={noticeError} />

      <button type="submit" className={PRIMARY_BUTTON} disabled={submit.isPending || !canSend}>
        <KeyRound aria-hidden className="h-4 w-4" />
        {submit.isPending ? "Changing…" : "Change password"}
      </button>
    </form>
  );
}
