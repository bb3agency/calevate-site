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
import type { useCreateLeadSource } from "@/lib/api/leadSources";

import { ChoiceCards } from "@/components/console/choiceCards";
import { IssuedSecretNotice, type IssuedSecret } from "./IssuedSecretNotice";
import {
  META_SOURCE,
  PUSH_SOURCES,
  WEBHOOK_KINDS,
  sourceLabel,
  sourceLogo,
  type PushSource,
  type WebhookKind,
} from "./sourceKinds";
import { FIELD } from "./styles";

const KINDS = [
  { value: "webhook", label: "Website or app form", hint: "Your website, Zoho, Sheets or any app." },
  { value: "meta", label: "Meta Lead Ads", hint: "Facebook and Instagram lead forms." },
  {
    value: "push",
    label: "Portal or CRM",
    hint: "IndiaMART, 99acres, MagicBricks, Housing.com, LeadSquared.",
  },
] as const;
type Kind = (typeof KINDS)[number]["value"];

/**
 * ADD A LEAD SOURCE: which kind and (rarely) the form's own field names. Who calls its leads
 * is the "Call new leads" Follow-up's choice, not the source's. The success step is the one
 * moment the minted secret exists in plaintext.
 *
 * Every control sits in one `fieldset disabled` for a viewer without `org:manage`, so the
 * form cannot be filled in and discovered inert at the last click.
 */
export function AddSourceDrawer({
  open,
  onClose,
  create,
  createStatus,
  canWrite,
}: {
  open: boolean;
  onClose: () => void;
  create: ReturnType<typeof useCreateLeadSource>;
  /** The add's state from the screen's `useActionFeedback`. */
  createStatus: FeedbackStatus;
  canWrite: boolean;
}) {
  const formId = useId();
  const [kind, setKind] = useState<Kind>("webhook");
  const [webhookKind, setWebhookKind] = useState<WebhookKind>("website_form");
  const [pushKind, setPushKind] = useState<PushSource>("indiamart");
  const [phoneField, setPhoneField] = useState("phone");
  const [nameField, setNameField] = useState("name");
  const [consentField, setConsentField] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [issued, setIssued] = useState<IssuedSecret | null>(null);
  const valid = useFormValidation();
  const appSecretTrack = valid.track("appSecret", "Paste your Meta App Secret.");
  const appSecretErrorId = `${useId()}-app-secret-error`;
  const isMeta = kind === "meta";
  const isPush = kind === "push";

  const close = () => {
    setIssued(null);
    setAppSecret("");
    create.reset();
    onClose();
  };

  const submit = () => {
    // A pushed sender's body is not ours to shape: an empty mapping takes its preset.
    const mapping: Record<string, string> = {};
    if (!isPush) {
      if (phoneField.trim()) mapping.phone = phoneField.trim();
      if (nameField.trim()) mapping.name = nameField.trim();
      if (consentField.trim()) mapping.consent_field = consentField.trim();
    }
    create.mutate(
      {
        source: isMeta ? META_SOURCE : isPush ? pushKind : webhookKind,
        mapping,
        ...(isMeta && appSecret.trim() ? { app_secret: appSecret.trim() } : {}),
      },
      {
        onSuccess: (made) => {
          setIssued({
            secret: made.secret,
            header: made.secret_header,
            path: made.ingest_path,
            expiresAt: null,
            pushPath: made.push_path ?? null,
            source: made.source,
          });
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
            <ActionButton
              type="submit"
              form={formId}
              status={createStatus}
              successLabel="Added"
              disabled={!canWrite}
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
              columns="sm:grid-cols-3"
            />

            {isPush && (
              <label className="block">
                <span className={FIELD_LABEL}>Which one</span>
                <select
                  aria-label="Portal or CRM"
                  value={pushKind}
                  onChange={(e) => setPushKind(e.target.value as PushSource)}
                  className={`${FIELD} mt-1 block w-full`}
                >
                  {PUSH_SOURCES.map((option) => (
                    <option key={option} value={option}>
                      {sourceLabel(option)}
                    </option>
                  ))}
                </select>
                <span className={FIELD_HINT}>You get one address to paste. Fields are read for you.</span>
              </label>
            )}

            {!isMeta && !isPush && (
              <label className="block">
                <span className={FIELD_LABEL}>What sends them</span>
                <span className="mt-1 flex items-center gap-2">
                  {sourceLogo(webhookKind) ? <ServiceLogo service={sourceLogo(webhookKind)} className="h-5 w-5" /> : null}
                  <select
                    aria-label="Lead source kind"
                    value={webhookKind}
                    onChange={(e) => setWebhookKind(e.target.value as WebhookKind)}
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
                  In Meta: App settings → Basic.
                </span>
              </div>
            )}

            {/* Consent is not a formality on this path: a lead that does not affirm it is
                saved and never dialled (FLOWS §4). The sentence stays visible. */}
            <div className="text-meta text-ink-muted">
              <p>The agent in Call new leads calls them.</p>
              {isPush ? (
                <>
                  <p>Enquiries sent to you are called within seven days.</p>
                  <p>Bought leads are saved, not called.</p>
                </>
              ) : (
                <p>Leads who don&apos;t agree to calls are never called.</p>
              )}
            </div>
            {isPush ? null : (
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
            )}
          </fieldset>
        </form>
      )}
    </Drawer>
  );
}
