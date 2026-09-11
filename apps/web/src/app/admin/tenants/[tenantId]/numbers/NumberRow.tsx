"use client";

/**
 * ONE PHONE NUMBER, AND THE THREE FACTS THAT DECIDE WHETHER IT RINGS ANYTHING.
 *
 * Primary job: *say who answers this number, and let an operator change it.*
 *
 * The row exists as its own module because it carries the whole of D-576. Until it
 * shipped, `phone_numbers.agent_id` had exactly one writer and it was the INSERT — no
 * screen, no route and no service ever moved it afterwards — so every number on this
 * platform was attached to nobody while every console row looked complete. The publish of
 * the client's receptionist reported success and the phone did not ring.
 *
 * Two states are therefore printed as the loudest thing on the row, in this order:
 *
 * 1. **Nobody answers it.** Foreground, never disclosed (UX §3: high consequence never
 *    discloses), with the picker that fixes it on the same row rather than behind a menu.
 * 2. **The voice platform has no handle for it** (`engine_linked`), which is D-537's half
 *    of the same sentence: an agent attached to such a number still cannot answer it.
 *
 * The agent picker is a native `<select>` inside its own `<label>` — implicit association,
 * because two rows editing two records on one screen collide on any id scheme (UX §8.1).
 */

import { useState } from "react";
import { PhoneOff } from "lucide-react";

import {
  FIELD,
  FIELD_LABEL,
  ProblemNotice,
  SECONDARY_BUTTON,
} from "@/components/ui";
import type { components } from "@/lib/api/schema";
import {
  useSetNumberAgent,
  useSetNumberEngineRef,
  type TenantNumberCost,
} from "@/lib/api/numbers";

type Agent = components["schemas"]["AgentOut"];

/** No agent, spelled as a wire value the `<select>` can hold. Empty string is the one
 *  option value a native select renders without inventing a sentinel id. */
const DETACHED = "";

export function NumberRow({
  number,
  tenantId,
  agents,
  agentsFailed,
  canWrite,
  onRelease,
}: {
  number: TenantNumberCost;
  tenantId: string;
  /** The tenant's agents, or undefined while we have no answer — never an empty array
   *  standing in for one (`tests/surfaceStatesGuard.test.ts`). */
  agents: Agent[] | undefined;
  agentsFailed: boolean;
  canWrite: boolean;
  onRelease: () => void;
}) {
  const attach = useSetNumberAgent(tenantId);
  const link = useSetNumberEngineRef(tenantId);
  const [ref, setRef] = useState("");

  // Only an agent that ANSWERS incoming calls can hold a number: the server refuses the
  // rest by name (`agent_does_not_answer_inbound`), and offering them here would be a
  // picker whose choices are mostly refusals. Deleted agents are excluded for the same
  // reason — archiving RELEASES an agent's numbers on purpose.
  const answering = agents?.filter(
    (agent) => agent.direction !== "outbound" && agent.status !== "archived",
  );

  return (
    <li className="space-y-2 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-ink">{number.e164}</span>
        <span className="rounded bg-brand-soft px-1.5 py-0.5 text-xs font-medium text-brand-strong">
          {number.series}
        </span>
        <span className="text-xs text-ink-muted">
          {number.engine_owned ? "we bought it" : "the client's own connection"}
        </span>
        {number.engine_owned && number.monthly_rental_usd && (
          <span className="text-xs text-ink-muted">${number.monthly_rental_usd} / month</span>
        )}
        {number.released && (
          <span className="text-xs text-ink-muted">released — no longer charged</span>
        )}
        {number.engine_owned && !number.released && canWrite && (
          <span className="ml-auto">
            <button type="button" className={SECONDARY_BUTTON} onClick={onRelease}>
              <PhoneOff className="mr-1.5 inline h-3.5 w-3.5" />
              Release
            </button>
          </span>
        )}
      </div>

      {!number.released && (
        <div className="space-y-2 rounded-card border border-line bg-surface-muted p-2">
          {/* THE SENTENCE THAT WAS MISSING FROM EVERY SCREEN. It is a fact, not a
              warning tone, and it is stated before the control that changes it. */}
          <p className="text-xs text-ink-muted">
            {number.agent_name
              ? `Answered by ${number.agent_name}.`
              : "No agent answers this number. A call to it reaches nobody — publishing an agent will report success and this phone will not ring."}
          </p>
          {attach.error && <ProblemNotice error={attach.error} />}
          {agentsFailed ? (
            <p className="text-xs text-ink-muted">
              We could not read this client&apos;s agents, so the choice cannot be offered
              right now. Reload the page to try again.
            </p>
          ) : answering === undefined ? (
            <p className="text-xs text-ink-muted">Reading this client&apos;s agents…</p>
          ) : (
            <label className="flex flex-wrap items-end gap-2">
              <span className="flex flex-col gap-1">
                <span className={FIELD_LABEL}>Answered by</span>
                <select
                  className={FIELD}
                  value={number.agent_id ?? DETACHED}
                  disabled={!canWrite || attach.isPending}
                  onChange={(ev) =>
                    attach.mutate({
                      numberId: number.id,
                      agentId: ev.target.value === DETACHED ? null : ev.target.value,
                    })
                  }
                >
                  <option value={DETACHED}>Nobody — this number does not ring</option>
                  {answering.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                      {agent.status === "live" ? "" : ` (${agent.status})`}
                    </option>
                  ))}
                </select>
              </span>
              {attach.isPending && <span className="text-xs text-ink-muted">Saving…</span>}
            </label>
          )}
          {/* The server's own counts, never a cheerier sentence composed here: "we told
              the platform and it refused" and "the platform now answers" are different
              outcomes and an operator has to be able to tell them apart. */}
          {attach.data && (
            <p className="text-xs text-ink-muted">
              {attach.data.failed > 0
                ? "Saved, but the voice platform refused the routing — this number is not answering yet."
                : attach.data.bound > 0
                  ? "Saved, and the voice platform now answers this number with that agent."
                  : attach.data.released > 0
                    ? "Saved, and the voice platform no longer answers this number."
                    : "Saved. It will start answering when that agent is published."}
            </p>
          )}
        </div>
      )}

      {!number.engine_linked && !number.released && (
        <div className="space-y-2 rounded-card border border-line bg-surface-muted p-2">
          <p className="text-xs text-ink-muted">
            The voice platform has no handle for this number, so no agent can answer it —
            publishing one will report success and the phone will not ring. Paste the
            identifier from the voice platform&apos;s own number list.
          </p>
          {link.error && <ProblemNotice error={link.error} />}
          <div className="flex flex-wrap gap-2">
            <input
              aria-label={`Voice platform identifier for ${number.e164}`}
              className={`flex-1 font-mono ${FIELD}`}
              value={ref}
              disabled={!canWrite}
              onChange={(ev) => setRef(ev.target.value.trim())}
              placeholder="3c90c3cc0d444b5088888dd25736052a"
            />
            <button
              type="button"
              className={SECONDARY_BUTTON}
              disabled={!canWrite || !ref || link.isPending}
              onClick={() => link.mutate({ numberId: number.id, ref })}
            >
              {link.isPending ? "Linking…" : "Link and route"}
            </button>
          </div>
          {link.data && (
            <p className="text-xs text-ink-muted">
              {link.data.failed > 0
                ? "Recorded, but the voice platform refused the routing — the number is not answering yet."
                : link.data.bound > 0
                  ? "Recorded, and the agent is now set to answer it."
                  : "Recorded. It will start answering when the agent is published."}
            </p>
          )}
        </div>
      )}
    </li>
  );
}
