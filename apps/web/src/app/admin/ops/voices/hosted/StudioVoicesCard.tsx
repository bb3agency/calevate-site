"use client";

import { useId, useState } from "react";
import { CircleCheck, KeyRound, PowerOff, TriangleAlert } from "lucide-react";

import { ConfirmDialog } from "@/components/confirmDialog";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
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
} from "@/lib/api/opsHostedVoices";

const UUID_SHAPE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Studio voices (D-717): our Cartesia key, switched on for the voice only in the voice platform
 * workspace of each client that publishes a Studio agent, automatically. Our developer workspace
 * only HOLDS the key with its switch off, so no client inherits it. The card shows whether Studio
 * can be sold, what is missing, and which client workspaces run it; "Studio ready" holds the key
 * and, given a client, switches that client on so the first Studio voices can be listed. Every
 * sentence about the state is the server's.
 */
export function StudioVoicesCard() {
  const studio = useStudioVoices(true);
  const enable = useEnableStudioVoices();
  const disable = useDisableStudioVoices();
  const [confirming, setConfirming] = useState<"enable" | "disable" | null>(null);
  const [tenantId, setTenantId] = useState("");
  const tenantField = useId();
  const last = enable.data ?? disable.data;
  const tenantValid = tenantId.trim() === "" || UUID_SHAPE.test(tenantId.trim());

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h2 className="text-body font-semibold text-ink">Studio voices (our Cartesia key)</h2>
          {studio.error != null ? (
            <ProblemNotice error={studio.error} onRetry={() => void studio.refetch()} />
          ) : !studio.data ? (
            <Skeleton rows={2} label="Reading whether Studio voices are ready" />
          ) : (
            <>
              <p className="flex items-center gap-1.5 text-body font-medium">
                {studio.data.ready ? (
                  <>
                    <CircleCheck aria-hidden className="h-4 w-4 text-brand-strong" />
                    <span className="text-ink">Ready — Studio voices can be offered</span>
                  </>
                ) : (
                  <>
                    <TriangleAlert aria-hidden className="h-4 w-4 text-warn" />
                    <span className="text-warn">Not ready — Studio voices cannot be offered</span>
                  </>
                )}
              </p>
              <p className="text-body text-ink-muted">{studio.data.note}</p>
              <p className="text-meta text-ink-muted">{studio.data.explanation}</p>
              {studio.data.developer_switch_on && (
                <NoticeBox tone="warn" title="Our developer workspace's own keys are on" className="mt-2">
                  <p className="mt-1">
                    Every client without a key of its own inherits it. Republish each Studio agent so
                    its client runs on its own key, then switch the developer workspace off below.
                  </p>
                </NoticeBox>
              )}
              <dl className="mt-1 grid gap-x-4 gap-y-0.5 text-meta text-ink-muted sm:grid-cols-[auto_1fr]">
                <dt className="font-medium">Cartesia key in the ops console</dt>
                <dd>{studio.data.cartesia_key_configured ? "Set" : "Not set"}</dd>
                <dt className="font-medium">Held in our developer workspace</dt>
                <dd>
                  {studio.data.developer_holds_key ? "Yes" : "No"}
                  {" · own keys "}
                  {studio.data.developer_switch_on ? "on" : "off"}
                </dd>
                <dt className="font-medium">Studio minute rate</dt>
                <dd>{studio.data.minute_attested ? "Attested" : "Not attested"}</dd>
                <dt className="font-medium">Cartesia voice price</dt>
                <dd>{studio.data.synthesis_priced ? "Attested" : "Not attested"}</dd>
                <dt className="font-medium">Studio voices listed</dt>
                <dd>{studio.data.voices_listed ? "Yes" : "No"}</dd>
                <dt className="font-medium">Client workspaces on Studio</dt>
                <dd className="tabular-nums">{formatCount(studio.data.workspaces.length)}</dd>
                <dt className="font-medium">Published Studio agents</dt>
                <dd className="tabular-nums">{formatCount(studio.data.live_studio_agents)}</dd>
              </dl>
              {studio.data.missing.length > 0 && (
                <ol className="mt-1 list-decimal pl-5 text-meta text-ink-muted">
                  {studio.data.missing.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
              )}
              {studio.data.workspaces.length > 0 && (
                <ul className="mt-1 space-y-0.5 text-meta text-ink-muted">
                  {studio.data.workspaces.map((ws) => (
                    <li key={ws.tenant_id}>
                      {ws.tenant_name ?? ws.tenant_id}
                      {ws.error_code ? ` · last error ${ws.error_code}` : " · on"}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
        {studio.data && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className={PRIMARY_BUTTON_SM}
              onClick={() => {
                enable.reset();
                setConfirming("enable");
              }}
            >
              <KeyRound aria-hidden className="h-4 w-4" />
              Studio ready
            </button>
            {studio.data.developer_switch_on && (
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
            )}
          </div>
        )}
      </div>
      {confirming === null && last && (
        <p role="status" className="mt-2 text-body text-ink-muted">
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
          <p>{studio.data?.explanation}</p>
          <p className="mt-2">
            Our Cartesia key is held in our developer workspace with its own keys left off. It installs
            a credential, so you may be asked to confirm it is still you.
          </p>
          <label htmlFor={tenantField} className={`mt-3 ${FIELD_LABEL}`}>
            First Studio client (optional, account id)
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
            Studio is switched on in this client&rsquo;s own workspace, its Clear agents kept off first,
            so the Studio voices can be listed.
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
    </div>
  );
}
