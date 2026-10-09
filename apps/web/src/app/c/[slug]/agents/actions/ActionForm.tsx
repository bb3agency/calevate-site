"use client";

/**
 * ADDING OR EDITING ONE ACTION — the shared fields, the kind-specific block, and the wire
 * body it builds.
 *
 * One component rather than seven because the SHARED half (name, when the agent should use
 * it, the connected account, the values it collects, when it runs, the line it says while
 * it works) is most of it; each kind adds a short block (`KindFields.tsx`). Seven forms
 * would be seven places to fix the next shared field.
 */

import { useState } from "react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import {
  ACTION_KIND_LABELS,
  useCreateAction,
  useCredentials,
  useUpdateAction,
  type ActionTool,
  type ActionToolInput,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";

import { useFormValidation } from "@/components/formValidation";

import { KindFields, buildConfig, initialDraft, type KindDraft } from "./KindFields";
import { ParamEditor } from "./ParamEditor";
import { credentialKindFor, fromParam, toParam, type DraftParam, type Kind, type Provider } from "./params";

const DEFAULT_PROVIDER: Partial<Record<Kind, Provider>> = {
  whatsapp: "aisensy",
  calendar: "google",
  payment_link: "razorpay",
  crm: "zoho",
  caller_lookup: "zoho",
};

/** Which providers a kind offers, in the order shown. */
const PROVIDER_CHOICES: Partial<Record<Kind, { value: Provider; label: string }[]>> = {
  whatsapp: [
    { value: "aisensy", label: "AiSensy" },
    { value: "meta_cloud", label: "WhatsApp Cloud API" },
    { value: "interakt", label: "Interakt" },
  ],
  crm: [
    { value: "zoho", label: "Zoho CRM" },
    { value: "hubspot", label: "HubSpot" },
  ],
  caller_lookup: [
    { value: "zoho", label: "Zoho CRM" },
    { value: "hubspot", label: "HubSpot" },
    { value: "sheet", label: "A Google Sheet" },
    { value: "api", label: "Your own API" },
  ],
};

/** Kinds that only make sense while the caller is on the line. */
const DURING_CALL_ONLY: readonly Kind[] = ["caller_lookup", "payment_link"];

const NAME_PLACEHOLDER: Record<Kind, string> = {
  custom_api: "check_order_status",
  whatsapp: "send_price_list",
  calendar: "book_appointment",
  sheets: "save_answers",
  payment_link: "send_payment_link",
  crm: "save_to_crm",
  caller_lookup: "look_up_caller",
};

const DESCRIPTION_PLACEHOLDER: Record<Kind, string> = {
  custom_api: "Look up an order when the caller gives the order number.",
  whatsapp: "Send the price list once the caller asks for it on WhatsApp.",
  calendar: "Check free times, then book once the caller agrees to one.",
  sheets: "Save the caller's answers as soon as they give their name and need.",
  payment_link: "Send the payment link once the caller agrees to pay the booking fee.",
  crm: "Save the caller to the CRM once you know their name and what they want.",
  caller_lookup: "Call this first, before greeting, to find out who is calling.",
};

export function ActionForm({
  kind,
  agentId,
  session,
  onDone,
  existing,
}: {
  kind: Kind;
  agentId: string;
  session: Session;
  onDone: () => void;
  /** The stored action this form edits; absent, it creates a new one. */
  existing?: ActionTool;
}) {
  const create = useCreateAction(session, agentId);
  const update = useUpdateAction(session, agentId);
  const save = existing ? update : create;
  const creds = useCredentials(session);
  const valid = useFormValidation();
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [trigger, setTrigger] = useState<"during_call" | "after_call">(
    existing?.trigger === "after_call" ? "after_call" : "during_call",
  );
  const [preCall, setPreCall] = useState(existing?.pre_call_message ?? "");
  const [credentialId, setCredentialId] = useState(existing?.credential_id ?? "");
  const choices = PROVIDER_CHOICES[kind];
  const [provider, setProvider] = useState<Provider>(
    choices?.find((c) => c.value === existing?.provider)?.value ??
      DEFAULT_PROVIDER[kind] ??
      "custom",
  );
  const [params, setParams] = useState<DraftParam[]>(() =>
    (existing?.params ?? []).map(fromParam),
  );
  const [draft, setDraft] = useState<KindDraft>(() => initialDraft(kind, existing));

  function buildBody(): ActionToolInput {
    const needsProvider = kind !== "custom_api" && kind !== "sheets";
    return {
      kind,
      provider: needsProvider ? provider : null,
      name,
      description,
      trigger: DURING_CALL_ONLY.includes(kind) ? "during_call" : trigger,
      pre_call_message: preCall || null,
      credential_id: credentialId || null,
      params: params.map(toParam),
      config: buildConfig(kind, provider, draft, params),
    };
  }

  // Only from a read that actually ARRIVED — a paused (offline) query reports no error and
  // no data, so `creds.data` must be checked directly rather than defaulted to `[]` (§52).
  const credentialKind = credentialKindFor(kind, provider);
  const relevantCreds = creds.data
    ? creds.data.filter((c) => c.kind === credentialKind)
    : undefined;

  return (
    <form
      className="min-w-0 space-y-3 rounded-card border border-line bg-app p-4"
      noValidate
      onSubmit={valid.onSubmit(() => {
        const body = buildBody();
        if (existing) update.mutate({ toolId: existing.id, body }, { onSuccess: onDone });
        else create.mutate(body, { onSuccess: onDone });
      })}
    >
      <p className="text-sm font-semibold text-ink">
        {existing ? `Edit ${existing.name}` : `New action: ${ACTION_KIND_LABELS[kind]}`}
      </p>

      {choices ? (
        <label className="block">
          <span className={FIELD_LABEL}>
            {kind === "caller_lookup" ? "Look the caller up in" : "Using"}
          </span>
          <select
            className={FIELD}
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value as Provider);
              setCredentialId("");
            }}
          >
            {choices.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <div>
        <label className="block">
          <span className={FIELD_LABEL}>Name</span>
          <input
            {...valid.field("name", "Give this action a name.")}
            className={FIELD}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={NAME_PLACEHOLDER[kind]}
            pattern="[a-z][a-z0-9_]{2,39}"
            required
          />
        </label>
        {valid.error("name")}
        <span className={FIELD_HINT}>
          3 to 40 lowercase letters, numbers or underscores, starting with a letter.
        </span>
      </div>
      <div>
        <label className="block">
          <span className={FIELD_LABEL}>When should the agent use this?</span>
          <textarea
            {...valid.field("description", "Say when the agent should use this.")}
            className={FIELD}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={DESCRIPTION_PLACEHOLDER[kind]}
            rows={2}
            minLength={10}
            required
          />
        </label>
        {valid.error("description")}
        <span className={FIELD_HINT}>
          The agent decides from this alone, so say when to use it and when not to.
        </span>
      </div>

      <KindFields
        kind={kind}
        provider={provider}
        draft={draft}
        onChange={setDraft}
        session={session}
        valid={valid}
      />

      {credentialKind ? (
        relevantCreds === undefined ? (
          <ProblemNotice
            error={creds.error ?? new Error("Your connected accounts could not be loaded.")}
          />
        ) : (
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>Connected account</span>
              <select
                className={FIELD}
                value={credentialId}
                onChange={(e) => setCredentialId(e.target.value)}
              >
                <option value="">
                  {kind === "custom_api" || provider === "api" ? "— no key needed —" : "— choose —"}
                </option>
                {relevantCreds.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label} (····{c.last_four})
                  </option>
                ))}
              </select>
            </label>
            {relevantCreds.length === 0 ? (
              <span className={FIELD_HINT}>
                Nothing connected for this yet. Connect it on the Integrations page, then come
                back.
              </span>
            ) : null}
          </div>
        )
      ) : null}

      {kind !== "caller_lookup" ? <ParamEditor params={params} onChange={setParams} /> : null}

      <div className="flex flex-wrap gap-2">
        {DURING_CALL_ONLY.includes(kind) ? null : (
          <div className="flex-1 sm:min-w-[12rem]">
            <label className="block">
              <span className={FIELD_LABEL}>When to run</span>
              <select
                className={FIELD}
                value={trigger}
                onChange={(e) => setTrigger(e.target.value as "during_call" | "after_call")}
              >
                <option value="during_call">During the call — the agent decides</option>
                <option value="after_call">After the call ends — automatic</option>
              </select>
            </label>
          </div>
        )}
        <div className="flex-1 sm:min-w-[12rem]">
          <label className="block">
            <span className={FIELD_LABEL}>What the agent says while it works</span>
            <input
              className={FIELD}
              value={preCall}
              maxLength={200}
              onChange={(e) => setPreCall(e.target.value)}
              placeholder="One moment, let me check."
            />
          </label>
        </div>
      </div>

      {save.isError ? <ProblemNotice error={save.error} /> : null}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={PRIMARY_BUTTON} disabled={save.isPending}>
          {save.isPending ? "Saving…" : existing ? "Save changes" : "Save action"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
