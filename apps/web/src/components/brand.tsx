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
 * committed. The masters are 1024x1024 and 2172x724/2171x724 (412 KB for the square mark
 * alone);
 * what ships here is 21 KB. `width`/`height` are stated on every one of them, so the
 * layout never shifts as they load.
 *
 * ## The canvases are not tight, and the sizes below account for it
 *
 * Measured from the masters rather than guessed, and RE-MEASURED when the founder
 * replaced the two lockups on 5 Sep 2026 — these numbers describe the artwork that is
 * actually in the repository, so they are re-taken whenever it changes rather than
 * carried forward:
 *
 *   - wordmark master (without tagline), 2171x724: ink rows 140..536 — 397px, 54.8% of
 *     the height — and cols 88..2106.
 *   - lockup master (with tagline), 2172x724: ink rows 143..544 — 402px, 55.5% — and
 *     cols 87..2095.
 *   - square mark, unchanged: ink 996x830 centred in 1024x1024.
 *
 * So a wordmark asked to be 40px tall draws about 22px of ink, and the square mark in a
 * 36px box draws 36x30. The numbers passed by callers are canvas sizes; the comments
 * beside them say what ink that yields.
 *
 * ⚠ THE TWO LOCKUPS ARE NOT THE SAME CANVAS ANY MORE. The new without-tagline master is
 * 2171 wide against the with-tagline's 2172 — one pixel, 0.05%, invisible — but it means
 * `wordmark.png` and `lockup.png` are both emitted at exactly 720x240 from canvases whose
 * ratios differ in the fourth decimal. That is deliberate: a shared output size keeps the
 * two interchangeable at a call site, and the alternative (a 719-wide wordmark) would put
 * a half-pixel seam on every sidebar to correct a distortion no one can see.
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
  /** Canvas px. 3:1, so the width is 3x this and the ink is ~55% of it tall. */
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

/**
 * The mark below `sm`, the wordmark at `sm` and up — as ONE element and ONE request.
 *
 * The marketing header is the logo, "Sign in" and "Create a workspace" on a single row,
 * and at 320px (an iPhone SE, still common) those three do not fit however the padding is
 * tuned: measured in Chromium, the row wanted 374px of a 320px viewport and produced real
 * horizontal scroll. Shrinking the wordmark alone was not enough — 108px of logo plus
 * 220px of nav plus the shell's own padding is still over — and letting the labels wrap
 * gave a two-line header. A brand system has a square mark precisely for this, and using
 * it here is what it is for.
 *
 * `<picture>` RATHER THAN TWO `<img>` WITH `hidden`/`block`. The two-element version is
 * the obvious spelling and it downloads both files: a `display:none` image is still
 * fetched. `<source media>` is the one mechanism that makes the browser evaluate the
 * query BEFORE choosing what to request, so a phone fetches 21 KB and nothing else.
 *
 * `width`/`height` describe the SQUARE, which is what `<img>` falls back to and what a
 * phone loads; the wordmark's own ratio is carried by `w-auto` beside a stated height, so
 * the row's height never shifts even though its width settles on load. In a flex row with
 * a fixed height that is the trade worth making.
 */
export function BrandHeaderMark({ size = 36, className = "" }: { size?: number; className?: string }) {
  return (
    <picture>
      <source media="(min-width: 640px)" srcSet={`${BRAND}/wordmark.png`} />
      <img
        src={`${BRAND}/icon.png`}
        alt="Calevate"
        width={size}
        height={size}
        className={`h-9 w-auto shrink-0 sm:h-[52px] ${className}`}
      />
    </picture>
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
