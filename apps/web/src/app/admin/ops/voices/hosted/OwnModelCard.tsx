"use client";

import Link from "next/link";
import { useId, useState } from "react";

import { StatusPill } from "@/components/admin/kit";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { InfoTip } from "@/components/console/infoTip";
import { TEXT_ACTION } from "@/components/console/section";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
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

const UUID_SHAPE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KEYS_HREF = "/admin/ops/config?section=credentials";
const CONFIG_HREF = "/admin/ops/config";
const DEVELOPER_STEP = "developer";

/** A step with `href: null` is done on this card (the developer workspace set-up). */
type Step = { id: string; label: string; done: boolean; detail: string; href: string | null; go: string };

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
      label: `Price ${data.default_model}`,
      done: data.default_offerable,
      detail: data.default_reason ?? "Attest the model's price from the Google invoice.",
      href: CONFIG_HREF,
      go: "Open prices",
    },
    {
      id: "data-use",
      label: "Attest how Google uses call data",
      done: data.data_use_attested,
      detail: "Paid tier, log sharing off: caller speech goes through this key on every turn.",
      href: CONFIG_HREF,
      go: "Open models",
    },
    {
      id: "minute",
      label: "Attest the Studio minute on our model",
      done: data.llm_voice_minute_attested,
      detail: "The own-voice-and-model (byok_llm_voice) per-minute rate.",
      href: CONFIG_HREF,
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
  const [confirmingDeveloper, setConfirmingDeveloper] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [tenantId, setTenantId] = useState("");
  const tenantField = useId();
  const tenantValid = UUID_SHAPE.test(tenantId.trim());

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
          <Link href={CONFIG_HREF} className={TEXT_ACTION}>
            Switch it on in the settings
          </Link>
        )}
      </p>

      <p className="text-meta text-ink-muted">
        {data.floor_model_inr_per_min == null
          ? `Cost floor: ${data.default_model} has no reference price to add at `
          : `Cost floor: ${data.default_model} adds ${formatRupeeRate(data.floor_model_inr_per_min)}/min at `}
        {data.floor_prompt_basis}.
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

      <button
        type="button"
        className={TEXT_ACTION}
        onClick={() => {
          enable.reset();
          setConfirming(true);
        }}
      >
        Install our key for a client now
      </button>

      {confirmingDeveloper && (
        <ConfirmDialog
          title="Set up our developer workspace?"
          confirmLabel="Set up"
          pendingLabel="Working…"
          pending={developer.isPending}
          error={developer.error}
          onCancel={() => setConfirmingDeveloper(false)}
          onConfirm={() => developer.mutate(undefined, { onSuccess: () => setConfirmingDeveloper(false) })}
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
          confirmLabel="Install"
          pendingLabel="Working…"
          pending={enable.isPending}
          error={enable.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            if (!tenantValid) return;
            enable.mutate({ tenant_id: tenantId.trim() }, { onSuccess: () => setConfirming(false) });
          }}
        >
          <p>
            Optional: publishing does this automatically. A paying client&rsquo;s first publish on our
            model installs our Google key in its own workspace. This pre-installs it for one paying
            client now, switching that workspace&rsquo;s own keys on if they are off, agents that would
            follow them kept off first. You may be asked to confirm it is still you.
          </p>
          <label htmlFor={tenantField} className={`mt-3 ${FIELD_LABEL}`}>
            Paying client, account id
          </label>
          <input
            id={tenantField}
            className={`mt-1 ${FIELD}`}
            value={tenantId}
            onChange={(event) => setTenantId(event.target.value)}
            aria-invalid={tenantId.trim() !== "" && !tenantValid}
          />
          <p className={FIELD_HINT}>The id is on the client&rsquo;s admin page.</p>
          {tenantId.trim() !== "" && !tenantValid && (
            <p className="mt-1 text-meta text-warn">That is not an account id.</p>
          )}
        </ConfirmDialog>
      )}
    </section>
  );
}
