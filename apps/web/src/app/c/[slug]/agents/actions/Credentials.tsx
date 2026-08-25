"use client";

/**
 * Saved integration credentials — the account-wide secrets an action can be pointed at.
 *
 * Split out of `Actions.tsx` (UX-DOCTRINE §6). It is an ACCOUNT-level list living on an
 * AGENT screen, which is why it reads no agent id and why its own copy says the secrets
 * are reused across actions.
 */

import { useState } from "react";
import { KeyRound, Plus, Trash2 } from "lucide-react";

import {
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import {
  PROVIDER_LABELS,
  useCreateCredential,
  useCredentials,
  useDeleteCredential,
  type IntegrationCredential,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

import type { CredKind } from "./params";

export function Credentials({ session }: { session: Session }) {
  const creds = useCredentials(session);
  const create = useCreateCredential(session);
  const remove = useDeleteCredential(session);
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<CredKind>("aisensy");
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");

  return (
    <div className="space-y-3 rounded-card border border-line bg-app p-4">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
          <KeyRound className="h-3.5 w-3.5" /> Saved credentials
        </h3>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen((v) => !v)}>
          <Plus className="mr-1 inline h-3.5 w-3.5" /> Add credential
        </button>
      </div>
      <p className={FIELD_HINT}>
        Saved once and reused across actions. Rotating one updates every action that uses it.
        We never show the value back.
      </p>
      {creds.isPending ? (
        <Skeleton rows={1} />
      ) : creds.isError ? (
        <ProblemNotice error={creds.error} />
      ) : creds.data.length === 0 ? (
        <p className="text-sm text-ink-muted">No credentials saved yet.</p>
      ) : (
        <ul className="space-y-1">
          {creds.data.map((c: IntegrationCredential) => (
            <li key={c.id} className="flex items-center justify-between text-sm">
              <span className="text-ink">
                {c.label}{" "}
                <span className="text-ink-faint">
                  · {lookup(PROVIDER_LABELS, c.kind) ?? c.kind} · ····{c.last_four}
                </span>
              </span>
              <button
                type="button"
                className={DANGER_BUTTON}
                onClick={() => {
                  if (confirm(`Delete credential “${c.label}”?`)) remove.mutate(c.id);
                }}
                aria-label={`Delete ${c.label}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {remove.error ? <ProblemNotice error={remove.error} /> : null}
      {open ? (
        <form
          className="space-y-2 border-t border-line pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(
              { kind, label, secret },
              {
                onSuccess: () => {
                  setOpen(false);
                  setLabel("");
                  setSecret("");
                },
              },
            );
          }}
        >
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>For</span>
              <select
                className={FIELD}
                value={kind}
                onChange={(e) => setKind(e.target.value as CredKind)}
              >
                <option value="aisensy">AiSensy API key</option>
                <option value="meta_cloud">Meta WhatsApp token</option>
                <option value="interakt">Interakt API key</option>
                <option value="custom_api">Custom API key / token</option>
              </select>
            </label>
          </div>
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>Name</span>
              <input
                className={FIELD}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                required
              />
            </label>
          </div>
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>Secret</span>
              <input
                className={FIELD}
                type="password"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                required
              />
            </label>
          </div>
          {create.isError ? <ProblemNotice error={create.error} /> : null}
          <button type="submit" className={PRIMARY_BUTTON_SM} disabled={create.isPending}>
            {create.isPending ? "Saving…" : "Save credential"}
          </button>
        </form>
      ) : null}
    </div>
  );
}
