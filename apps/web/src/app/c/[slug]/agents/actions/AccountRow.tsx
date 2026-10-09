"use client";

/**
 * WHICH CONNECTED ACCOUNT A JOB USES, as one label–value row: "Calendar  Google · sri@…
 * Change". The "connect if needed" step of the guided flow lives here: an account you
 * sign in to (Google, Zoho, HubSpot) connects from this row in a popup; an account that
 * takes a pasted key points to the Integrations page, where keys are added once for the
 * whole business.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { SettingRow } from "@/components/console/settingRow";
import { TEXT_ACTION } from "@/components/console/section";
import { FIELD, ProblemNotice } from "@/components/ui";
import { PROVIDER_LABELS, useConnectionsStatus, useCredentials, type OAuthKind } from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { useAccountSignIn } from "../../integrations/useAccountSignIn";
import type { CredKind } from "./params";

const OAUTH: readonly CredKind[] = ["google_calendar", "google_sheets", "zoho_crm", "hubspot"];
const isOAuth = (kind: CredKind): kind is OAuthKind & CredKind => OAUTH.includes(kind);

/** "Google · sri@…" — the service, then the account's own label. */
const SERVICE: Partial<Record<CredKind, string>> = {
  google_calendar: "Google",
  google_sheets: "Google",
  zoho_crm: "Zoho",
  hubspot: "HubSpot",
};

export function AccountRow({
  label,
  kind,
  value,
  onChange,
  session,
  optional = false,
}: {
  label: string;
  kind: CredKind;
  value: string;
  onChange: (credentialId: string) => void;
  session: Session;
  /** A custom API may run with no key at all. */
  optional?: boolean;
}) {
  const creds = useCredentials(session);
  const status = useConnectionsStatus(session);
  const { signIn, connect, complete, error } = useAccountSignIn(session);
  const [picking, setPicking] = useState(false);
  const { href } = useClientRealm();

  const mine = creds.data?.filter((c) => c.kind === kind);
  const chosen = mine?.find((c) => c.id === value);

  // The first account is the obvious choice: pre-select it rather than ask.
  useEffect(() => {
    if (!value && !optional && mine && mine.length > 0) onChange(mine[0]?.id ?? "");
  }, [value, optional, mine, onChange]);

  // A sign-in that just finished for this kind becomes the choice.
  useEffect(() => {
    if (complete.data && complete.data.kind === kind) {
      onChange(complete.data.id);
      setPicking(false);
    }
  }, [complete.data, kind, onChange]);

  if (creds.isPending) return <SettingRow label={label} value="Loading…" />;
  if (!mine) {
    return (
      <div className="py-3.5">
        <ProblemNotice
          error={creds.error ?? new Error("Your connected accounts could not be loaded.")}
          onRetry={() => void creds.refetch()}
        />
      </div>
    );
  }

  const service = SERVICE[kind] ?? lookup(PROVIDER_LABELS, kind) ?? kind;
  const oauth = isOAuth(kind);
  const available = !oauth || status.data?.[kind] === true;
  const connectButton = oauth ? (
    <button
      type="button"
      className={TEXT_ACTION}
      disabled={!available || connect.isPending}
      onClick={() => signIn(kind)}
    >
      {connect.isPending ? "Opening…" : mine.length ? "Connect another account" : `Connect ${service}`}
    </button>
  ) : (
    <Link className={TEXT_ACTION} href={href(`/c/${session.orgSlug}/integrations`)}>
      Add one on Integrations
    </Link>
  );

  let row;
  if (mine.length === 0) {
    row = (
      <SettingRow
        label={label}
        value={<span className="text-ink-muted">{optional ? "None" : "Not connected"}</span>}
        hint={oauth && !available ? "Not available on your account yet. Ask your Calevate team." : undefined}
        action={connectButton}
      />
    );
  } else if (picking) {
    row = (
      <SettingRow
        label={label}
        control={
          <select
            aria-label={label}
            className={`${FIELD} mt-0 sm:w-64`}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          >
            {optional ? <option value="">No key</option> : null}
            {mine.map((c) => (
              <option key={c.id} value={c.id}>
                {service} · {c.label}
              </option>
            ))}
          </select>
        }
        action={connectButton}
      />
    );
  } else {
    row = (
      <SettingRow
        label={label}
        value={chosen ? `${service} · ${chosen.label}` : <span className="text-ink-muted">None</span>}
        action={
          <button type="button" className={TEXT_ACTION} onClick={() => setPicking(true)}>
            Change
          </button>
        }
      />
    );
  }

  return (
    <>
      {row}
      {error ? <ProblemNotice error={error} /> : null}
    </>
  );
}
