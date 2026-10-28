import type { MemberRole } from "@/lib/api/members";

/**
 * The roles this console offers, in the order the picker lists them. One spelling, read
 * by the screen, the copilot declaration and every row's dropdown.
 */
export const ROLES: MemberRole[] = ["owner", "staff"];

/**
 * One short line per role for the invite row. `ROLE_COPY[role].can` (the full list) is the
 * explanation behind the ⓘ beside it; this is what a phone shows by default.
 */
export const ROLE_SHORT: Record<MemberRole, string> = {
  owner: "Everything, including billing and the team.",
  staff: "Leads, calls and agents. No billing.",
};
