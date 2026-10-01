"use client";

import { useId, useState } from "react";
import { UserPlus } from "lucide-react";

import { Drawer } from "@/components/console/drawer";
import {
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
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
 * Inviting a colleague, in a drawer over the team list.
 *
 * The email and role are held by the screen, not here, because the copilot declares them
 * (`TeamScreen`): closing the drawer must not lose what the assistant was told. The
 * button says "Send invite" because the link is emailed and never shown (D-190).
 */
export function InviteDrawer({
  open,
  onClose,
  email,
  setEmail,
  role,
  setRole,
}: {
  open: boolean;
  onClose: () => void;
  email: string;
  setEmail: (email: string) => void;
  role: MemberRole;
  setRole: (role: MemberRole) => void;
}) {
  const session = useClientSession();
  const invite = useInviteMember(session);
  const valid = useFormValidation();
  const formId = useId();
  /* Held here, never in the query cache, and cleared when another invitation is sent. */
  const [issued, setIssued] = useState<CreatedInvitation | null>(null);

  const close = () => {
    invite.reset();
    setIssued(null);
    onClose();
  };

  return (
    <Drawer
      open={open}
      onClose={close}
      title="Invite a colleague"
      description="They get an email with a link that works once."
      width="sm"
      footer={
        <>
          <button type="button" onClick={close} className={SECONDARY_BUTTON}>
            {issued ? "Done" : "Cancel"}
          </button>
          <button
            type="submit"
            form={formId}
            disabled={invite.isPending || email.trim().length < 3}
            className={PRIMARY_BUTTON}
          >
            <UserPlus aria-hidden className="h-4 w-4" />
            {invite.isPending ? "Sending…" : "Send invite"}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {issued && <IssuedInvite invitation={issued} />}
        <form
          id={formId}
          className="space-y-4"
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
          {/* The message sits OUTSIDE the wrapping label: inside it, the refusal would be
              folded into the field's accessible name and read back on every visit. */}
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
                className={`${FIELD} mt-1`}
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
            <span className="mt-1.5 block text-xs text-ink-muted">{ROLE_COPY[role].can}</span>
          </label>
          {invite.error != null && <ProblemNotice error={invite.error} />}
        </form>
      </div>
    </Drawer>
  );
}
