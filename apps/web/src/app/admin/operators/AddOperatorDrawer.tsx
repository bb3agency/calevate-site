"use client";

import { useState } from "react";
import { ShieldCheck, TriangleAlert, UserPlus } from "lucide-react";

import { WriteFailure } from "@/app/admin/writeFailure";
import { Drawer } from "@/components/console/drawer";
import { useFormValidation } from "@/components/formValidation";
import { TypedConfirmation, confirmationMatches } from "@/components/typedConfirmation";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
} from "@/components/ui";
import {
  ADMIN_ROLES,
  ROLE_COPY,
  useAddOperator,
  type AdminRole,
  type Operator,
} from "@/lib/api/adminOperators";
import { lookup } from "@/lib/lookup";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

/**
 * Add an account, and mail its setup link. No password is chosen, generated or shown: the
 * API mails a single-use link to the address typed here and has no response field it could
 * be put in (D-190: a token the inviter can see is an account squat).
 *
 * The typed phrase names the TIER, and the API's own header (`add_operator:<role>`, built in
 * `useAddOperator`) is bound to the same role, so changing the tier clears the phrase: one
 * typed to add an admin must not confirm a second super admin.
 */
export function AddOperatorDrawer({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: (created: Operator) => void;
}) {
  const add = useAddOperator();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<AdminRole>("operator");
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const copy = lookup(ROLE_COPY, role);
  const confirmPhrase = (copy?.label ?? role).toUpperCase();
  const valid = useFormValidation();
  // The address and the reason are answered at their own controls; what stays on the
  // button is the typed phrase, which is a gate on the act rather than an answer.
  const ready = confirmationMatches(typed, confirmPhrase);
  const dirty = email !== "" || name !== "" || reason !== "" || typed !== "";
  useUnsavedGuard(dirty);

  return (
    <Drawer
      dirty={dirty}
      open
      onClose={onClose}
      title="Add an admin"
      description="Recorded in the audit log against your account, with the reason you type."
    >
      <form
        className="space-y-4"
        noValidate
        onSubmit={valid.onSubmit(() => {
          add.mutate(
            {
              email: email.trim(),
              // An empty box is not an empty name: the column is nullable and the row falls
              // back to the address, which is more use than a blank cell.
              name: name.trim() === "" ? null : name.trim(),
              role,
              reason: reason.trim(),
            },
            { onSuccess: onAdded },
          );
        })}
      >
        <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2">
          <label className="block">
            <span className={FIELD_LABEL}>Their email address</span>
            <input
              {...valid.field("email", "Enter the address this admin signs in with.")}
              required
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="off"
              placeholder="asha@calevate.tech"
              aria-label="Email address of the admin to add"
              className={FIELD}
            />
            {valid.error("email")}
          </label>
          <label className="block">
            <span className={FIELD_LABEL}>Their name (optional)</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoComplete="off"
              placeholder="Asha Rao"
              aria-label="Name of the admin to add"
              className={FIELD}
            />
          </label>
        </div>
        <p className={FIELD_HINT}>
          The setup link is mailed to that address and nowhere else — we cannot show it to you,
          and there is no password to pass on.
        </p>

        <label className="block">
          <span className={FIELD_LABEL}>Tier</span>
          <select
            value={role}
            onChange={(event) => {
              setRole(event.target.value as AdminRole);
              setTyped("");
              add.reset();
            }}
            aria-label="Tier for the new admin"
            className={FIELD}
          >
            {ADMIN_ROLES.map((value) => (
              <option key={value} value={value}>
                {ROLE_COPY[value].label}
              </option>
            ))}
          </select>
        </label>

        {/* What the tier means, above the button: the sentence somebody is deciding on. */}
        <div className="flex gap-3 rounded-card border border-line p-4 text-sm">
          {role === "superadmin" ? (
            <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          ) : (
            <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
          )}
          <div className="min-w-0">
            <p className="font-semibold text-ink">
              {role === "superadmin"
                ? "A super admin can do everything you can, including this screen"
                : "An admin runs onboarding and support, and nothing platform-wide"}
            </p>
            <p className="mt-2 text-ink-muted">
              <span className="font-medium text-ink">Can</span> {copy?.can}
            </p>
            {copy?.cannot && (
              <p className="mt-1.5 text-ink-muted">
                <span className="font-medium text-ink">Cannot</span> {copy.cannot}
              </p>
            )}
          </div>
        </div>

        <label className="block">
          <span className={FIELD_LABEL}>Why</span>
          <input
            {...valid.field("reason", "Say why this admin is being added.")}
            required
            minLength={3}
            maxLength={500}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            aria-label="Why you are adding this admin"
            placeholder="e.g. 'joining as our second onboarding operator'"
            className={FIELD}
          />
          {valid.error("reason")}
          <span className={FIELD_HINT}>
            Recorded in the audit log beside who asked for it. Whoever reads this row in a year
            has to be able to decide whether the reason still holds.
          </span>
        </label>

        <TypedConfirmation
          phrase={confirmPhrase}
          hint="Naming the tier is the confirmation: change the tier and this phrase changes with it, so a phrase typed to add an admin cannot add a super admin."
          value={typed}
          onChange={(next) => {
            setTyped(next);
            add.reset();
          }}
        />

        {add.error != null && <WriteFailure error={add.error} actionLabel="Add" />}

        <button type="submit" disabled={!ready || add.isPending} className={PRIMARY_BUTTON}>
          <UserPlus aria-hidden className="h-4 w-4" />
          {add.isPending ? "Adding…" : `Add ${copy?.label.toLowerCase() ?? role}`}
        </button>
      </form>
    </Drawer>
  );
}
