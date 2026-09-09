"use client";

import { useId, useState } from "react";
import { Plus } from "lucide-react";

import { FieldMessage, useFormValidation } from "@/components/formValidation";
import { PasswordInput } from "@/components/passwordInput";
import { useToast } from "@/components/interior/toaster";
import {
  Card,
  EmptyState,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  Skeleton,
} from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";
import {
  useCreateLeadSource,
  useLeadSources,
  useRotateLeadSourceSecret,
  useSetLeadSourceActive,
  type NewLeadSource,
} from "@/lib/api/leadSources";

import { IssuedSecretNotice, type IssuedSecret } from "./IssuedSecretNotice";
import { LeadSourceRow } from "./LeadSourceRow";
import { CREATABLE_SOURCES, sourceLabel } from "./sourceKinds";
import { FIELD } from "./styles";

/**
 * The card that ended out-of-band provisioning: create a source, see the ones you have,
 * rotate a secret, turn one off and back on.
 *
 * The secret banner is the delicate part. It is rendered from the create/rotate
 * RESPONSE and from nothing else — there is no route that returns it again, and there
 * must never be a code path here that re-reads one — and it carries the whole
 * instruction (which header, which URL) because a client who dismisses it and comes
 * back cannot recover the value.
 */
export function SourcesPanel({
  session,
  canWrite,
}: {
  session: ReturnType<typeof useClientSession>;
  canWrite: boolean;
}) {
  const sources = useLeadSources(session);
  const agents = useAgents(session);
  const create = useCreateLeadSource(session);
  const rotate = useRotateLeadSourceSecret(session);
  const setActive = useSetLeadSourceActive(session);
  // Turning a source off/on has no on-screen trace beyond the row's own state flipping;
  // a transient cue confirms the write landed. Additive and no-op without a provider —
  // the mutation, its invalidation and the `setActive.error` `ProblemNotice` are unchanged.
  const { toast } = useToast();

  const [source, setSource] = useState<string>("website_form");
  const [agentId, setAgentId] = useState("");
  const [phoneField, setPhoneField] = useState("phone");
  const [nameField, setNameField] = useState("name");
  const [consentField, setConsentField] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [issued, setIssued] = useState<IssuedSecret | null>(null);
  const valid = useFormValidation();
  const appSecretTrack = valid.track("appSecret", "Paste your Meta App Secret.");
  const appSecretErrorId = `${useId()}-app-secret-error`;

  const items = sources.data?.items;
  const isMeta = source === "meta_lead_ads";

  const submit = () => {
    // Only the rules the client filled in. A blank field is not a mapping to an empty
    // field name — the server refuses those — it is "we do not map this one".
    const mapping: Record<string, string> = {};
    if (phoneField.trim()) mapping.phone = phoneField.trim();
    if (nameField.trim()) mapping.name = nameField.trim();
    if (consentField.trim()) mapping.consent_field = consentField.trim();

    create.mutate(
      {
        source,
        agent_id: agentId || null,
        mapping,
        ...(isMeta && appSecret.trim() ? { app_secret: appSecret.trim() } : {}),
      },
      {
        onSuccess: (made: NewLeadSource) => {
          setIssued({
            secret: made.secret,
            header: made.secret_header,
            path: made.ingest_path,
            expiresAt: null,
          });
          setAppSecret("");
        },
      },
    );
  };

  return (
    <Card title="Your lead sources">
      <p className="text-sm text-ink-muted">
        Each lead source is one place leads come from — a website form, an ad account, a
        CRM. Each has its own address and its own secret.
      </p>

      {issued && <IssuedSecretNotice issued={issued} onDismiss={() => setIssued(null)} />}

      {sources.error != null && (
        <div className="mt-3">
          <ProblemNotice error={sources.error} onRetry={() => sources.refetch()} />
        </div>
      )}
      {create.error != null && (
        <div className="mt-3">
          <ProblemNotice error={create.error} />
        </div>
      )}
      {rotate.error != null && (
        <div className="mt-3">
          <ProblemNotice error={rotate.error} />
        </div>
      )}
      {setActive.error != null && (
        <div className="mt-3">
          <ProblemNotice error={setActive.error} />
        </div>
      )}

      {/* Loading is a skeleton, a failed read is the notice above and NO list. "No lead
          sources yet" under a failed request would have a client create a second source
          for a form that is already wired up — two secrets, one form, and leads landing
          on whichever they pasted last. */}
      {sources.isLoading ? (
        <div className="mt-3">
          <Skeleton rows={2} />
        </div>
      ) : !items ? null : items.length ? (
        <ul className="mt-3 divide-y divide-line">
          {items.map((item) => (
            <LeadSourceRow
              key={item.id}
              item={item}
              canWrite={canWrite}
              busy={rotate.isPending || setActive.isPending}
              onRotate={(graceMinutes, secret) =>
                rotate.mutate(
                  { webhookId: item.id, graceMinutes, appSecret: secret },
                  {
                    onSuccess: (result) =>
                      setIssued({
                        secret: result.secret,
                        header: result.secret_header,
                        path: null,
                        expiresAt: result.previous_secret_expires_at,
                      }),
                  },
                )
              }
              onToggle={() =>
                setActive.mutate(
                  { webhookId: item.id, active: !item.active },
                  {
                    onSuccess: () =>
                      toast({
                        tone: "success",
                        title: item.active ? "Lead source turned off" : "Lead source turned on",
                        description: item.active
                          ? "It will stop accepting deliveries."
                          : "It will accept deliveries again.",
                      }),
                  },
                )
              }
            />
          ))}
        </ul>
      ) : (
        <div className="mt-3">
          <EmptyState
            title="No lead sources yet"
            hint="Add one below and point your website form at the address we give you."
          />
        </div>
      )}

      <form
        className="mt-4 space-y-3 border-t border-line pt-4"
        noValidate
        onSubmit={valid.onSubmit(submit)}
      >
        <p className="text-sm font-medium text-ink">Add a lead source</p>
        {/* A `fieldset`, not `disabled` on each control, and this form is why the
            distinction matters. Every field here stayed fully typeable for an operator
            in a read-only view-as session while only the submit button was gated — so a
            person could fill the whole thing in and discover it was inert at the last
            click. `disabled` on a fieldset cascades to every control it contains,
            INCLUDING ones added later, which is exactly how this drifted from
            `integrations/page.tsx` (which gates each input by hand, and is correct, but
            is one forgotten attribute away from repeating this).

            `m-0 border-0 p-0`: every browser gives a fieldset a default border, padding
            and margin, and this one is a behaviour wrapper rather than a visual
            grouping. `space-y-3` reproduces the spacing the form already had. */}
        <fieldset disabled={!canWrite} className="m-0 space-y-3 border-0 p-0">
          <div className="flex flex-wrap gap-3">
            <label className="text-xs text-ink-muted">
              Where leads come from
              <select
                aria-label="Lead source kind"
                value={source}
                onChange={(e) => setSource(e.target.value)}
                className={`${FIELD} mt-1 block w-full sm:min-w-[16rem]`}
              >
                {CREATABLE_SOURCES.map((kind) => (
                  <option key={kind} value={kind}>
                    {sourceLabel(kind)}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-muted">
              Which agent answers them
              {/* §52. `agents.data ?? []` left this picker holding ONE option — "Not yet —
                  save leads, don't call" — whenever `/v1/agents` failed, and that option is
                  a legitimate choice, so nothing looked wrong. A client would pick the only
                  thing on offer and walk away having built a source that saves leads and
                  never rings anybody, believing they had no agents to point it at. An empty
                  picker over a failed read is a statement about their business made from a
                  request that never landed. */}
              {/* `!agents.isLoading && !agents.data` is the same sentence for the
                  non-answer that carries no error: a query TanStack has PAUSED because the
                  browser is offline reports `isLoading === false`, `error === null` and no
                  data, so the picker below rendered "Not yet — save leads, don't call" as
                  the only option and made exactly the claim this branch exists to prevent. */}
              {agents.error != null || (!agents.isLoading && !agents.data) ? (
                <span className="mt-1 block max-w-md rounded-md border border-line bg-surface px-3 py-2 text-ink-muted">
                  We could not read your agents just now, so this cannot be chosen yet —
                  saving without it would create a source that never rings anyone. Reload
                  the page to try again.
                </span>
              ) : (
                <select
                  aria-label="Agent to answer these leads"
                  value={agentId}
                  disabled={agents.isLoading}
                  onChange={(e) => setAgentId(e.target.value)}
                  className={`${FIELD} mt-1 block w-full sm:min-w-[16rem]`}
                >
                  {/* Honest, not blank: a source with no agent SAVES leads and never dials
                      them, which is a legitimate state and a surprising one. Say it. */}
                  <option value="">
                    {agents.isLoading
                      ? "Reading your agents…"
                      : "Not yet — save leads, don't call"}
                  </option>
                  {(agents.data ?? []).map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
              )}
            </label>
          </div>

          <fieldset className="flex flex-wrap gap-3">
            <legend className="text-xs text-ink-muted">
              What your form calls each field (leave blank to send ours)
            </legend>
            <input
              value={phoneField}
              onChange={(e) => setPhoneField(e.target.value)}
              aria-label="Your form's phone field name"
              placeholder="phone_number"
              className={`${FIELD} font-mono`}
            />
            <input
              value={nameField}
              onChange={(e) => setNameField(e.target.value)}
              aria-label="Your form's name field name"
              placeholder="full_name"
              className={`${FIELD} font-mono`}
            />
            <input
              value={consentField}
              onChange={(e) => setConsentField(e.target.value)}
              aria-label="Your form's consent field name"
              placeholder="consent_to_call (optional)"
              className={`${FIELD} font-mono`}
            />
          </fieldset>
          {/* Consent is not a formality on this path: a lead that does not affirm it is
              saved and never dialled (FLOWS §4). Say what naming the field does. */}
          <p className="text-xs text-ink-faint">
            If your form asks permission to call, name that field — a lead that does not
            confirm it is saved and never dialled.
          </p>

          {isMeta && (
            <div className="block text-xs text-ink-muted">
              {/* NO LONGER A WRAPPING <label>, because the field now carries a real
                  button: a button inside the label's click target is a control the label
                  competes with for the click. The accessible name is unchanged — it was
                  already `aria-label`, which overrode this text before and still does. */}
              <span className="block">Your Meta app&apos;s App Secret</span>
              {/* `track` rather than `field`: `PasswordInput` owns the id and this
                  control is named by its own `aria-label`, so only the watching and the
                  message are wired here. */}
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
                wrapperClassName="block w-full max-w-md"
                className={`${FIELD} font-mono`}
              />
              {valid.message("appSecret") ? (
                <FieldMessage id={appSecretErrorId}>{valid.message("appSecret")}</FieldMessage>
              ) : null}
              <span className="mt-1 block text-ink-faint">
                Meta signs every notification with this, so we cannot generate it. Find it
                under App settings → Basic in the Meta App Dashboard.
              </span>
            </div>
          )}

          {/* Blocked while the agent list is unreadable, because otherwise the sentence
              above it is not true: the form would still POST, with no agent, and produce
              exactly the silent never-dialling source that sentence promises to prevent. */}
          <button
            type="submit"
            /* The secret's emptiness is answered at the field now; an unreadable agent
               list still holds the button, because that is not an answer this person can
               correct on this form. */
            disabled={!canWrite || create.isPending || agents.error != null}
            className={PRIMARY_BUTTON_SM}
          >
            <Plus className="h-4 w-4" />
            {create.isPending ? "Adding…" : "Add lead source"}
          </button>
        </fieldset>
      </form>
    </Card>
  );
}
