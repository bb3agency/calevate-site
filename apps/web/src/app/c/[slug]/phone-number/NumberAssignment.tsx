"use client";

/**
 * PUTTING A NUMBER ON AN AGENT — the binding every other gate needs.
 *
 * `phone_numbers.agent_id` is what makes a number the line an agent answers and the
 * caller ID a campaign dials from, so a number attached to nobody publishes a
 * receptionist whose phone never rings.
 *
 * ## The form opens on the binding the number HAS
 *
 * `NumberOut` carries `agent_id` and `direction`, and both seed the form. Opening on
 * "Nobody" instead made the panel's one button destructive: a Save pressed to change only
 * the direction, or pressed with nothing changed, posted `agent_id: null` and took the
 * number off its agent, so its line stopped being answered. An agent the list does not
 * offer (archived, say) is still named as the current choice rather than shown as
 * "Nobody", which would be the opposite of the truth.
 *
 * `AssignOut`'s counts are what the voice platform was TOLD, which is why the result
 * sentence is drawn from `bound`/`released`/`failed` rather than from the request: a
 * binding the platform refused must not be reported as one that worked.
 *
 * ## What it is FOR is asked here as well as at purchase
 *
 * The same three legs as the purchase: the segment words are the agent page's (one
 * question, one set of words), and the line under them is `direction.tsx`'s, which says
 * what the number itself does.
 */

import Link from "next/link";
import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatPhone,
} from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useCampaignNumbers } from "@/lib/api/campaigns";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  NOT_ACTIVATED_CODE,
  useAssignNumber,
  type CallDirection,
} from "@/lib/api/numberProvisioning";
import { useClientRealm } from "@/lib/api/session";
import { SegmentedControl } from "@/components/interior/segmented-control";

import { DIRECTIONS as AGENT_DIRECTIONS } from "../agents/DirectionChoice";
import { DIRECTIONS } from "./direction";

/** Detach: the recovery path from a wrong binding, and a real choice rather than a gap. */
const NOBODY = "";

/** Whether a refusal is the one the client can clear themselves. */
function notActivated(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  return (error as { code?: unknown }).code === NOT_ACTIVATED_CODE;
}

export function NumberAssignment({
  numberId,
  currentAgentId,
  currentDirection,
}: {
  numberId: string;
  /** `NumberOut.agent_id` — the agent the number is on now, or null for nobody. */
  currentAgentId: string | null;
  /** `NumberOut.direction` — what the number is recorded as being for. */
  currentDirection: CallDirection;
}) {
  const { session, href } = useClientRealm();
  const agents = useAgents(session);
  const assign = useAssignNumber(session);
  const assignFeedback = useActionFeedback(assign, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "choose which agent uses a number");

  const [agentId, setAgentId] = useState<string | null>(currentAgentId);
  const [direction, setDirection] = useState<CallDirection>(currentDirection);
  // The segmented control is a named region, and the screen lists every number with one of
  // these panels, so each needs its own name. The list is the screen's own cached read.
  const e164 = useCampaignNumbers(session).data?.find((number) => number.id === numberId)?.e164;
  const directionLabel = e164 ? `What it does, ${formatPhone(e164)}` : "What it does";

  if (agents.isLoading) return <Skeleton rows={2} label="Loading your agents" />;
  if (agents.error || !agents.data) {
    return <ProblemNotice error={agents.error ?? new Error("Your agents did not load.")} onRetry={() => agents.refetch()} />;
  }

  const result = assign.data;
  const unlisted =
    agentId !== null && !agents.data.some((agent) => agent.id === agentId) ? agentId : null;

  return (
    <section className="border-t border-line pt-4">
      <h3 className="text-body font-semibold text-ink">Put this number on an agent</h3>

      <div className="mt-3">
        <label className={FIELD_LABEL} htmlFor={`agent-${numberId}`}>
          The agent that uses it
        </label>
        <select
          id={`agent-${numberId}`}
          className={FIELD}
          value={agentId ?? NOBODY}
          disabled={!write.allowed}
          onChange={(event) =>
            setAgentId(event.target.value === NOBODY ? null : event.target.value)
          }
        >
          <option value={NOBODY}>Nobody (take this number off any agent)</option>
          {unlisted !== null && (
            <option value={unlisted}>The agent it is on now (not in your agent list)</option>
          )}
          {agents.data.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-3">
        <p className={FIELD_LABEL} aria-hidden>
          What it does
        </p>
        <SegmentedControl
          label={directionLabel}
          className="mt-1.5"
          value={direction}
          options={DIRECTIONS.map((option) => ({
            value: option.value,
            label: AGENT_DIRECTIONS.find((agent) => agent.value === option.value)?.label ?? option.label,
            disabled: !write.allowed,
          }))}
          onValueChange={(next) => setDirection(next as CallDirection)}
        />
        <p className={FIELD_HINT}>{DIRECTIONS.find((option) => option.value === direction)?.hint}</p>
      </div>

      <div className="mt-3">
        <RestrictionNote reason={write.reason} />
      </div>

      {assign.error && (
        <div className="mt-3 space-y-2">
          <ProblemNotice error={assign.error} />
          {/* The one refusal here a client can clear themselves: the number is bought and
              held, and verification is what releases it. */}
          {notActivated(assign.error) && (
            <Link
              href={href(`/c/${session.orgSlug}/verification`)}
              className={SECONDARY_BUTTON_SM}
            >
              Verify your business
            </Link>
          )}
        </div>
      )}

      {result && (
        <div className="mt-3">
          <NoticeBox tone={result.failed > 0 ? "stop" : "ok"}>
            {result.failed > 0 ? (
              <p>
                We could not connect this number to that agent, so it is not on an agent.
                Try again, and tell us if it keeps happening.
              </p>
            ) : result.agent_id === null ? (
              <p>Done. This number is on no agent now and will not be answered.</p>
            ) : (
              <p>Done. That agent now uses this number.</p>
            )}
          </NoticeBox>
        </div>
      )}

      <ActionButton
        variant="primary-sm"
        className="mt-3"
        // A 200 whose binding the voice platform refused is a failure to the owner, and the
        // notice above says so; the button must not tick beside it.
        status={assignFeedback.status === "success" && (result?.failed ?? 0) > 0 ? "error" : assignFeedback.status}
        disabled={!write.allowed}
        title={write.reason ?? undefined}
        onClick={() => assignFeedback.run({ numberId, agentId, direction })}
        pendingLabel="Saving…"
        successLabel="Saved"
      >
        Save
      </ActionButton>
    </section>
  );
}
