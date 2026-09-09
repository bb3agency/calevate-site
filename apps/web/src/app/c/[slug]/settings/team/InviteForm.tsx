"use client";

import { useState } from "react";
import { UserPlus } from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import {
  ROLE_COPY,
  useInviteMember,
  type CreatedInvitation,
  type MemberRole,
} from "@/lib/api/members";
import { useClientSession } from "@/lib/api/session";

import { ROLES } from "./roles";
import { IssuedInvite } from "./teamRows";

/**
 * Creating an invitation: the address, the role it grants, and the confirmation that one
 * was sent. Its own file because the ROLE is a grant of capability and the confirmation
 * is what the owner has instead of the link — neither belongs in the middle of the screen
 * that also removes people.
 *
 * The role is lifted here from the screen so the copilot declaration can still read it:
 * `role` and `setRole` are the screen's, this form only renders them.
 */
export function InviteForm({
  email,
  setEmail,
  role,
  setRole,
}: {
  email: string;
  setEmail: (email: string) => void;
  role: MemberRole;
  setRole: (role: MemberRole) => void;
}) {
  const session = useClientSession();
  const invite = useInviteMember(session);
  const valid = useFormValidation();
  /* Held here, never in the query cache: this is a credential, and the API cannot
     reissue it. Cleared when another invitation is created. */
  const [issued, setIssued] = useState<CreatedInvitation | null>(null);

  return (
    <Card title="Invite a colleague">
      <form
        className="mt-1 flex flex-wrap items-end gap-3"
        noValidate
        onSubmit={valid.onSubmit(() => {
          invite.mutate(
            { email: email.trim(), role },
            {
              onSuccess: (created) => {
                setIssued(created);
                setEmail("");
              },
            },
          );
        })}
      >
        {/* The message sits OUTSIDE the wrapping label on purpose: a `<label>` that
            encloses it would fold the refusal into the field's accessible NAME, so a
            screen reader would read it back on every subsequent visit to the field.
            `aria-describedby` is the association that belongs to a message. */}
        <div>
          <label className="block">
            <span className={FIELD_LABEL}>Their email address</span>
            <input
              {...valid.field("email", "Enter their email address.")}
              required
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="off"
              placeholder="priya@yourbusiness.in"
              aria-label="Email address to invite"
              className={`${FIELD} mt-1 w-72`}
            />
          </label>
          {valid.error("email")}
        </div>
        <label className="block">
          <span className={FIELD_LABEL}>Role</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as MemberRole)}
            aria-label="Role for the invitation"
            className={`${FIELD} mt-1`}
          >
            {ROLES.map((value) => (
              <option key={value} value={value}>
                {ROLE_COPY[value].label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={invite.isPending || email.trim().length < 3}
          className={PRIMARY_BUTTON_SM}
        >
          <UserPlus className="h-4 w-4" />
          {invite.isPending ? "Creating…" : "Create invite link"}
        </button>
      </form>

      <p className="mt-2 text-xs text-ink-faint">{ROLE_COPY[role].can}</p>

      {invite.error != null && (
        <div className="mt-3">
          <ProblemNotice error={invite.error} />
        </div>
      )}

      {issued && <IssuedInvite invitation={issued} />}
    </Card>
  );
}
