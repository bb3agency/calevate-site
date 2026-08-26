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
import { ChevronDown } from "lucide-react";
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
      {/* `flex-wrap`: the header is a title beside an action, and on a 320px screen the
          pair does not fit on one line — unwrapped, the action was what got squeezed. */}
      {(title || action) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-4 sm:px-6">
          {title && (
            <h2 className="text-[17px] font-semibold text-ink">{title}</h2>
          )}
          {action}
        </header>
      )}
      {/* 16px of padding on a phone, 24px from `sm` up. At 320px the old flat `p-6` spent
          48px of a 288px content strip — a sixth of the screen — on whitespace, and it is
          what pushed `/admin/tenants/[tenantId]`'s inner grid past the viewport (its
          single column's min-content is 288px and the padded box left it 238px). */}
      <div className={bodyClassName ?? "p-4 sm:p-6"}>{children}</div>
    </section>
  );
}

/**
 * The label over a block INSIDE a card, with the medallion the design puts on a marker.
 *
 * Hoisted out of `c/[slug]/agents/panels.tsx`, which had written "it belongs in
 * `components/ui.tsx` the moment a screen outside `/agents` wants one" — and had already
 * been imported across the route boundary by `agents/Actions.tsx` in the meantime, which
 * is the same signal one file later. UX-DOCTRINE §7: a primitive is added here, never
 * duplicated per route.
 *
 * `h3` and not a prop, deliberately. This marks a block within a `Card`, whose title is
 * the `h2` — so the level is a property of where the primitive is allowed to be used, not
 * a decision each call site re-takes. WCAG 2.4.6 Headings and Labels is about headings
 * being descriptive; 1.3.1 Info and Relationships is about the structure being real
 * rather than a font size, which is what makes this an `h3` and not a styled `<span>`
 * (w3.org/WAI/WCAG22/Understanding/info-and-relationships, read 25 Aug 2026).
 */
export function SectionHeading({
  icon,
  children,
}: {
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
        {icon}
      </span>
      {children}
    </h3>
  );
}

/**
 * One labelled fact. `dt`/`dd` because that is exactly what these are.
 *
 * The GOV.UK Design System's Summary list makes the same call and states the constraint
 * this component is held to: the summary list "uses the description list (`<dl>`) HTML
 * element, so only use it to present information that has a key and at least one value",
 * and not for tabular data or a plain list
 * (github.com/alphagov/govuk-design-system `src/components/summary-list/index.md`, read
 * 25 Aug 2026). Every caller here pairs one key with one value, so the element is the
 * honest one — and a `<dl>` is what tells a screen reader the pairing exists at all.
 *
 * Hoisted from `agents/panels.tsx` with `SectionHeading`, for the same reason.
 */
export function Fact({
  label,
  hint,
  icon,
  children,
}: {
  label: string;
  hint?: string;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        {icon && (
          <span aria-hidden className="shrink-0 text-brand">
            {icon}
          </span>
        )}
        {label}
      </dt>
      <dd className="mt-1 text-sm font-semibold text-ink">{children}</dd>
      {hint && <dd className="mt-0.5 text-xs text-ink-muted">{hint}</dd>}
    </div>
  );
}

/**
 * A switch, and the sentence that says what it moves.
 *
 * ## Why this is one component and not six copies of a class string
 *
 * The identical 400-character `peer-checked:` expression was written out three times in
 * this codebase — the two opening-notice switches, every extraction variable's "Required",
 * and the Actions master switch — and the copies had already diverged: two carried
 * `peer-disabled:opacity-50` and the third did not, so a switch mid-request looked live.
 * "One way per problem, and migrate rather than accumulate" (CLAUDE.md); all three callers
 * moved onto this in the same change.
 *
 * ## Why a native checkbox with `role="switch"` and not a styled `<div>`
 *
 * It is keyboard-operable with no JS, it announces its own state, and it is reachable by
 * the a11y sweep. The painted switch is drawn entirely from the input's own `peer` state,
 * so what is on screen and what is checked cannot disagree. The label WRAPS the input
 * (implicit association) rather than carrying an `id`: two editors of two agents on one
 * screen would collide on any id scheme, and the wrapping label is what keeps the axe
 * sweep green without one.
 *
 * `note` is rendered under the switch and is where a caller says what OFF does not do —
 * the sentence that turns a setting into an honest one rather than a trap.
 */
export function ToggleSwitch({
  label,
  hint,
  checked,
  disabled,
  onChange,
  children,
  className,
}: {
  label: ReactNode;
  hint?: ReactNode;
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  /** Anything shown under the control — a quoted sentence, a warning about OFF. */
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label className="flex cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          role="switch"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span aria-hidden className={SWITCH_TRACK} />
        <span className="min-w-0">
          <span className="block text-sm font-medium text-ink">{label}</span>
          {hint && <span className="block text-xs text-ink-muted">{hint}</span>}
        </span>
      </label>
      {children}
    </div>
  );
}

/**
 * The painted track and knob. A constant rather than inline so the one place it is
 * written is beside the component that owns it — and so a caller that genuinely needs a
 * bare switch (no label block) still gets the same pixels rather than a fourth copy.
 */
const SWITCH_TRACK =
  "relative mt-0.5 h-5 w-9 shrink-0 rounded-full border border-line bg-surface transition-colors peer-checked:border-brand peer-checked:bg-brand peer-disabled:opacity-50 peer-focus-visible:ring-2 peer-focus-visible:ring-brand peer-focus-visible:ring-offset-2 after:absolute after:left-0.5 after:top-0.5 after:h-3.5 after:w-3.5 after:rounded-full after:bg-ink-faint after:transition-transform peer-checked:after:translate-x-4 peer-checked:after:bg-white";

/**
 * A section a reader opens when they want it — the console's ONE disclosure mechanism.
 *
 * ## Why native `<details>` and not a built accordion
 *
 * It is keyboard-operable, it announces its expanded state, it survives a JavaScript
 * failure open-able, and it needs no focus management of our own. The marketing FAQ, the
 * leads column chooser, the admin lifecycle screen and the data-rights screen had each
 * already reached for `<details>` independently; this is that shape hoisted so the fifth
 * caller does not restyle it. (`components/marketing/faq.tsx` argues the same case.)
 *
 * ## When a caller may use it — this is a rule, not a taste
 *
 * The GOV.UK Design System is explicit and this component is held to it: "Do not use the
 * details component to hide information that the majority of your users will need", and
 * its own research records "evidence that some users avoid clicking the link to show more
 * details" (github.com/alphagov/govuk-design-system `src/components/details/index.md`,
 * read 25 Aug 2026). So a disclosure is for the rare and the reference — never for a
 * compliance obligation, never for the screen's primary job, and never for something a
 * first-time owner has to find. UX-DOCTRINE §3 carries the decision test.
 *
 * `summary` is the whole control, so it carries `touch:min-h-11` for SC 2.5.8's target
 * size; `subtitle` lets the closed state say what is inside without the reader opening it,
 * which is the "information scent" that makes a disclosure findable at all.
 */
export function Disclosure({
  title,
  subtitle,
  icon,
  defaultOpen = false,
  children,
  className,
}: {
  title: string;
  subtitle?: ReactNode;
  icon?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <details
      open={defaultOpen}
      className={clsx(
        "group rounded-card border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.02)]",
        className,
      )}
    >
      {/* The title is a REAL `h2` inside the `summary`, which the HTML spec allows and
          which is what GOV.UK's accordion does with its section headings. It costs nothing
          visually and it is the difference between a disclosed panel a screen-reader user
          can jump to from the heading list and one they can only find by tabbing. WCAG 2.2
          1.3.1 / 2.4.6 — the level is fixed at 2 for `Disclosure`'s reason above `Card`:
          a disclosed panel is a peer of a card, never nested inside one. */}
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-4 touch:min-h-11 sm:px-6 [&::-webkit-details-marker]:hidden">
        {icon && (
          <span
            aria-hidden
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong"
          >
            {icon}
          </span>
        )}
        <span className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
          {subtitle && (
            <span className="block text-xs text-ink-muted">{subtitle}</span>
          )}
        </span>
        {/* The affordance, in words as well as a chevron: an icon alone is what GOV.UK's
            research says people fail to notice. `group-open:` swaps the pair. */}
        <span className="shrink-0 text-xs font-medium text-brand-strong">
          <span className="group-open:hidden">Show</span>
          <span className="hidden group-open:inline">Hide</span>
        </span>
        <ChevronDown
          aria-hidden
          className="h-4 w-4 shrink-0 text-ink-faint transition-transform group-open:rotate-180"
        />
      </summary>
      <div className="border-t border-line p-4 sm:p-6">{children}</div>
    </details>
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
            tone === "strong"
              ? "bg-brand-strong text-white"
              : "bg-brand-soft text-brand-strong",
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
export function Avatar({
  name,
  className,
}: {
  name: string | null | undefined;
  className?: string;
}) {
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
  interested:
    "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-300",
  hot: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  won: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  lost: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
};

const CALL_STATUS_STYLES: Record<string, string> = {
  completed:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  in_progress: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  queued: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  ringing: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  no_answer:
    "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  busy: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  voicemail:
    "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
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
export function StatusBadge({
  value,
  kind = "lead",
}: {
  value: string;
  kind?: "lead" | "call";
}) {
  const styles = kind === "lead" ? LEAD_STATUS_STYLES : CALL_STATUS_STYLES;
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        lookup(styles, value) ??
          "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
      )}
    >
      {value.replace(/_/g, " ")}
    </span>
  );
}

/**
 * A fixed-width value — a key's last four, an ID, a version, a code, a phone number —
 * anything a reader takes in character by character. Renders in `font-mono`, which is
 * JetBrains Mono (globals.css) where 0/O and 1/l/I are distinct, so a value is never
 * misread because an O looked like a 0 on one screen and not the next. A component rather
 * than a bare `<span className="font-mono">` so that choice is made in one place across
 * both realms and the marketing site.
 */
export function MonoValue({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <span className={clsx("font-mono", className)}>{children}</span>;
}

/**
 * A technical or legal term kept verbatim and explained in place.
 *
 * Plain-language guidance (GOV.UK) allows an unavoidable technical term when it is
 * glossed where it is used — this is that mechanism, and the ONLY sanctioned way to put a
 * compliance term (DLT, PE, TM, DND, DPDP, the 140/160 number series) on screen.
 *
 * ## Why the gloss is a styled box, not the native `title`
 *
 * The term shows its meaning in a small box on HOVER, on keyboard FOCUS, and on TAP — the
 * three input modes a `title` tooltip fails: `title` is mouse-only, delayed, unstyled, and
 * shows nothing on a touch screen. The box is a pure-CSS `::after` pseudo-element, so it
 * needs no positioning JS; the `<abbr>` is `tabIndex={0}` so a keyboard user reaches it and
 * a touch user taps it into focus.
 *
 * ## Why the gloss lives in `data-gloss`, NOT as a child text node
 *
 * The box is drawn by `::after { content: attr(data-gloss) }`, so the gloss is a CSS
 * pseudo-element — NOT a DOM text node. That is deliberate and load-bearing: a hidden child
 * `<span>{children}</span>` would still be in the DOM, and because tests run under jsdom
 * (which applies no Tailwind CSS, so `hidden` does not hide) every `getByText`/`textContent`
 * assertion on a screen that uses a term would suddenly also see the gloss. Keeping the gloss
 * in an attribute means the rendered TEXT is exactly the term, on screen and in tests.
 *
 * The gloss is ALSO the accessible name (`aria-label`) so a screen reader announces it, and a
 * `::after` pseudo-element is not part of the accessibility tree — so the meaning is not read
 * twice. No native `title`: it would double the visible tooltip under the styled one.
 *
 *   <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss>
 */
export function TermGloss({
  term,
  children,
}: {
  term: string;
  children: string;
}) {
  // tabIndex on a non-interactive <abbr> so the box reveals on keyboard FOCUS and on TAP,
  // not mouse-hover alone (the WAI-ARIA tooltip pattern needs a focusable trigger). <abbr>
  // is kept rather than <button> because TermGloss renders inside <label>/<legend>, where a
  // nested interactive control would hijack the label.
  return (
    <abbr
      aria-label={`${term}: ${children}`}
      data-gloss={children}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      className={clsx(
        "relative cursor-help rounded-sm underline decoration-dotted underline-offset-2",
        "outline-none focus-visible:ring-2 focus-visible:ring-brand-strong",
        // The gloss box, drawn from `data-gloss` (see docstring). `normal-case`/`font-normal`
        // so it reads plainly even when the term sits inside an uppercase or bold label;
        // `whitespace-normal` + a max width so a long gloss wraps instead of running off-screen.
        "after:pointer-events-none after:absolute after:bottom-full after:left-0 after:z-50 after:mb-1",
        "after:hidden after:w-max after:max-w-[16rem] after:whitespace-normal after:rounded-md",
        "after:border after:border-line after:bg-surface after:px-2 after:py-1 after:text-left",
        "after:text-xs after:font-normal after:normal-case after:not-italic after:leading-snug",
        "after:text-ink after:shadow-lg after:[content:attr(data-gloss)]",
        "hover:after:block focus:after:block",
      )}
    >
      {term}
    </abbr>
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
export function ProblemNotice({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
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
      {problem?.remediation && (
        <p className="mt-1 text-rose-800 dark:text-rose-300">
          {problem.remediation}
        </p>
      )}
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
        <p className="mt-2 text-[11px] text-rose-700 dark:text-rose-400">
          Support reference:{" "}
          <span className="font-mono">{problem.traceId}</span>
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

/*
 * FORM AND BUTTON CLASSES, once.
 *
 * These were written in `/c/[slug]/campaigns` when it was the console's only real form,
 * with a note saying they belonged here "the moment a second screen needs them". Four
 * more arrived — signup, the onboarding wizard, the ops controls and the compliance
 * screens — and each copied them VERBATIM, which is the good outcome of that note and
 * also the last moment to act on it: five identical string literals stay identical only
 * until someone improves one.
 *
 * Exported as class strings rather than as `<Input>` / `<Button>` components because
 * the call sites differ in everything except appearance — `<input>`, `<select>`,
 * `<textarea>`, `<button>`, `<label>`, and one `<a>` styled as a button. A component
 * would have to re-expose every native prop of five elements to earn its place.
 * shadcn/ui, which `ui.tsx`'s own header says arrives with the design pass, is the
 * eventual answer; this is the honest interim and it costs one import.
 */
/*
 * `touch:min-h-11` on every control below, and the reason it is here rather than at the
 * call sites: 44px is the Apple HIG / WCAG 2.5.5 (AAA) target, WCAG 2.2 AA's 2.5.8 asks
 * 24px, and the measured console sat at 26–36px — passing AA, failing the finger. The
 * `touch` variant (globals.css) keys on `pointer: coarse`, so the desktop console's
 * density is untouched; only a device actually driven by a finger gets the taller box.
 *
 * `min-h-*`, never `h-*`: these controls wrap onto two lines with long Telugu or Hindi
 * labels, and a fixed height would clip the second line rather than grow.
 */
/**
 * "Type X to confirm" — the human half of a step-up confirmation.
 *
 * ## What a typed confirmation is for, and what it is NOT
 *
 * It exists so a consequential action cannot be sent by a reflex click. That works only
 * while the phrase NAMES THE THING BEING DONE: a fixed word like "CONFIRM" becomes muscle
 * memory by the third use, and muscle memory is exactly the reflex the control was added
 * to interrupt. So the phrase is always specific — a tier, an address, a name — and it
 * changes when the target changes.
 *
 * ## Why it is not the API's header string
 *
 * It used to be. The screen asked an operator to hand-type `add_operator:operator`, and
 * for the row actions `revoke_operator:0192f0aa-e954-7d43-92b9-e91f2b38ef30` — a UUID.
 * Nobody types a UUID; they copy it, which is a click with extra steps and confirms
 * nothing. Meanwhile the wire value is a WIRE value and has its own constraints: it
 * travels in `X-Confirm-Action`, so it may never carry an email address, because headers
 * land in access logs (hard rule 6).
 *
 * The two were never the same requirement. The header stays exactly what the API builds
 * and validates; this is what a person reads and types. `apps/api/core/stepup` still
 * refuses anything but its own string, so nothing here can weaken the server's check —
 * the worst a bug in this file could do is refuse a legitimate operator.
 *
 * ## Case-insensitive, and trimmed
 *
 * The phrase is a proof of attention, not a spelling test. An address typed with a
 * capital letter, or with a space picked up from a copy, is the same intent — and a
 * confirmation that rejects it teaches people to paste instead of read.
 */
export function confirmationMatches(typed: string, phrase: string): boolean {
  return typed.trim().toLowerCase() === phrase.trim().toLowerCase();
}

export interface TypedConfirmationProps {
  /** What the person must type. Human words, specific to this target. */
  phrase: string;
  /** One line on WHY this phrase — what it is bound to, so the binding is visible. */
  binding: string;
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}

export function TypedConfirmation({
  phrase,
  binding,
  value,
  onChange,
  disabled,
}: TypedConfirmationProps) {
  const matched = value.trim() !== "" && confirmationMatches(value, phrase);
  return (
    <label className="block">
      <span className={FIELD_LABEL}>
        To confirm, type{" "}
        <span className="font-semibold text-ink">{phrase}</span>
      </span>
      <input
        value={value}
        disabled={disabled}
        autoComplete="off"
        spellCheck={false}
        // `aria-label` carries the phrase, because the visible label's emphasis span is
        // not something a screen reader conveys as emphasis.
        aria-label={`Type ${phrase} to confirm`}
        onChange={(event) => onChange(event.target.value)}
        className={`${FIELD} ${matched ? "border-brand" : ""}`}
      />
      <span className={FIELD_HINT}>{binding}</span>
    </label>
  );
}

export const FIELD =
  "mt-1 w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint touch:min-h-11";
/**
 * `block` IS THE FIX FOR A BUG THAT LOOKED LIKE THREE DIFFERENT DESIGNS.
 *
 * Without it the label is INLINE, so it renders beside any field narrow enough to leave
 * room — and full-width fields wrapped it onto its own line. One form therefore showed
 * "Their email address" and "Their name" to the LEFT of their boxes and "Tier" above its
 * select, which reads as three deliberate decisions and was none: the labels behaved
 * differently because the FIELDS had different widths.
 *
 * Above the field, always. That is what every form in this product was already trying to
 * do, and it is the placement a person scanning a column of fields can follow.
 */
export const FIELD_LABEL = "block text-xs font-medium text-ink-muted";
export const FIELD_HINT = "mt-1 block text-xs text-ink-faint";
/**
 * `bg-brand-strong`, not `bg-brand`, and this was worth checking rather than assuming.
 *
 * The design's primary button rests at #0F6B3D (brand-strong) and DARKENS to #0c5932 on
 * hover; #16A05D (brand) is the medallion and fill colour, not a button. The version
 * first promoted here rested on `brand` and lightened — so the four screens that had
 * written their own copy (the three compliance screens and the prompt history) were the
 * ones matching the design, and the shared constant was the outlier. Two greens for one
 * button is exactly the drift extracting it was supposed to end.
 */
export const PRIMARY_BUTTON =
  "inline-flex items-center gap-2 rounded-md bg-brand-strong px-4 py-2 text-sm font-semibold text-white enabled:hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11";

/**
 * The primary button at HERO size — the one action a screen exists for.
 *
 * A third size rather than a `size` prop, because these are class strings and not
 * components (see the block above for why). It exists so a screen can express primacy
 * with size as well as position and colour, which is the whole of what "primary" means
 * visually — GOV.UK's Button guidance puts the rule the other way round and it is the
 * same rule: "Avoid using multiple default buttons on a single page. Having more than one
 * main call to action reduces their impact"
 * (github.com/alphagov/govuk-design-system `src/components/button/index.md`, read
 * 25 Aug 2026). One of these per screen. UX-DOCTRINE §4.
 */
export const PRIMARY_BUTTON_LG =
  "inline-flex items-center gap-2 rounded-md bg-brand-strong px-5 py-3 text-base font-semibold text-white enabled:hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11";

/** The same buttons at the size an inline action wants. */
export const PRIMARY_BUTTON_SM =
  "inline-flex items-center gap-1.5 rounded-md bg-brand-strong px-3 py-1.5 text-xs font-semibold text-white enabled:hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11";
export const SECONDARY_BUTTON_SM =
  "inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink enabled:hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:enabled:hover:bg-white/5 touch:min-h-11";
export const SECONDARY_BUTTON =
  "inline-flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-muted enabled:hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:enabled:hover:bg-white/5 touch:min-h-11";
/**
 * The button that does something a person cannot undo.
 *
 * Rose, deliberately not `PRIMARY_BUTTON`: the control that stops every tenant's
 * dialling must not sit in the same visual class as "Create campaign". An operator's
 * eye should refuse to find it there.
 */
export const DANGER_BUTTON =
  "inline-flex items-center gap-2 rounded-md bg-rose-600 px-4 py-2 text-sm font-semibold text-white enabled:hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11";

/**
 * A verdict, in the tone the verdict deserves.
 *
 * `NOTICE_TONES` above argued against a component, on the grounds that the boxes differ
 * in what they say and only the palette is common. That held while there were two of
 * them. There are now eight call sites across both realms, and the design pass added a
 * SECOND common part — the icon medallion — so each site was independently choosing a
 * gap, a padding, a radius and an icon size, and they had already drifted: `rounded-xl`
 * on one admin screen against `rounded-card` on the client ones, `gap-2` against
 * `gap-3`, `p-3` against `p-4`. The palette map stays exported, because a few callers
 * legitimately want the classes alone (a one-line badge, a table cell).
 *
 * `title` is optional: several of these are a single sentence, and forcing a heading
 * would make callers invent one.
 */
export function NoticeBox({
  tone,
  icon,
  title,
  children,
  className,
}: {
  tone: NoticeTone;
  icon?: ReactNode;
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        "flex items-start gap-3 rounded-card border p-4 text-sm",
        NOTICE_TONES[tone],
        className,
      )}
    >
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="min-w-0 flex-1">
        {title && <p className="text-base font-semibold">{title}</p>}
        {children}
      </div>
    </div>
  );
}

/**
 * A container that scrolls sideways, and can therefore be scrolled by a keyboard.
 *
 * There is no key that scrolls a non-focusable `<div>`. A wide table inside a bare
 * `overflow-x-auto` div is content a keyboard-only user simply cannot read the right-hand
 * side of — on the credit ledger and the invoice that is the money columns, on the leads
 * table it is whatever the column chooser put on the right. That is axe's
 * `scrollable-region-focusable` rule, and the WAI technique behind it is to make the
 * container focusable and name it (`role="region"` + `aria-label`), which also gives a
 * screen-reader user a landmark to jump to rather than a wall of cells.
 *
 * This shape was argued once, at `lib/legal/document.tsx`, and then not used by the
 * seventeen other scroll containers in the product. Hoisted here and every one of them
 * moved onto it in the same change — including `document.tsx`, which now imports it
 * rather than keeping the original.
 *
 * `label` is REQUIRED and unnamed regions are not offered: a `region` role with no
 * accessible name is not exposed as a landmark at all, so an optional label would let a
 * caller opt into a focus stop that buys a screen-reader user nothing.
 *
 * Note this cannot be guarded by the a11y sweep: jsdom implements no layout, so axe can
 * never determine that a container IS scrollable and `scrollable-region-focusable` never
 * fires there. `tests/responsive.test.ts` checks it from the class strings instead, which
 * is a check that can actually fail.
 */
export function ScrollRegion({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      role="region"
      aria-label={label}
      className={clsx("overflow-x-auto", className)}
      // The one place a non-interactive element must take focus — see above. The lint
      // rule's default allowed-roles list knows only `tabpanel` and predates the WAI
      // guidance for scrollable regions. Waived HERE, once, which is the point of the
      // component: seventeen call sites no longer each need their own waiver.
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- see above
      tabIndex={0}
    >
      {children}
    </div>
  );
}

/**
 * The `id` both shells put on their `<main>`, and the target of `SkipLink`.
 *
 * A constant rather than a literal in three files because a skip link whose target `id`
 * was renamed is a skip link that silently does nothing — the anchor still renders, still
 * takes focus, and goes nowhere.
 */
export const MAIN_CONTENT_ID = "main-content";

/**
 * "Skip to main content" — WCAG 2.4.1 Bypass Blocks, Level A.
 *
 * The client sidebar is 21 links across four groups, the admin sidebar 7, plus the
 * collapse and drawer buttons and the notification bell, and all of it precedes `<main>`
 * in the DOM on every one of ~30 screens. A keyboard or screen-reader user paid that Tab
 * cost on every single navigation.
 *
 * Visually hidden until focused (`sr-only` / `focus:not-sr-only`) rather than permanently
 * visible or permanently hidden: a permanently hidden one is the well-known failure mode
 * where the link exists for axe and not for the person using it, and 2.4.1 is satisfied
 * by a mechanism that is available, which a control nobody can see is not.
 *
 * The target `<main>` carries `tabIndex={-1}`. Following a fragment moves the browser's
 * scroll position but only moves FOCUS if the target is focusable — without it, the next
 * Tab continues from the skip link and lands back in the navigation, which is the bug
 * that makes skip links famously not work.
 */
export function SkipLink() {
  return (
    <a
      href={`#${MAIN_CONTENT_ID}`}
      className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:border focus:border-line focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-ink focus:shadow-lg"
    >
      Skip to main content
    </a>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="py-10 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {hint && <p className="mt-1 text-xs text-ink-muted">{hint}</p>}
    </div>
  );
}

/**
 * The loading state, said out loud as well as drawn.
 *
 * §52's first clause is "loading is a skeleton", and for ~96 sites this component WAS the
 * whole of it — a `<div aria-hidden>` of pulsing bars. To a sighted reader that is the
 * clearest possible statement that an answer is on its way. To a screen-reader user it
 * was nothing at all: the bars were hidden from the accessibility tree and no text
 * replaced them, so a screen that had refused to lie in pixels was silent in the one
 * modality where silence and "there is nothing here" are the same thing. That is P7.1's
 * defect on the audience `tests/a11y.ts` names, and `a11y.ts:42` says out loud that the
 * axe sweep cannot see it: axe checks the markup that exists, not the announcement that
 * never happens.
 *
 * **`role="status"` + `aria-live="polite"` on the container, an `sr-only` label inside
 * it, and `aria-hidden` kept on the bars.** That is the researched shape rather than an
 * invention — Adrian Roselli, "More Accessible Skeletons"; Semrush Intergalactic's
 * skeleton a11y guidance ("place skeleton loaders inside a container with role='status'
 * and aria-live='polite' … for the screen reader to announce the start of the loading
 * process"); MDN on `aria-busy`.
 *
 * **`aria-busy` is deliberately NOT here**, and that is a departure from the obvious fix.
 * `aria-busy` is a property of the region whose CONTENTS are changing, so it belongs on
 * the card or table that is about to be filled, not on the placeholder that will be
 * removed (vuetifyjs/vuetify#10999 makes exactly this correction). Putting it on the
 * skeleton marks the skeleton itself as busy, which is both untrue and useless. Doing it
 * properly means `aria-busy` on ~96 containers, which is a change to the call sites and
 * not to this component.
 *
 * **What this does not give**, stated rather than implied: it announces the START of a
 * load. It cannot announce the ARRIVAL, because a live region has to be in the document
 * when the change happens and this one is removed by the change. Saying "loaded" would
 * need a region that outlives the skeleton, in both shells, fed by every screen — a
 * different mechanism, and one that would say "loaded" 96 times a session unless it also
 * knew which loads a reader cares about.
 *
 * `label` names what is loading, because "Loading…" four times on one screen tells a
 * reader less than "Loading your calls". It has a default so no call site is obliged to
 * think about it, and the sites that mean something specific can say so.
 */
export function Skeleton({
  rows = 3,
  label = "Loading…",
}: {
  rows?: number;
  label?: string;
}) {
  return (
    <div role="status" aria-live="polite" className="space-y-2">
      <span className="sr-only">{label}</span>
      {/* The bars themselves stay out of the accessibility tree: they are the drawing of
          the sentence above, and reading them out is 96 announcements of nothing. */}
      <div aria-hidden className="space-y-2">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="h-8 animate-pulse rounded bg-black/5 dark:bg-white/10"
          />
        ))}
      </div>
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
        "rounded-full px-3 py-1.5 text-xs capitalize touch:min-h-11",
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

/**
 * "10 minutes", "5 min 30 s", "45 seconds" — a call CAP, in the units an owner thinks in.
 *
 * `formatDuration` above is for how long a call ACTUALLY ran and reads as a stopwatch
 * (`10:00`); a ceiling reads as a sentence. Two formats because they answer two different
 * questions, not because one was forgotten.
 *
 * IT LIVES HERE BECAUSE BOTH REALMS ASK IT. The client's agents screen and the admin
 * prompt screen each had their own — `formatCallCap` and `minutesReading` — describing
 * the SAME number (`effective_call_cap_s`) and disagreeing about it: one said "15
 * minutes" and "5 min 30 s", the other "15 min" and "5 min 30s". Nothing was broken by
 * that, which is the point: two ways of doing one thing is a defect even when both work,
 * and an operator and a client discussing the same cap were reading two spellings of it.
 *
 * The non-finite guard comes from the admin twin and is load-bearing there: its caller
 * passes `Number(<what the operator has typed>)`, which is `NaN` for a half-typed field,
 * and the client version would have rendered "NaN min NaN s".
 */
export function formatCallCap(seconds: number): string {
  if (!Number.isFinite(seconds)) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes === 0) return `${rest} seconds`;
  if (rest === 0) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  return `${minutes} min ${rest} s`;
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
  const grouped = head
    ? `${head.replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${tail}`
    : tail;
  const paise = `${fraction}00`.slice(0, 2);
  return `${negative ? "-" : ""}₹${grouped}.${paise}`;
}

/**
 * A per-minute RATE, at the precision the SERVER sent it — not `formatINR`.
 *
 * `formatINR` above keeps exactly two decimals, which is right for a total and wrong for
 * a rate: `overage_rate_inr` is NUMERIC(12,4) and a plan may legitimately quote
 * ₹7.1250/min, so printing ₹7.12 beside "× 20 min = ₹142.50" makes the invoice line
 * fail the one check a client performs on it. The same is true of the per-minute price
 * beside a model in the AI-model picker, where two rates a paisa apart are the whole
 * decision.
 *
 * The digits are the server's and are never parsed (hard rule 7); this only prefixes the
 * symbol. It lives here rather than beside either caller because it had already been
 * written twice — `rupeeRate` on `/c/[slug]/usage` and again for the model picker — and
 * two spellings of one rule is where the drift starts.
 */
export function formatRupeeRate(value: string): string {
  return `₹${value}`;
}

/**
 * Does this decimal STRING carry a value above zero?
 *
 * The question `Number(value) > 0` used to answer, without the parse. "0", "0.00" and
 * "0.0000" are all zero and no string comparison spots that; a single digit other than
 * zero anywhere in the string is exactly the condition, and it holds for every decimal
 * form the server can send. It usually picks a HINT rather than a figure — which is
 * precisely how the habit hard rule 7 is about survives to the line where it does matter.
 *
 * Here rather than beside a caller because it now has two: the usage screen asks it of
 * overage minutes and of the model surcharge, and the credit-pack table asks it of a
 * bonus percentage. Two spellings of one rule is where the drift starts.
 */
export function hasNonZeroDigit(value: string): boolean {
  return /[1-9]/.test(value);
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

/**
 * `formatIST`'s doctrine in the shape `<input type="datetime-local">` speaks — the pair
 * of conversions for a field whose value is IST BY NATURE rather than by who is looking.
 *
 * ## The bug this exists to make unwriteable
 *
 * `datetime-local` has no timezone in it, and both halves of the naive round trip read the
 * BROWSER's clock: `date.getHours()` on the way in and `new Date("2026-08-04T14:30")` on
 * the way out. That is correct on a machine set to India and silently wrong everywhere
 * else — and D-22's "view as client" plus a colleague on a laptop still set to a US zone
 * make "everywhere else" a real session rather than a hypothetical. The value it corrupts
 * is not the operator's: it is the timestamp on an Indian registrar's letter, which says
 * one thing and would be stored as another.
 *
 * ## Why the two directions are spelled differently, and why that is not two ways
 *
 * Both name ONE fact — the wall clock in India — and this repo already fixed each half
 * once. Forward, `Intl` is asked for the parts in `Asia/Kolkata`, which is what `formatIST`
 * above does and what `lib/api/invoice.ts` does for the billing month; `formatToParts` is
 * used rather than a formatted string so nothing depends on where a locale puts its comma.
 * Backward, the `+05:30` is WRITTEN IN, which is what `campaigns.ts::scheduleStartAt` and
 * `recurrenceUntil` do and for the identical reason recorded there. Going backwards
 * through `Intl` would mean solving for the offset at an instant we do not yet have —
 * machinery whose only purpose would be to rediscover a constant. India has observed
 * UTC+05:30 with no daylight saving since 1945 and IANA lists no future transition for
 * `Asia/Kolkata`; "IST" names that offset, which is why the input is labelled IST on
 * screen wherever this is used.
 *
 * A LABEL IS PART OF THIS CONTRACT, not decoration. An unlabelled `datetime-local` that
 * quietly means something other than the machine's clock is worse than the bug it fixes,
 * because the reader has no way to tell which one they are typing.
 */
const IST_INPUT_PARTS = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  // `hourCycle`, never `hour12: false` — the latter resolves to `h24` under some locale
  // data and renders midnight as "24:00", which no `datetime-local` will accept.
  hourCycle: "h23",
});

/** An instant → the `YYYY-MM-DDTHH:mm` an IST reader would type. `""` when there is none. */
export function formatISTInput(value: string | null | undefined): string {
  if (!value) return "";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return "";
  const parts: Partial<Record<Intl.DateTimeFormatPartTypes, string>> = {};
  for (const part of IST_INPUT_PARTS.formatToParts(at))
    parts[part.type] = part.value;
  const { year, month, day, hour, minute } = parts;
  if (!year || !month || !day || !hour || !minute) return "";
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

/**
 * The inverse: what an IST reader typed → the instant the API stores.
 *
 * `null` for an empty or unparseable field rather than a guess, which is the same answer
 * `scheduleStartAt` gives and for the same reason — a field the operator has not filled in
 * is not midnight, and a half-typed one is not a time at all.
 */
export function istInputToInstant(value: string): string | null {
  const typed = value.trim();
  if (typed === "") return null;
  // Seconds are appended because `datetime-local` omits them unless a `step` asks for
  // them, and `2026-08-04T14:30+05:30` is not a date-time any parser is obliged to accept.
  const withSeconds = typed.length === 16 ? `${typed}:00` : typed;
  const at = new Date(`${withSeconds}+05:30`);
  return Number.isNaN(at.getTime()) ? null : at.toISOString();
}
