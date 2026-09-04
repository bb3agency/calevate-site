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

import type { ReactNode } from "react";
import { CircleAlert, Hourglass, Layers, Zap } from "lucide-react";

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
    <Disclosure
      title="How changes take effect"
      subtitle="What waits to be applied, and what is in force on the next call."
      icon={<Layers className="h-4 w-4" />}
    >
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
      {/* THE ONE THING FIRST (D-527). This block used to open with the server's precedence
          rule — three clauses of our vocabulary — and put the sentence a person actually
          needs underneath it. The order is now the other way round: the guarantee leads,
          and the precedence rule stays as the smaller line beneath it because SURFACES §2b
          asks for it to be STATED and it is the server's own words for it. */}
      <p className="text-sm font-medium text-ink">
        A change to what the agent SAYS waits until it is applied. Everything
        else is in force on the next call.
      </p>
      <p className="mt-1 text-xs text-ink-muted">
        {lanes.data.precedence_rule}
      </p>

      <div className="mt-5 grid gap-6 sm:grid-cols-2">
        {/* No hint under the first two headings any more: "Waits to be applied" and
            "Applies straight away" were each followed by a line restating them, on the
            screen whose whole complaint was how much there is to read. The third keeps its
            hint, because "Ask your account manager" does not say on its own what the
            column is or why a setting is in it. */}
        <LaneList
          icon={<Hourglass className="h-3.5 w-3.5" />}
          title="Waits to be applied"
          lanes={waits}
        />
        <LaneList
          icon={<Zap className="h-3.5 w-3.5" />}
          title="Applies straight away"
          lanes={immediate}
        />
        <LaneList
          icon={<CircleAlert className="h-3.5 w-3.5" />}
          title="Ask your account manager"
          hint="We cannot tell you when these take effect from here."
          lanes={unclassified}
        />
      </div>

      <p className="mt-5 text-xs text-ink-muted">
        Every call is capped at {formatCallCap(lanes.data.call_cap_default_s)}{" "}
        by default — settable between {formatCallCap(lanes.data.call_cap_min_s)}{" "}
        and {formatCallCap(lanes.data.call_cap_max_s)}, never removable.
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
  training: "Knowledge and training",
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
  icon,
  title,
  hint,
  lanes,
}: {
  icon: ReactNode;
  title: string;
  /** Absent where the heading already says it — see the call sites. */
  hint?: string;
  lanes: Lane[];
}) {
  if (lanes.length === 0) return null;
  return (
    <div>
      <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
          {icon}
        </span>
        {title}
      </h3>
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
