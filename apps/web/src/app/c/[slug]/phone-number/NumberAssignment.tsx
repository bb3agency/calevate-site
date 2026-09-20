"use client";

/**
 * PUTTING A NUMBER ON AN AGENT — the binding every other gate needs.
 *
 * `phone_numbers.agent_id` is what makes a number the line an agent answers and the
 * caller ID a campaign dials from, so a number attached to nobody publishes a
 * receptionist whose phone never rings.
 *
 * ## This panel states what it DID, never what is currently set
 *
 * ⚠ `GET /v1/campaigns/numbers` (`campaigns/routes.py::NumberOut`) carries the number,
 * its series, its registration status and whether the platform can answer it — and NOT
 * the agent it is bound to. So there is nothing to read the current binding from, and the
 * honest response is a control that makes a change and reports the outcome, rather than a
 * select whose "Nobody" is a claim this console cannot support. §52's rule, one step
 * further out: an answer we do not have is not rendered as a state.
 *
 * `AssignOut`'s counts are what the voice platform was TOLD, which is why the result
 * sentence is drawn from `bound`/`released`/`failed` rather than from the request: a
 * binding the platform refused must not be reported as one that worked.
 *
 * ## What it is FOR is asked here as well as at purchase
 *
 * The same three legs, worded once in `direction.tsx` — including the sentence that
 * stops "call out from this number" reading as a freedom an ordinary number does not
 * have.
 */

import Link from "next/link";
import { useState } from "react";

import {
  FIELD,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  NOT_ACTIVATED_CODE,
  useAssignNumber,
  type CallDirection,
} from "@/lib/api/numberProvisioning";
import { useClientRealm } from "@/lib/api/session";

import { DIRECTIONS, OutboundRestriction } from "./direction";

/** Detach: the recovery path from a wrong binding, and a real choice rather than a gap. */
const NOBODY = "";

/** Whether a refusal is the one the client can clear themselves. */
function notActivated(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  return (error as { code?: unknown }).code === NOT_ACTIVATED_CODE;
}

export function NumberAssignment({
  numberId,
  series,
}: {
  numberId: string;
  /** DLT's number class, as the server derived it from the number's own prefix. */
  series: string;
}) {
  const { session, href } = useClientRealm();
  const agents = useAgents(session);
  const assign = useAssignNumber(session);
  const write = useWriteAccess(session, "org:manage", "choose which agent uses a number");

  const [agentId, setAgentId] = useState<string | null>(null);
  const [direction, setDirection] = useState<CallDirection>("inbound");

  if (agents.isLoading) return <Skeleton rows={2} label="Loading your agents" />;
  if (agents.error || !agents.data) {
    return <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />;
  }

  const result = assign.data;

  return (
    <div className="mt-3 rounded-card border border-line bg-app p-4">
      <p className="text-sm font-medium text-ink">Put this number on an agent</p>

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
          <option value={NOBODY}>Nobody — take this number off any agent</option>
          {agents.data.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
      </div>

      <fieldset className="mt-3" disabled={!write.allowed}>
        <legend className={FIELD_LABEL}>What it is for</legend>
        <div className="mt-2 space-y-2">
          {DIRECTIONS.map((option) => (
            <label key={option.value} className="flex items-start gap-2 text-sm text-ink">
              <input
                type="radio"
                className="mt-1"
                name={`direction-${numberId}`}
                value={option.value}
                checked={direction === option.value}
                onChange={() => setDirection(option.value)}
              />
              <span>
                {option.label}
                <span className="block text-xs text-ink-muted">{option.hint}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="mt-3">
        <OutboundRestriction direction={direction} series={series} />
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
                The voice platform did not accept that, so this number is not on an agent.
                Try again, and tell us if it keeps happening.
              </p>
            ) : result.agent_id === null ? (
              <p>Done — this number is no longer on any agent and will not be answered.</p>
            ) : (
              <p>Done — that agent now uses this number.</p>
            )}
          </NoticeBox>
        </div>
      )}

      <button
        type="button"
        className={`mt-3 ${PRIMARY_BUTTON_SM}`}
        disabled={!write.allowed || assign.isPending}
        title={write.reason ?? undefined}
        onClick={() => assign.mutate({ numberId, agentId, direction })}
      >
        {assign.isPending ? "Saving…" : "Save"}
      </button>
    </div>
  );
}
