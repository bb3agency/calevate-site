"use client";

import type { ReactNode } from "react";

import { CopyButton } from "@/components/interior/copy-button";
import { formatIST } from "@/components/ui";
import { API_BASE } from "@/lib/api/client";

import { CODE } from "./styles";

export interface IssuedSecret {
  /** Null for Meta: the client brought their own App Secret, so nothing was minted. */
  secret: string | null;
  header: string;
  /** Set on create; a rotation does not move the address. */
  path: string | null;
  /** When the previous secret stops working, on a rotation with a grace window. */
  expiresAt: string | null;
}

/**
 * What a create or a rotation just issued, each value with its own copy button.
 *
 * The secret exists in plaintext only in this response: nothing re-reads it, so the
 * sentence that says so is the first thing on the panel and is not softened.
 */
export function IssuedSecretNotice({ issued }: { issued: IssuedSecret }) {
  return (
    <div className="space-y-4 text-sm">
      {issued.secret ? (
        <>
          <p className="font-medium text-ink">Copy this secret now — we will not show it again.</p>
          <CopyRow label="Secret" value={issued.secret} copyLabel="Copy secret" />
          <CopyRow
            label="Header"
            value={issued.header}
            copyLabel="Copy header name"
            hint="Send the secret in this header on every submission."
          />
        </>
      ) : (
        <p className="font-medium text-ink">
          Saved. We store your app secret and verify every notification against it — there is
          nothing new for you to copy.
        </p>
      )}
      {issued.path && (
        <CopyRow
          label="Address"
          value={`${API_BASE}${issued.path}`}
          copyLabel="Copy address"
          hint="Send leads here."
        />
      )}
      {issued.expiresAt && (
        <p className="text-ink-muted">
          Your previous secret keeps working until {formatIST(issued.expiresAt)} — update your
          form before then and no lead is lost.
        </p>
      )}
      {issued.expiresAt === null && issued.path === null && (
        <p className="text-ink-muted">The previous secret stopped working immediately.</p>
      )}
    </div>
  );
}

export function CopyRow({
  label,
  value,
  copyLabel,
  hint,
}: {
  label: string;
  value: string;
  copyLabel: string;
  hint?: ReactNode;
}) {
  return (
    <div>
      <p className="text-xs font-medium text-ink-muted">{label}</p>
      <div className="mt-1 flex items-start gap-1">
        <code className={`${CODE} min-w-0 flex-1`}>{value}</code>
        <CopyButton value={value} label={copyLabel} />
      </div>
      {hint && <p className="mt-1 text-xs text-ink-faint">{hint}</p>}
    </div>
  );
}
