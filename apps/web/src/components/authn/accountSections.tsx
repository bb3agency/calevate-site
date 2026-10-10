"use client";

/**
 * The rows both realms' account pages share: the email address and the sessions block.
 *
 * Presentation plus the realm's own calls, handed in as a `RealmAuthn` exactly as
 * `EmailVerificationPanel` takes one. Nothing here holds or restores a session (D-177:
 * the realms never share session logic); each page passes its realm's instance and its
 * own sign-in path.
 */

import { useCallback, useState } from "react";

import { useMutation } from "@tanstack/react-query";

import { EmailVerificationPanel } from "@/components/authn/emailVerificationPanel";
import { AuthProblemNotice } from "@/components/authn/fields";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Section, TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { StatusPill } from "@/components/console/statusPill";
import type { RealmAuthn } from "@/lib/authn/realm";

/**
 * The address on file: verified, or a way to verify it.
 *
 * `email` is shown when the page knows it (the client realm reads it from `/v1/me`); a row
 * without it still says whether the address is verified, which is what the session knows.
 */
export function EmailRow({
  authn,
  email,
  verified,
  onVerified,
}: {
  authn: RealmAuthn;
  email?: string | null;
  verified: boolean;
  onVerified: () => void;
}) {
  const [verifying, setVerifying] = useState(false);
  const value = (
    <span className="inline-flex flex-wrap items-center justify-end gap-x-2.5 gap-y-1">
      {email ? <span className="[overflow-wrap:anywhere]">{email}</span> : null}
      {verified ? (
        <StatusPill tone="ok">Verified</StatusPill>
      ) : (
        <StatusPill tone="warn">Not verified</StatusPill>
      )}
    </span>
  );
  if (verified) {
    return (
      <SettingRow
        label="Email address"
        // What rests on a verified address, which is why losing the mailbox matters:
        // `POST /otp/request` and `POST /password/reset/request` mail only this subject.
        hint="Sign-in codes and password reset links only go here."
        value={value}
      />
    );
  }
  return (
    <div>
      <SettingRow
        label="Email address"
        hint="Verify it so you can reset your password."
        value={value}
        action={
          verifying ? undefined : (
            <button type="button" className={TEXT_ACTION} onClick={() => setVerifying(true)}>
              Verify
            </button>
          )
        }
      />
      {verifying && (
        <div className="max-w-sm pb-5">
          <EmailVerificationPanel authn={authn} onVerified={onVerified} />
        </div>
      )}
    </div>
  );
}

/**
 * "This browser: Sign out" and "Every device: Sign out everywhere", the second behind a
 * confirmation. Ending every session is the one irreversible act on the page, so its filled
 * red button lives only inside the dialog, and a refusal stays in the dialog where the
 * decision is being made.
 */
export function SessionsSection({
  authn,
  signInPath,
  lifetime,
  everywhereHint,
  everywhereConsequence,
}: {
  authn: RealmAuthn;
  /** Where the page goes once this browser's session has ended. */
  signInPath: string;
  /** The realm's session lifetime, as one line under the heading. */
  lifetime: string;
  /** One line under "Every device". */
  everywhereHint: string;
  /** The confirmation's body: what ending every session costs. */
  everywhereConsequence: string;
}) {
  const [confirming, setConfirming] = useState(false);

  const leave = useCallback(() => {
    window.location.assign(signInPath);
  }, [signInPath]);

  const signOut = useMutation({ mutationFn: () => authn.signOut(), onSuccess: leave });
  const signOutAll = useMutation({
    mutationFn: () => authn.signOutEverywhere(),
    onSuccess: leave,
  });
  const busy = signOut.isPending || signOutAll.isPending;

  return (
    <Section title="Sessions" description={lifetime}>
      <SettingRows className="border-y border-line">
        <SettingRow
          label="This browser"
          action={
            <button
              type="button"
              className={TEXT_ACTION}
              disabled={busy}
              onClick={() => {
                if (!signOut.isPending) signOut.mutate();
              }}
            >
              {signOut.isPending ? "Signing out…" : "Sign out"}
            </button>
          }
        />
        <SettingRow
          label="Every device"
          hint={everywhereHint}
          action={
            <button
              type="button"
              className={TEXT_ACTION_DANGER}
              disabled={busy}
              onClick={() => setConfirming(true)}
            >
              Sign out everywhere
            </button>
          }
        />
      </SettingRows>
      {signOut.error != null && (
        <div className="mt-3">
          <AuthProblemNotice error={signOut.error} />
        </div>
      )}

      {confirming && (
        <ConfirmDialog
          title="Sign out everywhere?"
          confirmLabel="Sign out everywhere"
          pendingLabel="Signing out…"
          pending={signOutAll.isPending}
          error={signOutAll.error}
          onCancel={() => {
            signOutAll.reset();
            setConfirming(false);
          }}
          onConfirm={() => {
            if (!signOutAll.isPending) signOutAll.mutate();
          }}
        >
          <p>{everywhereConsequence}</p>
        </ConfirmDialog>
      )}
    </Section>
  );
}

/** The quiet way back to a console, above an account page's heading. */
export const BACK_LINK =
  "press inline-flex items-center gap-1.5 rounded-sm text-meta font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11";
