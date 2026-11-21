/**
 * The client shell's page title: the sidebar's own label for the screen, or — for a screen
 * the sidebar does not list — its own name. Without the second, every unlisted screen matched
 * the Dashboard entry (`/c/<slug>` is a prefix of every path) and the Go live guide was
 * headed "Dashboard" (e2e audit OB-9).
 */

import type { LeadNouns } from "./businessCapabilities";
import { clientNavigation, inAccountWords } from "./clientNav";
import { lookup } from "./lookup";
import { currentNavItem } from "./nav";

/** Screens reached from a flow rather than the sidebar, by the path segment after the slug. */
const UNLISTED: Readonly<Record<string, string>> = {
  "go-live": "Go live",
};

/** `nouns` names the leads screens in the account's words (`useLeadNouns`); omitted: "Leads". */
export function clientPageTitle(slug: string, pathname: string, nouns?: LeadNouns): string {
  const segment = pathname.slice(`/c/${slug}/`.length).split("/")[0] ?? "";
  const unlisted = pathname.startsWith(`/c/${slug}/`) ? lookup(UNLISTED, segment) : undefined;
  if (unlisted !== undefined) return unlisted;
  const groups = clientNavigation(slug);
  const items = (nouns ? inAccountWords(groups, slug, nouns) : groups).flatMap((group) => group.items);
  return currentNavItem(items, pathname)?.label ?? "Dashboard";
}
