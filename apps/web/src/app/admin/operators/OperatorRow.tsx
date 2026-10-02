"use client";

import { useRef, useState } from "react";
import { Lock, ShieldCheck, UserCog } from "lucide-react";

import { RowMenu, type RowMenuItem } from "@/components/console/rowMenu";
import { formatIST } from "@/components/ui";
import {
  ROLE_COPY,
  operatorLabel,
  selfAdministrationBlock,
  tierChangeTarget,
  type Operator,
} from "@/lib/api/adminOperators";
import { lookup } from "@/lib/lookup";

import { ResendPanel, RevokePanel, RoleChangePanel } from "./rowConfirmations";

/** A tier as a badge, from the wire string, never from a guess about seniority. */
function RoleBadge({ role }: { role: string }) {
  const copy = lookup(ROLE_COPY, role);
  const isSuper = role === "superadmin";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
        isSuper ? "bg-brand-soft text-brand-strong" : "bg-ink/[0.06] text-ink-muted"
      }`}
    >
      {isSuper ? <ShieldCheck aria-hidden className="h-3 w-3" /> : <UserCog aria-hidden className="h-3 w-3" />}
      {/* Fails visible: a tier this build has no word for still gets its badge, with the
          wire string in it, because that account is the one somebody needs to look at. */}
      {copy?.label ?? role}
    </span>
  );
}

/** Which inline confirmation, if any, this row has open. */
type RowAction = "role" | "revoke" | "resend";

function LockLine({ children }: { children: string }) {
  return (
    <p className="mt-2 flex items-start gap-2 text-xs text-ink-muted">
      <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      {children}
    </p>
  );
}

export function OperatorRow({
  operator,
  viewerId,
  restriction,
}: {
  operator: Operator;
  viewerId: string | null;
  restriction: string | null;
}) {
  const [open, setOpen] = useState<RowAction | null>(null);
  const row = useRef<HTMLLIElement>(null);
  const selfBlock = selfAdministrationBlock(operator, viewerId);
  const label = operatorLabel(operator);
  // `null` for a tier this build has no words for: it will not guess which way a change
  // would move them. Revoking needs no opinion about the tier, so it stays.
  const target = tierChangeTarget(operator);
  const actionable = selfBlock === null && restriction === null;

  const close = () => {
    setOpen(null);
    row.current?.querySelector<HTMLElement>('button[aria-haspopup="menu"]')?.focus();
  };

  const items: RowMenuItem[] = [
    {
      id: "role",
      label: "Change tier",
      disabled: target === null,
      hint: target === null ? "Tier not recognised" : undefined,
      onSelect: () => setOpen("role"),
    },
    // Only for an account that never set a password: for anyone else it would be a
    // password reset, which the API refuses (`operator_already_activated`).
    ...(!operator.activated
      ? [{ id: "resend", label: "Resend setup link", onSelect: () => setOpen("resend") }]
      : []),
    { id: "revoke", label: "Revoke access", tone: "danger", onSelect: () => setOpen("revoke") },
  ];

  return (
    <li ref={row} className="px-1 py-3 text-sm">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span title={operator.name ?? undefined} className="min-w-0 truncate font-medium text-ink">
              {operator.name ?? "No name on file"}
            </span>
            {selfBlock !== null && <span className="text-xs text-ink-faint">(you)</span>}
            <RoleBadge role={operator.role} />
            {!operator.activated && (
              <span className="inline-flex items-center rounded-full border border-warn-line bg-warn-soft px-2 py-0.5 text-xs font-medium text-warn">
                Setup link outstanding
              </span>
            )}
          </div>
          {/* The whole address: two accounts at one domain must be told apart before one is
              revoked, and the confirmations are typed against it. */}
          <span title={operator.email ?? undefined} className="block truncate font-mono text-xs text-ink-muted">
            {operator.email ?? "no address on file"}
          </span>
          <span className="block text-xs text-ink-faint">Added {formatIST(operator.created_at)}</span>
          {/* The lockout sentence where the controls would be: the API refuses both acts on
              your own account outright, so a disabled control would never be available. */}
          {selfBlock !== null ? (
            <LockLine>{selfBlock}</LockLine>
          ) : restriction !== null ? (
            <LockLine>{restriction}</LockLine>
          ) : (
            target === null && (
              <p className="mt-2 text-xs text-ink-muted">
                This console does not recognise the tier{" "}
                <span className="font-mono">{operator.role}</span>, so it will not guess which way
                a change would move them. Revoking still works.
              </p>
            )
          )}
        </div>
        {actionable && <RowMenu label={label} items={items} />}
      </div>

      {open === "role" && target !== null && (
        <RoleChangePanel operator={operator} target={target} onClose={close} />
      )}
      {open === "revoke" && <RevokePanel operator={operator} onClose={close} />}
      {open === "resend" && <ResendPanel operator={operator} onClose={close} />}
    </li>
  );
}
