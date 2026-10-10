"use client";

import { Section } from "@/components/console/section";
import { useState } from "react";
import Link from "next/link";
import { CircleAlert, PowerOff } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptyState } from "@/components/console/emptyState";
import { Metric } from "@/components/console/metric";
import { PageHeader } from "@/components/console/pageHeader";
import {
  FIELD,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import {
  useHealerActions,
  useHealerIncidents,
  useHealerOverview,
  usePostStatus,
  useResolveIncident,
  useRetryIncident,
  type HealerIncident,
  type HealerOverview,
  type StatusComponentKey,
} from "@/lib/api/opsHealer";

const COMPONENTS: { value: StatusComponentKey; label: string }[] = [
  { value: "calls", label: "Phone calls" },
  { value: "numbers", label: "Phone numbers" },
  { value: "dashboard", label: "Dashboard" },
  { value: "assistant", label: "Assistant" },
];

const STATE_WORDS: Record<HealerIncident["state"], string> = {
  open: "Detected",
  mitigated: "Repairing",
  escalated: "Needs a person",
  resolved: "Resolved",
};

/**
 * The auto-healer, for the operator: whether it is on, where pages go, what it is working
 * on, what each playbook may do, and everything it did. The kill switches are console
 * settings (`healer_enabled`, `healer_paused_playbooks`); this screen shows them and links
 * to where they are changed rather than being a second writer.
 */
export function HealerScreen() {
  const access = useAdminAccess("ops:manage", "read and steer the auto-healer");
  const overview = useHealerOverview();
  return (
    <div className="max-w-4xl space-y-10 pb-12">
      <PageHeader description="Repairs that run on their own, lines it is holding, and what needs you." />
      {access.refused ? (
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          {overview.error != null && (
            <ProblemNotice error={overview.error} onRetry={() => overview.refetch()} />
          )}
          {overview.isLoading ? (
            <Skeleton rows={4} label="Loading the auto-healer" />
          ) : overview.data ? (
            <Overview data={overview.data} />
          ) : null}
          <Incidents />
          <StatusPost />
          {overview.data && <Playbooks data={overview.data} />}
          <Ledger />
        </>
      )}
    </div>
  );
}

function Overview({ data }: { data: HealerOverview }) {
  const paging = data.paging;
  const whatsappReady =
    paging.whatsapp_available &&
    paging.whatsapp_enabled &&
    paging.founder_number_set &&
    paging.founder_number_from_console;
  return (
    <div className="space-y-3">
      {!data.enabled && (
        <NoticeBox
          tone="stop"
          icon={<PowerOff aria-hidden className="h-5 w-5" />}
          title="The auto-healer is switched off"
        >
          <p className="mt-1">
            No repair, line hold or scheduled sweep runs on its own, except the agent
            settings check that also enforces the AI disclosure. Detection and notices carry
            on. Turn it back on in{" "}
            <Link href="/admin/ops/config" className="underline underline-offset-2">
              configuration
            </Link>
            .
          </p>
        </NoticeBox>
      )}
      {!whatsappReady && (
        <NoticeBox
          tone="warn"
          icon={<CircleAlert aria-hidden className="h-5 w-5" />}
          title="Pages go by email only"
        >
          <p className="mt-1">
            {!paging.whatsapp_available
              ? `WhatsApp is not set up on this deployment (${paging.whatsapp_reason ?? "no reason given"}).`
              : !paging.whatsapp_enabled
                ? "WhatsApp sending is switched off in configuration."
                : !paging.founder_number_set
                  ? "No founder WhatsApp number is set."
                  : "The founder WhatsApp number came from the server environment, not the console, so there is no record of it being chosen here; set it in configuration."}
            {!paging.email_set && " No alert email address is set either, so pages reach nobody."}
          </p>
        </NoticeBox>
      )}
      {data.unknown_paused.length > 0 && (
        <NoticeBox tone="warn" title="Some paused playbooks do not exist">
          <p className="mt-1">
            The paused list names {data.unknown_paused.join(", ")}, which no playbook is
            called. Check the spelling in configuration.
          </p>
        </NoticeBox>
      )}
      <div className="grid grid-cols-2 gap-4 border-y border-line py-4 sm:grid-cols-3">
        <Metric label="Open incidents" value={data.open_incidents} />
        <Metric
          label="Need a person"
          value={data.escalated_incidents}
          tone={data.escalated_incidents > 0 ? "warn" : "default"}
        />
        <Metric label="Playbooks paused" value={data.paused.length} className="col-span-2 sm:col-span-1" />
      </div>
    </div>
  );
}

function Incidents() {
  const incidents = useHealerIncidents();
  const retry = useRetryIncident();
  const resolve = useResolveIncident();
  const [resolving, setResolving] = useState<HealerIncident | null>(null);
  return (
    <Section title="Incidents">
      {incidents.error != null && (
        <ProblemNotice error={incidents.error} onRetry={() => incidents.refetch()} />
      )}
      {retry.error != null && <ProblemNotice error={retry.error} />}
      {incidents.isLoading ? (
        <Skeleton rows={3} label="Loading incidents" />
      ) : !incidents.data ? null : incidents.data.items.length === 0 ? (
        <EmptyState message="Nothing in the last 7 days." />
      ) : (
        <ul className="divide-y divide-line">
          {incidents.data.items.map((incident) => (
            <li key={incident.id} className="space-y-1.5 py-3 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-body font-semibold text-ink">
                  {incident.playbook.replace(/_/g, " ")} ·{" "}
                  <MonoValue>{incident.trigger_code}</MonoValue>
                </p>
                <span className="rounded-full border border-line px-2.5 py-0.5 text-meta font-medium text-ink-muted">
                  {STATE_WORDS[incident.state]}
                </span>
              </div>
              <p className="text-meta text-ink-muted">
                Opened {formatIST(incident.opened_at)} · {incident.attempts} attempt
                {incident.attempts === 1 ? "" : "s"}
                {incident.last_outcome && <> · last: {incident.last_outcome}</>}
                {incident.public && <> · on the status page</>}
              </p>
              {incident.resolved_at === null && (
                <div className="flex flex-wrap gap-2 pt-1">
                  <button
                    type="button"
                    className={SECONDARY_BUTTON_SM}
                    disabled={retry.isPending}
                    onClick={() => retry.mutate(incident.id)}
                  >
                    Run next step now
                  </button>
                  <button
                    type="button"
                    className={SECONDARY_BUTTON_SM}
                    onClick={() => setResolving(incident)}
                  >
                    Resolve
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {resolving && (
        <ConfirmDialog
          title="Resolve this incident?"
          confirmLabel="Resolve"
          pendingLabel="Resolving…"
          pending={resolve.isPending}
          error={resolve.error}
          onCancel={() => setResolving(null)}
          onConfirm={() =>
            resolve.mutate(resolving.id, { onSuccess: () => setResolving(null) })
          }
        >
          Any line it is holding is given back and any campaign it paused is resumed. Do this
          only once the cause is fixed.
        </ConfirmDialog>
      )}
    </Section>
  );
}

function StatusPost() {
  const post = usePostStatus();
  const [title, setTitle] = useState("");
  const [component, setComponent] = useState<StatusComponentKey>("calls");
  return (
    <Section title="Post on the status page">
      <form
        noValidate
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (title.trim().length < 3) return;
          post.mutate(
            { incidentId: null, title: title.trim(), component },
            { onSuccess: () => setTitle("") },
          );
        }}
      >
        <p className="text-body text-ink-muted">
          The public reads this at status.calevate.tech. Name no client and no supplier.
        </p>
        <label className="block">
          <span className={FIELD_LABEL}>What the public reads</span>
          <input
            className={FIELD}
            value={title}
            maxLength={120}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Some calls are not connecting"
          />
        </label>
        <label className="block">
          <span className={FIELD_LABEL}>Which part</span>
          <select
            className={FIELD}
            value={component}
            onChange={(event) => setComponent(event.target.value as StatusComponentKey)}
          >
            {COMPONENTS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        {post.error != null && <ProblemNotice error={post.error} />}
        <button
          type="submit"
          className={PRIMARY_BUTTON}
          disabled={post.isPending || title.trim().length < 3}
        >
          {post.isPending ? "Posting…" : "Post"}
        </button>
      </form>
    </Section>
  );
}

function Playbooks({ data }: { data: HealerOverview }) {
  return (
    <Section title="Playbooks">
      <ul className="divide-y divide-line">
        {data.playbooks.map((p) => (
          <li key={p.key} className="space-y-1 py-3 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-body font-semibold text-ink">
                {p.title} <MonoValue>{p.key}</MonoValue>
              </p>
              <span className="rounded-full border border-line px-2.5 py-0.5 text-meta font-medium text-ink-muted">
                {!p.automatic ? "Pages only" : p.paused ? "Paused" : p.pausable ? "On" : "Always on"}
              </span>
            </div>
            <dl className="grid gap-x-3 gap-y-0.5 text-meta text-ink-muted sm:grid-cols-[8rem_1fr]">
              <dt className="font-medium text-ink">Does</dt>
              <dd>{p.action}</dd>
              <dt className="font-medium text-ink">Proves it worked</dt>
              <dd>{p.verify}</dd>
              <dt className="font-medium text-ink">Undo</dt>
              <dd>{p.undo}</dd>
              <dt className="font-medium text-ink">Limits</dt>
              <dd>
                {p.max_attempts} attempt{p.max_attempts === 1 ? "" : "s"}, {Math.round(p.cooldown_s / 60)}{" "}
                min apart · reaches one {p.blast_radius === "platform" ? "platform" : p.blast_radius}
                {p.job && <> · runs on a schedule</>}
              </dd>
              {p.triggers.length > 0 && (
                <>
                  <dt className="font-medium text-ink">Woken by</dt>
                  <dd className="break-words">{p.triggers.join(", ")}</dd>
                </>
              )}
            </dl>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Ledger() {
  const actions = useHealerActions(null);
  return (
    <Section title="What it did">
      {actions.error != null && (
        <ProblemNotice error={actions.error} onRetry={() => actions.refetch()} />
      )}
      {actions.isLoading ? (
        <Skeleton rows={3} label="Loading the ledger" />
      ) : !actions.data ? null : actions.data.items.length === 0 ? (
        <EmptyState message="Nothing recorded yet." />
      ) : (
        <ul className="divide-y divide-line text-body">
          {actions.data.items.map((a) => (
            <li key={a.id} className="py-2 first:pt-0 last:pb-0">
              <p className="text-ink">
                <MonoValue>{a.playbook}</MonoValue> {a.step} —{" "}
                <span className={a.outcome === "failed" ? "font-medium text-danger" : ""}>
                  {a.outcome}
                </span>
                {a.actor_type !== "healer" && <> (by a person)</>}
              </p>
              <p className="break-words text-meta text-ink-muted">
                {formatIST(a.at)}
                {a.detail && <> · {a.detail}</>}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
