"use client";

import { useId, useState } from "react";
import { Webhook } from "lucide-react";

import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { Drawer } from "@/components/console/drawer";
import { IconTile } from "@/components/console/iconTile";
import { ServiceLogo } from "@/components/console/serviceLogo";
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

import { ChoiceCards } from "@/components/console/choiceCards";
import { IssuedSecretNotice, type IssuedSecret } from "./IssuedSecretNotice";
import { META_SOURCE, WEBHOOK_KINDS, sourceLabel, sourceLogo } from "./sourceKinds";
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
  createStatus,
  agents,
  canWrite,
}: {
  open: boolean;
  onClose: () => void;
  create: ReturnType<typeof useCreateLeadSource>;
  /** The add's state from the screen's `useActionFeedback`. */
  createStatus: FeedbackStatus;
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
      formId={formId}
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
            <ActionButton
              type="submit"
              form={formId}
              status={createStatus}
              successLabel="Added"
              disabled={!canWrite || agentsUnread}
            >
              Add lead source
            </ActionButton>
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
            <ChoiceCards
              legend="Where leads come from"
              legendClassName={FIELD_LABEL}
              name={`${formId}-kind`}
              value={kind}
              options={KINDS.map((option) => ({
                ...option,
                icon: <IconTile service={sourceLogo(option.value)} icon={Webhook} />,
              }))}
              onChange={setKind}
              columns="sm:grid-cols-2"
            />

            {!isMeta && (
              <label className="block">
                <span className={FIELD_LABEL}>What sends them</span>
                <span className="mt-1 flex items-center gap-2">
                  {sourceLogo(webhookKind) ? <ServiceLogo service={sourceLogo(webhookKind)} className="h-5 w-5" /> : null}
                  <select
                    aria-label="Lead source kind"
                    value={webhookKind}
                    onChange={(e) => setWebhookKind(e.target.value)}
                    className={`${FIELD} mt-0 block w-full`}
                  >
                    {WEBHOOK_KINDS.map((option) => (
                      <option key={option} value={option}>
                        {sourceLabel(option)}
                      </option>
                    ))}
                  </select>
                </span>
              </label>
            )}

            <div>
              <span className={FIELD_LABEL}>Which agent answers them</span>
              {agentsUnread ? (
                // An empty picker over a failed read offers "don't call" as the only choice,
                // and a client would build a source that never rings anyone.
                <p className="mt-1 rounded-md border border-line bg-surface px-3 py-2 text-meta text-ink-muted">
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
              <div className="text-meta text-ink-muted">
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
            <p className="text-meta text-ink-muted">
              If your form asks permission to call, name that field — a lead that does not
              confirm it is saved and never dialled.
            </p>
            <Disclosure
              variant="inline"
              headingLevel={3}
              title="Your form's field names"
              subtitle={`Phone: ${phoneField || "as sent"} · Name: ${nameField || "as sent"} · Consent: ${consentField || "none"}`}
            >
              <fieldset className="grid grid-cols-1 gap-3 sm:grid-cols-3">
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
