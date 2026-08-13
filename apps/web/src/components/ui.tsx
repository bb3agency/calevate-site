"use client";

/**
 * The small set of primitives every client screen is built from.
 *
 * Deliberately hand-rolled rather than pulled from shadcn/ui for M1: these are five
 * components, and the ones that matter (`ProblemNotice`, `StatusBadge`) encode OUR
 * rules — problem+json has `remediation` and `retryable` fields that a generic alert
 * component would throw away, and the lead status set is a fixed enum (D-21) that
 * should not be stringly-typed at every call site. shadcn lands with the design pass.
 */

import clsx from "clsx";
import type { ReactNode } from "react";

import { lookup } from "@/lib/lookup";

import { ApiProblem } from "@/lib/api/client";

/**
 * The card every panel on every screen is made of.
 *
 * Restyled to the dashboard design rather than joined by a second card component:
 * `rounded-card` (14px), a 1px `--line` border and a shadow so faint it reads as a
 * lift rather than a drop. Because the twenty-odd screens already built import THIS,
 * they inherit the new language without being touched — which is the whole reason the
 * design tokens went into `globals.css` instead of into the dashboard page.
 *
 * `bodyClassName` exists for the one shape the design needs and a fixed `p-4` cannot
 * give: a table that runs edge to edge under a padded header.
 */
export function Card({
  title,
  action,
  children,
  className,
  bodyClassName,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={clsx(
        "rounded-card border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.02)]",
        className,
      )}
    >
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-6 py-4">
          {title && <h2 className="text-[17px] font-semibold text-ink">{title}</h2>}
          {action}
        </header>
      )}
      <div className={bodyClassName ?? "p-6"}>{children}</div>
    </section>
  );
}

/**
 * One number, and what it is a number OF.
 *
 * `icon` is optional so the plain tiles on the older screens are unchanged; the
 * dashboard passes one and gets the medallion from the design.
 *
 * THERE IS NO `delta` PROP, and its absence is deliberate. The design shows a
 * "+18.4% vs Apr 28 – May 4" line under every figure, and the API cannot answer it:
 * nothing serves a previous-period comparison. A trend arrow is the most trusted
 * pixel on a dashboard — it is what an owner acts on — so a hardcoded one is worse
 * than none at all. `hint` carries what we can actually say, and the prop arrives
 * when the endpoint does.
 */
export function StatTile({
  label,
  value,
  hint,
  icon,
  tone = "soft",
}: {
  label: string;
  value: string | number | null | undefined;
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: "soft" | "strong";
}) {
  return (
    <div className="flex items-start gap-4 rounded-card border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
      {icon && (
        <div
          className={clsx(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
            tone === "strong" ? "bg-brand text-white" : "bg-brand-soft text-brand-strong",
          )}
        >
          {icon}
        </div>
      )}
      <div className="min-w-0">
        <p className="text-[13px] font-medium text-ink-muted">{label}</p>
        {/* `tabular-nums` so a polling number does not make the card twitch as digits
            change width (D-24: this screen refetches on an interval). */}
        <p className="mt-1 truncate text-2xl font-bold tracking-tight tabular-nums text-ink">
          {value ?? "—"}
        </p>
        {hint && <div className="mt-1 text-[11px] text-ink-muted">{hint}</div>}
      </div>
    </div>
  );
}

/**
 * A person's initials in a circle.
 *
 * Replaces the design's `api.dicebear.com` avatars. Three reasons, in the order they
 * would have hurt: it ships a request PER AVATAR to a third party carrying the user's
 * name in the query string, which is exactly the sort of quiet leak SEC-COMP §4 is
 * about; it puts the console's first paint behind a network the client's office may
 * not reach; and it renders nothing if that host is down. Initials need no network.
 */
export function Avatar({ name, className }: { name: string | null | undefined; className?: string }) {
  const initials = (name ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
  return (
    <span
      aria-hidden
      className={clsx(
        "flex shrink-0 items-center justify-center rounded-full bg-brand-soft text-[11px] font-bold text-brand-strong",
        className ?? "h-9 w-9",
      )}
    >
      {initials || "?"}
    </span>
  );
}

const LEAD_STATUS_STYLES: Record<string, string> = {
  new: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  contacted: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  interested: "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-300",
  hot: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  won: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  lost: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
};

const CALL_STATUS_STYLES: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  in_progress: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  queued: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  ringing: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  no_answer: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  busy: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  voicemail: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  failed: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
};

/**
 * The most-reached of the wire lookups: every leads table and every calls table.
 *
 * `LeadOut.status` is a generated union and `CallSummaryOut.status` is a bare `string`,
 * and the difference does not matter here — both are runtime strings the server chooses,
 * and a union is a claim this build makes, not one the server is bound by. `lookup`
 * rather than `styles[value]`, because a status naming an `Object.prototype` member
 * resolved to the `Object` FUNCTION, which `??` does not treat as missing: `clsx`
 * stringified it and the badge rendered `function Object() { [native code] }` as its
 * class list. Fails VISIBLE — neutral slate, and `value` is still printed, because a
 * status we have no colour for is exactly the one worth reading.
 */
export function StatusBadge({ value, kind = "lead" }: { value: string; kind?: "lead" | "call" }) {
  const styles = kind === "lead" ? LEAD_STATUS_STYLES : CALL_STATUS_STYLES;
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        lookup(styles, value) ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
      )}
    >
      {value.replace(/_/g, " ")}
    </span>
  );
}

/**
 * Renders an RFC-9457 problem the way its fields intend.
 *
 * The reason this exists instead of `alert(error.message)`: the API distinguishes a
 * compliance refusal ("this number is on the do-not-call list") from a transient
 * failure, and tells us which is which via `retryable` + `remediation`. Flattening
 * both into "something went wrong" would make the compliance gate look like a bug.
 */
export function ProblemNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const problem = error instanceof ApiProblem ? error : null;
  const title = problem?.message ?? "Something went wrong.";
  // Anything that is not an ApiProblem never reached the API — a dropped connection,
  // a DNS failure, a laptop that slept. The API's `retryable` cannot speak for those,
  // and they are the most retryable failures there are, so the button must not depend
  // on it: without this, a client on a train watches a screen with no way forward
  // except reloading the page.
  const canRetry = Boolean(onRetry) && (problem === null || problem.retryable);
  return (
    <div
      role="alert"
      className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200"
    >
      <p className="font-medium">{title}</p>
      {problem?.remediation && <p className="mt-1 text-rose-800 dark:text-rose-300">{problem.remediation}</p>}
      {problem === null && (
        <p className="mt-1 text-rose-800 dark:text-rose-300">
          We could not reach Calevate. Check your connection and try again.
        </p>
      )}
      {problem?.fields?.length ? (
        <ul className="mt-2 list-inside list-disc">
          {problem.fields.map((f) => (
            <li key={f.field}>
              <span className="font-medium">{f.field}</span>: {f.message}
            </li>
          ))}
        </ul>
      ) : null}
      {canRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-md bg-rose-600 px-2 py-1 text-xs font-medium text-white hover:bg-rose-700"
        >
          Try again
        </button>
      )}
      {problem?.traceId && (
        <p className="mt-2 font-mono text-[11px] text-rose-700 dark:text-rose-400">
          ref {problem.traceId}
        </p>
      )}
    </div>
  );
}

/**
 * Why the controls on this screen are disabled, said once at the top of it.
 *
 * The D-22 counterpart to `ProblemNotice`: that one renders a refusal we already
 * received, this one renders the refusal we can see coming. A control that explains
 * itself before the click beats a 403 after it — and it is deliberately quiet (slate,
 * not rose), because "you are looking at someone else's account read-only" is a normal
 * state of the world, not a fault.
 *
 * Renders nothing when there is nothing to say, so a caller can pass the reason
 * straight through while `/v1/me` is still in flight.
 */
export function RestrictionNote({ reason }: { reason: string | null }) {
  if (!reason) return null;
  return (
    <p className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink-muted">
      {reason}
    </p>
  );
}

/**
 * The four tones a compliance verdict box can carry, in one table.
 *
 * `ok` / `warn` / `stop` / `neutral` are the vocabulary the API already speaks about a
 * client's own state — cleared, lapsing, refused, nothing on file — so the colours live
 * here rather than being re-picked per screen. It started as a private constant on
 * `/verification`; `/campaign-review` needed the identical four, and two screens
 * describing the same four states in two colour tables is where the drift starts.
 *
 * A token map rather than a component: the verdict boxes differ in what they say and in
 * how many paragraphs they say it in, and only the palette is common.
 */
export type NoticeTone = "ok" | "warn" | "stop" | "neutral";

export const NOTICE_TONES: Record<NoticeTone, string> = {
  ok: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  warn: "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200",
  stop: "border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200",
  neutral:
    "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300",
};

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="py-10 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {hint && <p className="mt-1 text-xs text-ink-muted">{hint}</p>}
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 animate-pulse rounded bg-black/5 dark:bg-white/10" />
      ))}
    </div>
  );
}

/**
 * A one-of-N filter, as a pill.
 *
 * Extracted rather than copied a third time: the calls log and the leads table had
 * grown byte-similar copies of this, and the second copy is where a design language
 * starts to drift — one screen gets the new active colour and the other keeps the old
 * one, and nobody notices because neither is wrong on its own screen.
 *
 * `aria-pressed` rather than a `role="tab"`: these are toggles over one list, not
 * panels, and a screen reader should hear the state of the control rather than be told
 * to expect a tabpanel that does not exist.
 */
export function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={clsx(
        "rounded-full px-3 py-1.5 text-xs capitalize",
        active
          ? "bg-brand-strong font-semibold text-white"
          : "border border-line bg-surface font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5",
      )}
    >
      {label}
    </button>
  );
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** A count, grouped the way an Indian reader groups one (1,20,000 — not 120,000). */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-IN");
}

/**
 * Rupees, from the STRING the API sent.
 *
 * The money fields on `UsagePanelOut` are strings for a reason its docstring states:
 * they are `Decimal` all the way through billing (hard rule 7) and a JSON float cannot
 * hold a rupee amount exactly — `Number("10159.00")` is how ₹10,159.00 becomes
 * ₹10,158.999999999998 on a screen a client is checking against their own books.
 *
 * So this formats the DIGITS and never parses them: split on the decimal point, group
 * the integer part Indian-style (last three, then twos), keep exactly two decimals.
 * The value is never converted to a number at any point, which is the whole exercise.
 */
export function formatINR(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const negative = value.startsWith("-");
  const [whole = "0", fraction = ""] = value.replace(/^[-+]/, "").split(".");
  const head = whole.length > 3 ? whole.slice(0, -3) : "";
  const tail = whole.slice(-3);
  const grouped = head ? `${head.replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${tail}` : tail;
  const paise = `${fraction}00`.slice(0, 2);
  return `${negative ? "-" : ""}₹${grouped}.${paise}`;
}

/** Times are stored UTC and shown IST at the edge (CLAUDE.md conventions). */
export function formatIST(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
