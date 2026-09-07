/**
 * WHICH CONSOLE AM I IN? — answered by the CHROME, before anything is read.
 *
 * ## The defect this closes
 *
 * The two shells were the same shell. Same 72px `bg-surface` header, same `bg-app` body,
 * same `bg-brand-soft`/`brand-strong` nav highlight, same green. The only thing that told
 * an operator with both tabs open which one they were looking at was the words "Admin
 * realm" in the sidebar footer and a `hidden sm:inline-block` badge in the header — text,
 * at the two ends of the window, one of which is not on screen at all on a phone.
 *
 * An operator must never believe they are inside a client account. Everything they do in
 * this realm is cross-tenant and audited, and the actions that differ most between the two
 * consoles — a spend cap, a hold, a maintenance window that sheds live traffic — are the
 * ones a misread costs most. Peripheral vision does not read words; it reads colour and
 * shape. So the difference is made structural: a solid dark rail across the top of the
 * whole window, and the identity block that names the realm rendered on the same dark.
 *
 * ## Why slate, and why only the admin shell
 *
 * SLATE because it is the one family that is neither realm's brand nor any of this app's
 * meaning colours: green is the product's brand and the client shell's highlight, amber is
 * "view as client" (D-22) and the offline strip, rose is a refusal. A neutral near-black
 * cannot be confused with any of those, and it reads at a glance as "tooling" rather than
 * as a state something is in.
 *
 * ONLY the admin shell changes. The client console is what a clinic owner sees all day and
 * it is correct as it is; the marker belongs on the surface that is unusual, and an
 * operator learns one exception rather than two conventions.
 *
 * `bg-slate-900` light / `bg-slate-200` dark: the rail has to stay the DARKEST or the
 * LIGHTEST thing on the window in either theme, and a near-black rail on a near-black dark
 * ground would disappear — which is the one failure this component cannot have.
 */

/**
 * The rail. Decorative by construction, so it is `aria-hidden` and carries no text: what
 * it says is already said in words twice over (the sidebar's "Calevate admin / Operator
 * console" and the identity block below it), and a screen-reader user gets those. This is
 * for the eye that is not looking.
 */
export function AdminRealmRail() {
  return (
    <div
      aria-hidden
      data-admin-realm-rail
      className="h-1.5 w-full shrink-0 bg-slate-900 dark:bg-slate-200"
    />
  );
}

/**
 * The dark treatment for the admin sidebar's identity block — the second half of the same
 * signal, at the other end of the panel, where an operator's eye goes to check who they
 * are signed in as.
 *
 * A class string rather than a component because the block it dresses is not shared: the
 * two shells' identity footers say different things and are built separately, and wrapping
 * one of them in a component would invent a shared thing that does not exist.
 */
export const ADMIN_REALM_IDENTITY_CLASS = "bg-slate-900 text-white dark:bg-slate-800";
