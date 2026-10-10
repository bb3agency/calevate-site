/**
 * A CONNECTED SERVICE'S OWN ICON, small, always beside its name and never instead of it
 * (REDESIGN-2). Only services a client connects; never our own telephony, voice or AI
 * vendors (D-679).
 *
 * THE FILES ARE THE BRANDS' OWN, UNMODIFIED, served from `public/brand/services/` and drawn
 * with a plain `<img>` (an SVG loaded as an image cannot run script, and the same-origin
 * `img-src 'self'` already allows it). Sources, read 10 Oct 2026:
 *
 * - `google`: the standard-colour "G", https://developers.google.com/static/identity/images/g-logo.png,
 *   from https://developers.google.com/identity/branding-guidelines. Use it only inside a
 *   "Continue with Google" button beside the words, never on its own, never recoloured.
 * - `google_calendar`, `google_sheets`: the product icons Google hosts on its own Workspace
 *   branding page, https://knowledge.workspace.google.com/static/images/icons/product/{calendar,sheets}.svg
 *   (page: knowledge.workspace.google.com/admin/getting-started/brand-your-internal-communications-with-google-workspace).
 *   Google's co-branding guidance (partnermarketinghub.withgoogle.com/brands/google/use-cases/product-co-branding,
 *   redirected from about.google/brand-resource-center/guidance/apis) allows product icons
 *   in a product UI showing an action and says never to use them by themselves. The
 *   Calendar file gained `viewBox="0 0 192 192"` so it scales; its geometry is untouched.
 *
 * The rest are each brand's own site icon, as its homepage links it in `<link rel="icon">`
 * or `rel="apple-touch-icon"`, downloaded once on 10 Oct 2026 and committed unchanged (no
 * recolouring, no cropping). Trademarks remain their owners'; we show them only beside the
 * service's name, to say which account a client connected.
 * - `whatsapp`: https://static.whatsapp.net/rsrc.php/y1/r/FJbTMJqMap7.svg (www.whatsapp.com).
 * - `meta_cloud`: https://static.xx.fbcdn.net/rsrc.php/yQ/r/0eWKxz9kEoF.webp, 180px
 *   (apple-touch-icon of www.meta.com).
 * - `hubspot`: https://www.hubspot.com/hubfs/HubSpot_Logos/HubSpot-Inversed-Favicon.png, 288px.
 * - `zoho_crm`: https://www.zohowebstatic.com/sites/zweb/images/favicon.ico, 48px. zoho.com/crm
 *   links the Zoho mark, not a CRM product icon.
 * - `razorpay`: https://framerusercontent.com/images/CU1m0xFonUl76ZeaW0IdkQ0M.png, 163px
 *   (the icon razorpay.com links; its site is hosted on Framer).
 * - `aisensy`: https://umsousercontent.com/lib_EyxlwrMuBuWXHRhZ/lde75byhovvwhjj1.png, 96px
 *   (the icon aisensy.com links, fetched without its `?w=32` resize).
 * - `interakt`: https://www.interakt.shop/wp-content/uploads/2025/03/Interakt-FAV.svg.
 * Replace a file only from the same kind of source, and update its line here.
 */

import { lookup } from "@/lib/lookup";

export type ServiceLogoKey =
  | "google"
  | "google_calendar"
  | "google_sheets"
  | "whatsapp"
  | "meta_cloud"
  | "aisensy"
  | "interakt"
  | "zoho_crm"
  | "hubspot"
  | "razorpay";

const KEYS: readonly ServiceLogoKey[] = [
  "google",
  "google_calendar",
  "google_sheets",
  "whatsapp",
  "meta_cloud",
  "aisensy",
  "interakt",
  "zoho_crm",
  "hubspot",
  "razorpay",
];

/** True for a wire string (a credential kind, a provider) this component knows. */
export function isServiceLogoKey(value: string | null | undefined): value is ServiceLogoKey {
  return value !== null && value !== undefined && (KEYS as readonly string[]).includes(value);
}

const FILES: Record<ServiceLogoKey, string> = {
  google: "/brand/services/google-g.png",
  google_calendar: "/brand/services/google-calendar.svg",
  google_sheets: "/brand/services/google-sheets.svg",
  whatsapp: "/brand/services/whatsapp.svg",
  meta_cloud: "/brand/services/meta.webp",
  hubspot: "/brand/services/hubspot.png",
  zoho_crm: "/brand/services/zoho.ico",
  razorpay: "/brand/services/razorpay.png",
  aisensy: "/brand/services/aisensy.png",
  interakt: "/brand/services/interakt.svg",
};

/** Wire names that mean the same service as a key above. */
const ALIASES: Record<string, ServiceLogoKey> = {
  google_calendar: "google_calendar",
  google_sheets: "google_sheets",
  sheet: "google_sheets",
  zoho: "zoho_crm",
};

export function serviceKeyFor(value: string | null | undefined): ServiceLogoKey | null {
  if (!value) return null;
  return lookup(ALIASES, value) ?? (isServiceLogoKey(value) ? value : null);
}

export function ServiceLogo({
  service,
  className = "h-4 w-4",
}: {
  service: ServiceLogoKey | string | null | undefined;
  className?: string;
}) {
  const key = serviceKeyFor(service);
  const file = key ? FILES[key] : undefined;
  if (!file) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- a 16px static brand file; next/image adds nothing here
    <img src={file} alt="" aria-hidden width={16} height={16} className={`inline-block shrink-0 object-contain ${className}`} />
  );
}
