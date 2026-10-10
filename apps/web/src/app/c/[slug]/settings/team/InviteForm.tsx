"use client";

/**
 * INVITE SOMEONE, ON ONE LINE (founder, REDESIGN-2): their email, their role, Send invite.
 * The role's one line of what it can do sits under the row, so the choice is made knowing
 * what it means. It replaced a drawer opened from the header: an invite is two fields, and
 * a drawer for two fields hid the one thing an owner comes to this screen to do.
 *
 * The link is emailed and never shown (D-190); what comes back is the confirmation
 * (`IssuedInvite`). Only an owner sees this section; the screen decides that.
 */

import { useState } from "react";

import { Section } from "@/components/console/section";
import { useFormValidation } from "@/components/formValidation";
import { FIELD, PRIMARY_BUTTON, ProblemNotice } from "@/components/ui";
import { ROLE_COPY, useInviteMember, type CreatedInvitation, type MemberRole } from "@/lib/api/members";
import { useClientSession } from "@/lib/api/session";

import { ROLES } from "./roles";
import { IssuedInvite } from "./teamRows";

export function InviteInline({
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
  const [issued, setIssued] = useState<CreatedInvitation | null>(null);

  return (
    <Section title="Invite someone" description="They get an email with a link that works once.">
      <form
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
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
          {/* The message sits OUTSIDE the wrapping label: inside it, the refusal would be
              folded into the field's accessible name and read back on every visit. */}
          <div className="min-w-0 flex-1">
            <label className="block">
              <span className="sr-only">Their email address</span>
              <input
                {...valid.field("email", "Enter their email address.")}
                required
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  setIssued(null);
                }}
                autoComplete="off"
                placeholder="Their email address"
                aria-label="Email address to invite"
                className={`${FIELD} mt-0`}
              />
            </label>
            {valid.error("email")}
          </div>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as MemberRole)}
            aria-label="Role for the invitation"
            className={`${FIELD} mt-0 sm:w-36`}
          >
            {ROLES.map((value) => (
              <option key={value} value={value}>
                {ROLE_COPY[value].label}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={invite.isPending || email.trim().length < 3}
            className={`${PRIMARY_BUTTON} justify-center`}
          >
            {invite.isPending ? "Sending…" : "Send invite"}
          </button>
        </div>
        <p className="mt-2 text-meta text-ink-muted">
          <span className="font-medium text-ink">{ROLE_COPY[role].label}:</span> {ROLE_COPY[role].can}
        </p>
        {invite.error != null && (
          <div className="mt-3">
            <ProblemNotice error={invite.error} />
          </div>
        )}
        {issued && (
          <div className="mt-3">
            <IssuedInvite invitation={issued} />
          </div>
        )}
      </form>
    </Section>
  );
}
