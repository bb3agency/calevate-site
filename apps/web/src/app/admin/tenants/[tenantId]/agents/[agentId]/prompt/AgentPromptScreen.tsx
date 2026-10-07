"use client";

import { useState } from "react";

import { PageHeader } from "@/components/console/pageHeader";
import { SettingsLayout, type SettingsSection } from "@/components/console/settingsLayout";
import { ProblemNotice } from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import { useTenant, useTenantAgents } from "@/lib/api/admin";
import { usePromptHistory } from "@/lib/api/prompts";
import { usePublishingRefresh, useTenantExperiment, useTenantPending } from "@/lib/api/publishing";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { AGENT_STATUS_TONE, StatePill } from "../../../statePill";
import { CallCapPanel } from "./sections/callCap";
import { ExperimentPanel } from "./sections/experiment";
import { GoLivePanel, PublishingPanel } from "./sections/live";
import { ScriptSection } from "./sections/script";
import { VoicePanel } from "./sections/voice";

/**
 * ONE AGENT: its script, voice and limits, and proof of what callers hear (admin surface —
 * every write here is `agents:write` and exists only in this realm).
 *
 * Primary job: *get the right script live on this agent.* The screen is a settings layout
 * (D-657) with one section per subject. **Live** opens first because it carries the
 * read-back's truthful-answer and disclosure verdicts, which are never behind a section
 * switch (UX-DOCTRINE §8.7); **Script** holds the editor, the one large button.
 *
 * Two-speed publishing (SURFACES §2b) is why Live and Script are separate: saving a version
 * STAGES it (`agents.system_prompt_id` is the draft pointer, `live_prompt_id` is what callers
 * hear) and only **Apply to live calls** moves the live one. The client sees the same staged
 * state on their own screen and cannot act on it.
 *
 * Reads go through the tenant's impersonated session (the slug comes from `useTenant`, a
 * cache hit under the layout) and writes go to admin routes: read as the tenant, write as
 * ourselves (D-22).
 */
const SECTIONS_BASE: SettingsSection[] = [
  { id: "live", label: "Live" },
  { id: "script", label: "Script" },
  { id: "voice", label: "Voice" },
  { id: "limits", label: "Call length" },
  { id: "test", label: "A/B test" },
];

export function AgentPromptScreen({ tenantId, agentId }: { tenantId: string; agentId: string }) {
  const tenant = useTenant(tenantId);
  const slug = tenant.data?.slug ?? "";

  const history = usePromptHistory(tenantId, agentId);
  const roster = useTenantAgents(slug);
  const agent = roster.data?.find((a) => a.id === agentId);
  const pending = useTenantPending(slug, agentId);
  const experiment = useTenantExperiment(slug, agentId);
  const refreshPublishing = usePublishingRefresh({ tenantId, agentId, slug });

  // Every write on this screen — save, roll back, apply, undo, call cap, voice, A/B — is
  // `agents:write`. One gate, read once and passed down, so five controls cannot answer at
  // five different moments as `/v1/admin/me` resolves.
  const write = useAdminAccess("agents:write", "change this agent's script");

  // The draft is held HERE, above the sections, so switching to Voice and back keeps it.
  // The guard still covers a reload or a closed tab.
  const [body, setBody] = useState("");
  const [notes, setNotes] = useState("");
  useUnsavedGuard(body.trim() !== "" || notes.trim() !== "");

  /*
   * THE SCRIPT EDITOR, DECLARED TO THE SCREEN ASSISTANT — the one admin screen with a
   * writable draft. `apply` writes through the same setters the textarea uses, never the
   * DOM. What a fill cannot do is why this is safe: saving STAGES a version and only a
   * person's Apply moves the live pointer, and the compliance sentences are not in this box
   * at all — `compose_engine_prompt` appends them server-side on every publish and the drift
   * sweep re-checks them (hard rule 5). The history goes as counts and version numbers, not
   * bodies; past `notes` are operator prose and stay behind.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/agents/{agentId}/prompt",
    title: "Agent prompt",
    realm: "admin",
    fields: [
      {
        id: "prompt-body",
        label: "New version — the agent's system prompt",
        type: "textarea",
        value: body,
        writable: write.allowed,
        help:
          "The full instruction the agent thinks with. Saving STAGES it; callers keep " +
          "hearing the live version until a person presses Apply. Do not write the AI " +
          "disclosure or the recording notice here — the server appends both to every " +
          "published prompt and verifies them against the engine, and nothing written " +
          "in this box can withdraw them. Minimum 20 characters.",
      },
      {
        id: "prompt-notes",
        label: "Notes — what changed and why",
        type: "text",
        value: notes,
        writable: write.allowed,
        help: "Optional, at most 200 characters. Read by whoever rolls this version back.",
      },
    ],
    facts: [
      { key: "tenant_id", label: "Tenant id", value: tenantId },
      { key: "client", label: "Client", value: tenant.data?.name ?? "not read yet" },
      { key: "agent_id", label: "Agent id", value: agentId },
      { key: "agent", label: "Agent", value: agent?.name ?? "not read yet" },
      {
        key: "versions",
        label: "Versions written so far",
        value: history.data ? String(history.data.length) : "could not be read",
      },
      {
        key: "live_version",
        label: "Version callers hear now",
        value: history.data
          ? (history.data.find((entry) => entry.active)?.version.toString() ?? "none is live")
          : "could not be read",
      },
      {
        key: "has_pending",
        label: "Is there a staged change waiting to be applied",
        value: pending.data ? (pending.data.has_pending ? "yes" : "no") : "could not be read",
      },
      {
        key: "agent_status",
        label: "Agent status",
        value: pending.data?.agent_status ?? "could not be read",
      },
      {
        key: "may_write",
        label: "May this operator change this agent's script",
        value: write.allowed ? "yes" : "no",
      },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id === "prompt-body") setBody(asText(item.value));
        if (item.field_id === "prompt-notes") setNotes(asText(item.value));
      }
    },
  });

  // Badges only from answers the server gave: an unread state shows nothing, never "0".
  const sections = SECTIONS_BASE.map((section) =>
    section.id === "test" && experiment.data?.experiment?.status === "running"
      ? { ...section, badge: "running" }
      : section,
  );

  return (
    <div className="space-y-6">
      <PageHeader
        // The agent's NAME, because a client with four agents makes any generic title
        // ambiguous; it renders once the roster has answered.
        title={agent?.name ?? "Agent"}
        status={
          <>
            {pending.data && (
              <StatePill tone={lookup(AGENT_STATUS_TONE, pending.data.agent_status) ?? "neutral"}>
                {pending.data.agent_status}
              </StatePill>
            )}
            {pending.data && !pending.data.published && (
              <StatePill tone="warn">not on the voice platform</StatePill>
            )}
            {pending.data?.has_pending && <StatePill tone="warn">change staged</StatePill>}
          </>
        }
        description="Every save is a new version, staged until someone presses Apply to live calls."
      />

      {tenant.error && <ProblemNotice error={tenant.error} onRetry={() => tenant.refetch()} />}

      <SettingsLayout
        label="Agent settings"
        // A row of pills: this page already sits beside the client's own section column,
        // and a second column would leave the content about 490px wide at 1280.
        menu="row"
        sections={sections}
        renderSection={(id) => {
          switch (id) {
            case "script":
              return (
                <ScriptSection
                  tenantId={tenantId}
                  agentId={agentId}
                  pending={pending.data}
                  write={write}
                  body={body}
                  notes={notes}
                  onBody={setBody}
                  onNotes={setNotes}
                  onWritten={() => void refreshPublishing()}
                />
              );
            case "voice":
              return (
                <VoicePanel
                  tenantId={tenantId}
                  agentId={agentId}
                  slug={slug}
                  agent={agent}
                  pending={pending.data}
                  tenantLoading={tenant.isLoading || pending.isLoading}
                  write={write}
                />
              );
            case "limits":
              return (
                <CallCapPanel
                  tenantId={tenantId}
                  agentId={agentId}
                  slug={slug}
                  pending={pending.data}
                  write={write}
                />
              );
            case "test":
              return (
                <ExperimentPanel
                  tenantId={tenantId}
                  agentId={agentId}
                  slug={slug}
                  write={write}
                  versions={history.data}
                />
              );
            default:
              return (
                <div className="space-y-5">
                  <GoLivePanel
                    tenantId={tenantId}
                    agentId={agentId}
                    slug={slug}
                    write={write}
                    pending={pending.data}
                    hasAScript={history.data === undefined ? undefined : history.data.length > 0}
                    isLoading={tenant.isLoading || pending.isLoading || history.isLoading}
                    readFailed={pending.error != null || history.error != null}
                  />
                  <PublishingPanel
                    tenantId={tenantId}
                    agentId={agentId}
                    slug={slug}
                    write={write}
                    pending={pending.data}
                    isLoading={tenant.isLoading || pending.isLoading}
                    error={pending.error}
                    onRetry={() => pending.refetch()}
                  />
                </div>
              );
          }
        }}
      />
    </div>
  );
}
