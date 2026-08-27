"use client";

/**
 * The three forms that set a password from an emailed link, as one form (D-174, §5.6).
 *
 * Password reset confirmation, invitation redemption and the first-administrator bootstrap
 * differ in their endpoint, their copy and whether they take a name. Everything else is
 * identical: read a single-use token out of a link, take a new password, refuse it locally
 * against the SAME bounds the API enforces, submit once, and say something useful about
 * every way it can fail. Writing that three times is how two of the three come to be
 * missing the confirmation field or the length rule — CLAUDE.md's one-way-per-problem
 * rule, applied where the temptation to copy is strongest.
 *
 * ## The bounds are the API's, per realm, and that is §5.7 defect 8
 *
 * The reference's client validator accepts 128 characters against a bcrypt that truncates
 * at 72, so it advertises strength it does not store. `lib/authn/password.ts` holds ours
 * and `tests/authnSourceGuards.test.ts` reads them back out of the API — the per-realm
 * floors from `apps/api/authn/policy.py::MIN_CHARS_BY_REALM` and the ceiling from
 * `apps/api/authn/hashing.py` — so the two cannot drift without the build saying so.
 * That is why `realm` is a required prop: the floor is 15 on the client realm and 12 on
 * the admin realm, and a form showing the wrong one is the same defect one level up.
 *
 * ## Length is checked here; the BLOCKLIST is checked only by the server
 *
 * `authn/policy.py` also refuses passwords that are keyboard walks, short repetitions, or
 * the person's own address wearing a suffix. None of that is mirrored into this file, and
 * that is deliberate: a second copy of a blocklist is a second thing to keep in step, and
 * the rules need the account's email address, which this form does not have — it holds a
 * single-use token and nothing else. So the refusal arrives from the submit, carrying the
 * reason NIST SP 800-63B-4 §3.1.1.2 requires it to carry, and `passwordFieldMessage`
 * puts it under the field the person is looking at.
 *
 * ## The confirmation field
 *
 * Present because this is the one place a typo is unrecoverable: the person is holding a
 * single-use token, and a password they cannot reproduce means asking for another link.
 * It is compared locally, on plain strings, which is the one comparison of this shape that
 * is legitimate — §5.7 defect 6 is a `===` comparing a credential against a stored SECRET
 * for authentication, and this compares two values the same person just typed, in their
 * own browser, deciding nothing but whether to enable a button. Nothing is authenticated
 * here and there is no attacker to time.
 */

import { useState, type FormEvent, type ReactNode } from "react";

import { useMutation } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";

import { AuthField, AuthProblemNotice } from "@/components/authn/fields";
import { Card, NoticeBox, PRIMARY_BUTTON } from "@/components/ui";
import {
  MAX_PASSWORD_CHARS,
  MIN_PASSWORD_CHARS_BY_REALM,
  passwordProblem,
  passwordRule,
  type AuthnRealm,
} from "@/lib/authn/password";
import { passwordFieldMessage } from "@/lib/authn/problems";
import { useLinkToken } from "@/lib/authn/useLinkToken";

export interface SetPasswordSubmission {
  token: string;
  password: string;
  /** Only sent by the invitation form; the other two have no name to take. */
  name?: string;
}

export interface SetPasswordFormProps<T> {
  /**
   * WHICH REALM this password is for, and it is required rather than defaulted.
   *
   * The minimum length differs between the two (`@/lib/authn/password`), because a
   * client password is single-factor and an admin password is one factor of two. A
   * default here would silently show one realm's floor on the other realm's form, and
   * showing the SMALLER of the two on a client form is the exact defect
   * `lib/authn/password.ts` exists to prevent: a validator looser than the server's,
   * which accepts a password the submit then refuses.
   */
  realm: AuthnRealm;
  /** What the button says, and what the heading above the fields says. */
  submitLabel: string;
  /** Prose above the fields — what this link is and what using it does. */
  intro: ReactNode;
  /** Ask for a display name too. Invitation redemption only. */
  askForName?: boolean;
  /** What to render once it has worked. Given the server's own answer. */
  renderSuccess: (result: T) => ReactNode;
  /** What to render when the link carried no token at all. */
  renderMissingToken: ReactNode;
  onSubmit: (submission: SetPasswordSubmission) => Promise<T>;
}

export function SetPasswordForm<T>({
  realm,
  submitLabel,
  intro,
  askForName = false,
  renderSuccess,
  renderMissingToken,
  onSubmit,
}: SetPasswordFormProps<T>) {
  const { token, ready } = useLinkToken();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [name, setName] = useState("");
  /** Shown only after a submit attempt, so the field is not red before it is touched. */
  const [attempted, setAttempted] = useState(false);

  const submit = useMutation({
    mutationFn: () =>
      onSubmit({
        token,
        password,
        name: askForName ? name.trim() || undefined : undefined,
      }),
    onSuccess: () => {
      // The credential's last use has happened. Held no longer than the request needed it.
      setPassword("");
      setConfirmation("");
    },
  });

  const lengthProblem = passwordProblem(password, realm);
  /**
   * The blocklist reason, when the last submit came back with one.
   *
   * It is shown AT THE FIELD rather than in the notice below, because that is where a
   * person looking at a red input reads, and because `NoticeBox` renders a single
   * sentence chosen by code — which cannot name a reason that depends on what was typed.
   * When it is showing, `AuthProblemNotice` is suppressed: two sentences about one
   * refusal, in two places, is how a person comes to believe two things went wrong.
   * The generic guidance is not lost — it is the field's own hint, permanently.
   */
  const blocklistProblem = passwordFieldMessage(submit.error);
  const mismatch = confirmation !== "" && confirmation !== password;
  const canSend = lengthProblem === null && !mismatch && confirmation !== "";

  if (submit.isSuccess) return <>{renderSuccess(submit.data)}</>;
  // `ready` gates this so a server render and the first client paint do not both claim the
  // link is broken before anything has looked at it.
  if (ready && token === "") return <>{renderMissingToken}</>;

  return (
    <Card>
      <form
        className="space-y-4"
        noValidate
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          setAttempted(true);
          if (submit.isPending || !canSend || token === "") return;
          submit.mutate();
        }}
      >
        <div className="space-y-2 text-sm text-ink-muted">{intro}</div>

        {askForName && (
          <AuthField
            label="Your name (optional)"
            autoComplete="name"
            maxLength={200}
            value={name}
            onChange={(event) => setName(event.target.value)}
            hint="Shown to colleagues on your account. You can change it later."
          />
        )}

        <AuthField
          label="New password"
          type="password"
          autoComplete="new-password"
          minLength={MIN_PASSWORD_CHARS_BY_REALM[realm]}
          maxLength={MAX_PASSWORD_CHARS}
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
            // The refusal described the string that WAS submitted. The moment it is
            // edited it describes nothing on screen, and leaving it up is a red field a
            // person cannot clear by fixing it. `reset()` rather than a remembered copy
            // of the refused password: nothing here should hold a credential longer than
            // the request needed it (see `onSuccess`).
            if (submit.isError) submit.reset();
          }}
          hint={passwordRule(realm)}
          error={attempted ? (lengthProblem ?? blocklistProblem) : null}
        />

        <AuthField
          label="Type it again"
          type="password"
          autoComplete="new-password"
          maxLength={MAX_PASSWORD_CHARS}
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          error={mismatch ? "These two do not match." : null}
        />

        {blocklistProblem === null && <AuthProblemNotice error={submit.error} />}

        <button
          type="submit"
          className={PRIMARY_BUTTON}
          disabled={submit.isPending || !canSend}
        >
          <KeyRound aria-hidden className="h-4 w-4" />
          {submit.isPending ? "Saving…" : submitLabel}
        </button>

        <p className="text-xs text-ink-faint">
          The link works once. If this fails, ask for a new one rather than reloading the
          page.
        </p>
      </form>
    </Card>
  );
}

/** The panel every one of the three shows when its link arrived without its code. */
export function MissingLinkCode({ what, remedy }: { what: string; remedy: string }) {
  return (
    <Card>
      <div className="space-y-3 text-sm text-ink-muted">
        {/* Not "this link is invalid": nothing has been checked. The likeliest cause is a
            chat app or mail client wrapping a long URL across two lines, so the remedy is
            about the LINK and is one the reader can act on without involving anybody. */}
        <NoticeBox tone="warn" title={`This ${what} link is missing its code`}>
          <p className="mt-1">
            A {what} link ends with a long code. This one arrived without it, so there is
            nothing here to open — it does not mean the link has been used or has expired.
          </p>
        </NoticeBox>
        <p>
          Open it from the original message rather than retyping it, and copy all of it.
          {" "}
          {remedy}
        </p>
      </div>
    </Card>
  );
}
