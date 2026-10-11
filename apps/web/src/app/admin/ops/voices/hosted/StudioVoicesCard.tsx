"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { PowerOff } from "lucide-react";

import { StatusPill } from "@/components/admin/kit";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { InfoTip } from "@/components/console/infoTip";
import { TEXT_ACTION } from "@/components/console/section";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NOTICE_TONES,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
} from "@/components/ui";
import {
  useDisableStudioVoices,
  useEnableStudioVoices,
  useStudioVoices,
  type StudioVoices,
} from "@/lib/api/opsHostedVoices";

const UUID_SHAPE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KEYS_HREF = "/admin/ops/config?section=credentials";
const PRICES_HREF = "/admin/ops/config";

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
      label: "Hold the key in our developer workspace",
      done: data.developer_holds_key,
      detail: "Its own-keys switch stays off, so no client inherits it.",
      go: { dialog: "key", label: "Studio ready" },
    },
    {
      id: "minute",
      label: "Attest the Studio minute rate",
      done: data.minute_attested,
      detail: "The voice-only own-key (byok_voice) per-minute rate.",
      go: { href: PRICES_HREF, label: "Open prices" },
    },
    {
      id: "voice-price",
      label: "Attest the Cartesia voice price",
      done: data.synthesis_priced,
      detail: "A Studio minute carries Cartesia's charge as a second cost.",
      go: { href: PRICES_HREF, label: "Open prices" },
    },
    {
      id: "listed",
      label: "List the Studio voices",
      done: data.voices_listed,
      detail: "Switch Studio on for the first Studio client, then refresh.",
      go: { dialog: "client", label: "Name the first client" },
    },
  ];
}

/**
 * Studio (D-717): our Cartesia key, switched on only in the workspace of each client that
 * publishes a Studio agent. A checklist with the one next step as the primary button, two
 * small stats, and — only when it applies — the one-line warning about our developer
 * workspace's own keys being on.
 */
export function StudioVoicesCard() {
  const studio = useStudioVoices(true);
  const enable = useEnableStudioVoices();
  const disable = useDisableStudioVoices();
  const [confirming, setConfirming] = useState<"enable" | "disable" | null>(null);
  const [askClient, setAskClient] = useState(false);
  const [tenantId, setTenantId] = useState("");
  const tenantField = useId();
  const last = enable.data ?? disable.data;
  const tenantValid = tenantId.trim() === "" || UUID_SHAPE.test(tenantId.trim());

  const openEnable = (withClient: boolean) => {
    enable.reset();
    setAskClient(withClient);
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

      {data.developer_switch_on && (
        <div
          className={`flex flex-wrap items-center justify-between gap-3 rounded-md border px-4 py-2.5 text-body ${NOTICE_TONES.warn}`}
        >
          <p className="min-w-0 grow basis-60">
            Our developer workspace&rsquo;s own keys are on, so clients inherit our key. Switch it off.
          </p>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => {
              disable.reset();
              setConfirming("disable");
            }}
          >
            <PowerOff aria-hidden className="h-4 w-4" />
            Switch developer workspace off
          </button>
        </div>
      )}

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
          <button type="button" className={TEXT_ACTION} onClick={() => openEnable(true)}>
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
          pending={enable.isPending}
          error={enable.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            if (!tenantValid) return;
            const tenant = tenantId.trim();
            enable.mutate(tenant ? { tenant_id: tenant } : {}, { onSuccess: () => setConfirming(null) });
          }}
        >
          <p>
            This holds our Cartesia key in our developer workspace with its own keys left off. It
            installs a credential, so you may be asked to confirm it is still you.
          </p>
          <label htmlFor={tenantField} className={`mt-3 ${FIELD_LABEL}`}>
            First Studio client{askClient ? "" : " (optional)"}, account id
          </label>
          <input
            id={tenantField}
            className={`mt-1 ${FIELD}`}
            value={tenantId}
            onChange={(event) => setTenantId(event.target.value)}
            aria-invalid={!tenantValid}
            placeholder="Leave empty once a client runs Studio"
          />
          <p className={FIELD_HINT}>
            Studio is switched on in this client&rsquo;s own workspace, its Clear agents kept off
            first, so the Studio voices can be listed. The id is on the client&rsquo;s admin page.
          </p>
          {!tenantValid && <p className="mt-1 text-meta text-warn">That is not an account id.</p>}
        </ConfirmDialog>
      )}
      {confirming === "disable" && (
        <ConfirmDialog
          title="Switch our developer workspace's own keys off?"
          confirmLabel="Switch it off"
          pendingLabel="Switching off…"
          pending={disable.isPending}
          error={disable.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => disable.mutate(undefined, { onSuccess: () => setConfirming(null) })}
        >
          <p>
            Clients stop inheriting our key. The server refuses while any published Studio agent still
            depends on it, and names why.
          </p>
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
