"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { configHref } from "@/app/admin/ops/config/configSections";
import { StatusPill } from "@/components/admin/kit";
import { useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { InfoTip } from "@/components/console/infoTip";
import { TEXT_ACTION } from "@/components/console/section";
import {
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  Skeleton,
  formatCount,
  formatRupeeRate,
} from "@/components/ui";
import {
  useEnableOwnModelDeveloper,
  useEnableOwnModelWorkspace,
  useOwnModel,
  type OwnModel,
} from "@/lib/api/opsHostedVoices";

import { ClientPicker } from "./ClientPicker";
import { formatCacheShare } from "./cacheShare";

// Each step lands on the panel, key or setting it names (`configHref`).
const KEYS_HREF = configHref("credentials", { credential: "gemini_api_key" });
const PRICES_HREF = configHref("language-models", { panel: "model_pricing" });
const MODELS_HREF = configHref("language-models");
const DATA_USE_HREF = configHref("language-models", { panel: "in_call_data_use" });
const MINUTE_HREF = configHref("voice-engine", { panel: "engine_minute_price" });
const DEFAULT_MODEL_HREF = configHref("voice-engine", { setting: "thinnest_own_model_default" });
const SWITCH_HREF = configHref("voice-engine", { setting: "thinnest_own_model" });
const DEVELOPER_STEP = "developer";

/** A step with `href: null` is done on this card (the developer workspace set-up). */
type Step = { id: string; label: string; done: boolean; detail: string; href: string | null; go: string };

/**
 * The default-model step, by where the server says it is fixed (`default_fix`): only a
 * missing price is fixed in the prices; a model Google limits, or one the platform does not
 * run, is fixed by choosing another default.
 */
function defaultModelStep(data: OwnModel): Pick<Step, "label" | "href" | "go"> {
  switch (data.default_fix) {
    case "key":
      return { label: `Make ${data.default_model} usable`, href: KEYS_HREF, go: "Open keys" };
    case "deployment":
      return { label: `Make ${data.default_model} usable`, href: MODELS_HREF, go: "Open models" };
    case "default":
      return { label: "Choose a model our key can run", href: DEFAULT_MODEL_HREF, go: "Choose the model" };
    default:
      return { label: `Price ${data.default_model}`, href: PRICES_HREF, go: "Open prices" };
  }
}

/**
 * The five steps before our own model may be switched on, in the order an operator does them,
 * from the server's booleans (`OwnModelOut`). Runbook: runbooks/thinnest-own-model.md §1.
 */
export function ownModelSteps(data: OwnModel): Step[] {
  return [
    {
      id: "key",
      label: "Save our Google key",
      done: data.google_key_configured,
      detail: "The Gemini API key, in the platform keys; test it there.",
      href: KEYS_HREF,
      go: "Open keys",
    },
    {
      id: "model",
      done: data.default_offerable,
      detail: data.default_reason ?? "Attest the model's price from the Google invoice.",
      ...defaultModelStep(data),
    },
    {
      id: "data-use",
      label: "Attest how Google uses callers' speech",
      done: data.data_use_attested,
      detail:
        "In-call data use: paid tier, log sharing off. Caller speech goes through this key on every turn; the dashboard assistant's attestation does not count.",
      href: DATA_USE_HREF,
      go: "Open attestation",
    },
    {
      id: "minute",
      label: "Attest the Studio minute on our model",
      done: data.llm_voice_minute_attested,
      detail: "The own-voice-and-model (byok_llm_voice) per-minute rate.",
      href: MINUTE_HREF,
      go: "Open prices",
    },
    {
      id: DEVELOPER_STEP,
      label: "Set up our developer workspace",
      done: data.developer_ready,
      detail: data.developer_error_code
        ? `Free-trial agents answer there. Last error: ${data.developer_error_code}.`
        : "Free-trial agents answer there: our Google key installed and read back.",
      href: null,
      go: "Set up developer workspace",
    },
  ];
}

/**
 * Our own model (D-764, D-834): every agent, free-trial ones included, answers on Gemini through
 * our Google key. The switch itself is the ops setting `thinnest_own_model`; this card says what
 * it still needs, sets up our developer workspace (where free-trial agents live), says which
 * clients are on our key, and can install the key for one paying client ahead of its publish.
 */
export function OwnModelCard() {
  const own = useOwnModel(true);
  const enable = useEnableOwnModelWorkspace();
  const developer = useEnableOwnModelDeveloper();
  // Each dialog prints its own refusal; a success closes it, so the toast says what happened.
  const enableFeedback = useActionFeedback(enable, {
    errorDisplay: "inline",
    successToast: "Our Google key is installed for that client",
  });
  const developerFeedback = useActionFeedback(developer, {
    errorDisplay: "inline",
    successToast: "Our developer workspace is set up",
  });
  const [confirmingDeveloper, setConfirmingDeveloper] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [tenantId, setTenantId] = useState("");
  useEffect(() => {
    if (developerFeedback.status === "success") setConfirmingDeveloper(false);
  }, [developerFeedback.status]);
  useEffect(() => {
    if (enableFeedback.status === "success") setConfirming(false);
  }, [enableFeedback.status]);
  const openInstall = (client = "") => {
    enable.reset();
    setTenantId(client);
    setConfirming(true);
  };

  if (own.error != null) {
    return (
      <section aria-labelledby="own-model-setup" className="space-y-3">
        <h2 id="own-model-setup" className="text-heading text-ink">
          Our own model
        </h2>
        <ProblemNotice error={own.error} onRetry={() => void own.refetch()} />
      </section>
    );
  }
  if (!own.data) return <Skeleton rows={2} label="Reading whether our own model is ready" />;

  const data = own.data;
  const steps = ownModelSteps(data);
  const next = steps.find((step) => !step.done);
  const items: ChecklistItem[] = steps.map((step) => ({
    id: step.id,
    label: step.label,
    state: step.done ? "done" : "todo",
    detail: step.done ? undefined : step.detail,
    action: step.done ? undefined : step.href == null ? (
      <button
        type="button"
        className={step === next ? PRIMARY_BUTTON_SM : TEXT_ACTION}
        onClick={() => {
          developer.reset();
          setConfirmingDeveloper(true);
        }}
      >
        {step.go}
      </button>
    ) : (
      <Link href={step.href} className={step === next ? PRIMARY_BUTTON_SM : TEXT_ACTION}>
        {step.go}
      </Link>
    ),
  }));
  const status = data.switched_on ? "On" : data.ready ? "Ready, off" : "Not ready";
  const onKey = new Set(data.workspaces.map((ws) => ws.tenant_id));
  const pendingCode = new Map(data.pending_workspaces.map((ws) => [ws.tenant_id, ws.error_code]));

  return (
    <section aria-labelledby="own-model-setup" className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 id="own-model-setup" className="text-heading text-ink">
          Our own model
        </h2>
        <StatusPill tone={data.switched_on || data.ready ? "ok" : "warn"}>{status}</StatusPill>
        <InfoTip label="Our own model">{data.explanation}</InfoTip>
        <p className="w-full text-meta tabular-nums text-ink-muted sm:ml-auto sm:w-auto">
          {formatCount(data.workspaces.length)} client{" "}
          {data.workspaces.length === 1 ? "workspace" : "workspaces"} on our key · developer workspace{" "}
          {data.developer_ready ? "on our key" : "not set up"}
        </p>
      </div>

      <Checklist
        label="Before agents can answer on our own model"
        items={items}
        collapsible
        defaultOpen={!data.ready}
      />

      <p className="text-meta text-ink-muted">
        {data.note}{" "}
        {data.ready && !data.switched_on && (
          <Link href={SWITCH_HREF} className={TEXT_ACTION}>
            Switch it on in the settings
          </Link>
        )}
      </p>

      <p className="text-meta text-ink-muted">
        {data.floor_model_inr_per_min == null
          ? `Cost floor: ${data.default_model} has no reference price to add at `
          : `Cost floor: ${data.default_model} adds ${formatRupeeRate(data.floor_model_inr_per_min)}/min at `}
        {data.floor_prompt_basis}.{" "}
        {data.fleet_cache_share == null
          ? "Cache share: not measured yet."
          : `Cache share: ${formatCacheShare(data.fleet_cache_share)} of input over ${formatCount(data.fleet_cache_calls)} ${
              data.fleet_cache_calls === 1 ? "call" : "calls"
            } in 30 days; the floor assumes none.`}
      </p>

      {data.workspaces.length > 0 && (
        <p className="text-meta text-ink-muted">
          On our key:{" "}
          {data.workspaces.map((ws, i) => (
            <span key={ws.tenant_id}>
              {i > 0 && ", "}
              <Link href={`/admin/tenants/${ws.tenant_id}`} className={TEXT_ACTION}>
                {ws.tenant_name ?? "Unnamed client"}
              </Link>
              {ws.error_code && <span className="text-warn">{` (last error ${ws.error_code})`}</span>}
            </span>
          ))}
        </p>
      )}

      {data.pending_workspaces.length > 0 && (
        <p className="text-meta text-ink-muted">
          Not on our key yet:{" "}
          {data.pending_workspaces.map((ws, i) => (
            <span key={ws.tenant_id}>
              {i > 0 && ", "}
              <Link href={`/admin/tenants/${ws.tenant_id}`} className={TEXT_ACTION}>
                {ws.tenant_name ?? "Unnamed client"}
              </Link>
              <span className="text-warn">{` (last error ${ws.error_code})`}</span>{" "}
              <button type="button" className={TEXT_ACTION} onClick={() => openInstall(ws.tenant_id)}>
                Retry
              </button>
            </span>
          ))}
        </p>
      )}

      <button type="button" className={TEXT_ACTION} onClick={() => openInstall()}>
        Install our key for a client now
      </button>

      {confirmingDeveloper && (
        <ConfirmDialog
          title="Set up our developer workspace?"
          confirmLabel="Set up"
          pendingLabel="Working…"
          status={developerFeedback.status}
          error={developer.error}
          onCancel={() => setConfirmingDeveloper(false)}
          onConfirm={() => developerFeedback.run(undefined)}
        >
          <p>
            This installs our Google key in our ThinnestAI developer workspace, where free-trial agents
            live, and reads it back. If that workspace&rsquo;s own keys are off, every agent that would
            follow them is kept off first. Its default key scope is left as it is. You may be asked to
            confirm it is still you.
          </p>
        </ConfirmDialog>
      )}

      {confirming && (
        <ConfirmDialog
          title="Install our Google key for a client?"
          confirmDisabled={!tenantId}
          confirmLabel="Install"
          pendingLabel="Working…"
          status={enableFeedback.status}
          error={enable.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            if (!tenantId) return;
            enableFeedback.run({ tenant_id: tenantId });
          }}
        >
          <p>
            Optional: publishing does this automatically. A paying client&rsquo;s first publish on our
            model installs our Google key in its own workspace. This pre-installs it for one paying
            client now, switching that workspace&rsquo;s own keys on if they are off, agents that would
            follow them kept off first. You may be asked to confirm it is still you.
          </p>
          <ClientPicker
            label="Paying client"
            clients={data.clients}
            value={tenantId}
            onChange={setTenantId}
            emptyLabel="Choose a client"
            hint="Clients with a voice workspace of their own."
            note={(id) => (onKey.has(id) ? "on our key" : pendingCode.get(id) ? "not on our key yet" : undefined)}
          />
        </ConfirmDialog>
      )}
    </section>
  );
}
