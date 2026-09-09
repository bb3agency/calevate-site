"use client";

import { useId, useState } from "react";
import { KeyRound, Power } from "lucide-react";

import { FieldMessage, useFormValidation } from "@/components/formValidation";
import { PasswordInput } from "@/components/passwordInput";
import { PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM, formatIST } from "@/components/ui";
import type { LeadSource } from "@/lib/api/leadSources";

import { sourceLabel } from "./sourceKinds";
import { FIELD } from "./styles";

/** One source: what it is, which secret we hold, and the two things you can do to it. */
export function LeadSourceRow({
  item,
  canWrite,
  busy,
  onRotate,
  onToggle,
}: {
  item: LeadSource;
  canWrite: boolean;
  busy: boolean;
  onRotate: (graceMinutes: number, appSecret?: string) => void;
  onToggle: () => void;
}) {
  const [rotating, setRotating] = useState(false);
  const [grace, setGrace] = useState("60");
  const [appSecret, setAppSecret] = useState("");
  const valid = useFormValidation();
  const appSecretTrack = valid.track("appSecret", "Paste the new Meta App Secret.");
  const appSecretErrorId = `${useId()}-new-app-secret-error`;
  const isMeta = item.source === "meta_lead_ads";

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-ink">{sourceLabel(item.source)}</span>
        {!item.active && (
          <span className="rounded-full border border-line bg-app px-2 py-0.5 text-xs text-ink-muted">
            off
          </span>
        )}
        <code className="text-xs text-ink-faint">{item.id}</code>
        {/* The fingerprint, never the secret: enough to tell the client which key we
            hold when they are staring at two of them in a form vendor's settings. */}
        <span className="ml-auto text-xs text-ink-faint">key ···{item.secret_fingerprint}</span>
        <button
          type="button"
          disabled={!canWrite || busy}
          onClick={() => setRotating((open) => !open)}
          className={SECONDARY_BUTTON_SM}
        >
          <KeyRound className="h-3.5 w-3.5" />
          {rotating ? "Cancel" : "New secret"}
        </button>
        <button
          type="button"
          disabled={!canWrite || busy}
          onClick={onToggle}
          className={SECONDARY_BUTTON_SM}
        >
          <Power className="h-3.5 w-3.5" />
          {item.active ? "Turn off" : "Turn on"}
        </button>
      </div>

      {item.previous_secret_expires_at && (
        <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
          Your previous secret still works until {formatIST(item.previous_secret_expires_at)}.
        </p>
      )}

      {rotating && (
        <form
          className="mt-2 flex flex-wrap items-end gap-2"
          noValidate
          onSubmit={valid.onSubmit(() => {
            onRotate(Number(grace), isMeta ? appSecret.trim() || undefined : undefined);
            setRotating(false);
            setAppSecret("");
          })}
        >
          {isMeta && (
            <div className="text-xs text-ink-muted">
              <span className="block">Your new Meta App Secret</span>
              <PasswordInput
                inputRef={appSecretTrack.ref}
                onInput={appSecretTrack.onInput}
                required
                aria-label="New Meta App Secret"
                aria-invalid={valid.message("appSecret") ? true : undefined}
                aria-describedby={valid.message("appSecret") ? appSecretErrorId : undefined}
                reveals="new app secret"
                value={appSecret}
                onChange={(e) => setAppSecret(e.target.value)}
                wrapperClassName="block w-56"
                className={`${FIELD} font-mono`}
              />
              {valid.message("appSecret") ? (
                <FieldMessage id={appSecretErrorId}>{valid.message("appSecret")}</FieldMessage>
              ) : null}
            </div>
          )}
          <label className="text-xs text-ink-muted">
            Keep the old secret working for
            <select
              aria-label="How long the old secret keeps working"
              value={grace}
              onChange={(e) => setGrace(e.target.value)}
              className={`${FIELD} mt-1 block`}
            >
              <option value="60">1 hour (recommended)</option>
              <option value="1440">24 hours</option>
              {/* The revocation, named for what it costs rather than for what it is:
                  a client choosing this because it sounds tidiest would drop the leads
                  submitted in the minutes it takes them to update their form. */}
              <option value="0">Stop it immediately — my secret leaked</option>
            </select>
          </label>
          <button type="submit" disabled={busy} className={PRIMARY_BUTTON_SM}>
            Issue new secret
          </button>
        </form>
      )}
    </li>
  );
}
