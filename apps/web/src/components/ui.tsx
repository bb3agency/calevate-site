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
import { useCallback, useEffect, useRef } from "react";
import type { ReactNode } from "react";

import { lookup } from "@/lib/lookup";
import { InfoTip } from "@/components/console/infoTip";
import { NOTICE_DOT, StatusPill } from "@/components/console/statusPill";
import { TEXT_ACTION } from "@/components/console/section";

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
  info,
  density = "default",
  children,
  className,
  bodyClassName,
}: {
  title?: string;
  action?: ReactNode;
  /**
   * Help prose behind an ⓘ beside the title (`components/console/infoTip.tsx`). Never a
   * compliance sentence or an error: those stay visible (UX-DOCTRINE §3, §8.7).
   */
  info?: ReactNode;
  /**
   * `compact` is the console's denser panel: a 15px title with no divider under it and
   * 16px of padding — for side columns and dense screens where the default's document-
   * like header is too heavy. Same element and the same `h2` either way.
   */
  density?: "default" | "compact";
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  const compact = density === "compact";
  return (
    <section
      className={clsx(
        "rounded-card border border-line bg-surface",
        className,
      )}
    >
      {/* `flex-wrap`: the header is a title beside an action, and on a 320px screen the
          pair does not fit on one line — unwrapped, the action was what got squeezed. */}
      {(title || action) && (
        <header
          className={
            compact
              ? "flex flex-wrap items-center justify-between gap-2 px-4 pb-2 pt-3.5"
              : "flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-4 sm:px-6"
          }
        >
          {title && (
            <div className="flex min-w-0 items-center gap-1">
              <h2 className={compact ? "text-[15px] font-semibold text-ink" : "text-[17px] font-semibold text-ink"}>
                {title}
              </h2>
              {info && <InfoTip label={title}>{info}</InfoTip>}
            </div>
          )}
          {action}
        </header>
      )}
      {/* 16px of padding on a phone, 24px from `sm` up. At 320px the old flat `p-6` spent
          48px of a 288px content strip — a sixth of the screen — on whitespace, and it is
          what pushed `/admin/tenants/[tenantId]`'s inner grid past the viewport (its
          single column's min-content is 288px and the padded box left it 238px). */}
      {/* A compact card's header supplies the top padding; without one the body needs its
          own, or the first line sits on the border. */}
      <div
        className={
          bodyClassName ?? (compact ? (title || action ? "px-4 pb-4" : "p-4") : "p-4 sm:p-6")
        }
      >
        {children}
      </div>
    </section>
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
 * Hoisted from `agents/panels.tsx` when a second route needed it (UX-DOCTRINE §7).
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
      <dt className="flex items-center gap-1.5 text-meta text-ink-muted">
        {icon && (
          <span aria-hidden className="shrink-0 text-brand">
            {icon}
          </span>
        )}
        {label}
      </dt>
      {/* `anywhere`: an email or a GSTIN is one unbroken token, and in a two-column grid
          on a phone it would otherwise push past the card. */}
      <dd className="mt-0.5 text-body font-medium text-ink [overflow-wrap:anywhere]">{children}</dd>
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
      <label className="flex cursor-pointer items-start gap-3 touch:min-h-11 touch:py-2.5">
        <input
          type="checkbox"
          role="switch"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          // `disabled` stops a person, not a dispatched click (jsdom delivers one, and so
          // does any script), so the handler refuses too: a greyed switch that still
          // writes is a refusal on screen and a request on the wire.
          onChange={(event) => {
            if (disabled) return;
            onChange(event.target.checked);
          }}
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
 *
 * ## `variant="inline"` — the same mechanism at strip size
 *
 * A card-shaped panel is the right container for a section. It is the wrong one for a
 * LIST of one-line facts, each of which has a longer sentence behind it: five bordered
 * cards inside a card is a stack of chrome around ten words apiece, and the doc comment
 * above says outright that a disclosed panel is a peer of a card and never nested in one.
 * `variant="inline"` drops the border, the shadow and the padding and keeps everything
 * that makes this component the console's one disclosure: the native `<details>`, the
 * announced state, the Show/Hide affordance in words, and the touch target.
 *
 * It is a VARIANT rather than a second component because the alternative on offer was a
 * hand-rolled `<details>` beside `WhatCallsCost`, which is the thing UX-DOCTRINE §3
 * forbids ("do not hand-roll a second").
 *
 * Two contract differences, both deliberate:
 *
 * - **`headingLevel`.** The card variant's `h2` is a peer of `Card`'s own `h2`. An inline
 *   disclosure sits INSIDE a card's body, under that `h2`, so it takes `3` there —
 *   otherwise the heading list reads as two peers where one contains the other.
 *   `4` is for a disclosure inside one row of a list that sits under an `h3` (a setting's
 *   technical details on the ops configuration screen).
 * - **`subtitle` is not expected.** §3 requires the closed state to carry the FACT rather
 *   than a tease; in the inline variant the TITLE is the fact ("No GST, and no tax
 *   invoice") and the body is only the elaboration, so a subtitle would
 *   be a third line of text on a strip that exists to remove text.
 */
export function Disclosure({
  title,
  subtitle,
  status,
  icon,
  defaultOpen = false,
  variant = "card",
  headingLevel = 2,
  children,
  className,
  onToggle,
  name,
  showLabel = "Show",
  hideLabel = "Hide",
}: {
  title: string;
  subtitle?: ReactNode;
  /**
   * A short state beside the affordance ("Off", "Below ₹500"), shown open or closed and at
   * every width — unlike `subtitle`, which a phone hides while the panel is closed. For a
   * setting whose closed row must still say what it is set to.
   */
  status?: ReactNode;
  icon?: ReactNode;
  defaultOpen?: boolean;
  variant?: "card" | "inline";
  headingLevel?: 2 | 3 | 4;
  children: ReactNode;
  className?: string;
  /** Told when the reader opens or closes it, for content that should act only while open. */
  onToggle?: (open: boolean) => void;
  /**
   * Disclosures sharing a `name` form an exclusive group: opening one closes the others
   * (the native `<details name>` behaviour, so no script decides it). `Accordion` in
   * `components/arc/accordion.tsx` sets it for a list.
   */
  name?: string;
  showLabel?: string;
  hideLabel?: string;
}) {
  const inline = variant === "inline";
  const Heading = headingLevel === 4 ? "h4" : headingLevel === 3 ? "h3" : "h2";
  return (
    <details
      name={name}
      open={defaultOpen}
      onToggle={onToggle ? (event) => onToggle(event.currentTarget.open) : undefined}
      className={clsx(
        "group",
        inline
          ? "border-b border-line/60 last:border-b-0"
          : "rounded-card border border-line bg-surface",
        className,
      )}
    >
      {/* The title is a REAL `h2` inside the `summary`, which the HTML spec allows and
          which is what GOV.UK's accordion does with its section headings. It costs nothing
          visually and it is the difference between a disclosed panel a screen-reader user
          can jump to from the heading list and one they can only find by tabbing. WCAG 2.2
          1.3.1 / 2.4.6 — the level is fixed at 2 for `Disclosure`'s reason above `Card`:
          a disclosed panel is a peer of a card, never nested inside one. */}
      <summary
        className={clsx(
          "flex cursor-pointer list-none items-center gap-3 touch:min-h-11 [&::-webkit-details-marker]:hidden",
          inline ? "py-2" : "px-4 py-4 sm:px-6",
        )}
      >
        {icon && (
          <span
            aria-hidden
            className={clsx(
              "flex shrink-0 items-center justify-center",
              inline
                ? "text-brand"
                : "h-8 w-8 rounded-full bg-brand-soft text-brand-strong",
            )}
          >
            {icon}
          </span>
        )}
        <span className="min-w-0 flex-1">
          <Heading
            className={clsx(
              "text-ink",
              inline ? "text-body font-medium" : "text-[15px] font-semibold",
            )}
          >
            {title}
          </Heading>
          {/* On a phone a closed panel is its title alone: the subtitle wrapped to three
              lines there and turned a stack of collapsed panels back into a wall of text. */}
          {subtitle && (
            <span className="block text-xs text-ink-muted max-sm:hidden max-sm:[details[open]>summary_&]:block">{subtitle}</span>
          )}
          {/* The status goes UNDER the title on a phone and beside it from `sm`: at 375px a
              title, a status and the affordance on one line squeezed the title to a word a
              line. Only one of the two is displayed, so a screen reader hears it once. */}
          {status !== undefined && status !== null && (
            <span className="block text-meta tabular-nums text-ink-muted sm:hidden">{status}</span>
          )}
        </span>
        {status !== undefined && status !== null && (
          <span className="shrink-0 text-meta tabular-nums text-ink-muted max-sm:hidden">{status}</span>
        )}
        {/* The affordance, in words as well as a chevron: an icon alone is what GOV.UK's
            research says people fail to notice. Its OWN details' open state swaps the pair:
            `group-open:` matches any open ancestor, so a disclosure nested in an open one
            read "Hide" while closed. Muted ink,
            not brand green: green is the console's colour for the one action on a screen,
            and a stack of closed panels each wearing it read as a column of calls to act. */}
        <span className="shrink-0 text-meta font-medium text-ink-muted [summary:hover_&]:text-ink">
          <span className="[details[open]>summary_&]:hidden">{showLabel}</span>
          <span className="hidden [details[open]>summary_&]:inline">{hideLabel}</span>
        </span>
        <ChevronDown
          aria-hidden
          className="h-4 w-4 shrink-0 text-ink-faint transition-transform [details[open]>summary>&]:rotate-180"
        />
      </summary>
      <div
        className={clsx(
          inline
            ? "pb-3 text-body text-ink-muted"
            : "border-t border-line p-4 sm:p-6",
        )}
      >
        {children}
      </div>
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
    <div className="@container flex items-start gap-3 rounded-card border border-line bg-surface p-4 sm:gap-4 sm:p-5">
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
            change width (D-24: this screen refetches on an interval). Never truncated — an
            amount cut to "₹1,23,4…" is a wrong number — so it steps down a size in a
            narrow tile and wraps only as a last resort. */}
        <p className="mt-1 text-xl font-bold tracking-tight tabular-nums text-ink [overflow-wrap:anywhere] @[13rem]:text-2xl">
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

// Lead and call states on the four tones (D-771). Colour only where the owner acts: a hot
// lead or a missed connection is warn, a done or won thing is ok, a failure is stop, and
// everything still moving or closed is neutral.
const LEAD_STATUS_TONES: Record<string, NoticeTone> = {
  new: "neutral",
  contacted: "neutral",
  interested: "ok",
  hot: "warn",
  won: "ok",
  lost: "neutral",
};

const CALL_STATUS_TONES: Record<string, NoticeTone> = {
  completed: "ok",
  in_progress: "neutral",
  queued: "neutral",
  ringing: "neutral",
  no_answer: "warn",
  busy: "warn",
  voicemail: "warn",
  failed: "stop",
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
 * class list. Fails VISIBLE: the neutral tone, and `value` is still printed, because a
 * status we have no colour for is exactly the one worth reading.
 */
export function StatusBadge({
  value,
  kind = "lead",
}: {
  value: string;
  kind?: "lead" | "call";
}) {
  const tones = kind === "lead" ? LEAD_STATUS_TONES : CALL_STATUS_TONES;
  return (
    <StatusPill tone={lookup(tones, value) ?? "neutral"}>
      {kind === "call" ? sentenceCase(value) : value.replace(/_/g, " ")}
    </StatusPill>
  );
}

/** `no_answer` → "No answer": a call state reads like the outcome tag beside it. */
function sentenceCase(value: string): string {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
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
 * Prefer `<Term id="dlt" />` (`@/lib/glossary`) to writing the words here: the map is what
 * keeps one term from being explained two ways on two screens. This component is the
 * mechanism; the glossary is the vocabulary.
 *
 * ## Why the gloss is a styled box, not the native `title`
 *
 * The term shows its meaning in a small box on HOVER, on keyboard FOCUS, and on TAP — the
 * three input modes a `title` tooltip fails: `title` is mouse-only, delayed, unstyled, and
 * shows nothing on a touch screen. The `<abbr>` is `tabIndex={0}` so a keyboard user reaches
 * it and a touch user taps it into focus.
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
 * ## TWO DEFECTS A BROWSER FOUND, BOTH INVISIBLE TO jsdom
 *
 * Measured in Chromium against the production Tailwind bundle (the instrument
 * `tests/responsive.test.ts` describes), because jsdom applies no CSS and this component is
 * ENTIRELY CSS. The founder photographed a gloss box that looked "cut off"; it was both of
 * these at once.
 *
 * **1. The box was empty — the gloss text never rendered, on any screen, in any browser.**
 * The class was the arbitrary PROPERTY form of `after:` + `[content: attr(...)]` (spelled
 * without the space, which is why it is not spelled that way here: Tailwind scans comments
 * too, and naming the class in prose is enough to emit a rule for it). Tailwind emits
 * `content: var(--tw-content)` into EVERY `after:` rule it generates, and `--tw-content`
 * defaults to `""` — so `.hover\:after\:block:hover::after` and
 * `.focus\:after\:block:focus::after`, which sort later in the sheet and carry a higher
 * specificity, blanked the content in exactly the two states that reveal the box. Measured:
 * `getComputedStyle(el, "::after").content === '""'`, an 18×10px empty white rectangle.
 * The fix is the `content-[…]` UTILITY, which sets `--tw-content` itself, so every later
 * `content: var(--tw-content)` resolves to the gloss instead of over-writing it.
 *
 * **2. The box was clipped by the shell.** It was `after:absolute after:bottom-full`, whose
 * containing block is the `<abbr>` — inside `<main class="overflow-y-auto">` (a scroll
 * container: `overflow-y: auto` forces the `visible` x-axis to `auto`, so it clips
 * horizontally too) and inside every `ScrollRegion`. Measured at 1280×800: a term in the
 * right-hand column had 106px of a 192px box cut off by `main`'s right edge, and a term in a
 * table inside a `ScrollRegion` lost 16.5px of its 26.5px height off the region's top edge.
 *
 * So the box is now `position: fixed` — which escapes ancestor overflow entirely — with its
 * coordinates written as custom properties by `placeGloss` when the term is hovered, focused
 * or tapped, and kept in step while it is showing. What that buys over the alternatives:
 *
 * - **CSS anchor positioning** (`anchor-name` + `position-area` + `position-try-fallbacks`)
 *   is the pure-CSS answer and needs no listener, but it is not in every browser we serve,
 *   so it would need the clipped `absolute` rules kept underneath as an `@supports`
 *   fallback — two positioning mechanisms in one component, and the fallback is the broken
 *   one. Take it when support is universal; it deletes `placeGloss` and nothing else.
 * - **A portal / the native `popover` attribute** puts a real element in the top layer,
 *   which also solves it — and costs the property the section above is about: the gloss
 *   becomes a DOM text node that every `getByText` on every screen using a term would then
 *   match. Rejected for that, not for the DOM weight.
 *
 * The one place `fixed` does NOT escape is inside an ancestor that carries a transform,
 * filter or `contain`, which becomes the containing block for fixed descendants — an
 * identity `translate-x-0` counts. Nothing glossed today sits in one; the shells' sidebar
 * panel does (`sidebarCollapse.tsx` animates `transform`), so a gloss put INSIDE the
 * sidebar would be placed relative to the panel rather than the viewport.
 *
 * With JS unavailable (a hydration failure, a blocked bundle) the vars are unset, `top`,
 * `left` and `bottom` all resolve to `auto`, and a fixed box at its static position lands
 * beside the term — unclipped, unflipped, still readable. It degrades, it does not vanish.
 *
 *   <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss>
 */

/** `after:max-w-[16rem]`, in px — the widest the box can be, so the flip can be decided
 *  without measuring a pseudo-element (which cannot be read with `getBoundingClientRect`
 *  and whose computed width is only resolvable while it is displayed). */
const GLOSS_MAX_WIDTH = 256;
/** Enough for the longest gloss in `@/lib/glossary` at that width — three 12px lines plus
 *  padding. Used only to decide above-or-below, never to size the box. */
const GLOSS_MAX_HEIGHT = 76;
/** The gap between term and box, and the margin the box keeps off a viewport edge. */
const GLOSS_GAP = 6;
const GLOSS_EDGE = 8;

/**
 * Writes the fixed coordinates of one term's gloss box.
 *
 * Exported for the test: the geometry is the part that was broken, and asserting it through
 * a real hover would need a browser. Given the term's viewport rect and the viewport size,
 * this is the whole positioning decision — clamp inside the right edge, and flip below when
 * there is not room above.
 */
export function glossPosition(
  rect: { top: number; bottom: number; left: number },
  viewport: { width: number; height: number },
): { left: string; top: string; bottom: string } {
  const left = Math.max(
    GLOSS_EDGE,
    Math.min(rect.left, viewport.width - GLOSS_MAX_WIDTH - GLOSS_EDGE),
  );
  // Above by default (it covers the sentence the reader has already read rather than the
  // one they have not); below only when the term sits too near the top for the box to fit,
  // which is every term in the first row of the first panel on a screen.
  const fitsAbove = rect.top >= GLOSS_MAX_HEIGHT + GLOSS_GAP + GLOSS_EDGE;
  return {
    left: `${Math.round(left)}px`,
    top: fitsAbove ? "auto" : `${Math.round(rect.bottom + GLOSS_GAP)}px`,
    bottom: fitsAbove
      ? `${Math.round(viewport.height - rect.top + GLOSS_GAP)}px`
      : "auto",
  };
}

export function TermGloss({
  term,
  children,
}: {
  term: string;
  children: string;
}) {
  const ref = useRef<HTMLElement>(null);
  // The listener is attached only while a gloss is showing, and detached when it hides:
  // a `scroll` handler per glossed term on a screen that has a dozen of them would run on
  // every frame of every scroll for boxes nobody is looking at.
  const detach = useRef<(() => void) | null>(null);

  const place = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const at = glossPosition(r, {
      width: window.innerWidth,
      height: window.innerHeight,
    });
    el.style.setProperty("--gloss-left", at.left);
    el.style.setProperty("--gloss-top", at.top);
    el.style.setProperty("--gloss-bottom", at.bottom);
  }, []);

  const show = useCallback(() => {
    place();
    if (detach.current) return;
    // `capture`, because the thing that moves the term is `<main>` scrolling, not the
    // window: a scroll event on an inner element does not bubble to `window` in the
    // bubbling phase but is seen in the capture phase.
    const onMove = () => place();
    window.addEventListener("scroll", onMove, { capture: true, passive: true });
    window.addEventListener("resize", onMove, { passive: true });
    detach.current = () => {
      window.removeEventListener("scroll", onMove, { capture: true });
      window.removeEventListener("resize", onMove);
      detach.current = null;
    };
  }, [place]);

  const hide = useCallback(() => {
    detach.current?.();
  }, []);

  useEffect(() => hide, [hide]);

  // tabIndex on a non-interactive <abbr> so the box reveals on keyboard FOCUS and on TAP,
  // not mouse-hover alone (the WAI-ARIA tooltip pattern needs a focusable trigger). <abbr>
  // is kept rather than <button> because TermGloss renders inside <label>/<legend>, where a
  // nested interactive control would hijack the label.
  return (
    <abbr
      ref={ref}
      aria-label={`${term}: ${children}`}
      data-gloss={children}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      // The handlers only POSITION the box; CSS is still what reveals it, so a gloss that
      // never gets a pointer or focus event costs nothing and one whose JS failed still
      // shows (see the docstring's last paragraph).
      onPointerEnter={show}
      onPointerLeave={hide}
      onFocus={show}
      onBlur={hide}
      className={clsx(
        "relative cursor-help rounded-sm underline decoration-dotted underline-offset-2",
        "outline-none focus-visible:ring-2 focus-visible:ring-brand-strong",
        // The gloss box, drawn from `data-gloss` (see docstring). `normal-case`/`font-normal`
        // so it reads plainly even when the term sits inside an uppercase or bold label;
        // `whitespace-normal` + a max width so a long gloss wraps instead of running off-screen.
        // `fixed` + the three custom properties are the anti-clipping mechanism, also above.
        "after:pointer-events-none after:fixed after:z-dropdown",
        "after:[left:var(--gloss-left,auto)] after:[top:var(--gloss-top,auto)]",
        "after:[bottom:var(--gloss-bottom,auto)]",
        "after:hidden after:w-max after:max-w-[16rem] after:whitespace-normal after:rounded-md",
        "after:border after:border-line after:bg-surface after:px-2 after:py-1 after:text-left",
        "after:text-xs after:font-normal after:normal-case after:not-italic after:leading-snug",
        "after:text-ink after:shadow-raised after:content-[attr(data-gloss)]",
        "hover:after:block focus:after:block",
      )}
    >
      {term}
    </abbr>
  );
}

/**
 * The problem kinds where a support reference is worth printing.
 *
 * A reference is for a failure only WE can look into. `validation`, `permission`,
 * `auth`, `not_found`, `conflict` and `business_rule` are the API telling the person what
 * it needs — a 32-character id beside "check what you entered" makes a typo look like an
 * outage, which is exactly what the photographed sign-in box did. The three kinds here
 * are the ones whose answer is in a log line rather than on the screen
 * (`apps/api/core/errors.py`: `dependency`, `transient`, `internal`).
 */
const REFERENCE_KINDS = new Set(["dependency", "transient", "internal"]);

/**
 * Renders an RFC-9457 problem the way its fields intend.
 *
 * The reason this exists instead of `alert(error.message)`: the API distinguishes a
 * compliance refusal ("this number is on the do-not-call list") from a transient
 * failure, and tells us which is which via `retryable` + `remediation`. Flattening
 * both into "something went wrong" would make the compliance gate look like a bug.
 *
 * ## The hierarchy, and why the support reference moved down it
 *
 * A live sign-in refusal was photographed reading: *"One or more fields are invalid /
 * Correct the fields named in this response and send the request again / password: String
 * should have at least 12 characters / Support reference: 9c83825c…"*. The server half of
 * that is somebody else's fix. THIS half is that four things were given near-equal weight,
 * and the only one that helped — use a longer password — was third.
 *
 * So: the sentence is the loudest thing in the box; what to do next sits under it; and the
 * support reference is shown **only when there is genuinely something for support to look
 * up**. A 4xx is the API telling the person what it needs — a 32-character id beside it is
 * noise that makes a fixable refusal look like an outage. A 5xx, an unclassified failure,
 * or a refusal that names nothing to do, is ours: there the reference is the whole point,
 * because it is what turns "it broke" into a row somebody can find.
 *
 * `break-words` on every element that can hold server prose, because the server puts the
 * CLIENT's own strings in it — the endpoint URL they typed on `/integrations`, a slug, a
 * host. One 300-character token with no space in it walked a 320px card off the screen,
 * and `overflow-wrap` does not inherit past a child that sets its own.
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
  // A blank `detail` is the ABSENCE of a sentence, and `ApiProblem` now hands one back as
  // `"We could not finish that."` rather than as `""` — but a plain `Error` thrown by a
  // screen ("This preview could not be loaded.") reaches here too, and an empty message on
  // one of those would still paint a box with no words in it.
  const title =
    problem?.message?.trim() ||
    (problem === null ? "Something went wrong." : "We could not finish that.");
  // Anything that is not an ApiProblem never reached the API — a dropped connection,
  // a DNS failure, a laptop that slept. The API's `retryable` cannot speak for those,
  // and they are the most retryable failures there are, so the button must not depend
  // on it: without this, a client on a train watches a screen with no way forward
  // except reloading the page.
  const canRetry = Boolean(onRetry) && (problem === null || problem.retryable);
  // See the docstring: a reference is for a failure only WE can look into. A 4xx that
  // told the person what it needs is not one, and the id beside it only competes with the
  // instruction.
  const ours = problem !== null && REFERENCE_KINDS.has(problem.kind);
  // A RESPONSE THAT ARRIVED speaks for itself: its own headline above its own sentence.
  // Only a received problem (`status > 0`) gets the headline — the browser's own problems
  // (`status: 0`: no reply, a timeout, a local auth refusal) restate their title in their
  // detail, and printing both would say the same thing twice.
  const headline =
    problem !== null && problem.status > 0 && problem.title && problem.title !== title
      ? problem.title
      : null;
  return (
    <div role="alert" data-notice="stop" className={clsx(NOTICE_BASE, NOTICE_BAR.stop)}>
      {headline && <p className="break-words font-semibold text-ink">{headline}</p>}
      <p className={headline ? "break-words text-ink-muted" : "break-words font-semibold text-ink"}>
        {title}
      </p>
      {problem?.remediation && (
        <p className="break-words text-ink-muted">{problem.remediation}</p>
      )}
      {problem === null && (
        /* A plain `Error` thrown by a screen reaches this arm, never a transport failure
           (those arrive as `TransportProblem`). So it names no cause and promises no
           outcome: the screen's own sentence above says what did not happen. */
        <p className="break-words text-ink-muted">
          Try again in a moment. If it keeps happening, contact us.
        </p>
      )}
      {problem?.fields?.length ? (
        /* The noun is the server's `label` or nothing: `f.field` is a wire path, and
           printing it put our schema's word in front of the person's own. */
        <ul className="mt-1 list-inside list-disc text-ink-muted">
          {problem.fields.map((f) => (
            <li key={f.field} className="break-words">
              {f.label ? <span className="break-words font-medium text-ink">{f.label}: </span> : null}
              {f.message}
            </li>
          ))}
        </ul>
      ) : null}
      {(canRetry || (ours && problem.traceId)) && (
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
          {canRetry && (
            <button type="button" onClick={onRetry} className={TEXT_ACTION}>
              Try again
            </button>
          )}
          {ours && problem.traceId && (
            /* Secondary on purpose: the sentence and the action lead, and this is only what
               support asks for. The full id stays in the text (one click selects it) because
               it is what our request log is searched by. */
            <p className="break-words text-meta text-ink-faint">
              Error code <span className="select-all break-all font-mono">{problem.traceId}</span>
            </p>
          )}
        </div>
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
    <p data-notice="neutral" className={clsx("border-l-2 bg-surface py-1 pl-3 text-body text-ink-muted", NOTICE_BAR.neutral)}>
      {reason}
    </p>
  );
}

/**
 * The four tones a status can carry: cleared, needs a look, refused, nothing on file.
 * They are the vocabulary the API already speaks about a client's own state, so the
 * colours live here rather than being re-picked per screen.
 */
export type NoticeTone = "ok" | "warn" | "stop" | "neutral";

/**
 * The tone of a notice is its LEFT RULE and nothing else. Chart fills, not text tokens:
 * the rule is a mark beside words that carry the meaning, so it is not held to 4.5:1.
 */
export const NOTICE_BAR: Record<NoticeTone, string> = {
  ok: "border-brand",
  warn: "border-chart-warn",
  stop: "border-chart-danger",
  neutral: "border-chart-neutral",
};

/** The matching status dot, for a caller that wants one beside a title. Defined beside
 *  `StatusPill`, which server components import, and a "use client" module cannot hand a
 *  server component a plain value. */
export { NOTICE_DOT };

/**
 * The quiet notice frame: the page's own white ground, a 2px tone rule on the left, ink
 * text. Exported for the few hand-rolled notices that cannot take `NoticeBox` (a
 * `<label>`, a `<li>`); `tests/noticeStyle.test.ts` rejects tinted notice cards.
 */
/**
 * A site-wide strip above the content (offline, maintenance, view-as): a hairline under
 * white, ink text, and a tone dot before the sentence. Never a tinted band.
 */
export const SITE_STRIP = "flex items-start gap-2 border-b border-line bg-surface px-4 py-2 text-sm text-ink lg:px-8";

export const NOTICE_BASE = "space-y-1 border-l-2 bg-surface py-1 pl-3 text-body text-ink";

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
export const FIELD =
  "mt-1 w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint touch:min-h-11 transition-[border-color] duration-(--duration-fast) ease-out focus:border-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/25 aria-[invalid=true]:border-danger";
/**
 * The same control for a FLEX ROW, where `FIELD`'s `w-full` would be wrong.
 *
 * `min-w-0 max-w-full` instead: an <input> with no width utility sizes to its `size`
 * attribute (~20 characters), which at the 16px this repo gives touch devices is ~256px
 * — 2px wider than the 254px card it sits in at 320px, so it painted across the border.
 * A CAP rather than `w-full` because these sit in flex rows where a forced full width
 * would restyle the desktop console; `min-w-0` because a flex item will not otherwise
 * shrink below its own min-content.
 *
 * Hoisted from `do-not-call` and `messaging-consent`, which each carried the
 * byte-identical trio under the SAME NAME as this module's `FIELD` — shadowing that made
 * any future edit here silently not reach them (ux-audit MC-2).
 */
export const FIELD_INLINE =
  "rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint min-w-0 max-w-full touch:min-h-11 transition-[border-color] duration-(--duration-fast) ease-out focus:border-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/25 aria-[invalid=true]:border-danger";
/** `FIELD_INLINE` with room for a leading icon. */
export const FIELD_INLINE_ICON =
  "rounded-md border border-line bg-surface pl-8 pr-3 py-1.5 text-sm text-ink placeholder:text-ink-faint min-w-0 max-w-full touch:min-h-11 transition-[border-color] duration-(--duration-fast) ease-out focus:border-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/25 aria-[invalid=true]:border-danger";
/**
 * A FIELD WITH A FIXED PREFIX OR SUFFIX ("+91", "₹"): the frame is the wrapper, so border,
 * focus colour and focus ring are drawn ONCE, around prefix and input together, exactly as
 * `FIELD` draws them around a lone input. `FIELD_GROUP_INPUT` is the bare input inside it.
 *
 * Putting `FIELD` inside a ringed wrapper is the defect this replaces: the input kept its own
 * focus ring and border colour, which the wrapper's `overflow-hidden` clipped into a thick
 * green bar on its left edge, beside a second ring around the whole group.
 * `FIELD_GROUP_AFFIX` is the "+91" / "₹" cell, laid OVER the input's left padding and deaf to
 * the pointer, so a tap on the prefix lands in the field; give the input a left padding
 * wider than the affix (`pl-14` for "+91").
 */
export const FIELD_GROUP =
  "relative flex min-w-0 items-stretch overflow-hidden rounded-md border border-line bg-surface touch:min-h-11 transition-[border-color,box-shadow] duration-(--duration-fast) ease-out focus-within:border-brand has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand/25 has-[[aria-invalid=true]]:border-danger";
export const FIELD_GROUP_INPUT =
  "min-w-0 flex-1 border-0 bg-transparent py-1.5 pr-3 text-sm text-ink placeholder:text-ink-faint outline-none focus:outline-none focus-visible:outline-none";
export const FIELD_GROUP_AFFIX =
  "pointer-events-none absolute inset-y-0 left-0 flex select-none items-center border-r border-line bg-surface-muted px-3 text-sm text-ink-muted";
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
// `[&:not(:disabled)]:hover` rather than `enabled:hover`: `:enabled` never matches an `<a>`,
// so these constants on a `<Link>` would have no hover state at all.
export const PRIMARY_BUTTON =
  "inline-flex items-center gap-2 rounded-md bg-brand-strong px-4 py-2 text-sm font-semibold text-white [&:not(:disabled)]:hover:bg-brand-deep disabled:cursor-not-allowed disabled:bg-ink/[0.08] disabled:text-ink-faint touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 press";

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
  "inline-flex items-center gap-2 rounded-md bg-brand-strong px-5 py-3 text-base font-semibold text-white [&:not(:disabled)]:hover:bg-brand-deep disabled:cursor-not-allowed disabled:bg-ink/[0.08] disabled:text-ink-faint touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 press";

/** The same buttons at the size an inline action wants. */
export const PRIMARY_BUTTON_SM =
  "inline-flex items-center gap-1.5 rounded-md bg-brand-strong px-3 py-1.5 text-xs font-semibold text-white [&:not(:disabled)]:hover:bg-brand-deep disabled:cursor-not-allowed disabled:bg-ink/[0.08] disabled:text-ink-faint touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 press";
export const SECONDARY_BUTTON_SM =
  "inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink [&:not(:disabled)]:hover:bg-black/5 disabled:cursor-not-allowed disabled:border-line disabled:bg-ink/[0.04] disabled:text-ink-faint dark:[&:not(:disabled)]:hover:bg-white/5 touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 press";
// Both sizes label in ink: a muted label reads as disabled beside a primary button (D-771).
export const SECONDARY_BUTTON =
  "inline-flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink [&:not(:disabled)]:hover:bg-black/5 disabled:cursor-not-allowed disabled:border-line disabled:bg-ink/[0.04] disabled:text-ink-faint dark:[&:not(:disabled)]:hover:bg-white/5 touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 press";
/**
 * The button that does something a person cannot undo.
 *
 * Rose, deliberately not `PRIMARY_BUTTON`: the control that stops every tenant's
 * dialling must not sit in the same visual class as "Create campaign". An operator's
 * eye should refuse to find it there.
 */
/**
 * A small icon-only control inside a row: remove, move up, move down. Ink-muted with a
 * hover tint, never a filled or bordered block, so a list of rows does not read as a
 * toolbar per row. Destructive red is for the confirmation, not for the row's ×. Always
 * give it an `aria-label` that names the row ("Remove amount").
 */
export const QUIET_ICON_BUTTON =
  "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-muted hover:bg-ink/[0.05] hover:text-ink disabled:cursor-not-allowed disabled:text-ink-faint disabled:hover:bg-transparent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11";

export const DANGER_BUTTON =
  "inline-flex items-center gap-2 rounded-md bg-danger px-4 py-2 text-sm font-semibold text-white [&:not(:disabled)]:hover:bg-danger/90 disabled:cursor-not-allowed disabled:bg-ink/[0.08] disabled:text-ink-faint touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger focus-visible:ring-offset-2 press";

/**
 * A MODAL: a bottom sheet on a phone, a centred card from `sm`. Class strings rather than
 * a component for the reason the buttons above are: each modal keeps its own focus trap
 * and ids, and only the frame is shared.
 *
 * On a phone the card sits at the bottom edge, where the thumb is, at full width; it
 * scrolls inside itself (`max-h` in `dvh`, so the browser's own bars are allowed for)
 * instead of running off a short or landscape screen with its buttons out of reach, and
 * pads past the home indicator. The actions stack full width there, primary on top.
 */
export const MODAL_SCRIM =
  "scrim-enter fixed inset-0 z-modal flex items-end justify-center bg-black/40 sm:items-center sm:p-4";
export const MODAL_PANEL =
  "modal-enter w-full max-w-md max-h-[calc(100dvh-1.5rem)] overflow-y-auto overscroll-contain rounded-t-2xl border border-line bg-surface p-4 pb-[calc(1rem+env(safe-area-inset-bottom,0px))] shadow-overlay outline-none sm:max-h-[calc(100dvh-2rem)] sm:rounded-card sm:p-6";
export const MODAL_ACTIONS =
  "mt-5 flex flex-col-reverse gap-2 *:justify-center sm:flex-row sm:flex-wrap sm:justify-end";

/**
 * ONE MESSAGE, said quietly: a tone rule on the left, the title in ink, the detail in
 * muted ink, and the one action inline at the end.
 *
 * Not a tinted card. The old box (cream or rose fill, border, icon medallion, bold
 * coloured title, every line in the tone colour) made every notice look equally urgent
 * and read as generated (founder, 11 Oct 2026). Colour now marks only the rule, the
 * optional dot and whatever the caller makes actionable.
 *
 * - `title`: the one line. Short, plain, no em dash, no "This account is…".
 * - `children`: at most a line of detail. Anything longer goes in `info` (an ⓘ).
 * - `action`: a button or link, rendered inline at the end of the bar.
 * - Several blockers or steps are not one message: use `ChecklistRows`.
 * - `icon` is accepted for old callers and NOT rendered: the medallion was the slop.
 */
export function NoticeBox({
  tone,
  title,
  children,
  action,
  info,
  infoLabel,
  dot = false,
  role,
  className,
}: {
  tone: NoticeTone;
  /** Accepted and ignored. See the docstring. */
  icon?: ReactNode;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  info?: ReactNode;
  /** What the ⓘ is about ("About <infoLabel>"); defaults to the title when it is text. */
  infoLabel?: string;
  dot?: boolean;
  role?: "status" | "alert" | "note";
  className?: string;
}) {
  const tipLabel = infoLabel ?? (typeof title === "string" ? title : "this notice");
  return (
    <div
      data-notice={tone}
      role={role}
      className={clsx(
        "flex flex-wrap items-center gap-x-4 gap-y-2 border-l-2 bg-surface py-1 pl-3 text-body text-ink",
        NOTICE_BAR[tone],
        className,
      )}
    >
      <div className="min-w-0 flex-1 basis-60">
        {/* A div, not a p: callers pass a heading (FailureScreen's <h1>), and a p cannot hold one. */}
        {title && (
          <div className="flex items-center gap-2 font-medium text-ink">
            {dot && <span aria-hidden className={clsx("h-2 w-2 shrink-0 rounded-full", NOTICE_DOT[tone])} />}
            <div className="min-w-0">{title}</div>
            {info && <InfoTip label={tipLabel}>{info}</InfoTip>}
          </div>
        )}
        {children && (
          <div className={clsx("min-w-0", title ? "mt-0.5 text-ink-muted" : "text-ink")}>
            {children}
          </div>
        )}
      </div>
      {/* With no title, the ⓘ sits with the action rather than inside the sentence: its
          44px touch target would otherwise open a gap in the line it interrupts. */}
      {(action || (!title && info)) && (
        <div className="flex w-full max-w-full flex-wrap items-center gap-2 sm:w-auto sm:shrink-0">
          {!title && info && <InfoTip label={tipLabel}>{info}</InfoTip>}
          {action}
        </div>
      )}
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
 * THE CONTENT RAIL — the one width both consoles lay their content out on.
 *
 * `<main>` has always capped its content at 1280px and centred it, and the two shells'
 * page headers had no cap at all: they sat flush against the viewport's own `px-8`. On
 * anything wider than about 1600px that put the page title and the notification bell
 * OUTSIDE the column of content they belong to — the title several centimetres to the
 * left of the first card under it, the bell the same distance to the right of that card's
 * right edge — which reads as a header with the wrong padding and is really a header on
 * the wrong rail. Nothing is visible below ~1600px, which is why it survived: at 1280 the
 * cap is not reached and the two agree exactly.
 *
 * A shared constant rather than a fourth copy of the literal: the number is the property
 * that has to match across four elements in two shells, and a width that has to agree in
 * four places is the one that drifts.
 *
 * The width is the CSS variable `--shell-rail` (`globals.css`), set on the shell root, so
 * the header and the content always read the same number. It is the same on every page:
 * a wider rail on one tab moved the header and the page sideways whenever the tab changed
 * (founder, 22 Oct 2026), and a per-page `max-w-*` on the content alone would put the
 * header back on a different rail from the page under it.
 */
export const SHELL_RAIL_CLASS = "mx-auto w-full max-w-(--shell-rail)";

/**
 * The shells' `<main>`: the one scroll container and its gutters. The sticky page bar
 * (`console/stickyPageBar`) cancels exactly this padding, so the two are kept together
 * here rather than as literals in each shell.
 */
export const SHELL_MAIN_CLASS = "relative flex-1 overflow-y-auto bg-surface px-4 py-4 lg:px-8 lg:py-8";

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
      className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-toast focus:rounded-md focus:border focus:border-line focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-ink focus:shadow-raised"
    >
      Skip to main content
    </a>
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
            className="h-8 animate-pulse rounded bg-black/5 motion-reduce:animate-none dark:bg-white/10"
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
  /** In sentence case, as written: the chip does not change its case. */
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
        "press rounded-full px-3 py-1.5 text-xs touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2",
        active
          ? "border border-ink bg-ink/[0.06] font-medium text-ink"
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

/**
 * A phone number for READING: "+91 98765 43210" from the E.164 "+919876543210".
 *
 * Display only. The E.164 string stays the value everywhere else — in request bodies, in
 * what a copy button puts on the clipboard, in what a test or a CSV compares — and it is
 * never put in a URL (hard rule 6). An Indian mobile (+91 and ten digits) is grouped 5-5,
 * the way it is written on a business card; every other shape is returned unchanged
 * rather than guessed at, because a wrongly grouped number reads as a different number.
 */
export function formatPhone(e164: string | null | undefined): string {
  if (!e164) return "—";
  const india = /^\+91(\d{5})(\d{5})$/.exec(e164);
  return india ? `+91 ${india[1]} ${india[2]}` : e164;
}

/** A count, grouped the way an Indian reader groups one (1,20,000 — not 120,000). */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-IN");
}

/**
 * A count with its noun agreeing: "1 day", "3 days", never "3 day(s)". `plural` defaults
 * to `singular + "s"`; pass it for nouns that do not take a plain "s" ("entries").
 */
export function formatCountOf(
  value: number | null | undefined,
  singular: string,
  plural: string = `${singular}s`,
): string {
  return `${formatCount(value)} ${value === 1 ? singular : plural}`;
}

// Rupees and other figures: the display rule, its exceptions and why live in
// lib/numberDisplay.ts. Re-exported here because every screen already imports its
// formatters from this module.
export {
  formatDecimal,
  formatINR,
  formatINRExact,
  formatPercent,
  formatRupeeRateExact,
} from "@/lib/numberDisplay";

/**
 * A WHOLE COUNT as the server sent it, grouped for reading — not `formatINR`.
 *
 * Two callers, both money's shadow: a monthly call-minute VOLUME and the CHARACTER count
 * behind it. `billing/rates.py` multiplies each by a rupee figure to price a subscription,
 * so both cross the wire as exact decimal strings and neither is parsed here (hard rule 7).
 * The name is deliberately not `formatMinutes`: it is one rule about counts, and a
 * minute-shaped name on the function printing characters is how the next reader is misled
 * about a unit.
 *
 * What a count needs that a rupee figure does not is a DROPPED fraction: "2314.814814…" is
 * a real answer from an exact division and "2,314 min/mo" is what an operator acts on,
 * while `formatINR`'s two forced decimals would print "₹2,314.81" of minutes — a unit error
 * on the face of a screen.
 *
 * The digits are the server's: split on the point, discard the fraction, group the integer
 * part Indian-style exactly as `formatINR` does. No `Number()`, no rounding decision —
 * truncation is stated rather than implied, because a volume is a threshold an operator
 * compares against and rounding 2,314.8 up to 2,315 would make the screen disagree with the
 * break-even the server computed.
 */
export function formatWholeCount(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const negative = value.startsWith("-");
  const [whole = "0"] = value.replace(/^[-+]/, "").split(".");
  const head = whole.length > 3 ? whole.slice(0, -3) : "";
  const tail = whole.slice(-3);
  const grouped = head
    ? `${head.replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${tail}`
    : tail;
  return `${negative ? "-" : ""}${grouped}`;
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

/**
 * Times are stored as instants and shown in IST, the platform's standard time (D-709).
 *
 * The unparseable arm is not defensive padding: `new Date("…").toLocaleString()` renders
 * the literal words **"Invalid Date"**, and this is the helper all hundred-odd timestamps
 * on this console go through. Every other date helper in this file and beside it already
 * guards it (`formatCallCap`, `istDateToInstant`, the quality screen's `calendarDay`);
 * this one did not, so one malformed instant anywhere in an API response put a phrase from
 * a JavaScript runtime in front of a shop owner. "—" is the same absence marker the null
 * arm above already uses, and it is honest: we do not know when this happened.
 */
export function formatIST(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * The calendar day in India an instant falls on, as a person reads a deadline: "Saturday,
 * 7 November". `null` when there is no instant or it does not parse, so the caller words the
 * sentence without a date rather than printing a placeholder inside one.
 */
export function formatISTDay(value: string | null | undefined): string | null {
  if (!value) return null;
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return null;
  return at.toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata",
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

/**
 * The calendar day in India an instant falls on, with the year: "27 Oct 2027". For a date a
 * year or more away, such as when credit lapses, where `formatIST`'s day and month alone
 * would not say which year. `null` when there is no instant or it does not parse.
 */
export function formatISTDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return null;
  return at.toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/**
 * The calendar day in India, as `YYYY-MM-DD` — for naming a file after the day it was taken.
 *
 * `new Date().toISOString().slice(0, 10)` is the spelling this replaces, and it is wrong
 * for the whole of an Indian small hours: at 00:30 IST, UTC is still on the previous day,
 * so the CSV a client exported on the 4th was called `leads-2026-09-03.csv`. Those two
 * files — the leads export and the subject-access JSON — are the ones a client is most
 * likely to keep, forward and later have to place in time, which is exactly when a
 * filename that is a day out costs something. `campaigns/page.tsx::todayInputValue`
 * already carried the warning for a date picker's `max`; the filenames had not heard it.
 *
 * `en-CA` because it formats as `YYYY-MM-DD` — the same trick `currentISTMonth` was
 * already using, which is why that helper now reads its answer from here rather than
 * spelling the conversion a second time.
 */
export function istDateStamp(at: Date = new Date()): string {
  return at.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
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
 * An instant as `YYYY-MM-DD HH:mm IST`, year and zone spelled out — for a time that is read
 * as text rather than seen in a table, such as a fact handed to the copilot (D-709: IST is
 * the platform's standard time). `absent` when there is no instant or it does not parse.
 */
export function formatISTStamp(value: string | null | undefined, absent = "—"): string {
  const local = formatISTInput(value);
  return local ? `${local.replace("T", " ")} IST` : absent;
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

/**
 * The same conversion for a DATE-ONLY field: `<input type="date">` → midnight IST.
 *
 * A `type="date"` value is a calendar date, not an instant, and every one of them on this
 * console names a day in India — the day a registrar issued a letter, the day a client
 * collected consent. The API stores an instant, so a day has to be given a time, and
 * WHICH midnight it is given is the whole of the correctness:
 *
 * - `new Date("2026-08-10")` is UTC midnight = 05:30 IST, which for "today" is a moment
 *   that has not happened yet, and the server refuses a future date.
 * - `new Date("2026-08-10T00:00:00")` is midnight in the BROWSER's zone, which is the
 *   defect `formatISTInput` above documents at length. East of IST it lands on the
 *   previous IST date outright — Auckland midnight is 16:30 IST the day before — so the
 *   same digits record a different day depending on who typed them, and the value is
 *   then read back with `formatIST`, which is where the disagreement becomes visible.
 * - Midnight IST is the earliest instant of the day the person actually picked, in the
 *   zone every reader of it is in. It is never in the future when the day is not.
 *
 * Separate from `istInputToInstant` rather than folded into it: that one takes a
 * `datetime-local` and would silently accept a bare date by appending nothing, and a
 * helper that guesses which of two input types it was handed is a helper that guesses.
 */
export function istDateToInstant(value: string): string | null {
  const typed = value.trim();
  if (typed === "") return null;
  const at = new Date(`${typed}T00:00:00+05:30`);
  return Number.isNaN(at.getTime()) ? null : at.toISOString();
}
