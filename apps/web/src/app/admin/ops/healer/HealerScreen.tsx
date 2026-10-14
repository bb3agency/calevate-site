"use client";

import { RowLink } from "@/components/console/checklist";
import { Section } from "@/components/console/section";
import { useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { lookup } from "@/lib/lookup";
import { StatusPill } from "@/components/admin/kit";
import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
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
  type NoticeTone,
} from "@/components/ui";
import {
  useHealerActions,
  useHealerIncidents,
  useHealerOverview,
  usePostStatus,
  useResolveIncident,
  useRetryIncident,
  type HealerAction,
  type HealerIncident,
  type HealerOverview,
  type StatusComponentKey,
} from "@/lib/api/opsHealer";

const COMPONENTS: { value: StatusComponentKey; label: string }[] = [
  { value: "calls", label: "Phone calls" },
  { value: "numbers", label: "Phone numbers" },
  { value: "dashboard", label: "Dashboard" },
  { value: "assistant", label: "Pip" },
];

/**
 * The pill on an incident. The sentence beside it (`progress`) and the problem's own words
 * (`kind`) come from the API's catalogue (`apps/api/healer/wording.py`), so this screen
 * never turns a code into words itself.
 */
const STATE_PILL: Record<HealerIncident["state"], { text: string; tone: NoticeTone }> = {
  open: { text: "Just found", tone: "neutral" },
  mitigated: { text: "Being fixed", tone: "neutral" },
  escalated: { text: "Needs you", tone: "warn" },
  resolved: { text: "Closed", tone: "ok" },
};

/** The ledger's steps (`healer/ledger.Step`); a step not listed shows as itself. */
const STEP_WORDS: Record<string, string> = {
  schedule: "Ran its scheduled check",
  act: "Tried a repair",
  verify: "Checked the repair",
  undo: "Undid a change",
  escalate: "Handed it to you",
  protect: "Held the line",
  restore: "Gave the line back",
  notify: "Sent a notice",
  propose: "Suggested a fix to the client",
  decide: "Recorded a decision",
};

const OUTCOME_WORDS: Record<HealerAction["outcome"], string> = {
  ok: "done",
  failed: "failed",
  skipped: "skipped",
  refused: "refused",
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
      <PageHeader description="Problems the platform found, what it fixed on its own, and what needs you." />
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
          <Ledger titles={playbookTitles(overview.data)} />
        </>
      )}
    </div>
  );
}

function playbookTitles(data: HealerOverview | undefined): Record<string, string> {
  return Object.fromEntries((data?.playbooks ?? []).map((p) => [p.key, p.title]));
}

function Overview({ data }: { data: HealerOverview }) {
  const paging = data.paging;
  const whatsappReady =
    paging.whatsapp_available &&
    paging.whatsapp_enabled &&
    paging.founder_number_set &&
    paging.founder_number_from_console;
  const pausedRepairs = data.playbooks.filter((p) => p.paused).length;
  return (
    <div className="space-y-3">
      {!data.enabled && (
        <NoticeBox
          tone="stop"
          title="The auto-healer is switched off"
          action={<RowLink href="/admin/ops/config">Turn on in configuration</RowLink>}
          info="Only the agent settings check runs, because it also enforces the AI disclosure. Detection and notices carry on."
          infoLabel="a switched-off healer"
        >
          No repair, line hold or scheduled sweep runs on its own.
        </NoticeBox>
      )}
      {!whatsappReady && (
        <NoticeBox
          tone="warn"
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
        <Metric
          label="Open problems"
          value={data.open_incidents}
          hint="Not closed yet, including any waiting for you."
        />
        <Metric
          label="Waiting for you"
          value={data.escalated_incidents}
          tone={data.escalated_incidents > 0 ? "warn" : "default"}
          hint="The healer could not fix these on its own."
        />
        <Metric
          label="Repairs switched off"
          value={pausedRepairs}
          className="col-span-2 sm:col-span-1"
          hint={
            data.enabled
              ? "Paused in configuration, so they do not run."
              : "The whole auto-healer is off."
          }
        />
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
    <Section title="Problems">
      {incidents.error != null && (
        <ProblemNotice error={incidents.error} onRetry={() => incidents.refetch()} />
      )}
      {retry.error != null && <ProblemNotice error={retry.error} />}
      {incidents.isLoading ? (
        <Skeleton rows={3} label="Loading problems" />
      ) : !incidents.data ? null : incidents.data.items.length === 0 ? (
        <EmptyState message="Nothing in the last 7 days." />
      ) : (
        <ul className="divide-y divide-line">
          {incidents.data.items.map((incident) => (
            <IncidentRow
              key={incident.id}
              incident={incident}
              retrying={retry.isPending}
              onRetry={() => retry.mutate(incident.id)}
              onResolve={() => setResolving(incident)}
            />
          ))}
        </ul>
      )}
      {resolving && (
        <ConfirmDialog
          title="Mark this as handled?"
          confirmLabel="Mark as handled"
          pendingLabel="Marking…"
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

function IncidentRow({
  incident,
  retrying,
  onRetry,
  onResolve,
}: {
  incident: HealerIncident;
  retrying: boolean;
  onRetry: () => void;
  onResolve: () => void;
}) {
  const pill = STATE_PILL[incident.state];
  const { kind } = incident;
  return (
    <li className="space-y-1.5 py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1 basis-56">
          <p className="text-meta text-ink-muted">{incident.group}</p>
          <div className="flex items-center gap-1">
            <p className="min-w-0 text-body font-semibold text-ink">{kind.title}</p>
            <InfoTip label={kind.title}>
              <p>{kind.meaning}</p>
              <p>
                <span className="font-medium text-ink">What to do: </span>
                {kind.next_step}
              </p>
              <p>
                Code for logs: <MonoValue>{incident.trigger_code}</MonoValue>
              </p>
            </InfoTip>
          </div>
        </div>
        <StatusPill tone={pill.tone}>{pill.text}</StatusPill>
      </div>
      <p className="text-meta text-ink-muted">
        {incident.progress} · Found {formatIST(incident.opened_at)}
        {incident.resolved_at && <> · Closed {formatIST(incident.resolved_at)}</>}
        {incident.public && <> · On the status page</>}
      </p>
      {incident.state === "escalated" && (
        <p className="text-meta text-ink">
          <span className="font-medium">What to do: </span>
          {kind.next_step}
        </p>
      )}
      {incident.resolved_at === null && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {incident.automatic && (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={retrying}
              onClick={onRetry}
            >
              Check again now
            </button>
          )}
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={onResolve}>
            Mark as handled
          </button>
          <InfoTip label={`the buttons for ${kind.title}`}>
            {incident.automatic && (
              <p>
                <span className="font-medium text-ink">Check again now</span> runs this
                problem&apos;s next step on the healer&apos;s next minute&apos;s check instead
                of waiting. If the problem has cleared it closes; if a repair try is left, it
                repairs again.
              </p>
            )}
            <p>
              <span className="font-medium text-ink">Mark as handled</span> closes it. Any
              line it is holding is given back and any campaign it paused is resumed, so do
              this only once the cause is fixed. You confirm first.
            </p>
          </InfoTip>
        </div>
      )}
    </li>
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
    <Section title="What it can fix">
      <ul className="divide-y divide-line">
        {data.playbooks.map((p) => (
          <li key={p.key} className="space-y-1 py-3 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-body font-semibold text-ink">
                {p.title} <MonoValue className="text-meta font-normal text-ink-muted">{p.key}</MonoValue>
              </p>
              <StatusPill tone={p.paused ? "warn" : "neutral"}>
                {!p.automatic ? "Tells you only" : p.paused ? "Switched off" : p.pausable ? "On" : "Always on"}
              </StatusPill>
            </div>
            <dl className="grid gap-x-3 gap-y-0.5 text-meta text-ink-muted sm:grid-cols-[8rem_1fr]">
              <dt className="font-medium text-ink">Does</dt>
              <dd>{p.action}</dd>
              <dt className="font-medium text-ink">How it checks</dt>
              <dd>{p.verify}</dd>
              <dt className="font-medium text-ink">Undo</dt>
              <dd>{p.undo}</dd>
              {p.automatic && (
                <>
                  <dt className="font-medium text-ink">Limits</dt>
                  <dd>
                    {p.max_attempts} tr{p.max_attempts === 1 ? "y" : "ies"},{" "}
                    {Math.round(p.cooldown_s / 60)} min apart · a mistake could reach{" "}
                    {p.blast_radius === "tenant"
                      ? "one client"
                      : p.blast_radius === "platform"
                        ? "every client"
                        : "one agent"}
                    {p.job && <> · runs on a schedule</>}
                  </dd>
                </>
              )}
              {p.woken_by.length > 0 && (
                <>
                  <dt className="font-medium text-ink">Starts when</dt>
                  <dd className="break-words">{p.woken_by.map((k) => k.title).join("; ")}</dd>
                </>
              )}
            </dl>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Ledger({ titles }: { titles: Record<string, string> }) {
  const actions = useHealerActions(null);
  return (
    <Section title="What it did">
      {actions.error != null && (
        <ProblemNotice error={actions.error} onRetry={() => actions.refetch()} />
      )}
      {actions.isLoading ? (
        <Skeleton rows={3} label="Loading what it did" />
      ) : !actions.data ? null : actions.data.items.length === 0 ? (
        <EmptyState message="Nothing recorded yet." />
      ) : (
        <ul className="divide-y divide-line text-body">
          {actions.data.items.map((a) => (
            <li key={a.id} className="py-2 first:pt-0 last:pb-0">
              <p className="text-ink">
                {lookup(titles, a.playbook) ?? a.playbook}: {lookup(STEP_WORDS, a.step) ?? a.step},{" "}
                <span className={a.outcome === "failed" ? "font-medium text-danger" : ""}>
                  {lookup(OUTCOME_WORDS, a.outcome) ?? a.outcome}
                </span>
                {a.actor_type !== "healer" && <> (by a person)</>}
              </p>
              <p className="break-words text-meta text-ink-muted">
                {formatIST(a.at)}
                {a.detail && (
                  <>
                    {" "}
                    · <MonoValue className="text-meta">{a.detail}</MonoValue>
                  </>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
