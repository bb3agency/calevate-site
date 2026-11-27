"use client";

/**
 * AN INBOUND LINE'S DAY (W4.1): what it did today in IST and who is still waiting for a call,
 * on the lines list and at the top of a line's page. Every number links to the calls behind
 * it: answered and missed open the call log on exactly those calls, and "want a call back"
 * opens the people still waiting, where the one button is.
 *
 * And the line's "Call back missed callers" switch (W4.2), which is the line's own
 * Follow-up: on, a caller the line missed is rung back once, inside calling hours, through
 * the same checks as every call (Do not call, hours, pacing). Its words are the state the
 * server read back, never what was last pressed.
 */

import Link from "next/link";
import { PhoneForwarded } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { PRIMARY_BUTTON_SM, ProblemNotice, Skeleton, ToggleSwitch, formatCount } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useLineCallBack,
  useSetLineCallBack,
  type LineCallBack,
  type LineToday,
} from "@/lib/api/inboundToday";
import { useClientRealm } from "@/lib/api/session";

/** The people a line still owes a call; `show` opens it on one kind. */
export function callersPath(slug: string, lineId: string, show?: "missed" | "asked"): string {
  return `/c/${slug}/inbound/${encodeURIComponent(lineId)}/callers${show ? `?show=${show}` : ""}`;
}

/** The call log on one line's calls of one IST day, test calls left out. */
function logPath(slug: string, lineId: string, day: string, status: "completed" | "missed"): string {
  const query = new URLSearchParams({ inbound_line_id: lineId, day, status, test_calls: "false" });
  return `/c/${slug}/calls?${query.toString()}`;
}

const COUNT_LINK =
  "relative z-raised rounded-sm font-medium text-ink underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand";

/** "Today: 4 answered · 2 want a call back · 1 missed", each part a link. */
export function TodayCounts({
  slug,
  lineId,
  day,
  today,
  failed = false,
}: {
  slug: string;
  lineId: string;
  day: string | undefined;
  today: LineToday | undefined;
  failed?: boolean;
}) {
  const { href } = useClientRealm();
  if (failed) return <p className="text-meta text-ink-muted">Today&apos;s calls did not load.</p>;
  if (!today || !day) return <p className="h-5 w-48 animate-pulse rounded bg-ink/[0.05]" aria-hidden />;
  if (today.answered + today.missed === 0) {
    return <p className="text-meta text-ink-muted">No calls yet today.</p>;
  }
  const parts = [
    { key: "answered", n: today.answered, words: "answered", to: logPath(slug, lineId, day, "completed") },
    { key: "call_back", n: today.call_back, words: "want a call back", to: callersPath(slug, lineId, "asked") },
    { key: "missed", n: today.missed, words: "missed", to: logPath(slug, lineId, day, "missed") },
  ];
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-meta text-ink-muted">
      <span>Today:</span>
      {parts.map((part, i) => (
        <span key={part.key} className="inline-flex items-baseline gap-2">
          {i > 0 && <span aria-hidden>·</span>}
          {part.n > 0 ? (
            <Link href={href(part.to)} className={`${COUNT_LINK} tabular-nums`}>
              {formatCount(part.n)} {part.words}
            </Link>
          ) : (
            <span className="tabular-nums">
              {formatCount(part.n)} {part.words}
            </span>
          )}
        </span>
      ))}
    </p>
  );
}

/** The one button a line gets when someone is waiting, and nothing when nobody is. */
export function CallBackButton({ slug, lineId, waiting }: { slug: string; lineId: string; waiting: number }) {
  const { href } = useClientRealm();
  if (waiting === 0) return null;
  return (
    <Link href={href(callersPath(slug, lineId))} className={`${PRIMARY_BUTTON_SM} relative z-raised`}>
      <PhoneForwarded aria-hidden className="h-4 w-4" />
      Call back {formatCount(waiting)}
    </Link>
  );
}

function switchWords(data: LineCallBack): string {
  switch (data.state) {
    case "on":
      return "On. Your agent rings them back once, in calling hours.";
    case "covered":
      return "On for every line, from your follow-ups.";
    case "cannot":
      return "None of your agents can place calls yet.";
    default:
      return "Off. Missed callers are not rung back.";
  }
}

export function MissedCallBackSwitch({ slug, lineId }: { slug: string; lineId: string }) {
  const { session, href } = useClientRealm();
  const read = useLineCallBack(session, lineId);
  const save = useSetLineCallBack(session, lineId);
  const write = useWriteAccess(session, "leads:dispatch", "change call-backs");
  useActionFeedback(save, {
    errorDisplay: "inline",
    successToast: (data) => (data.state === "on" ? "Missed callers get a call back" : "Missed callers are not rung back"),
  });
  if (read.isLoading) return <Skeleton rows={1} label="Reading whether missed callers are called back" />;
  if (!read.data) return <ProblemNotice error={read.error} onRetry={() => read.refetch()} />;
  const data = read.data;
  const fixed = data.state === "covered" || data.state === "cannot";
  return (
    <div className="space-y-2">
      <ToggleSwitch
        label="Call back missed callers"
        hint={switchWords(data)}
        checked={data.state === "on" || data.state === "covered"}
        disabled={!write.allowed || fixed || save.isPending}
        onChange={(on) => save.mutate(on)}
      />
      <p className="text-meta text-ink-muted">Never a number on your Do not call list.</p>
      {data.state === "covered" && data.covered_by && (
        <Link href={href(`/c/${slug}/follow-ups/${data.covered_by}`)} className={TEXT_ACTION_SM}>
          Open {data.covered_by_name || "the follow-up"}
        </Link>
      )}
      {data.state === "cannot" && (
        <Link href={href(`/c/${slug}/agents`)} className={TEXT_ACTION_SM}>
          See your agents
        </Link>
      )}
      {!write.allowed && write.reason && <p className="text-meta text-ink-muted">{write.reason}</p>}
      {save.error != null && <ProblemNotice error={save.error} />}
    </div>
  );
}

