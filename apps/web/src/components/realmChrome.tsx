/**
 * WHICH CONSOLE AM I IN? — answered where an operator already looks: at the block that
 * says who they are signed in as.
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
 * shape. So the identity block that names the realm is rendered on a solid dark, and the
 * screen assistant that floats over every screen in both consoles wears the same dark in
 * this realm (`components/copilot/`).
 *
 * ## THE RAIL IS GONE (founder, 9 Sep 2026), AND THIS FILE USED TO EXPORT IT
 *
 * There was a second half to the signal: `AdminRealmRail`, an `h-1.5` slate bar across the
 * top of the whole admin window, above the sidebar as well as the content — which is why
 * the admin shell was a COLUMN where the client shell is a row. The founder saw it, asked
 * what it was, was told it was the deliberate "you are in the admin realm" marker, and
 * chose to remove it entirely. His ground: the sidebar already says "Calevate admin /
 * Operator console" and the identity block already says who you are signed in as, so the
 * realm is stated twice in words before any chrome is read.
 *
 * What that costs, said plainly rather than left implicit: the marker no longer covers the
 * top of the window, so an operator whose eye is on the header rather than on the sidebar
 * has one fewer place to catch it. What survives is the identity block below and the
 * assistant's launcher and panel — both of which sit where an operator's eye goes when the
 * question is actually "whose account is this", and both of which are on screen in every
 * state of the shell including the collapsed rail. The admin shell is now the same row
 * `data-app-shell` the client shell is; nothing else moved.
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
 */

/**
 * The dark treatment for the admin sidebar's identity block — where an operator's eye goes
 * to check who they are signed in as, and, since the rail was removed, the shell's only
 * realm marker that is not a word.
 *
 * A class string rather than a component because the block it dresses is not shared: the
 * two shells' identity footers say different things and are built separately, and wrapping
 * one of them in a component would invent a shared thing that does not exist.
 */
export const ADMIN_REALM_IDENTITY_CLASS = "bg-slate-900 text-white dark:bg-slate-800";
