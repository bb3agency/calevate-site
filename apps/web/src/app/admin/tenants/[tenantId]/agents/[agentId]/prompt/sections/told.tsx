"use client";

import { useState } from "react";

import { Accordion } from "@/components/arc/accordion";
import { UsageMeter } from "@/components/arc/usage-meter";
import { EmptyState } from "@/components/console/emptyState";
import { StatusPill } from "@/components/admin/kit";
import { CopyButton } from "@/components/interior/copy-button";
import {
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatCount,
  formatIST,
  type NoticeTone,
} from "@/components/ui";
import {
  usePromptLayers,
  type PromptHolder,
  type PromptLayer,
} from "@/lib/api/prompts";
import { lookup } from "@/lib/lookup";

/**
 * WHAT IT IS TOLD (D-882): for each campaign, Inbound line and test copy that holds an engine
 * agent of this agent's (D-1019), what a publish sends now, built by the server from that
 * holder's own script and settings: the instructions by layer with their length against the
 * platform's limit, then the first words, steps, settings, tools and knowledge. Beside it,
 * whether that differs from what the last publish sent and what the last platform check
 * found. Read-only; nothing is recomposed here.
 */

const OWNER_LABEL: Record<PromptLayer["owner"], string> = {
  platform: "Platform",
  client: "Client",
  per_call: "Each call",
};

const KIND_LABEL: Record<PromptHolder["kind"], string> = {
  campaign: "Campaign",
  line: "Inbound line",
  test_copy: "Test copy",
  arm: "Script test",
  agent: "Agent",
};

/** The last scheduled check of the platform's copy (`engine_agent_routes.drift_state`). */
const DRIFT: Record<string, { tone: NoticeTone; text: string }> = {
  applied: { tone: "ok", text: "The voice platform holds this" },
  not_applied: { tone: "stop", text: "The voice platform holds something different" },
  truthful_answer_missing: {
    tone: "stop",
    text: "The voice platform's copy is missing the truthful answers",
  },
  unreadable: { tone: "warn", text: "The voice platform's copy could not be read" },
  unreachable: { tone: "warn", text: "The voice platform could not be reached" },
  not_published: { tone: "neutral", text: "Not on the voice platform" },
};

function liveState(holder: PromptHolder): { tone: NoticeTone; text: string } {
  if (holder.changed_since_publish === true) {
    return { tone: "warn", text: "Changed since last publish: republish" };
  }
  if (holder.changed_since_publish === false) {
    return { tone: "ok", text: "Live matches what would be sent now" };
  }
  return { tone: "neutral", text: "No publish recorded yet" };
}

function HolderStates({ holder }: { holder: PromptHolder }) {
  const verdict = lookup(DRIFT, holder.drift_state);
  const live = liveState(holder);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-meta text-ink-muted">
      <StatusPill tone={live.tone}>{live.text}</StatusPill>
      <StatusPill tone={verdict?.tone ?? "neutral"}>
        {verdict?.text ?? holder.drift_state ?? "Not checked yet"}
      </StatusPill>
      {holder.published && <span>Published {formatIST(holder.published.at)} IST</span>}
      {holder.drift_checked_at && (
        <span>Checked {formatIST(holder.drift_checked_at)} IST</span>
      )}
    </div>
  );
}

function LayerSubtitle({ layer, total }: { layer: PromptLayer; total: number }) {
  const share = total > 0 ? Math.min(Math.max((layer.chars / total) * 100, 0.5), 100) : 0;
  return (
    <span className="mt-1 block space-y-1.5">
      <span className="flex flex-wrap gap-x-2">
        <span className="font-medium text-ink">{OWNER_LABEL[layer.owner]}</span>
        <span aria-hidden>·</span>
        <span>{layer.from_agent_settings ? "Shaped by this agent's settings" : "Same for every agent"}</span>
        <span aria-hidden>·</span>
        <span className="tabular-nums">{formatCount(layer.chars)} characters</span>
      </span>
      {/* The length is in words beside it; the bar only shows proportion. */}
      <span aria-hidden className="block h-1.5 w-full max-w-sm overflow-hidden rounded-full bg-ink/[0.06]">
        <span
          className={`block h-full rounded-full ${layer.owner === "client" ? "bg-brand" : "bg-ink-faint"}`}
          style={{ width: `${String(share)}%` }}
        />
      </span>
    </span>
  );
}

const TEXT_BLOCK =
  "max-h-[28rem] overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-ink/[0.03] p-3 font-mono text-meta text-ink";

function LayerBody({ layer }: { layer: PromptLayer }) {
  return (
    <div className="space-y-3 pb-4">
      <p className="text-body text-ink-muted">{layer.purpose}</p>
      <pre className={TEXT_BLOCK}>{layer.text}</pre>
      <CopyButton value={layer.text} label={`Copy ${layer.title}`} variant="text" />
    </div>
  );
}

type SentNow = NonNullable<PromptHolder["sent_now"]>;

function Rows({ rows }: { rows: { label: string; value: string }[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 pb-4 sm:grid-cols-[minmax(10rem,auto)_1fr]">
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <dt className="text-meta text-ink-muted">{row.label}</dt>
          <dd className="text-body text-ink">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function StepsBody({ steps }: { steps: SentNow["steps"] }) {
  if (steps.length === 0) {
    return (
      <p className="pb-4 text-body text-ink-muted">
        No steps are sent: the outline stays inside the script.
      </p>
    );
  }
  return (
    <ol className="list-decimal space-y-3 pb-4 pl-5">
      {steps.map((step, i) => (
        <li key={`${String(i)}-${step.title}`} className="space-y-1">
          <p className="font-medium text-ink">{step.title || "Untitled step"}</p>
          {step.detail && <p className="text-body text-ink-muted">{step.detail}</p>}
          {step.branches.map(([when, action]) => (
            <p key={`${when}-${action}`} className="text-meta text-ink-muted">
              If {when}: {action}
            </p>
          ))}
          {step.collect.length > 0 && (
            <p className="text-meta text-ink-muted">Notes: {step.collect.join(", ")}</p>
          )}
        </li>
      ))}
    </ol>
  );
}

function ToolsBody({ sent }: { sent: SentNow }) {
  const on = sent.built_in_tools.filter((t) => t.on).map((t) => t.label);
  const off = sent.built_in_tools.filter((t) => !t.on).map((t) => t.label);
  return (
    <Rows
      rows={[
        { label: "Platform tools on", value: on.join(", ") || "None" },
        { label: "Platform tools off", value: off.join(", ") || "None" },
        { label: "Our actions", value: sent.custom_actions.join(", ") || "None" },
      ]}
    />
  );
}

function KnowledgeBody({ holder }: { holder: PromptHolder }) {
  if (holder.documents_total === 0) {
    return <p className="pb-4 text-body text-ink-muted">No documents are attached.</p>;
  }
  return (
    <div className="space-y-2 pb-4">
      <ul className="space-y-1">
        {holder.documents.map((doc) => (
          <li key={`${doc.kind}-${doc.name}`} className="text-body text-ink">
            {doc.name} <span className="text-meta text-ink-muted">· {doc.kind}</span>
          </li>
        ))}
      </ul>
      {holder.documents_total > holder.documents.length && (
        <p className="text-meta text-ink-muted">
          And {formatCount(holder.documents_total - holder.documents.length)} more.
        </p>
      )}
    </div>
  );
}

function SentSections({ holder, sent }: { holder: PromptHolder; sent: SentNow }) {
  return (
    <Accordion
      exclusive={false}
      headingLevel={4}
      items={[
        {
          id: "greeting",
          title: "First words",
          subtitle: `${formatCount(sent.greeting_chars)} characters`,
          content: (
            <div className="space-y-3 pb-4">
              <pre className={TEXT_BLOCK}>{sent.greeting}</pre>
              <CopyButton value={sent.greeting} label="Copy the first words" variant="text" />
            </div>
          ),
        },
        {
          id: "steps",
          title: "Steps",
          subtitle: sent.steps.length ? `${formatCount(sent.steps.length)} steps` : "None sent",
          content: <StepsBody steps={sent.steps} />,
        },
        {
          id: "settings",
          title: "Settings",
          subtitle: sent.settings.map((s) => s.label).slice(0, 3).join(", "),
          content: (
            <div className="space-y-3">
              <Rows rows={sent.settings.map((s) => ({ label: s.label, value: s.value }))} />
              {sent.thinking_lines.length > 0 && (
                <div className="space-y-1 pb-4">
                  <p className="text-meta text-ink-muted">Thinking filler lines</p>
                  <ul className="list-disc space-y-1 pl-5 text-body text-ink">
                    {sent.thinking_lines.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ),
        },
        {
          id: "tools",
          title: "Tools and actions",
          subtitle: `${formatCount(sent.built_in_tools.filter((t) => t.on).length)} platform tools on, ${formatCount(sent.custom_actions.length)} of ours`,
          content: <ToolsBody sent={sent} />,
        },
        {
          id: "knowledge",
          title: "Knowledge",
          subtitle: `${formatCount(holder.documents_total)} documents attached`,
          content: <KnowledgeBody holder={holder} />,
        },
      ]}
    />
  );
}

function HolderDetail({ holder }: { holder: PromptHolder }) {
  const limit = holder.limit_chars ?? 0;
  return (
    <section aria-labelledby={`holder-${holder.kind}-${holder.holder_id ?? "own"}`} className="space-y-5">
      <div className="space-y-2">
        <h3
          id={`holder-${holder.kind}-${holder.holder_id ?? "own"}`}
          className="text-body font-semibold text-ink"
        >
          {holder.name}
        </h3>
        <p className="text-meta text-ink-muted">
          {KIND_LABEL[holder.kind]}
          {holder.status ? ` · ${holder.status}` : ""}
        </p>
        <HolderStates holder={holder} />
      </div>

      {!holder.has_script ? (
        <EmptyState
          align="start"
          message="Nothing has been written for this yet."
          hint="Its instructions appear here once a script is saved."
        />
      ) : (
        <>
          <UsageMeter
            label="Length of the instructions"
            used={holder.total_chars}
            limit={limit}
            usedText={`${formatCount(holder.total_chars)} characters`}
            limitText={limit > 0 ? `${formatCount(limit)}` : undefined}
            noLimitText="no limit on this platform"
            overTone="danger"
            hint={
              holder.over_chars > 0
                ? `${formatCount(holder.over_chars)} characters over: a publish is refused until the script is shorter.`
                : holder.engine_added_chars != null
                  ? `The voice platform adds about ${formatCount(holder.engine_added_chars)} characters of its own on every turn, outside this limit.`
                  : undefined
            }
          />
          {holder.training_cut_chars > 0 && (
            <p className="max-w-prose text-meta text-ink-muted">
              The company training is shortened by {formatCount(holder.training_cut_chars)}{" "}
              characters here so the instructions fit. The owner sees this on Company training.
            </p>
          )}
          {holder.caller_memory === "kept_by_engine" && (
            <p className="max-w-prose text-meta text-ink-muted">
              Caller memory is kept by the voice platform and added on each call, so it is not
              part of this text.
            </p>
          )}

          <Accordion
            exclusive={false}
            headingLevel={4}
            items={holder.layers.map((layer) => ({
              id: layer.key,
              title: layer.title,
              subtitle: <LayerSubtitle layer={layer} total={holder.total_chars} />,
              content: <LayerBody layer={layer} />,
            }))}
          />

          {holder.refused ? (
            <NoticeBox tone="stop" title="A publish would be refused">
              {holder.refused.detail}
            </NoticeBox>
          ) : (
            holder.sent_now && <SentSections holder={holder} sent={holder.sent_now} />
          )}
        </>
      )}
    </section>
  );
}

function holderKey(holder: PromptHolder): string {
  return `${holder.kind}:${holder.holder_id ?? "own"}`;
}

function HolderPicker({
  holders,
  selected,
  onSelect,
}: {
  holders: PromptHolder[];
  selected: string;
  onSelect: (key: string) => void;
}) {
  return (
    <ul aria-label="What holds this agent on the voice platform" className="divide-y divide-line rounded-md border border-line">
      {holders.map((holder) => {
        const key = holderKey(holder);
        const live = liveState(holder);
        return (
          <li key={key}>
            <button
              type="button"
              aria-pressed={key === selected}
              onClick={() => onSelect(key)}
              className={`flex min-h-11 w-full flex-wrap items-center justify-between gap-x-4 gap-y-1 px-3 py-2 text-left focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-brand ${
                key === selected ? "bg-ink/[0.04]" : "hover:bg-ink/[0.02]"
              }`}
            >
              <span className="min-w-0">
                <span className="block truncate font-medium text-ink">{holder.name}</span>
                <span className="block text-meta text-ink-muted">
                  {KIND_LABEL[holder.kind]}
                  {holder.status ? ` · ${holder.status}` : ""}
                </span>
              </span>
              <span className="flex items-center gap-4 text-meta text-ink-muted">
                <span className="tabular-nums">{formatCount(holder.total_chars)} characters</span>
                <StatusPill tone={live.tone}>{live.text}</StatusPill>
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function PromptLayersPanel({ tenantId, agentId }: { tenantId: string; agentId: string }) {
  const layers = usePromptLayers(tenantId, agentId);
  const [picked, setPicked] = useState<string | null>(null);

  if (layers.isLoading) return <Skeleton rows={4} />;
  if (layers.error || !layers.data) {
    return (
      <ProblemNotice
        error={layers.error ?? new Error("What this agent is told could not be read just now.")}
        onRetry={() => void layers.refetch()}
      />
    );
  }
  const { holders, more_holders: more } = layers.data;
  const selected = holders.find((h) => holderKey(h) === picked) ?? holders[0];
  if (!selected) {
    return (
      <EmptyState
        align="start"
        message="Nothing of this agent's is on the voice platform yet."
        hint="Each campaign, Inbound line and test copy gets its own copy on the voice platform when it is published, and appears here."
      />
    );
  }

  return (
    // The settings layout's own heading names this section.
    <div className="space-y-6">
      <p className="max-w-prose text-body text-ink-muted">
        Each campaign, Inbound line and test copy has its own copy on the voice platform, built
        from its own script and settings. Pick one to see what a publish sends now.
      </p>
      {holders.length > 1 && (
        <HolderPicker holders={holders} selected={holderKey(selected)} onSelect={setPicked} />
      )}
      {more > 0 && (
        <p className="text-meta text-ink-muted">And {formatCount(more)} more not shown.</p>
      )}
      <HolderDetail holder={selected} />
    </div>
  );
}
