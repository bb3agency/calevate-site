"use client";

/**
 * WHAT AN AGENT MAY DO MID-CALL — the master switch, the credentials, and the tool list.
 *
 * Master switch, saved credentials, and per-agent tool definitions across the three kinds
 * (Custom API, WhatsApp, Google Calendar). Every value binding is one of three things the
 * founder's spec names: a static value, a lead/call variable (`</>` — the caller's number,
 * the call id), or ✨ AI-decided (the model fills it from the conversation). A change
 * reaches live calls at the next publish, exactly like a voice or cap change.
 *
 * Types come off the generated client; nothing here recomputes server state.
 *
 * ## What this file is now, after the split (UX-DOCTRINE §6)
 *
 * It was 738 lines carrying five components and the whole wire mapping. It is now the
 * ORCHESTRATION only — which reads happen, what the master switch does, and which of the
 * four children renders. The children are one subject each, in this directory:
 * `Credentials`, `ToolRow` (with its test panel), `ActionForm`, `ParamEditor`, and the
 * React-free vocabulary in `params.ts`.
 */

import { useState } from "react";
import { PlugZap, Plus } from "lucide-react";

import {
  FIELD_HINT,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  SectionHeading,
  Skeleton,
  ToggleSwitch,
} from "@/components/ui";
import {
  ACTION_KIND_LABELS,
  useAgentActions,
  useSetMasterSwitch,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";

import { ActionForm } from "./ActionForm";
import { Credentials } from "./Credentials";
import { ToolRow } from "./ToolRow";
import type { Kind } from "./params";

export function Actions({ agentId, session }: { agentId: string; session: Session }) {
  const actions = useAgentActions(session, agentId);
  const setMaster = useSetMasterSwitch(session, agentId);
  const [adding, setAdding] = useState<Kind | null>(null);

  if (actions.isPending) return <Skeleton rows={4} label="Loading actions…" />;
  if (actions.isError)
    return <ProblemNotice error={actions.error} onRetry={() => void actions.refetch()} />;

  const settings = actions.data;

  return (
    <section className="space-y-6">
      <SectionHeading icon={<PlugZap className="h-3.5 w-3.5" />}>
        Actions during the call
      </SectionHeading>
      <p className="text-sm text-ink-muted">
        Let this agent do things mid-call — send a WhatsApp, look something up, book a slot.
        Changes take effect on live calls the next time you publish the agent.
      </p>

      <ToggleSwitch
        label="Enable API actions"
        hint="Master switch for every integration on this agent."
        checked={settings.api_actions_enabled}
        disabled={setMaster.isPending}
        onChange={(next) => setMaster.mutate(next)}
        className="rounded-card border border-line bg-app p-4"
      />
      {setMaster.isError ? <ProblemNotice error={setMaster.error} /> : null}

      <Credentials session={session} />

      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-ink">Configured actions</h3>
        {settings.tools.length === 0 ? (
          <p className="text-sm text-ink-muted">No actions yet. Add one below.</p>
        ) : (
          <ul className="space-y-2">
            {settings.tools.map((tool) => (
              <ToolRow key={tool.id} tool={tool} agentId={agentId} session={session} />
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-ink">Add an action</h3>
        <div className="flex flex-wrap gap-2">
          {(["custom_api", "whatsapp", "calendar"] as Kind[]).map((kind) => (
            <button
              key={kind}
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => setAdding(kind)}
            >
              <Plus className="mr-1 inline h-3.5 w-3.5" />
              {ACTION_KIND_LABELS[kind]}
            </button>
          ))}
        </div>
        {settings.calendar_available ? null : (
          <p className={FIELD_HINT}>
            Google Calendar is not connected for your account yet — contact support to enable it.
          </p>
        )}
        {adding ? (
          <ActionForm
            kind={adding}
            agentId={agentId}
            session={session}
            onDone={() => setAdding(null)}
          />
        ) : null}
      </div>
    </section>
  );
}
