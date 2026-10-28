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

import { InfoTip } from "@/components/console/infoTip";
import { Section } from "@/components/console/section";
import { useFormValidation } from "@/components/formValidation";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FIELD, FIELD_LABEL, ProblemNotice } from "@/components/ui";
import { ROLE_COPY, useInviteMember, type CreatedInvitation, type MemberRole } from "@/lib/api/members";
import { useClientSession } from "@/lib/api/session";

import { ROLES, ROLE_SHORT } from "./roles";
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
  const inviteFeedback = useActionFeedback(invite, { errorDisplay: "inline" });
  const valid = useFormValidation();
  const emailField = valid.field("email", "Enter their email address.");
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
        {/* Labels above both fields; the button sits on the fields' baseline from `sm`. The
            email's refusal sits under its box, outside the label, so it is not folded into
            the field's accessible name. */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1">
            <label htmlFor={emailField.id} className={FIELD_LABEL}>
              Their email address
            </label>
            <input
              {...emailField}
              required
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setIssued(null);
              }}
              autoComplete="off"
              placeholder="name@business.in"
              className={FIELD}
            />
            {valid.error("email")}
          </div>
          <div className="sm:w-36">
            <label htmlFor="team-invite-role" className={FIELD_LABEL}>
              Role
            </label>
            <select
              id="team-invite-role"
              value={role}
              onChange={(e) => setRole(e.target.value as MemberRole)}
              className={FIELD}
            >
              {ROLES.map((value) => (
                <option key={value} value={value}>
                  {ROLE_COPY[value].label}
                </option>
              ))}
            </select>
          </div>
          <ActionButton
            type="submit"
            status={inviteFeedback.status}
            disabled={email.trim().length < 3 && inviteFeedback.status !== "success"}
            successLabel="Sent"
            className="w-full justify-center sm:mt-5 sm:w-auto"
          >
            Send invite
          </ActionButton>
        </div>
        <p className="mt-2 flex items-center gap-1 text-meta text-ink-muted">
          <span>
            <span className="font-medium text-ink">{ROLE_COPY[role].label}:</span> {ROLE_SHORT[role]}
          </span>
          <InfoTip label={`the ${ROLE_COPY[role].label} role`} className="touch:-my-2.5">
            <p>{ROLE_COPY[role].can}</p>
          </InfoTip>
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
