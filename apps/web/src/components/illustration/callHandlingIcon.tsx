/**
 * "Call handling": a handset with two slider knobs, for the settings page that decides how
 * every agent ends a caller's turn and its calls (D-751). Lucide has no phone-plus-settings
 * glyph, and a bare phone would collide with Call logs and Phone numbers in the same nav.
 *
 * Drawn on Lucide's grid (24 units, 2-unit stroke, round caps, `currentColor`) so it sits
 * beside the library's icons without a visible change of hand. The handset is Lucide's
 * `phone` path; the sliders use the space its curve leaves free in the top right.
 */
export function CallHandlingIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <path d="M13.832 16.568a1 1 0 0 0 1.213-.303l.355-.465A2 2 0 0 1 17 15h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2A18 18 0 0 1 2 4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-.8 1.6l-.468.351a1 1 0 0 0-.292 1.233 14 14 0 0 0 6.392 6.384" />
      <path d="M14 3h1.5M20 3h1" />
      <circle cx={17.5} cy={3} r={1.5} />
      <path d="M14 9h4" />
      <circle cx={19.5} cy={9} r={1.5} />
    </svg>
  );
}
