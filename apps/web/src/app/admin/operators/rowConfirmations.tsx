"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { MailCheck, UserCog, UserMinus } from "lucide-react";

import { WriteFailure } from "@/app/admin/writeFailure";
import { TypedConfirmation, confirmationMatches } from "@/components/typedConfirmation";
import {
  DANGER_BUTTON,
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON_SM,
  SECONDARY_BUTTON,
} from "@/components/ui";
import {
  ROLE_COPY,
  operatorConfirmPhrase,
  operatorLabel,
  useResendOperatorSetupLink,
  useRevokeOperator,
  useSetOperatorRole,
  type AdminRole,
  type Operator,
} from "@/lib/api/adminOperators";
import { lookup } from "@/lib/lookup";

/**
 * The confirmation every consequential row action opens, inline under its row.
 *
 * One component rather than three near-copies: what differs is the heading, the
 * consequence and the phrase; what must not differ is the reason's bounds, the
 * typed-confirmation rule, the disabled predicate and where the failure renders.
 */
function ConfirmBlock({
  heading,
  consequence,
  confirmPhrase,
  reasonLabel,
  actionLabel,
  pendingLabel,
  danger,
  icon,
  pending,
  error,
  onConfirm,
  onClose,
  children,
}: {
  heading: string;
  consequence: ReactNode;
  /** What a PERSON types — the account's address, not the API's id-bound header string. */
  confirmPhrase: string;
  /**
   * The reason box's accessible name, naming the act and the account: every block's
   * visible label is "Why", and identical prompts cannot be told apart by a screen reader.
   * It begins with "Why" so the name still contains the visible label.
   */
  reasonLabel: string;
  actionLabel: string;
  pendingLabel: string;
  danger: boolean;
  icon: ReactNode;
  pending: boolean;
  error: unknown;
  onConfirm: (reason: string) => void;
  onClose: () => void;
  children?: ReactNode;
}) {
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  // Opened from the row's menu, so focus follows into the block it opened.
  useEffect(() => panel.current?.focus(), []);
  // Trimmed before it is measured: the API strips the reason and refuses anything under
  // three characters, and a form that lit up on "   " would read as a flaky API.
  const ready =
    reason.trim().length >= 3 && confirmationMatches(typed, confirmPhrase) && !pending;

  return (
    <div
      ref={panel}
      tabIndex={-1}
      role="group"
      aria-label={heading}
      className="mt-3 w-full space-y-3 rounded-card border border-line bg-surface p-4 outline-none focus-visible:ring-2 focus-visible:ring-brand"
    >
      <div className="flex gap-3">
        <span className={`mt-0.5 shrink-0 ${danger ? "text-danger" : "text-ink-faint"}`}>{icon}</span>
        <div className="min-w-0">
          <p className="font-semibold text-ink">{heading}</p>
          <div className="mt-1 text-ink-muted">{consequence}</div>
          <p className="mt-1 text-xs text-ink-faint">
            Recorded in the audit log against your admin account, with the reason you type
            below.
          </p>
        </div>
      </div>

      {children}

      <label className="block">
        <span className={FIELD_LABEL}>Why</span>
        <input
          required
          minLength={3}
          maxLength={500}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          aria-label={reasonLabel}
          placeholder="e.g. 'left the company on Friday'"
          className={FIELD}
        />
      </label>

      {/* The address, not `revoke_operator:<uuid>`: nobody types a UUID, they copy it. The
          address never leaves this page; the header the API validates is still the
          id-bound string (hard rule 6 keeps mailboxes out of headers). */}
      <TypedConfirmation
        phrase={confirmPhrase}
        hint="This names the account you are acting on, so a phrase typed for somebody else cannot be used here."
        value={typed}
        onChange={setTyped}
      />

      {error != null && <WriteFailure error={error} actionLabel={actionLabel} />}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!ready}
          onClick={() => onConfirm(reason.trim())}
          className={danger ? DANGER_BUTTON : PRIMARY_BUTTON_SM}
        >
          {pending ? pendingLabel : actionLabel}
        </button>
        <button type="button" disabled={pending} onClick={onClose} className={SECONDARY_BUTTON}>
          Cancel
        </button>
      </div>
    </div>
  );
}

export function RoleChangePanel({
  operator,
  target,
  onClose,
}: {
  operator: Operator;
  /** Decided by `tierChangeTarget`; the row offers no change at all when it is null. */
  target: AdminRole;
  onClose: () => void;
}) {
  const change = useSetOperatorRole();
  const targetCopy = lookup(ROLE_COPY, target);
  const label = operatorLabel(operator);
  const promoting = target === "superadmin";

  return (
    <ConfirmBlock
      heading={promoting ? `Promoting ${label} to super admin` : `Demoting ${label} to admin`}
      consequence={
        promoting ? (
          <p>
            They gain everything you can do: the vendor API keys, the platform configuration,
            the incident switches, and this screen — so they will be able to add and remove
            admins, including you. Their live sessions end, so the change is in force on their
            next request.
          </p>
        ) : (
          <p>
            They keep onboarding and support across every client and lose the four
            platform-wide authorities: the vendor API keys, the platform configuration, the
            incident switches and this screen. Their live sessions end, so the change is in
            force on their next request.
          </p>
        )
      }
      confirmPhrase={operatorConfirmPhrase(operator)}
      reasonLabel={`Why you are changing ${label}'s tier`}
      actionLabel={promoting ? "Promote to super admin" : "Demote to admin"}
      pendingLabel="Saving…"
      danger={promoting}
      icon={<UserCog aria-hidden className="h-4 w-4" />}
      pending={change.isPending}
      error={change.error}
      onConfirm={(reason) =>
        change.mutate({ operatorId: operator.id, role: target, reason }, { onSuccess: onClose })
      }
      onClose={onClose}
    >
      <p className="text-xs text-ink-faint">{targetCopy?.can}</p>
    </ConfirmBlock>
  );
}

export function RevokePanel({ operator, onClose }: { operator: Operator; onClose: () => void }) {
  const revoke = useRevokeOperator();
  const label = operatorLabel(operator);

  return (
    <ConfirmBlock
      heading={`Revoking ${label}'s access to this console`}
      consequence={
        <>
          <p>
            Their password, their live sessions and any outstanding setup link are destroyed,
            and they cannot sign in from their next request onwards. There is no undo: adding
            them again creates a new account and a new setup link.
          </p>
          <p className="mt-1">
            Their row is kept and their name stays on what they decided — the campaigns they
            approved, the identity checks they signed off, the credentials they installed.
            Nothing about this is a data erasure.
          </p>
        </>
      }
      confirmPhrase={operatorConfirmPhrase(operator)}
      reasonLabel={`Why you are revoking ${label}'s access`}
      actionLabel="Revoke access"
      pendingLabel="Revoking…"
      danger
      icon={<UserMinus aria-hidden className="h-4 w-4" />}
      pending={revoke.isPending}
      error={revoke.error}
      onConfirm={(reason) =>
        revoke.mutate({ operatorId: operator.id, reason }, { onSuccess: onClose })
      }
      onClose={onClose}
    />
  );
}

export function ResendPanel({ operator, onClose }: { operator: Operator; onClose: () => void }) {
  const resend = useResendOperatorSetupLink();
  const label = operatorLabel(operator);

  return (
    <ConfirmBlock
      heading={`Sending ${label} a fresh setup link`}
      consequence={
        <>
          <p>
            A new single-use link is mailed to{" "}
            <span className="font-mono">{operator.email ?? "their address"}</span> and the
            previous one stops working. It is not shown here and cannot be forwarded.
          </p>
          {/* Not a password reset, and the API refuses to let it become one. */}
          <p className="mt-1">
            This only works for an account that has never set a password. Somebody who has
            forgotten theirs uses the sign-in page&apos;s reset, which mails the link to them
            rather than to you.
          </p>
        </>
      }
      confirmPhrase={operatorConfirmPhrase(operator)}
      reasonLabel={`Why you are re-sending ${label}'s setup link`}
      actionLabel="Send a new setup link"
      pendingLabel="Sending…"
      danger={false}
      icon={<MailCheck aria-hidden className="h-4 w-4" />}
      pending={resend.isPending}
      error={resend.error}
      onConfirm={(reason) =>
        resend.mutate({ operatorId: operator.id, reason }, { onSuccess: onClose })
      }
      onClose={onClose}
    />
  );
}
