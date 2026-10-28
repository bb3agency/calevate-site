"use client";

/**
 * WHICH CHANGES WAIT AND WHICH DO NOT — reference material, disclosed.
 *
 * Split out of the roster route (UX-DOCTRINE §6) and moved behind a `Disclosure` (§3): it
 * is a property of the PLATFORM rather than of any agent, it is read once and understood,
 * and it was the largest block on a screen whose one question is "which of my agents is
 * working". Frequency low, consequence low-if-missed (the two-speed guarantee is restated
 * where it bites, on the agent's own screen and in the builder) — so it discloses.
 *
 * Every word of it comes from `GET /v1/agents/lanes`: the sentence, the reason under each
 * row, and which lane a field is on. The server owns that wording because the server
 * enforces the split, and a screen that paraphrased it is precisely how "voice applies
 * immediately" turns into a support ticket (the API module says so in those words). The
 * only thing decided here is the LABEL — `max_call_duration_s` is our column name, not a
 * sentence to show a clinic owner.
 */

import {
  Disclosure,
  ProblemNotice,
  Skeleton,
  formatCallCap,
} from "@/components/ui";
import { humanise } from "@/lib/agentState";
import type { Session } from "@/lib/api/client";
import { useLanes, type Lane } from "@/lib/api/publishing";
import { lookup } from "@/lib/lookup";

export function HowChangesTakeEffect({ session }: { session: Session }) {
  const lanes = useLanes(session);

  return (
    <Disclosure title="When changes reach callers">
      <LaneBody lanes={lanes} />
    </Disclosure>
  );
}

/** The body, so the §52 branches are one function and the disclosure shell is another. */
function LaneBody({ lanes }: { lanes: ReturnType<typeof useLanes> }) {
  if (lanes.error) {
    return (
      <ProblemNotice error={lanes.error} onRetry={() => void lanes.refetch()} />
    );
  }
  if (!lanes.data) return <Skeleton rows={4} />;

  /**
   * Three buckets, not two. `lane` is a bare `string` on the wire and the server's `Lane`
   * literal has two members TODAY; a split of `staged` versus everything-else would
   * announce a third lane shipped by the API as "applies straight away, nothing to
   * approve" — a promise about a live phone line, made about a value this build has never
   * seen. Unknown fails VISIBLE and claims nothing.
   */
  const waits = lanes.data.lanes.filter((lane) => lane.lane === "staged");
  const immediate = lanes.data.lanes.filter((lane) => lane.lane === "live");
  const unclassified = lanes.data.lanes.filter(
    (lane) => lane.lane !== "staged" && lane.lane !== "live",
  );

  return (
    <>
      {/* THE ONE THING FIRST (D-527): the guarantee leads, as two short lines, and the
          server's precedence rule stays beneath it because SURFACES §2b asks for it to be
          STATED and it is the server's own words for it. */}
      <ul className="space-y-1 text-body font-medium text-ink">
        <li>Script changes: only once you put them live.</li>
        <li>Everything else: from the next call.</li>
      </ul>
      <p className="mt-1 text-meta text-ink-muted">
        {lanes.data.precedence_rule}
      </p>

      <div className="mt-5 grid grid-cols-1 gap-6 sm:grid-cols-2">
        {/* No hint under the first two headings any more: "Waits to be applied" and
            "Applies straight away" were each followed by a line restating them, on the
            screen whose whole complaint was how much there is to read. The third keeps its
            hint, because "Ask us" does not say on its own what the
            column is or why a setting is in it. */}
        <LaneList
          title="Waits to be applied"
          lanes={waits}
        />
        <LaneList
          title="Applies straight away"
          lanes={immediate}
        />
        <LaneList
          title="Ask us"
          hint="We can't tell when these apply."
          lanes={unclassified}
        />
      </div>

      <p className="mt-5 text-meta text-ink-muted">
        Call limit: {formatCallCap(lanes.data.call_cap_default_s)} by default.
        {" "}Set {formatCallCap(lanes.data.call_cap_min_s)} to{" "}
        {formatCallCap(lanes.data.call_cap_max_s)}. Always on.
      </p>
    </>
  );
}

/** Our word for one of the server's field names. Unknown fields degrade to the name
 *  itself rather than disappearing — a lane the client cannot see is worse than an ugly
 *  label, and a new lane ships from the API without a frontend release. */
const FIELD_LABELS: Record<string, string> = {
  script: "What the agent says",
  max_call_duration_s: "Longest a call may run",
  extraction_fields: "What it writes down",
  training: "What it knows and training",
  voice: "Its voice",
  /* D-163's two rows shipped in `LANES` without a label here, so they rendered as
     "ai disclosure enabled" and "recording notice enabled" — our column names, in a list a
     clinic owner reads. The `why` beneath each is the server's and is NOT summarised here:
     both sentences end with the guarantee that the answer a caller gets when they ask
     outright is always the truth and cannot be switched off, and that is the one wording
     on this screen a paraphrase must never touch (hard rule 5). */
  ai_disclosure_enabled: "Saying it is an AI at the start",
  recording_notice_enabled: "Saying the call is recorded at the start",
};

function LaneList({
  title,
  hint,
  lanes,
}: {
  title: string;
  /** Absent where the heading already says it — see the call sites. */
  hint?: string;
  lanes: Lane[];
}) {
  if (lanes.length === 0) return null;
  return (
    <div>
      <h3 className="text-body font-semibold text-ink">{title}</h3>
      {hint && <p className="mt-1 text-xs text-ink-muted">{hint}</p>}
      <ul className="mt-3 space-y-3">
        {lanes.map((lane) => (
          <li key={lane.field}>
            <p className="text-sm font-medium text-ink">
              {/* Fails VISIBLE: an unnamed lane degrades to its own field name rather than
                  vanishing. `lookup` is what makes the `??` reachable — a bare index on a
                  prototype key returns a function, which is not nullish (lib/lookup.ts). */}
              {lookup(FIELD_LABELS, lane.field) ?? humanise(lane.field)}
            </p>
            <p className="text-xs text-ink-muted">{lane.why}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
