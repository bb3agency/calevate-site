"use client";

import { Accordion } from "@/components/arc/accordion";
import { UsageMeter } from "@/components/arc/usage-meter";
import { EmptyState } from "@/components/console/emptyState";
import { StatusPill } from "@/components/admin/kit";
import { CopyButton } from "@/components/interior/copy-button";
import { ProblemNotice, Skeleton, formatCount, formatIST, type NoticeTone } from "@/components/ui";
import { usePromptLayers, type PromptLayer, type PromptLayers } from "@/lib/api/prompts";
import { lookup } from "@/lib/lookup";

/**
 * WHAT IT IS TOLD (D-882): the instructions a publish of this agent sends, in the order the
 * voice platform reads them, each part with who writes it and its length, so an operator can
 * see which part grew or changed without opening code. Read-only; the text is the server's
 * composition, never rebuilt here.
 */

const OWNER_LABEL: Record<PromptLayer["owner"], string> = {
  platform: "Platform",
  client: "Client",
  per_call: "Each call",
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

function DriftLine({ data }: { data: PromptLayers }) {
  if (!data.on_engine) {
    return <StatusPill tone="neutral">Not on the voice platform yet</StatusPill>;
  }
  const verdict = lookup(DRIFT, data.drift_state);
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-ink-muted">
      <StatusPill tone={verdict?.tone ?? "neutral"}>
        {verdict?.text ?? data.drift_state ?? "Not checked yet"}
      </StatusPill>
      {data.drift_checked_at && (
        // The sweep compared the copy with the composition as it stood then.
        <span>Last checked {formatIST(data.drift_checked_at)} IST</span>
      )}
    </p>
  );
}

function memoryNote(memory: PromptLayers["caller_memory"]): string | null {
  if (memory === "kept_by_engine") {
    return "Caller memory is kept by the voice platform and added on each call, so it is not part of this text.";
  }
  if (memory === "in_prompt") {
    return "Caller memory is shown empty: it is filled in for each call.";
  }
  return null;
}

function LayerSubtitle({ layer, total }: { layer: PromptLayer; total: number }) {
  const share = total > 0 ? Math.max((layer.chars / total) * 100, 0.5) : 0;
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

function LayerBody({ layer }: { layer: PromptLayer }) {
  return (
    <div className="space-y-3 pb-4">
      <p className="text-body text-ink-muted">{layer.purpose}</p>
      <pre className="max-h-[28rem] overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-ink/[0.03] p-3 font-mono text-meta text-ink">
        {layer.text}
      </pre>
      <CopyButton value={layer.text} label={`Copy ${layer.title}`} variant="text" />
    </div>
  );
}

export function PromptLayersPanel({ tenantId, agentId }: { tenantId: string; agentId: string }) {
  const layers = usePromptLayers(tenantId, agentId);

  if (layers.isLoading) return <Skeleton rows={4} />;
  if (layers.error || !layers.data) {
    return (
      <ProblemNotice
        error={layers.error ?? new Error("What this agent is told could not be read just now.")}
        onRetry={() => void layers.refetch()}
      />
    );
  }
  const data = layers.data;
  if (!data.has_script) {
    return (
      <EmptyState
        align="start"
        message="Nothing has been written for this agent yet."
        hint="Its instructions appear here once a script is saved and applied."
      />
    );
  }
  const note = memoryNote(data.caller_memory);
  const limit = data.limit_chars ?? 0;

  return (
    // The settings layout's own heading names this section.
    <div className="space-y-5">
      <div className="space-y-2">
        <p className="max-w-prose text-body text-ink-muted">
          Everything the voice platform is given for this agent, in the order it reads it, as
          the next publish would send it.
        </p>
        <DriftLine data={data} />
      </div>

      <UsageMeter
        label="Length of the instructions"
        used={data.total_chars}
        limit={limit}
        usedText={`${formatCount(data.total_chars)} characters`}
        limitText={limit > 0 ? `${formatCount(limit)}` : undefined}
        noLimitText="no limit on this platform"
        overTone="danger"
        hint={
          data.over_chars > 0
            ? `${formatCount(data.over_chars)} characters over: a publish is refused until it is shorter.`
            : data.engine_added_chars != null
              ? `The voice platform adds about ${formatCount(data.engine_added_chars)} characters of its own on every turn, outside this limit.`
              : undefined
        }
      />

      {note && <p className="max-w-prose text-meta text-ink-muted">{note}</p>}

      <Accordion
        exclusive={false}
        headingLevel={3}
        items={data.layers.map((layer) => ({
          id: layer.key,
          title: layer.title,
          subtitle: <LayerSubtitle layer={layer} total={data.total_chars} />,
          content: <LayerBody layer={layer} />,
        }))}
      />
    </div>
  );
}
