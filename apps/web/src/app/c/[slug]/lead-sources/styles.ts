/* Split so the JSON box can be smaller without `${FIELD} text-xs` — two font-size
   utilities on one element, where Tailwind's emission order decides the winner and
   `text-sm` happens to be the one that does. */
/* `min-w-0 max-w-full`: an <input> with no width utility sizes to its `size`
   attribute (~20 characters), which at the 16px this repo now gives touch devices
   is ~256px — 2px wider than the 254px card it sits in at 320px, so it painted
   across the border. A CAP rather than `w-full`: these sit in flex rows where a
   forced full width would restyle the desktop console, and on desktop there is
   room so the cap never binds. `min-w-0` because a flex item will not otherwise
   shrink below its own min-content. */
export const FIELD_BASE =
  "rounded-md border border-line bg-surface px-3 py-1.5 text-ink placeholder:text-ink-faint min-w-0 max-w-full touch:min-h-11";
export const FIELD = `${FIELD_BASE} text-sm`;
export const QUIET_BUTTON =
  "flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5";
export const CODE = "break-all rounded bg-app px-2 py-1 font-mono text-xs text-ink";
