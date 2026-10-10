/**
 * One client's pages, grouped as D-661 sets them out: Overview, Agents, Numbers, Money,
 * Compliance, People, Settings, Activity. Every item is a ROUTE under
 * `/admin/tenants/<id>`, not a search param: each of these pages has its own reads, its own
 * audited writes and often its own unsaved state, so they cannot share one mounted screen
 * the way `SettingsLayout`'s sections do.
 *
 * The section menu, the command palette and the tests all read this list, so a page that
 * is added or renamed here is renamed everywhere at once.
 */

export interface TenantSection {
  /** Path under `/admin/tenants/<id>`, "" for the overview. */
  path: string;
  label: string;
  /** Other paths this item answers for, e.g. a route that redirects into it. */
  alsoMatches?: readonly string[];
}

export interface TenantSectionGroup {
  label: string;
  items: readonly TenantSection[];
}

export const TENANT_SECTION_GROUPS: readonly TenantSectionGroup[] = [
  { label: "Overview", items: [{ path: "", label: "Overview" }] },
  { label: "Agents", items: [{ path: "/agents", label: "Agents" }] },
  { label: "Numbers", items: [{ path: "/numbers", label: "Numbers" }] },
  {
    label: "Money",
    items: [
      { path: "/credits", label: "Credits" },
      { path: "/commercials", label: "Commercials" },
      { path: "/spend", label: "Spend" },
      { path: "/invoice", label: "Invoice" },
    ],
  },
  {
    label: "Compliance",
    items: [
      // Named for the question ("why can this client not have a number") rather than for
      // either record: both our identity check and the carrier's application live here.
      { path: "/kyc", label: "Identity & carrier" },
      { path: "/readiness", label: "Before their first call" },
      { path: "/dnd-scrub", label: "DND scrub" },
      { path: "/first-campaign-review", label: "Campaign review" },
      { path: "/campaign-setup", label: "Campaign setup" },
    ],
  },
  // Members and invitations are one page; `/invitations` redirects into it.
  {
    label: "People",
    items: [{ path: "/members", label: "People", alsoMatches: ["/invitations"] }],
  },
  {
    label: "Settings",
    items: [
      { path: "/profile", label: "Business details" },
      { path: "/lead-details", label: "Lead details" },
      { path: "/feature-flags", label: "Feature flags" },
      { path: "/llm-model", label: "Language model" },
      { path: "/lifecycle", label: "Account state" },
      { path: "/closure", label: "Closing the account" },
    ],
  },
  { label: "Activity", items: [{ path: "/activity", label: "Activity" }] },
];

export const TENANT_SECTIONS: readonly TenantSection[] = TENANT_SECTION_GROUPS.flatMap(
  (group) => group.items,
);

export function tenantBase(tenantId: string): string {
  return `/admin/tenants/${tenantId}`;
}

export function tenantSectionHref(tenantId: string, section: TenantSection): string {
  return `${tenantBase(tenantId)}${section.path}`;
}

/**
 * The item `pathname` belongs to: the longest matching path segment wins, so
 * `/agents/<id>/prompt` lands on Agents. The overview matches only its own path; an
 * unknown sub-route marks nothing rather than claiming to be the overview.
 */
export function currentTenantSection(
  tenantId: string,
  pathname: string,
): TenantSection | undefined {
  const base = tenantBase(tenantId);
  if (pathname !== base && !pathname.startsWith(`${base}/`)) return undefined;
  const rest = pathname.slice(base.length).replace(/\/$/, "");
  let best: TenantSection | undefined;
  let bestLength = -1;
  for (const section of TENANT_SECTIONS) {
    for (const path of [section.path, ...(section.alsoMatches ?? [])]) {
      const hit = path === "" ? rest === "" : rest === path || rest.startsWith(`${path}/`);
      if (hit && path.length > bestLength) {
        best = section;
        bestLength = path.length;
      }
    }
  }
  return best;
}
