"use client";

/**
 * ACCOUNTS YOUR AGENTS USE — the calendar, sheet, CRM, WhatsApp, payment and API accounts
 * this business's agents act in (D-700).
 *
 * Account-wide, which is why it lives on the Integrations page and not on an agent: one
 * WhatsApp account or one CRM serves every agent that uses it. Two ways in:
 *
 * - SIGN IN (Google Calendar, Google Sheets, Zoho CRM, HubSpot): `useAccountSignIn` opens
 *   the consent page in a popup and finishes the connection when it comes back.
 * - PASTE A KEY (WhatsApp providers, Razorpay, the client's own API): sealed on save and
 *   never shown again — the list carries a fingerprint only.
 *
 * One list of services, each row saying whether it is connected and to what (REDESIGN-2).
 * It used to be four "Connect" cards above a separate list of what was connected, so the
 * owner read the same fact in two places and matched them up themselves.
 *
 * Only the owner connects or removes an account; an operator viewing the account is
 * refused by the server with the reason, which renders here as the error.
 */

import { useId, useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { Section, TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import { FieldMessage, useFormValidation } from "@/components/formValidation";
import { PasswordInput } from "@/components/passwordInput";
import {
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
  useTestCredential,
  type CredentialTest,
  type IntegrationCredential,
  type OAuthKind,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

import type { KeyKind } from "../agents/actions/params";
import { useAccountSignIn } from "./useAccountSignIn";

const SIGN_IN: { kind: OAuthKind; label: string; what: string }[] = [
  { kind: "google_calendar", label: "Google Calendar", what: "Find free times and book them for callers." },
  {
    kind: "google_sheets",
    label: "Google Sheets",
    what: "Write calls and leads into the spreadsheets you choose, and look callers up.",
  },
  { kind: "zoho_crm", label: "Zoho CRM", what: "Save callers as leads and greet them by name." },
  { kind: "hubspot", label: "HubSpot", what: "Save callers as contacts and greet them by name." },
];
const SIGN_IN_KINDS: readonly string[] = SIGN_IN.map((s) => s.kind);

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
  const { signIn, connect, complete, error: signInError } = useAccountSignIn(session);
  const remove = useDeleteCredential(session);
  const probe = useTestCredential(session);
  const [tested, setTested] = useState<{ id: string; result: CredentialTest } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<IntegrationCredential | null>(null);
  const [adding, setAdding] = useState(false);

  /** Check and Disconnect for one connected account, and the check's answer under it. */
  const accountActions = (c: IntegrationCredential) => (
    <span className="flex flex-wrap items-center gap-x-4">
      <button
        type="button"
        className={TEXT_ACTION}
        disabled={!canWrite || probe.isPending}
        onClick={() => probe.mutate(c.id, { onSuccess: (result) => setTested({ id: c.id, result }) })}
        aria-label={`Check ${c.label}`}
      >
        Check
      </button>
      <button
        type="button"
        className={TEXT_ACTION_DANGER}
        disabled={!canWrite}
        onClick={() => setPendingDelete(c)}
        aria-label={`Disconnect ${c.label}`}
      >
        Disconnect
      </button>
    </span>
  );
  const checkResult = (c: IntegrationCredential) =>
    tested?.id === c.id ? (
      <p className={`text-meta ${tested.result.ok ? "text-ink-muted" : "text-danger"}`} role="status">
        {tested.result.message}
      </p>
    ) : null;

  const keys = creds.data?.filter((c) => !SIGN_IN_KINDS.includes(c.kind)) ?? [];

  return (
    <div className="space-y-10">
      <Section
        title="Accounts your agents use"
        description="Connect each one once. Every agent can then use it on calls."
      >
        {creds.isPending ? (
          <Skeleton rows={4} />
        ) : creds.isError ? (
          <ProblemNotice error={creds.error} onRetry={() => void creds.refetch()} />
        ) : (
          <ul className="divide-y divide-line border-y border-line">
            {SIGN_IN.map((s) => {
              const available = status.data?.[s.kind] === true;
              const mine = creds.data.filter((c) => c.kind === s.kind);
              return (
                <li key={s.kind} className="flex flex-col gap-2 py-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
                  <div className="min-w-0">
                    <p className="text-body font-medium text-ink">{s.label}</p>
                    <p className="text-meta text-ink-muted">{s.what}</p>
                  </div>
                  <div className="min-w-0 space-y-1.5 sm:text-right">
                    {mine.map((c) => (
                      <div key={c.id}>
                        <div className="flex flex-wrap items-center gap-x-4 sm:justify-end">
                          <span className="text-body text-ink [overflow-wrap:anywhere]">{c.label}</span>
                          {accountActions(c)}
                        </div>
                        {checkResult(c)}
                      </div>
                    ))}
                    {mine.length === 0 ? (
                      <button
                        type="button"
                        className={SECONDARY_BUTTON_SM}
                        disabled={!canWrite || !available || connect.isPending}
                        onClick={() => signIn(s.kind)}
                      >
                        {available ? `Connect ${s.label}` : "Not available yet"}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className={TEXT_ACTION}
                        disabled={!canWrite || !available || connect.isPending}
                        onClick={() => signIn(s.kind)}
                      >
                        Connect another
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {signInError ? <ProblemNotice error={signInError} /> : null}
        {complete.isSuccess ? (
          <NoticeBox tone="ok" title="Connected" className="mt-3">
            {complete.data.label} is connected. Choose it on an agent&rsquo;s Actions.
          </NoticeBox>
        ) : null}
        <p className={`${FIELD_HINT} mt-3`}>
          Google asks for permission on the account you choose. Calevate can open only the
          spreadsheets you pick.
        </p>
      </Section>

      <Section
        headingLevel={2}
        title="Keys"
        description="For services you connect by pasting a key. We seal it and never show it again."
        action={
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={!canWrite}
            onClick={() => setAdding((v) => !v)}
            aria-expanded={adding}
          >
            Add a key
          </button>
        }
      >
        {adding ? <AddKey session={session} onDone={() => setAdding(false)} /> : null}
        {creds.data && keys.length === 0 && !adding ? (
          <p className="text-body text-ink-muted">No keys yet.</p>
        ) : null}
        {keys.length > 0 ? (
          <ul className="divide-y divide-line border-y border-line">
            {keys.map((c) => (
              <li key={c.id} className="py-3.5">
                <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1">
                  <span className="min-w-0 text-body text-ink [overflow-wrap:anywhere]">
                    {c.label}{" "}
                    <span className="text-ink-muted">
                      · {lookup(PROVIDER_LABELS, c.kind) ?? c.kind} · ····{c.last_four}
                    </span>
                  </span>
                  {accountActions(c)}
                </div>
                {checkResult(c)}
              </li>
            ))}
          </ul>
        ) : null}
      </Section>

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
    </div>
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
      className="mb-6 max-w-md space-y-3"
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
