"use client";

import { useId, useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { Drawer } from "@/components/console/drawer";
import { FieldMessage, useFormValidation } from "@/components/formValidation";
import { PasswordInput } from "@/components/passwordInput";
import {
  Disclosure,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
} from "@/components/ui";
import type { useAgents } from "@/lib/api/agents";
import type { useCreateLeadSource } from "@/lib/api/leadSources";

import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { IssuedSecretNotice, type IssuedSecret } from "./IssuedSecretNotice";
import { META_SOURCE, WEBHOOK_KINDS, sourceLabel } from "./sourceKinds";
import { FIELD } from "./styles";

const KINDS = [
  { value: "webhook", label: "Webhook", hint: "A website form, Zoho, Google Sheets, or anything that can POST." },
  { value: "meta", label: "Meta Lead Ads", hint: "Facebook and Instagram lead forms." },
] as const;

/**
 * ADD A LEAD SOURCE: which kind, which agent answers, and (rarely) the form's own field
 * names. The success step is the one moment the minted secret exists in plaintext.
 *
 * Every control sits in one `fieldset disabled` for a viewer without `org:manage`, so the
 * form cannot be filled in and discovered inert at the last click.
 */
export function AddSourceDrawer({
  open,
  onClose,
  create,
  agents,
  canWrite,
}: {
  open: boolean;
  onClose: () => void;
  create: ReturnType<typeof useCreateLeadSource>;
  agents: ReturnType<typeof useAgents>;
  canWrite: boolean;
}) {
  const formId = useId();
  const [kind, setKind] = useState<"webhook" | "meta">("webhook");
  const [webhookKind, setWebhookKind] = useState<string>("website_form");
  const [agentId, setAgentId] = useState("");
  const [phoneField, setPhoneField] = useState("phone");
  const [nameField, setNameField] = useState("name");
  const [consentField, setConsentField] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [issued, setIssued] = useState<IssuedSecret | null>(null);
  const valid = useFormValidation();
  const appSecretTrack = valid.track("appSecret", "Paste your Meta App Secret.");
  const appSecretErrorId = `${useId()}-app-secret-error`;
  const isMeta = kind === "meta";
  /** §52: no agent list (failed, or paused offline) means the choice cannot be made yet. */
  const agentsUnread = agents.error != null || (!agents.isLoading && !agents.data);

  const close = () => {
    setIssued(null);
    setAppSecret("");
    create.reset();
    onClose();
  };

  const submit = () => {
    const mapping: Record<string, string> = {};
    if (phoneField.trim()) mapping.phone = phoneField.trim();
    if (nameField.trim()) mapping.name = nameField.trim();
    if (consentField.trim()) mapping.consent_field = consentField.trim();
    create.mutate(
      {
        source: isMeta ? META_SOURCE : webhookKind,
        agent_id: agentId || null,
        mapping,
        ...(isMeta && appSecret.trim() ? { app_secret: appSecret.trim() } : {}),
      },
      {
        onSuccess: (made) => {
          setIssued({ secret: made.secret, header: made.secret_header, path: made.ingest_path, expiresAt: null });
          setAppSecret("");
        },
      },
    );
  };

  return (
    <Drawer
      open={open}
      onClose={close}
      title={issued ? "Lead source added" : "Add a lead source"}
      footer={
        issued ? (
          <button type="button" onClick={close} className={PRIMARY_BUTTON}>
            I&apos;ve saved it
          </button>
        ) : (
          <>
            <button type="button" onClick={close} className={SECONDARY_BUTTON}>
              Cancel
            </button>
            {/* Blocked while the agent list is unreadable: the form would otherwise POST
                with no agent and make exactly the silent never-dialling source the
                sentence beside the picker promises to prevent. */}
            <button
              type="submit"
              form={formId}
              disabled={!canWrite || create.isPending || agentsUnread}
              className={PRIMARY_BUTTON}
            >
              {create.isPending ? "Adding…" : "Add lead source"}
            </button>
          </>
        )
      }
    >
      {issued ? (
        <IssuedSecretNotice issued={issued} />
      ) : (
        <form id={formId} noValidate onSubmit={valid.onSubmit(submit)}>
          <fieldset disabled={!canWrite} className="m-0 space-y-5 border-0 p-0">
            {create.error != null && <ProblemNotice error={create.error} />}
            <fieldset>
              <legend className={FIELD_LABEL}>Where leads come from</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {KINDS.map((option) => (
                  <label key={option.value} className={`${CHOICE_CARD} ${kind === option.value ? CHOICE_ON : CHOICE_OFF}`}>
                    <input
                      type="radio"
                      name={`${formId}-kind`}
                      className="sr-only"
                      checked={kind === option.value}
                      onChange={() => setKind(option.value)}
                    />
                    {kind === option.value && (
                      <CheckCircle2 aria-hidden className="absolute right-2 top-2 h-4 w-4 text-brand-strong" />
                    )}
                    <span className="block pr-6 text-sm font-semibold text-ink">{option.label}</span>
                    <span className="mt-0.5 block text-xs text-ink-faint">{option.hint}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            {!isMeta && (
              <label className="block">
                <span className={FIELD_LABEL}>What sends them</span>
                <select
                  aria-label="Lead source kind"
                  value={webhookKind}
                  onChange={(e) => setWebhookKind(e.target.value)}
                  className={`${FIELD} mt-1 block w-full`}
                >
                  {WEBHOOK_KINDS.map((option) => (
                    <option key={option} value={option}>
                      {sourceLabel(option)}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <div>
              <span className={FIELD_LABEL}>Which agent answers them</span>
              {agentsUnread ? (
                // An empty picker over a failed read offers "don't call" as the only choice,
                // and a client would build a source that never rings anyone.
                <p className="mt-1 rounded-md border border-line bg-surface px-3 py-2 text-xs text-ink-muted">
                  We could not read your agents just now, so this cannot be chosen yet — saving
                  without it would create a source that never rings anyone. Reload the page to try
                  again.
                </p>
              ) : (
                <select
                  aria-label="Agent to answer these leads"
                  value={agentId}
                  disabled={agents.isLoading}
                  onChange={(e) => setAgentId(e.target.value)}
                  className={`${FIELD} mt-1 block w-full`}
                >
                  {/* A source with no agent SAVES leads and never dials them: say it. */}
                  <option value="">
                    {agents.isLoading ? "Reading your agents…" : "Not yet — save leads, don't call"}
                  </option>
                  {(agents.data ?? []).map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {isMeta && (
              <div className="text-xs text-ink-muted">
                <span className={FIELD_LABEL}>Your Meta app&apos;s App Secret</span>
                <PasswordInput
                  inputRef={appSecretTrack.ref}
                  onInput={appSecretTrack.onInput}
                  required
                  aria-label="Meta App Secret"
                  aria-invalid={valid.message("appSecret") ? true : undefined}
                  aria-describedby={valid.message("appSecret") ? appSecretErrorId : undefined}
                  reveals="app secret"
                  value={appSecret}
                  onChange={(e) => setAppSecret(e.target.value)}
                  wrapperClassName="mt-1 block w-full"
                  className={`${FIELD} font-mono`}
                />
                {valid.message("appSecret") ? (
                  <FieldMessage id={appSecretErrorId}>{valid.message("appSecret")}</FieldMessage>
                ) : null}
                <span className={FIELD_HINT}>
                  Meta signs every notification with this. Find it under App settings → Basic.
                </span>
              </div>
            )}

            {/* Consent is not a formality on this path: a lead that does not affirm it is
                saved and never dialled (FLOWS §4). The sentence stays visible. */}
            <p className="text-xs text-ink-muted">
              If your form asks permission to call, name that field — a lead that does not
              confirm it is saved and never dialled.
            </p>
            <Disclosure
              variant="inline"
              headingLevel={3}
              title="Your form's field names"
              subtitle={`Phone: ${phoneField || "as sent"} · Name: ${nameField || "as sent"} · Consent: ${consentField || "none"}`}
            >
              <fieldset className="grid gap-3 sm:grid-cols-3">
                <legend className="sr-only">What your form calls each field (leave blank to send ours)</legend>
                <label className="block min-w-0">
                  <span className={FIELD_LABEL}>Phone</span>
                  <input
                    value={phoneField}
                    onChange={(e) => setPhoneField(e.target.value)}
                    aria-label="Your form's phone field name"
                    placeholder="phone_number"
                    className={`${FIELD} w-full font-mono`}
                  />
                </label>
                <label className="block min-w-0">
                  <span className={FIELD_LABEL}>Name</span>
                  <input
                    value={nameField}
                    onChange={(e) => setNameField(e.target.value)}
                    aria-label="Your form's name field name"
                    placeholder="full_name"
                    className={`${FIELD} w-full font-mono`}
                  />
                </label>
                <label className="block min-w-0">
                  <span className={FIELD_LABEL}>Consent (optional)</span>
                  <input
                    value={consentField}
                    onChange={(e) => setConsentField(e.target.value)}
                    aria-label="Your form's consent field name"
                    placeholder="consent_to_call (optional)"
                    className={`${FIELD} w-full font-mono`}
                  />
                </label>
              </fieldset>
            </Disclosure>
          </fieldset>
        </form>
      )}
    </Drawer>
  );
}
