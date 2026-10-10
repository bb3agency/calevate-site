"use client";

import { FIELD_INLINE } from "@/components/ui";

/**
 * WHICH AGENT RINGS A LEAD FROM THIS TABLE. The agent decides the script, the voice and
 * the disclosure line, so the choice is on screen whenever there is one. The checks
 * sentence stays visible beside it: it is what every call from this table is subject to.
 * When the reads behind it failed, the sentence that says so stands in its place.
 */
export function DialerPicker({
  unavailable,
  canCall,
  dialers,
  selectedAgentId,
  onSelect,
}: {
  unavailable: string | null;
  canCall: boolean;
  dialers: { id: string; name: string }[] | undefined;
  selectedAgentId: string;
  onSelect: (agentId: string) => void;
}) {
  if (unavailable !== null) return <p className="text-meta text-ink-muted">{unavailable}</p>;
  if (!canCall) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-meta text-ink-muted">
      <span>Calls from this table are placed by</span>
      {dialers !== undefined && dialers.length > 1 ? (
        <select
          value={selectedAgentId}
          onChange={(e) => onSelect(e.target.value)}
          aria-label="Agent that places calls from this table"
          className={FIELD_INLINE}
        >
          {dialers.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
      ) : (
        <span className="font-semibold text-ink">{dialers?.[0]?.name}</span>
      )}
      <span>
        · every call still goes through the do-not-call, calling-hours and consent checks, and
        can be refused.
      </span>
    </div>
  );
}
