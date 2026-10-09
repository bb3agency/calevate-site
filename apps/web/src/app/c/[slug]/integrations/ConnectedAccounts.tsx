"use client";

/**
 * CONNECTED ACCOUNTS — the calendar, CRM, WhatsApp, payment and API accounts this
 * business's agents act in (D-700).
 *
 * Account-wide, which is why it lives on the Integrations page and not on an agent: one
 * WhatsApp account or one CRM serves every agent that uses it. Two ways in:
 *
 * - SIGN IN (Google Calendar, Zoho CRM, HubSpot): the consent page opens in a popup, the
 *   provider returns to `/oauth/callback/<provider>`, which hands the code back here
 *   (`oauthReturn.ts`), and the server keeps the long-lived connection.
 * - PASTE A KEY (WhatsApp providers, Razorpay, the client's own API): sealed on save and
 *   never shown again — the list carries a fingerprint only.
 *
 * Only the owner connects or removes an account; an operator viewing the account is
 * refused by the server with the reason, which renders here as the error.
 */

import { useEffect, useId, useState } from "react";
import { FlaskConical, KeyRound, LogIn, Plus, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { FieldMessage, useFormValidation } from "@/components/formValidation";
import { PasswordInput } from "@/components/passwordInput";
import {
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import {
  PROVIDER_LABELS,
  useConnectionsStatus,
  useCreateCredential,
  useCredentials,
  useDeleteCredential,
  useOAuthComplete,
  useOAuthConnect,
  useTestCredential,
  type CredentialTest,
  type IntegrationCredential,
  type OAuthKind,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

import type { KeyKind } from "../agents/actions/params";
import { beginOAuthReturn, takeOAuthReturn, OAUTH_RETURN_KEY } from "./oauthReturn";

const SIGN_IN: { kind: OAuthKind; label: string; what: string }[] = [
  { kind: "google_calendar", label: "Google Calendar", what: "Find free times and book appointments." },
  { kind: "zoho_crm", label: "Zoho CRM", what: "Save callers as leads and greet them by name." },
  { kind: "hubspot", label: "HubSpot", what: "Save callers as contacts and greet them by name." },
];

const KEY_KINDS: { kind: KeyKind; label: string; hint: string }[] = [
  { kind: "aisensy", label: "AiSensy API key", hint: "AiSensy → Manage → API key." },
  {
    kind: "meta_cloud",
    label: "WhatsApp Cloud API token",
    hint: "A permanent system user token from Meta Business Settings.",
  },
  { kind: "interakt", label: "Interakt API key", hint: "Interakt → Settings → Developer Settings." },
  {
    kind: "razorpay",
    label: "Razorpay keys",
    hint: "Razorpay Dashboard → Account & Settings → API Keys. Payments go to your account.",
  },
  { kind: "custom_api", label: "Your own API key", hint: "Sent only to your own address." },
];

export function ConnectedAccounts({ session, canWrite }: { session: Session; canWrite: boolean }) {
  const creds = useCredentials(session);
  const status = useConnectionsStatus(session);
  const connect = useOAuthConnect(session);
  const complete = useOAuthComplete(session);
  const remove = useDeleteCredential(session);
  const probe = useTestCredential(session);
  const [tested, setTested] = useState<{ id: string; result: CredentialTest } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<IntegrationCredential | null>(null);
  const [adding, setAdding] = useState(false);

  // A consent that came back — in this tab after a redirect, or in the popup, which writes
  // it to storage for this tab to finish (`oauthReturn.ts`).
  useEffect(() => {
    const finish = () => {
      const back = takeOAuthReturn(session.orgSlug);
      if (back) complete.mutate(back);
    };
    finish();
    const onStorage = (e: StorageEvent) => {
      if (e.key === OAUTH_RETURN_KEY) finish();
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
    // `complete` is stable for this component's life; re-running on it would re-read storage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.orgSlug]);

  function signIn(kind: OAuthKind) {
    connect.mutate(kind, {
      onSuccess: (r) => {
        beginOAuthReturn(session.orgSlug, kind);
        const popup = window.open(r.authorize_url, "calevate-connect", "width=520,height=720");
        // A blocked popup: go there in this tab; the callback page brings the client back.
        if (!popup) window.location.assign(r.authorize_url);
      },
    });
  }

  return (
    <section className="space-y-4 rounded-card border border-line bg-surface p-4" aria-labelledby="connected-accounts">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="connected-accounts" className="flex items-center gap-1.5 text-base font-semibold text-ink">
          <KeyRound className="h-4 w-4" /> Connected accounts
        </h2>
      </div>
      <p className="text-sm text-ink-muted">
        The accounts your agents use during calls. Connect each one once and choose it on an
        agent&rsquo;s Actions. We never show a saved key or password again, and only the
        account owner can connect or remove one.
      </p>

      <ul className="grid gap-2 sm:grid-cols-3">
        {SIGN_IN.map((s) => {
          const available = status.data?.[s.kind] === true;
          return (
            <li key={s.kind} className="rounded-card border border-line bg-app p-3">
              <p className="text-sm font-medium text-ink">{s.label}</p>
              <p className="text-xs text-ink-muted">{s.what}</p>
              <button
                type="button"
                className={`${SECONDARY_BUTTON_SM} mt-2`}
                disabled={!canWrite || !available || connect.isPending}
                onClick={() => signIn(s.kind)}
              >
                <LogIn className="mr-1 inline h-3.5 w-3.5" />
                {available ? `Connect ${s.label}` : "Not available yet"}
              </button>
            </li>
          );
        })}
      </ul>
      {connect.isError ? <ProblemNotice error={connect.error} /> : null}
      {complete.isError ? <ProblemNotice error={complete.error} /> : null}
      {complete.isSuccess ? (
        <NoticeBox tone="ok" title="Connected">
          {complete.data.label} is connected. Choose it on an agent&rsquo;s Actions.
        </NoticeBox>
      ) : null}

      <p className={FIELD_HINT}>
        {status.data?.sheets_share_with
          ? `Google Sheets: share your sheet with ${status.data.sheets_share_with} as an Editor — no sign-in needed.`
          : "Google Sheets is not available on your account yet."}
      </p>

      {creds.isPending ? (
        <Skeleton rows={2} />
      ) : creds.isError ? (
        <ProblemNotice error={creds.error} onRetry={() => void creds.refetch()} />
      ) : creds.data.length === 0 ? (
        <p className="text-sm text-ink-muted">Nothing connected yet.</p>
      ) : (
        <ul className="divide-y divide-line rounded-card border border-line bg-app">
          {creds.data.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
              <span className="min-w-0 break-words text-ink">
                {c.label}{" "}
                <span className="text-ink-faint">
                  · {lookup(PROVIDER_LABELS, c.kind) ?? c.kind} · ····{c.last_four}
                </span>
              </span>
              <span className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className={SECONDARY_BUTTON_SM}
                  disabled={!canWrite || probe.isPending}
                  onClick={() =>
                    probe.mutate(c.id, { onSuccess: (result) => setTested({ id: c.id, result }) })
                  }
                >
                  <FlaskConical className="mr-1 inline h-3.5 w-3.5" /> Check
                </button>
                <button
                  type="button"
                  className={DANGER_BUTTON}
                  disabled={!canWrite}
                  onClick={() => setPendingDelete(c)}
                  aria-label={`Disconnect ${c.label}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </span>
              {tested?.id === c.id ? (
                <p className={`w-full text-xs ${tested.result.ok ? "text-ink" : "text-danger"}`} role="status">
                  {tested.result.message}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {probe.isError ? <ProblemNotice error={probe.error} /> : null}
      {remove.error && pendingDelete === null ? <ProblemNotice error={remove.error} /> : null}
      {pendingDelete && (
        <ConfirmDialog
          title={`Disconnect “${pendingDelete.label}”?`}
          confirmLabel="Disconnect"
          pendingLabel="Disconnecting…"
          pending={remove.isPending}
          error={remove.error}
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => remove.mutate(pendingDelete.id, { onSuccess: () => setPendingDelete(null) })}
        >
          <p>
            Every action that uses it is taken off your live agents straight away. If a caller
            asks for one anyway, the agent says it can&rsquo;t do that right now.
          </p>
          <p>Connect it again any time and choose it on those actions.</p>
        </ConfirmDialog>
      )}

      <div>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={!canWrite}
          onClick={() => setAdding((v) => !v)}
          aria-expanded={adding}
        >
          <Plus className="mr-1 inline h-3.5 w-3.5" /> Add a key
        </button>
        {adding ? <AddKey session={session} onDone={() => setAdding(false)} /> : null}
      </div>
    </section>
  );
}

function AddKey({ session, onDone }: { session: Session; onDone: () => void }) {
  const create = useCreateCredential(session);
  const [kind, setKind] = useState<KeyKind>("aisensy");
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");
  const [keyId, setKeyId] = useState("");
  const secretId = useId();
  const valid = useFormValidation();
  const secretTrack = valid.track("secret", "Paste the key.");
  const chosen = KEY_KINDS.find((k) => k.kind === kind);

  return (
    <form
      className="mt-3 space-y-2 rounded-card border border-line bg-app p-3"
      noValidate
      onSubmit={valid.onSubmit(() => {
        create.mutate(
          {
            kind,
            label,
            secret,
            non_secret: kind === "razorpay" ? { key_id: keyId.trim() } : null,
          },
          { onSuccess: onDone },
        );
      })}
    >
      <label className="block">
        <span className={FIELD_LABEL}>What is it?</span>
        <select className={FIELD} value={kind} onChange={(e) => setKind(e.target.value as KeyKind)}>
          {KEY_KINDS.map((k) => (
            <option key={k.kind} value={k.kind}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      {chosen ? <p className={FIELD_HINT}>{chosen.hint}</p> : null}
      <div>
        <label className="block">
          <span className={FIELD_LABEL}>Name it</span>
          <input
            {...valid.field("label", "Give it a name you will recognise.")}
            className={FIELD}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Main WhatsApp number"
            required
          />
        </label>
        {valid.error("label")}
      </div>
      {kind === "razorpay" ? (
        <div>
          <label className="block">
            <span className={FIELD_LABEL}>Key ID</span>
            <input
              {...valid.field("keyId", "Paste the Key ID.")}
              className={FIELD}
              value={keyId}
              onChange={(e) => setKeyId(e.target.value)}
              autoComplete="off"
              required
            />
          </label>
          {valid.error("keyId")}
        </div>
      ) : null}
      <div>
        <label htmlFor={secretId} className={`block ${FIELD_LABEL}`}>
          {kind === "razorpay" ? "Key Secret" : "Key"}
        </label>
        <PasswordInput
          inputRef={secretTrack.ref}
          onInput={secretTrack.onInput}
          id={secretId}
          reveals="key"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          required
          aria-invalid={valid.message("secret") ? true : undefined}
          aria-describedby={valid.message("secret") ? `${secretId}-error` : undefined}
        />
        {valid.message("secret") ? (
          <FieldMessage id={`${secretId}-error`}>{valid.message("secret")}</FieldMessage>
        ) : null}
        <span className={FIELD_HINT}>Shown once, here. We seal it and never show it again.</span>
      </div>
      {create.isError ? <ProblemNotice error={create.error} /> : null}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={PRIMARY_BUTTON_SM} disabled={create.isPending}>
          {create.isPending ? "Saving…" : "Save"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
