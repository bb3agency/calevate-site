"use client";

import type { Lead, Member } from "@/lib/api/leads";

/**
 * Who owns this lead — THE one assignment control, shared by the leads table, the board
 * and the lead's own screen.
 *
 * A file of its own rather than three copies or an export out of a `page.tsx`: three
 * surfaces let a client change an owner, and the second copy of a control is where a
 * design language starts to drift (`FilterChip` in `components/ui.tsx` carries the same
 * note about the same mistake).
 *
 * Three states, and telling them apart is the whole job:
 *
 * - **The team list arrived and this session may write** → a real `<select>` whose
 *   options are the account's members plus "Unassigned". Choosing the blank option
 *   sends an explicit `null`, which is how an owner who leaves is recorded as an event
 *   rather than inferred from a later silence (`crm.routes.patch_lead`).
 * - **This session may not write** (staff without the permission, or a D-22 operator)
 *   → the select is DISABLED and carries the server's own reason as its title, so the
 *   explanation is on the control and not a screenful away.
 * - **The team list did not load** → no select at all. The owner is still named,
 *   because `assigned_to_name` came down with the ROW and is the server's own answer;
 *   what is missing is the list of people to change it to. An empty dropdown here
 *   would say "you have no colleagues", which is a claim about the business made from
 *   a request that never landed (BUILD-LOG §52).
 *
 * The unassigned case reads "Unassigned" and never a blank cell: a blank is
 * indistinguishable from a column that failed to render.
 */
export function AssigneeSelect({
  lead,
  members,
  unavailableReason,
  disabled,
  onChange,
  className,
}: {
  lead: Lead;
  members: Member[] | undefined;
  unavailableReason: string | null;
  disabled: boolean;
  onChange: (userId: string | null) => void;
  className: string;
}) {
  // `assigned_to_name` is null for an unassigned lead AND for an owner this account can
  // no longer name — a member who has left. The two are different sentences and the
  // server tells them apart with `assigned_to`, so the screen does too.
  const orphaned = lead.assigned_to != null && !lead.assigned_to_name;
  const label = lead.assigned_to_name ?? (orphaned ? "No longer on this account" : "Unassigned");

  if (!members) {
    return (
      <span className="text-xs text-ink-muted" title={unavailableReason ?? undefined}>
        {label}
      </span>
    );
  }

  return (
    <select
      value={lead.assigned_to ?? ""}
      // Names the LEAD: a screen reader meeting a hundred selects called "owner" cannot
      // tell which row it is on — the same reasoning as `StatusSelect`.
      aria-label={`Owner of ${lead.name ?? lead.phone_masked}`}
      disabled={disabled}
      title={unavailableReason ?? undefined}
      onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
      className={className}
    >
      <option value="">Unassigned</option>
      {/* An owner who has left is still SHOWN as the current value; without this option
          the select would silently snap to "Unassigned" and the next change the client
          made would look like they had done it. */}
      {orphaned && <option value={lead.assigned_to ?? ""}>No longer on this account</option>}
      {members.map((member) => (
        <option key={member.id} value={member.id}>
          {/* The API sends no email (hard rule 6 / the redaction guardrail), so an
              unnamed colleague is named as one rather than by an address. */}
          {member.name ?? "Unnamed member"}
        </option>
      ))}
    </select>
  );
}
