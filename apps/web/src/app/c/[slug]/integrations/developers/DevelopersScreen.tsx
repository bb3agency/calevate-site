"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Drawer, DrawerSubmit } from "@/components/console/drawer";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  FilterChip,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
  type NoticeTone,
} from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { API_BASE } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { CopyRow } from "../../lead-sources/IssuedSecretNotice";
import {
  useApiActivity,
  useApiKeys,
  useCreateApiKey,
  useRenewApiKey,
  useRevokeApiKey,
  type ApiKey,
  type CreatedApiKey,
} from "./api";
import { PRESETS, SCOPE_WORDS, parseAddresses, presetScopes, type PresetId } from "./presets";

const STATE: Record<ApiKey["state"], { label: string; tone: NoticeTone }> = {
  active: { label: "Working", tone: "ok" },
  expiring: { label: "Expires soon", tone: "warn" },
  expired: { label: "Expired", tone: "neutral" },
  revoked: { label: "Revoked", tone: "neutral" },
};

/**
 * Keys for the business's own systems to use the public API (D-1047): make one, see what
 * each one did in the last day, renew it before it lapses, stop it at once.
 *
 * The key is shown once, in the drawer that made it. The list shows only its first
 * characters, so a screenshot of this page is never a disclosure.
 */
export function DevelopersScreen() {
  const session = useClientSession();
  const keys = useApiKeys(session);
  const write = useWriteAccess(session, "org:manage", "make or stop API keys");
  const [making, setMaking] = useState(false);
  const [made, setMade] = useState<CreatedApiKey | null>(null);
  const [stopping, setStopping] = useState<ApiKey | null>(null);
  const revoke = useRevokeApiKey(session);
  const revokeFeedback = useActionFeedback(revoke, { errorDisplay: "inline" });
  const renew = useRenewApiKey(session);
  useActionFeedback(renew, { errorDisplay: "inline", successToast: "Renewed for 90 days" });
  const [keyFilter, setKeyFilter] = useState<string | null>(null);
  const [failedOnly, setFailedOnly] = useState(false);
  const activity = useApiActivity(session, keyFilter, failedOnly);
  // Undefined until the keys arrive: a failed or parked read is refused below, never shown
  // as "No keys yet".
  const list = keys.data?.keys;
  const names = new Map(list?.map((k) => [k.id, k.name]));

  return (
    <div className="max-w-4xl space-y-10 pb-12">
      <PageHeader
        description="Place calls, read results and keep your do-not-call list."
        back={{ href: `/c/${session.orgSlug}/integrations`, label: "Integrations" }}
      />
      <RestrictionNote reason={write.reason} />

      <Section
        title="API keys"
        description="Each key works from a server, never from a web page."
        info={
          <p>
            A key can do only what you can do, and only what you tick. Keys stop after 90 days
            unless you renew them.
          </p>
        }
        action={
          <button
            type="button"
            onClick={() => setMaking(true)}
            disabled={!write.allowed}
            title={write.reason ?? undefined}
            className={SECONDARY_BUTTON_SM}
          >
            Make a key
          </button>
        }
      >
        {revoke.error && !stopping && <ProblemNotice error={revoke.error} />}
        {renew.error && <ProblemNotice error={renew.error} />}
        {keys.isLoading ? (
          <Skeleton rows={3} label="Loading your keys…" />
        ) : keys.error || !list ? (
          <ProblemNotice
            error={keys.error ?? new Error("Your API keys could not be loaded.")}
            onRetry={() => void keys.refetch()}
          />
        ) : list.length === 0 ? (
          <p className="text-body text-ink-muted">No keys yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {list.map((key) => (
              <li key={key.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start">
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="flex flex-wrap items-center gap-2 text-body font-medium text-ink">
                    <span className="break-all">{key.name}</span>
                    <StatusPill tone={lookup(STATE, key.state)?.tone ?? "neutral"}>
                      {lookup(STATE, key.state)?.label ?? key.state}
                    </StatusPill>
                  </p>
                  <p className="text-meta text-ink-muted">
                    <span className="font-mono">{key.display_prefix}…</span> ·{" "}
                    {key.scopes.map((s) => lookup(SCOPE_WORDS, s) ?? s).join(", ")}
                  </p>
                  <p className="text-meta text-ink-faint">
                    {key.state === "revoked" && key.revoked_at
                      ? `Revoked ${formatIST(key.revoked_at)}`
                      : `Expires ${formatIST(key.expires_at)}`}
                    {key.last_used_at ? ` · Last used ${formatIST(key.last_used_at)}` : " · Not used yet"}
                  </p>
                  {key.health.requests_24h > 0 && (
                    <p className="text-meta text-ink-faint">
                      {`Last 24 hours: ${key.health.requests_24h} requests, ${key.health.failed_24h} refused`}
                      {key.health.last_rate_limited_at
                        ? ` · Slowed down ${formatIST(key.health.last_rate_limited_at)}`
                        : ""}
                    </p>
                  )}
                </div>
                {(key.state === "active" || key.state === "expiring") && (
                  <div className="flex shrink-0 gap-2">
                    <ActionButton
                      variant="secondary-sm"
                      status={renew.isPending && renew.variables === key.id ? "pending" : undefined}
                      pendingLabel="Renewing…"
                      disabled={!write.allowed}
                      onClick={() => renew.mutate(key.id)}
                    >
                      Renew
                    </ActionButton>
                    <button
                      type="button"
                      className={SECONDARY_BUTTON_SM}
                      disabled={!write.allowed}
                      onClick={() => setStopping(key)}
                    >
                      Revoke
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Recent requests" description="The last 100, newest first.">
        <div className="mb-3 flex flex-wrap gap-2">
          <FilterChip label="All keys" active={keyFilter === null} onClick={() => setKeyFilter(null)} />
          {list?.map((key) => (
            <FilterChip
              key={key.id}
              label={key.name}
              active={keyFilter === key.id}
              onClick={() => setKeyFilter(key.id)}
            />
          ))}
          <FilterChip label="Refused only" active={failedOnly} onClick={() => setFailedOnly(!failedOnly)} />
        </div>
        {activity.error && <ProblemNotice error={activity.error} onRetry={() => void activity.refetch()} />}
        {activity.data && activity.data.requests.length === 0 && (
          <p className="text-body text-ink-muted">Nothing yet.</p>
        )}
        <ul className="divide-y divide-line">
          {(activity.data?.requests ?? []).map((row) => (
            <li key={row.id} className="py-2 text-meta">
              <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className={row.status >= 400 ? "font-medium text-danger" : "text-ink"}>{row.status}</span>
                <span className="break-all font-mono text-ink">
                  {row.method} {row.route}
                </span>
                <span className="text-ink-faint">{formatIST(row.created_at)}</span>
                <span className="text-ink-faint">{`${row.latency_ms} ms`}</span>
                {row.replayed && <span className="text-ink-faint">answered from the first try</span>}
                {!keyFilter && <span className="text-ink-faint">{names.get(row.api_key_id) ?? ""}</span>}
              </p>
              {row.problem_code && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-ink-muted">
                    <span className="font-mono">{row.problem_code}</span> · What to do
                  </summary>
                  <p className="mt-1 text-ink-muted">{row.remediation ?? "Check the request and try again."}</p>
                  {row.trace_id && <p className="mt-1 font-mono text-ink-faint">{`Reference ${row.trace_id}`}</p>}
                </details>
              )}
            </li>
          ))}
        </ul>
      </Section>

      <Section
        title="First request"
        description="Send the key as a bearer token."
        info={
          <p>
            The header means a retry never rings twice. Every answer says how many requests are
            left this minute.
          </p>
        }
      >
        <CopyRow
          label="Check a key works"
          value={`curl ${API_BASE}/api/v1/me -H "Authorization: Bearer YOUR_KEY"`}
          copyLabel="Copy the command"
        />
        <p className="mt-3 text-meta text-ink-muted">
          Calls that ring a phone need an <span className="font-mono">Idempotency-Key</span> header.
        </p>
        <p className="mt-1 text-meta text-ink-muted">
          <Link href={`/c/${session.orgSlug}/integrations`} className="underline">
            Webhooks
          </Link>{" "}
          tell your system when calls finish.
        </p>
      </Section>

      <MakeKeyDrawer
        open={making}
        onClose={() => setMaking(false)}
        onMade={(created) => {
          setMaking(false);
          setMade(created);
        }}
      />

      <Drawer
        open={made !== null}
        onClose={() => setMade(null)}
        title="Your new key"
        width="lg"
        footer={
          <button type="button" onClick={() => setMade(null)} className={PRIMARY_BUTTON}>
            I&apos;ve saved it
          </button>
        }
      >
        {made && (
          <div className="space-y-3 text-body">
            <p className="font-medium text-ink">Copy it now. We keep no copy and cannot show it again.</p>
            <CopyRow label={made.key.name} value={made.secret} copyLabel="Copy the key" />
            <p className="text-meta text-ink-muted">Keep it on your server or in your automation tool.</p>
            <p className="text-meta text-ink-muted">Never put it in a web page or an app.</p>
          </div>
        )}
      </Drawer>

      {stopping && (
        <ConfirmDialog
          title={`Revoke ${stopping.name}?`}
          confirmLabel="Revoke the key"
          pendingLabel="Revoking…"
          successLabel="Revoked"
          cancelLabel="Keep it"
          status={revokeFeedback.status}
          error={revoke.error}
          onCancel={() => {
            revoke.reset();
            setStopping(null);
          }}
          onConfirm={() => revoke.mutate(stopping.id, { onSuccess: () => setStopping(null) })}
        >
          <p>Its next request is refused. Anything using it stops.</p>
          <p>
            <strong className="font-semibold text-ink">This cannot be undone.</strong> Make a new key to
            replace it.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}

function MakeKeyDrawer({
  open,
  onClose,
  onMade,
}: {
  open: boolean;
  onClose: () => void;
  onMade: (created: CreatedApiKey) => void;
}) {
  const session = useClientSession();
  const agents = useAgents(session);
  const create = useCreateApiKey(session);
  useActionFeedback(create, { errorDisplay: "inline" });
  const [name, setName] = useState("");
  const [preset, setPreset] = useState<PresetId>("read");
  const [agentIds, setAgentIds] = useState<string[]>([]);
  const [addresses, setAddresses] = useState("");
  const [rate, setRate] = useState("");
  const formId = "make-api-key";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const perMinute = Number.parseInt(rate, 10);
    const ranges = parseAddresses(addresses);
    create.mutate(
      {
        name: name.trim(),
        scopes: presetScopes(preset),
        agent_ids: agentIds.length ? agentIds : null,
        ip_cidrs: ranges.length ? ranges : null,
        rate_per_minute: Number.isFinite(perMinute) ? perMinute : null,
      },
      {
        onSuccess: (created) => {
          setName("");
          setAgentIds([]);
          setAddresses("");
          setRate("");
          onMade(created);
        },
      },
    );
  };

  const toggleAgent = (id: string) =>
    setAgentIds((current) => (current.includes(id) ? current.filter((a) => a !== id) : [...current, id]));

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Make an API key"
      description="We will ask for the code we email you."
      formId={formId}
      dirty={name.length > 0}
      footer={<DrawerSubmit disabled={!name.trim() || create.isPending}>Make the key</DrawerSubmit>}
    >
      <form id={formId} onSubmit={submit} noValidate className="space-y-5">
        {create.error && <ProblemNotice error={create.error} />}
        <label className="block">
          <span className={FIELD_LABEL}>Name</span>
          <input
            className={FIELD}
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
            placeholder="Office CRM"
            required
          />
          <span className={FIELD_HINT}>So you can tell your keys apart.</span>
        </label>

        <fieldset className="space-y-2">
          <legend className={FIELD_LABEL}>What it may do</legend>
          {PRESETS.map((p) => (
            <label key={p.id} className="flex items-start gap-2 text-body">
              <input
                type="radio"
                name="preset"
                className="mt-1"
                checked={preset === p.id}
                onChange={() => setPreset(p.id)}
              />
              <span>
                <span className="font-medium text-ink">{p.label}</span>
                <span className="block text-meta text-ink-muted">{p.hint}</span>
              </span>
            </label>
          ))}
        </fieldset>

        {agents.isLoading ? (
          <Skeleton rows={1} label="Loading your agents…" />
        ) : agents.error || !agents.data ? (
          <ProblemNotice
            error={agents.error ?? new Error("Your agents could not be loaded.")}
            onRetry={() => void agents.refetch()}
          />
        ) : agents.data.length > 1 && (
          <fieldset className="space-y-2">
            <legend className={FIELD_LABEL}>Only these agents (optional)</legend>
            {agents.data.map((agent) => (
              <label key={agent.id} className="flex items-center gap-2 text-body">
                <input
                  type="checkbox"
                  checked={agentIds.includes(agent.id)}
                  onChange={() => toggleAgent(agent.id)}
                />
                <span className="break-all">{agent.name}</span>
              </label>
            ))}
            <span className={FIELD_HINT}>Leave all unticked to allow every agent.</span>
          </fieldset>
        )}

        <label className="block">
          <span className={FIELD_LABEL}>Only from these addresses (optional)</span>
          <textarea
            className={FIELD}
            rows={2}
            value={addresses}
            onChange={(e) => setAddresses(e.target.value)}
            placeholder="203.0.113.7, 198.51.100.0/24"
          />
          <span className={FIELD_HINT}>Your server&apos;s address. Requests from elsewhere are refused.</span>
        </label>

        <label className="block">
          <span className={FIELD_LABEL}>Most requests a minute (optional)</span>
          <input
            className={FIELD}
            inputMode="numeric"
            value={rate}
            onChange={(e) => setRate(e.target.value.replace(/\D/g, ""))}
            placeholder="120"
          />
        </label>
      </form>
    </Drawer>
  );
}
