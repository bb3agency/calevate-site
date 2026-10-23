"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { StatusPill } from "@/components/admin/kit";
import { useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { InfoTip } from "@/components/console/infoTip";
import { TEXT_ACTION } from "@/components/console/section";
import { configHref } from "@/app/admin/ops/config/configSections";
import { ClientPicker } from "./ClientPicker";
import {
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  Skeleton,
  formatCount,
} from "@/components/ui";
import {
  useEnableStudioVoices,
  useStudioVoices,
  type StudioVoices,
} from "@/lib/api/opsHostedVoices";

// Each step lands on the panel or key it names (`configHref`).
const KEYS_HREF = configHref("credentials", { credential: "cartesia_api_key" });
const MINUTE_HREF = configHref("voice-engine", { panel: "engine_minute_price" });
const VOICE_PRICE_HREF = configHref("language-models", { panel: "model_pricing" });

type Step = {
  id: string;
  label: string;
  done: boolean;
  detail: string;
  /** A page to go to, or the Studio ready dialog (with or without a first client). */
  go: { href: string; label: string } | { dialog: "key" | "client"; label: string };
};

/**
 * The five steps before Studio can be sold, in the order an operator does them, from the
 * server's booleans (`StudioVoicesOut`). Runbook: runbooks/thinnest-studio-voices.md §1-2.
 */
export function studioSteps(data: StudioVoices): Step[] {
  return [
    {
      id: "key",
      label: "Save our Cartesia key",
      done: data.cartesia_key_configured,
      detail: "In the platform keys, then test it there.",
      go: { href: KEYS_HREF, label: "Open keys" },
    },
    {
      id: "held",
      label: "Switch the key on in our developer workspace",
      done: data.developer_holds_key && data.developer_switch_on,
      detail: "Free-trial agents speak Studio there. Agents not on Studio are kept off it first.",
      go: { dialog: "key", label: "Studio ready" },
    },
    {
      id: "minute",
      label: "Attest the Studio minute rate",
      done: data.minute_attested,
      detail: "The voice-only own-key (byok_voice) per-minute rate.",
      go: { href: MINUTE_HREF, label: "Open prices" },
    },
    {
      id: "voice-price",
      label: "Attest the Cartesia voice price",
      done: data.synthesis_priced,
      detail: "A Studio minute carries Cartesia's charge as a second cost.",
      go: { href: VOICE_PRICE_HREF, label: "Open prices" },
    },
    {
      id: "listed",
      label: "List the Studio voices",
      done: data.voices_listed,
      detail: "Studio ready lists them once our key is on; refresh the voices if they are missing.",
      go: { dialog: "key", label: "List the voices" },
    },
  ];
}

/**
 * Studio: our Cartesia key, switched on in our developer workspace where free-trial agents live
 * (D-727) and in the workspace of each paying client that publishes a Studio agent (D-717). A
 * checklist with the one next step as the primary button, and two small stats.
 */
export function StudioVoicesCard() {
  const studio = useStudioVoices(true);
  const enable = useEnableStudioVoices();
  // The dialog prints a refusal; a success closes it and the server's note is printed below.
  const enableFeedback = useActionFeedback(enable, { errorDisplay: "inline" });
  const [confirming, setConfirming] = useState<"enable" | null>(null);
  const [askClient, setAskClient] = useState(false);
  const [tenantId, setTenantId] = useState("");
  const last = enable.data;
  useEffect(() => {
    if (enableFeedback.status === "success") setConfirming(null);
  }, [enableFeedback.status]);

  const openEnable = (withClient: boolean, client = "") => {
    enable.reset();
    setAskClient(withClient);
    setTenantId(client);
    setConfirming("enable");
  };

  if (studio.error != null) {
    return (
      <section aria-labelledby="studio-setup" className="space-y-3">
        <h2 id="studio-setup" className="text-heading text-ink">
          Studio voices
        </h2>
        <ProblemNotice error={studio.error} onRetry={() => void studio.refetch()} />
      </section>
    );
  }
  if (!studio.data) return <Skeleton rows={2} label="Reading whether Studio voices are ready" />;

  const data = studio.data;
  const steps = studioSteps(data);
  const next = steps.find((step) => !step.done);
  const failing = data.workspaces.filter((ws) => ws.error_code);
  const onStudio = new Set(data.workspaces.map((ws) => ws.tenant_id));
  const items: ChecklistItem[] = steps.map((step) => ({
    id: step.id,
    label: step.label,
    state: step.done ? "done" : "todo",
    detail: step.done ? undefined : step.detail,
    action: step.done ? undefined : (
      <StepAction step={step} primary={step === next} onDialog={(kind) => openEnable(kind === "client")} />
    ),
  }));

  return (
    <section aria-labelledby="studio-setup" className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 id="studio-setup" className="text-heading text-ink">
          Studio voices
        </h2>
        <StatusPill tone={data.ready ? "ok" : "warn"}>{data.ready ? "Ready" : "Not ready"}</StatusPill>
        <InfoTip label="Studio voices">{data.explanation}</InfoTip>
        <p className="w-full text-meta tabular-nums text-ink-muted sm:ml-auto sm:w-auto">
          {formatCount(data.workspaces.length)} client{" "}
          {data.workspaces.length === 1 ? "workspace" : "workspaces"} on Studio
          {" · "}
          {formatCount(data.live_studio_agents)} live Studio{" "}
          {data.live_studio_agents === 1 ? "agent" : "agents"}
        </p>
      </div>

      <Checklist
        label="Before clients can choose Studio voices"
        items={items}
        collapsible
        defaultOpen={!data.ready}
      />

      {data.workspaces.length > 0 && (
        <p className="text-meta text-ink-muted">
          On Studio:{" "}
          {data.workspaces.map((ws, i) => (
            <span key={ws.tenant_id}>
              {i > 0 && ", "}
              <Link href={`/admin/tenants/${ws.tenant_id}`} className={TEXT_ACTION}>
                {ws.tenant_name ?? "Unnamed client"}
              </Link>
              {ws.error_code && <span className="text-warn">{` (last error ${ws.error_code})`}</span>}
            </span>
          ))}
          {failing.length > 0 && "."}{" "}
          <button
            type="button"
            className={TEXT_ACTION}
            onClick={() => openEnable(true, failing.length === 1 ? (failing[0]?.tenant_id ?? "") : "")}
          >
            {failing.length > 0 ? "Retry for a client" : "Switch Studio on for a client"}
          </button>
        </p>
      )}

      {confirming === null && last && (
        <p role="status" className="text-body text-ink-muted">
          {last.note}
        </p>
      )}

      {confirming === "enable" && (
        <ConfirmDialog
          title="Make Studio ready?"
          confirmLabel="Studio ready"
          pendingLabel="Working…"
          status={enableFeedback.status}
          error={enable.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => enableFeedback.run(tenantId ? { tenant_id: tenantId } : {})}
        >
          <p>
            This switches our Cartesia key on, for the voice only, in our developer workspace, where
            free-trial agents speak Studio. Every agent not on a Studio voice is kept off it first. It
            installs a credential, so you may be asked to confirm it is still you.
          </p>
          <ClientPicker
            label={`Paying client to switch on now${askClient ? "" : " (optional)"}`}
            clients={data.clients}
            value={tenantId}
            onChange={setTenantId}
            emptyLabel="None now: a client is switched on at its first Studio publish"
            hint="Studio is switched on in this client's own workspace, its Clear agents kept off first."
            note={(id) => (onStudio.has(id) ? "on Studio" : undefined)}
          />
        </ConfirmDialog>
      )}
    </section>
  );
}

function StepAction({
  step,
  primary,
  onDialog,
}: {
  step: Step;
  primary: boolean;
  onDialog: (kind: "key" | "client") => void;
}) {
  const className = primary ? PRIMARY_BUTTON_SM : TEXT_ACTION;
  if ("href" in step.go) {
    return (
      <Link href={step.go.href} className={className}>
        {step.go.label}
      </Link>
    );
  }
  const kind = step.go.dialog;
  return (
    <button type="button" className={className} onClick={() => onDialog(kind)}>
      {step.go.label}
    </button>
  );
}
