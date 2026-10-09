"use client";

/**
 * SETTING UP OR CHANGING ONE ACTION — the guided form for every job except booking.
 *
 * What a client needs is up front: which service (when a job offers more than one), the
 * job's own settings (`KindFields.tsx`) and the account it uses. The machine half — the
 * action's `name`, what the agent is told, the values it collects, when it runs and what
 * it says while it works — is derived (`jobs.ts`) and sits under Advanced, closed, with
 * the fact in its subtitle. A custom API opens Advanced, because there the values ARE the
 * job (REDESIGN-2). The wire body is unchanged.
 */

import { useCallback, useState } from "react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRows } from "@/components/console/settingRow";
import { useFormValidation } from "@/components/formValidation";
import { Disclosure, FIELD, FIELD_HINT, FIELD_LABEL, PRIMARY_BUTTON, ProblemNotice } from "@/components/ui";
import {
  useCreateAction,
  useUpdateAction,
  type ActionTool,
  type ActionToolInput,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";

import { AccountRow } from "./AccountRow";
import { DEFAULT_INSTRUCTIONS, NAME_BASE, defaultParams, humanName, jobFor, uniqueName } from "./jobs";
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

const NAME_PATTERN = "[a-zA-Z][a-zA-Z0-9_]{2,39}";

export function ActionForm({
  kind,
  agentId,
  session,
  onDone,
  onSaved,
  existing,
  takenNames = [],
}: {
  kind: Kind;
  agentId: string;
  session: Session;
  onDone: () => void;
  /** After a successful save, before `onDone` (the orchestrator switches actions on). */
  onSaved?: () => void;
  /** The stored action this form edits; absent, it creates a new one. */
  existing?: ActionTool;
  /** Names other actions on this agent already use, so a derived name never collides. */
  takenNames?: readonly string[];
}) {
  const create = useCreateAction(session, agentId);
  const update = useUpdateAction(session, agentId);
  const save = existing ? update : create;
  const valid = useFormValidation();
  const job = jobFor(kind);
  const choices = PROVIDER_CHOICES[kind];
  const [provider, setProvider] = useState<Provider>(
    choices?.find((c) => c.value === existing?.provider)?.value ?? DEFAULT_PROVIDER[kind] ?? "custom",
  );
  const base = kind === "calendar" ? "calendar_step" : NAME_BASE[kind];
  const [name, setName] = useState(existing?.name ?? uniqueName(base, takenNames));
  const [description, setDescription] = useState(
    existing?.description ?? (kind === "calendar" ? "" : DEFAULT_INSTRUCTIONS[kind]),
  );
  const [trigger, setTrigger] = useState<"during_call" | "after_call">(
    existing?.trigger === "after_call" ? "after_call" : "during_call",
  );
  const [preCall, setPreCall] = useState(existing?.pre_call_message ?? "");
  const [credentialId, setCredentialId] = useState(existing?.credential_id ?? "");
  const [params, setParams] = useState<DraftParam[]>(() =>
    existing ? existing.params.map(fromParam) : defaultParams(kind, provider),
  );
  const [draft, setDraft] = useState<KindDraft>(() => initialDraft(kind, existing));
  const pickCredential = useCallback((id: string) => setCredentialId(id), []);

  const credentialKind = credentialKindFor(kind, provider);
  const fills = params.map((p) => p.name).filter(Boolean);
  const advancedFact = [
    `Named ${name || "—"}`,
    fills.length ? `fills ${fills.join(", ")}` : null,
    trigger === "after_call" ? "runs after the call" : "runs during the call",
  ]
    .filter(Boolean)
    .join(" · ");

  function buildBody(): ActionToolInput {
    const needsProvider = kind !== "custom_api" && kind !== "sheets";
    return {
      kind,
      provider: needsProvider ? provider : null,
      name,
      description,
      trigger: DURING_CALL_ONLY.includes(kind) ? "during_call" : trigger,
      pre_call_message: preCall || null,
      // A sheet's Google account is chosen with the spreadsheet itself.
      credential_id: (credentialKind === "google_sheets" ? draft.sheet_credential : credentialId) || null,
      params: params.map(toParam),
      config: buildConfig(kind, provider, draft, params),
    };
  }

  return (
    <form
      className="min-w-0"
      noValidate
      onSubmit={valid.onSubmit(() => {
        const body = buildBody();
        const done = () => {
          onSaved?.();
          onDone();
        };
        if (existing) update.mutate({ toolId: existing.id, body }, { onSuccess: done });
        else create.mutate(body, { onSuccess: done });
      })}
    >
      <Section
        headingLevel={3}
        title={existing ? `Change “${humanName(existing.name)}”` : (job?.title ?? "New action")}
        description={existing ? undefined : job?.line}
      >
        <div className="space-y-4">
          {choices ? (
            <label className="block max-w-sm">
              <span className={FIELD_LABEL}>{kind === "caller_lookup" ? "Look the caller up in" : "Using"}</span>
              <select
                className={FIELD}
                value={provider}
                onChange={(e) => {
                  const next = e.target.value as Provider;
                  // Values still at the old service's defaults follow the new service.
                  if (!existing && JSON.stringify(params) === JSON.stringify(defaultParams(kind, provider))) {
                    setParams(defaultParams(kind, next));
                  }
                  setProvider(next);
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

          <KindFields kind={kind} provider={provider} draft={draft} onChange={setDraft} session={session} valid={valid} />

          {credentialKind && credentialKind !== "google_sheets" ? (
            <SettingRows className="border-y border-line">
              <AccountRow
                label="Account"
                kind={credentialKind}
                value={credentialId}
                onChange={pickCredential}
                session={session}
                optional={kind === "custom_api" || provider === "api"}
              />
            </SettingRows>
          ) : null}
        </div>

        <Disclosure
          variant="inline"
          headingLevel={4}
          title="Advanced"
          defaultOpen={kind === "custom_api" && !existing}
          className="mt-3"
        >
          <p className="mb-3 text-meta text-ink-muted">{advancedFact}</p>
          <div className="space-y-3">
            <div>
              <label className="block">
                <span className={FIELD_LABEL}>What your agent is told</span>
                <textarea
                  {...valid.field("description", "Say when your agent should do this.")}
                  className={FIELD}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  minLength={10}
                  required
                />
              </label>
              {valid.error("description")}
              <span className={FIELD_HINT}>Your agent decides when to do this from these words alone.</span>
            </div>
            {kind !== "caller_lookup" ? <ParamEditor params={params} onChange={setParams} /> : null}
            <div className="flex flex-wrap gap-3">
              {DURING_CALL_ONLY.includes(kind) ? null : (
                <label className="block flex-1 sm:min-w-[12rem]">
                  <span className={FIELD_LABEL}>When it runs</span>
                  <select
                    className={FIELD}
                    value={trigger}
                    onChange={(e) => setTrigger(e.target.value as "during_call" | "after_call")}
                  >
                    <option value="during_call">During the call, when your agent decides</option>
                    <option value="after_call">After the call ends, every time</option>
                  </select>
                </label>
              )}
              <label className="block flex-1 sm:min-w-[12rem]">
                <span className={FIELD_LABEL}>What your agent says while it works</span>
                <input
                  className={FIELD}
                  value={preCall}
                  maxLength={200}
                  onChange={(e) => setPreCall(e.target.value)}
                  placeholder="One moment, let me check."
                />
              </label>
            </div>
            <div>
              <label className="block max-w-sm">
                <span className={FIELD_LABEL}>Name (for your developer)</span>
                <input
                  {...valid.field("name", "Give this action a name.")}
                  className={FIELD}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  pattern={NAME_PATTERN}
                  required
                />
              </label>
              {valid.error("name")}
            </div>
          </div>
        </Disclosure>

        {save.isError ? (
          <div className="mt-4">
            <ProblemNotice error={save.error} />
          </div>
        ) : null}
        <div className="mt-6 flex flex-wrap items-center justify-end gap-x-5 gap-y-3">
          <button type="button" className={TEXT_ACTION} onClick={onDone}>
            Cancel
          </button>
          <button type="submit" className={PRIMARY_BUTTON} disabled={save.isPending}>
            {save.isPending ? "Saving…" : existing ? "Save changes" : "Turn it on"}
          </button>
        </div>
      </Section>
    </form>
  );
}
