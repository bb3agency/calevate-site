/* eslint-disable @next/next/no-img-element -- FILE-SCOPED AND ARGUED, not silenced.
   The rule's advice is `next/image`, which in Next 15 needs `sharp` — a native
   dependency this lockfile does not carry, and adding one for a logo is a supply-chain
   decision (hard rule 9) with a compile on the VPS attached. What the rule is protecting
   against is an oversized image and a layout shift; `scripts/generate_brand_assets.py`
   answers the first (412 KB master -> 21 KB asset) and the stated width/height on every
   element below answers the second. This is the whole file's subject, so one directive
   here beats three identical ones inline. */
/**
 * The Calevate logo, in the three forms the founder supplied — and ONE definition of each.
 *
 * Five screens carried a placeholder before this: a lucide glyph inside a green chip on
 * both console sidebars, another on the marketing header and footer, and the bare word
 * "Calevate" on the auth frame. Five copies of "what our logo is" is the drift this repo
 * treats as a defect even while every copy still works, so they all come here.
 *
 * ## The one thing that would have gone wrong, and why it does not
 *
 * **The mark is GREEN INK ON TRANSPARENCY, not a white glyph.** Every placeholder it
 * replaces sat inside a `bg-brand-strong` chip with `text-white`, and dropping the real
 * mark into that chip renders dark green on dark green — invisible, and invisible in a
 * way that looks deliberate. So the chip goes with the glyph; the mark sits on the
 * surface it is on, which is what the artwork is drawn for.
 *
 * ## Why `<img>` and not `next/image`
 *
 * Next 15's image optimisation needs `sharp`, which is not in this lockfile. Adding a
 * native dependency for a logo is a supply-chain decision (hard rule 9) with a compile on
 * the VPS attached to it, and the thing it would buy — right-sized variants — is bought
 * instead by `scripts/generate_brand_assets.py`, which is run by hand and whose output is
 * committed. The masters are 1024x1024 and 2172x724 (412 KB for the square mark alone);
 * what ships here is 21 KB. `width`/`height` are stated on every one of them, so the
 * layout never shifts as they load.
 *
 * ## The canvases are not tight, and the sizes below account for it
 *
 * Measured from the masters rather than guessed: the wordmark and lockup are 3:1
 * canvases whose ink occupies 54% of the height (rows 147..540 of 724), and the square
 * mark's ink is 996x830 centred in 1024x1024. So a wordmark asked to be 40px tall draws
 * about 22px of ink, and the square mark in a 36px box draws 36x30. The numbers passed by
 * callers are canvas sizes; the comments beside them say what ink that yields.
 *
 * ## The size is stated ONCE
 *
 * The first spelling of these call sites passed `height={40}` AND `className="h-10"` —
 * the same number twice, in two languages, with nothing keeping them equal. An `<img>`
 * carrying `width` and `height` attributes and no CSS already renders at exactly that
 * size, so the attributes do the whole job and the classes are gone. A caller that
 * genuinely needs responsive sizing can still pass `className`; none does.
 */

const BRAND = "/brand";

/**
 * The square mark alone — the sidebars, collapsed or not, and anywhere the wordmark has
 * no room. Decorative BY DEFAULT (`alt=""`): every caller renders the product name in
 * text beside it, so a non-empty alt would have a screen reader say "Calevate" twice.
 */
export function BrandIcon({
  size = 36,
  className = "",
}: {
  /** Canvas px. The ink is 97% of this wide and 81% of it tall, centred. */
  size?: number;
  className?: string;
}) {
  return (
    <img
      src={`${BRAND}/icon.png`}
      alt=""
      width={size}
      height={size}
      className={`shrink-0 ${className}`}
    />
  );
}

/**
 * Mark + "calevate". Replaces the product name rather than sitting beside it, so this one
 * carries a real `alt` — it IS the name, and a decorative logo here would leave the
 * marketing header and the sign-in door with no accessible name at all.
 */
export function BrandWordmark({
  height = 40,
  className = "",
}: {
  /** Canvas px. 3:1, so the width is 3x this and the ink is ~54% of it tall. */
  height?: number;
  className?: string;
}) {
  return (
    <img
      src={`${BRAND}/wordmark.png`}
      alt="Calevate"
      width={height * 3}
      height={height}
      className={className}
    />
  );
}

/** Mark + "calevate" + the tagline. The footer, where a tagline reads as a signature. */
export function BrandLockup({
  height = 40,
  className = "",
}: {
  height?: number;
  className?: string;
}) {
  return (
    <img
      src={`${BRAND}/lockup.png`}
      alt="Calevate — AI voice calling agents"
      width={height * 3}
      height={height}
      className={className}
    />
  );
}
