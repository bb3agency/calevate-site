import { CircleAlert } from "lucide-react";

import { type CampaignRecurrence } from "@/lib/api/campaigns";

import { WEEKDAYS } from "./choices";

/**
 * WHEN THIS CAMPAIGN WILL DIAL, AND WHAT HAPPENS IF IT MAY NOT — the schedule and repeat
 * vocabulary.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6: extract by SUBJECT). Arming a schedule runs
 * no compliance gate; the gate runs when it FIRES, on every occurrence (D-79,
 * `campaigns/scheduling.py` decision 3) — so `FireTimeRefusal` is the sentence that keeps
 * an armed-but-doomed schedule from being discovered by silence. It is a compliance
 * statement and is never disclosed (UX-DOCTRINE §3/§8); it moved file, not wording.
 */
/**
 * An occurrence in the words a client can check against their own calendar.
 *
 * `formatIST` (ui.tsx) gives "14 Aug, 10:00", which is right everywhere else on this
 * console and NOT enough here: the one thing a repeat has to survive is the client
 * asking "is that this Tuesday?". So the weekday is spelled out — "Tuesday 14 Aug, 10:00
 * IST" — and only for schedule times. A local helper rather than a second export from
 * `ui.tsx`, because the weekday matters exactly where a repeat rule is read and nowhere
 * else on the console.
 */
export function formatOccurrence(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    weekday: "long",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "every Tuesday and Friday at 10:00" — the rule, read back as a sentence. */
export function describeRepeat(recurrence: CampaignRecurrence): string {
  const chosen = WEEKDAYS.filter((day) => recurrence.days.includes(day.value));
  if (chosen.length === WEEKDAYS.length) return `every day at ${recurrence.at}`;
  const names = chosen.map((day) => day.label);
  const listed =
    names.length <= 1
      ? (names[0] ?? "no day")
      : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  return `every ${listed} at ${recurrence.at}`;
}

/**
 * Why an occurrence did not run, in the client's words.
 *
 * `missed` is the only reason the server records today, and it is the one that most
 * needs explaining: a client who sees "we skipped Tuesday" and no reason assumes we
 * dropped their campaign. The truth — we would have dialled at the wrong time of day, so
 * we waited for the next slot — is both better and reassuring, and it is the promise
 * `campaigns/scheduling.py` decision 2 makes on their behalf.
 */
export const SKIP_COPY: Record<string, string> = {
  missed: [
    "We could not start it close enough to the time you picked, so we waited for the",
    "next one rather than calling people at a different time of day.",
  ].join(" "),
};

/**
 * **The fire-time refusal, said in advance** — what a schedule will do about the blockers
 * this campaign has RIGHT NOW.
 *
 * The two forms this appears in are deliberately reachable with blockers outstanding: the
 * server runs NO compliance gate when a schedule is armed, only when it FIRES
 * (`campaigns/scheduling.py` decision 3, D-79), so a client waiting on the registrar can
 * legitimately put next Tuesday on a campaign that would not launch today.
 *
 * The cost of that reachability is real, and this is the payment. A client CAN arm a start
 * on a campaign that would dial nobody, and a screen that let them do it in silence would
 * have swapped a confusing form for a dangerous one — a schedule that looks armed and
 * produces a quiet nothing on Tuesday morning. `when` is the difference between the two
 * moments that silence would fall in, and both need saying:
 *
 * - `arming` — a form the client is filling in. The point to make is that setting a time is
 *   allowed and is not a promise.
 * - `armed` — a start or repeat already on the campaign, before the tick has tried it even
 *   once. Without this the campaign says "Starts Monday, 10:00 IST" and nothing else until
 *   the first attempt fails, which is the discovery-by-silence this note exists to prevent.
 *   (Once an attempt HAS failed, the schedule carries `last_blocked` and the cards say so
 *   from the server's own record instead — a stronger statement, so this one stands down.)
 *
 * `kind` is the consequence, and the two genuinely differ — they are the server's, not a
 * turn of phrase:
 *
 * - a ONE-TIME start is retried for `GRACE` (24h) and then given up on: the schedule is
 *   cleared and the campaign returns to draft (`scheduling._expire`);
 * - an OCCURRENCE of a repeat is retried only inside `RECURRENCE_CATCHUP` (1h) and is then
 *   abandoned rather than fired into a different time of day — the repeat itself survives
 *   and the next run is checked afresh (`scheduling._skip_occurrence`, decision 2).
 *
 * Every call site guards on the launch check having ANSWERED and answered "not ready". A
 * warning that is always on screen is a warning nobody reads, and one derived from a
 * verdict we do not have is the §52 defect itself.
 */
export function FireTimeRefusal({
  kind,
  when,
}: {
  kind: "start" | "repeat";
  when: "arming" | "armed";
}) {
  return (
    <p className="flex gap-2.5 text-sm text-ink-muted">
      <CircleAlert
        aria-hidden
        className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
      />
      <span>
        As things stand{" "}
        {kind === "start"
          ? "this campaign would not start"
          : "the next run would not start"}
        .{" "}
        {when === "arming"
          ? "You can still set a time — the same check runs again at the moment it does, so anything you clear before then is enough. If the reasons above are still outstanding then, "
          : "The reasons are listed below. Clear them before the time comes and it goes ahead as planned; if they are still outstanding then, "}
        {kind === "start"
          ? "no calls go out, and after a day of trying the campaign goes back to draft."
          : "that run is skipped rather than dialled at a different time of day, and the repeat itself carries on."}
      </span>
    </p>
  );
}
