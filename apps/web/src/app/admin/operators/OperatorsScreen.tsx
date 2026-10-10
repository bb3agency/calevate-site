"use client";

import { useState } from "react";
import { CircleHelp, MailCheck, UserPlus } from "lucide-react";

import { WithheldPanel, forbiddenReason, isForbidden } from "@/app/admin/withheld";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { NoticeBox, PRIMARY_BUTTON, ProblemNotice, Skeleton, formatCount } from "@/components/ui";
import {
  ADMIN_ROLES,
  ROLE_COPY,
  operatorLabel,
  useOperators,
  type Operator,
} from "@/lib/api/adminOperators";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { AddOperatorDrawer } from "./AddOperatorDrawer";
import { OperatorRow } from "./OperatorRow";

/**
 * The screen proper, mounted once the identity read has settled on something other than a
 * refusal. `restriction` is non-null when we do not KNOW what the viewer may do (the
 * identity read failed or was paused): the controls stay closed with that sentence, while
 * the list read is still attempted, because the API is the enforcement.
 */
export function OperatorsScreen({
  viewerId,
  restriction,
}: {
  /** `admin_users.id` of the signed-in operator, or null when we could not find out. */
  viewerId: string | null;
  restriction: string | null;
}) {
  const list = useOperators();
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState<Operator | null>(null);

  /**
   * `.data`, never `.data ?? []`, and ERROR FIRST: a failed refetch keeps the previous
   * rows, so a colleague revoked thirty seconds ago by another super admin would still be
   * shown as having access under a box that reads as a network blip. Withholding costs a
   * reload; the other way costs a wrong belief about who can reach every client's data.
   */
  const operators = list.error ? undefined : list.data?.operators;

  // Counts only, never a roster: every row is a named person with an email address, and a
  // map of who holds privileged access is not the assistant's to receive.
  useCopilotSurface({
    route: "/admin/operators",
    title: "Admin accounts",
    realm: "admin",
    fields: [],
    facts: operators
      ? [
          { key: "accounts", label: "Accounts that may sign in", value: String(operators.length) },
          {
            key: "by_role",
            label: "How many in each tier",
            value:
              ADMIN_ROLES.map(
                (role) =>
                  `${ROLE_COPY[role].label}: ${operators.filter((operator) => operator.role === role).length}`,
              ).join(", ") || "none",
          },
          {
            key: "not_activated",
            label: "Invited but not yet activated",
            value: String(operators.filter((operator) => !operator.activated).length),
          },
          {
            key: "controls",
            label: "Are the add/promote/revoke controls open to this operator",
            value: restriction === null ? "yes" : "no",
          },
          {
            key: "identities_withheld",
            label: "Who those accounts are",
            value: "not sent to the assistant — see the comment above this declaration",
          },
        ]
      : [
          {
            key: "roster",
            label: "The admin allowlist",
            value: list.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  if (isForbidden(list.error)) {
    return (
      <div className="max-w-3xl">
        <WithheldPanel
          title="Admin accounts"
          reason={
            forbiddenReason(list.error) ??
            "The API refused this read: your admin account may not see who may use this console."
          }
          subject="This screen would list who may sign in to this console and in which tier."
        />
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-10 pb-12">
      <PageHeader
        description="Who can sign in to this console, and in which tier. Every change is recorded in the audit log against you."
        actions={
          <button
            type="button"
            className={PRIMARY_BUTTON}
            disabled={restriction !== null}
            onClick={() => setAdding(true)}
          >
            <UserPlus aria-hidden className="h-4 w-4" />
            Add an admin
          </button>
        }
      />

      {restriction && (
        <NoticeBox
          tone="warn"
          icon={<CircleHelp aria-hidden className="h-5 w-5" />}
          title="We could not check what you may do here"
        >
          <p className="mt-1">{restriction}</p>
          <p className="mt-2">
            The controls below stay closed until we know. These actions are only ever allowed
            for a super admin, whatever this screen shows, so nothing is being withheld that you
            could otherwise have done.
          </p>
        </NoticeBox>
      )}

      {added && (
        <NoticeBox
          tone="ok"
          icon={<MailCheck aria-hidden className="h-5 w-5" />}
          title={`Setup link sent to ${added.email ?? operatorLabel(added)}`}
        >
          <p className="mt-1">
            The account exists and cannot sign in until they follow that link and choose their
            own password. It works once and expires within the hour.
          </p>
          <p className="mt-2 text-meta">
            We cannot show or forward the link — it is stored only as a fingerprint. If it does
            not arrive, use <span className="font-semibold">Resend setup link</span> on their
            row below, which invalidates the previous one.
          </p>
        </NoticeBox>
      )}

      <section aria-labelledby="operators-list" className="space-y-2">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h2 id="operators-list" className="text-heading text-ink">
            Admin accounts
          </h2>
          <InfoTip label="Admin accounts">
            Revoked accounts are not listed: their rows survive as the record of what they
            approved, and &ldquo;who was removed and when&rdquo; is a question for the audit log,
            which keeps a record that cannot be quietly changed.
          </InfoTip>
          {/* No count until the server has sent a list: "1 account" in flight is a claim
              about who can reach every client's data, made on no evidence. */}
          {operators && (
            <span className="text-meta text-ink-muted">
              {formatCount(operators.length)} {operators.length === 1 ? "account" : "accounts"}
            </span>
          )}
        </div>

        {list.error != null && (
          <div className="space-y-2">
            <ProblemNotice error={list.error} onRetry={() => void list.refetch()} />
            <p className="text-meta text-ink-muted">
              No accounts are listed while that read is failing, including any this screen had
              already shown: a list that is thirty seconds stale would tell you somebody still
              has access after another super admin has taken it away.
            </p>
          </div>
        )}

        {/* No "you are the only admin" fallback: wrong, it answers "who else can reach every
            client's data" with a reassurance nobody checked. */}
        {list.isLoading ? (
          <Skeleton rows={3} />
        ) : !operators ? null : operators.length ? (
          <ul className="divide-y divide-line border-y border-line">
            {operators.map((operator) => (
              <OperatorRow
                key={operator.id}
                operator={operator}
                viewerId={viewerId}
                restriction={restriction}
              />
            ))}
          </ul>
        ) : (
          <EmptyState
            message={
              <>
                No admin accounts are listed
                <span className="mt-1 block text-meta text-ink-muted">
                  That cannot be right — you are signed in to this console, so at least your own
                  account exists. Reload the page, and treat it as an incident if it stays empty.
                </span>
              </>
            }
          />
        )}
      </section>

      {adding && (
        <AddOperatorDrawer
          onClose={() => setAdding(false)}
          onAdded={(created) => {
            setAdded(created);
            setAdding(false);
          }}
        />
      )}
    </div>
  );
}
