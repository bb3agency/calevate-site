"use client";

/**
 * WHO TAKES THE CALL WHEN A CALLER ASKS FOR A PERSON (D-533).
 *
 * ## What this screen has to be honest about, before anything else
 *
 * The founder asked for four things: one ordered hunt list, a spoken briefing to the human
 * before the call is bridged, trying the next number and then a call-back, and never
 * transferring outside business hours. **Two of the four are not possible on the platform
 * this product runs on**, and a screen that implied otherwise would be the worst kind of
 * defect — the client would sell a promise to their own callers on our word:
 *
 * * **Nobody is briefed in their ear.** Playing a message to the person answering, while
 *   the caller hears ringing, is a telephony feature that needs control of the caller's
 *   line. Our voice platform places the transfer on its own carrier account. What happens
 *   instead is that the handover is recorded and shown here the moment the call ends —
 *   and `docs/evidence/handoff-warm-transfer.md` records what would change that.
 * * **The list is not tried in turn DURING a call.** The platform allows one handover per
 *   conversation, so the person who is rung is chosen BEFORE the call from the order below
 *   — position one unless they are off duty or switched off — and a handover nobody answers
 *   becomes a call-back rather than a second attempt.
 *
 * The copy on this panel says both, in the client's words, once.
 *
 * **WHETHER A HANDOVER CAN HAPPEN AT ALL IS THE ENGINE'S ANSWER, NOT THIS PANEL'S
 * (D-592).** `GET …/handoff` asks `transfer_blocked_reason(get_engine())` and returns it
 * as `unavailable_reason` with its `remediation`. Render the server's sentence.
 *
 * ## The people come from the business profile (D-695)
 *
 * Names and mobiles are kept once, on the business profile, for every agent; this list
 * picks who of them THIS agent may put a caller through to, and in what order. A renamed
 * contact is renamed everywhere, and an agent can hand over to a subset.
 *
 * ## Why the whole list saves at once
 *
 * The ORDER is the product, so "move Priya above Ravi and switch Ravi off while he is
 * away" is one intention. Four requests over rows can half-apply into two people at the
 * same position or a roster that is briefly empty. One PUT, one draft, one Save.
 */

import Link from "next/link";
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { HowItWorks } from "@/components/console/howItWorks";
import {
  FIELD,
  FIELD_LABEL,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  ToggleSwitch,
  formatIST,
  NOTICE_BAR,
  NOTICE_BASE,
} from "@/components/ui";
import {
  useHandoff,
  useSetHandoff,
  type Agent,
  type HandoffIn,
  type HandoffOut,
} from "@/lib/api/agents";
import { setupHref, useBusinessProfile, type BusinessContact } from "@/lib/api/businessProfile";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { HandoverRow } from "./handoverRow";

/** One row of the draft. `key` is local and only ever identifies a row while editing. */
export type HandoverDraft = {
  key: string;
  contact_id: string;
  active: boolean;
  note: string;
};

function toDraft(members: HandoffOut["members"]): HandoverDraft[] {
  return members.flatMap((member, index) =>
    member.contact_id
      ? [
          {
            key: `${member.id}-${index}`,
            contact_id: member.contact_id,
            active: member.active,
            note: member.note ?? "",
          },
        ]
      : [],
  );
}

function move(rows: HandoverDraft[], from: number, to: number): HandoverDraft[] {
  if (to < 0 || to >= rows.length) return rows;
  const next = [...rows];
  const [row] = next.splice(from, 1);
  next.splice(to, 0, row);
  return next;
}

export function Handover({ agent }: { agent: Agent }) {
  const { session, href: realmHref } = useClientRealm();
  const handoff = useHandoff(session, agent.id);
  const profile = useBusinessProfile(session);
  const save = useSetHandoff(session, agent.id);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  // `PUT /v1/agents/{id}/handoff` is `org:manage`; staff read this panel on `agents:read`.
  const write = useWriteAccess(session, "org:manage", "change who calls are put through to");

  const [enabled, setEnabled] = useState(false);
  const [rows, setRows] = useState<HandoverDraft[]>([]);
  const [dirty, setDirty] = useState(false);
  const [adding, setAdding] = useState("");

  /*
   * THE SERVER'S ANSWER SEEDS THE DRAFT, and only while the draft is clean. A refetch
   * lands every thirty seconds (the verdict is a function of the clock), and one that
   * overwrote a half-made change would lose an edit the owner is in the middle of.
   */
  useEffect(() => {
    if (!handoff.data || dirty) return;
    setEnabled(handoff.data.enabled);
    setRows(toDraft(handoff.data.members));
  }, [handoff.data, dirty]);

  useUnsavedGuard(dirty);

  if (handoff.isLoading || profile.isLoading) return <Skeleton rows={4} />;
  if (handoff.error)
    return <ProblemNotice error={handoff.error} onRetry={() => void handoff.refetch()} />;
  if (profile.error)
    return <ProblemNotice error={profile.error} onRetry={() => void profile.refetch()} />;
  if (!handoff.data || !profile.data) return null;

  const data = handoff.data;
  const contacts = new Map<string, BusinessContact>(profile.data.contacts.map((c) => [c.id, c]));
  const available = profile.data.contacts.filter(
    (c) => !rows.some((row) => row.contact_id === c.id),
  );
  const contactsHref = setupHref(
    (path) => realmHref(`/c/${session.orgSlug}${path}`),
    "contacts",
  );
  const change = (next: HandoverDraft[]) => {
    setDirty(true);
    setRows(next);
  };
  const payload: HandoffIn = {
    enabled,
    // The trigger stays as the account has it: this panel does not edit it.
    trigger: data.trigger,
    members: rows.map((row) => ({
      contact_id: row.contact_id,
      active: row.active,
      note: row.note.trim() || null,
      hours: null,
    })),
  };

  /*
   * A warning only when the owner has something to do. "Off" restates the switch, and
   * "outside hours" or "this agent cannot transfer" ask nothing of them, so those are a
   * quiet line at most. The two that need action: on with nobody switched on (judged on
   * the DRAFT, so it clears the moment someone is added) and hours the server cannot read.
   */
  const nobodyChosen = enabled && !rows.some((row) => row.active);
  const needsHours = enabled && !nobodyChosen && data.unavailable_reason === "hours_unknown";
  const quietNote =
    data.unavailable_reason === "platform_cannot_transfer" ||
    (enabled && !nobodyChosen && data.unavailable_reason === "outside_hours")
      ? data.remediation
      : null;
  const onDuty = data.members.find((member) => member.id === data.on_duty_member_id)?.label;

  return (
    <section>
      <h3 className="text-heading text-ink">Transfer to a person</h3>
      <p className="mt-1 text-sm text-ink-muted">
        Choose who takes the call, from your{" "}
        <Link href={contactsHref} className="font-medium text-brand-strong hover:underline">
          business profile
        </Link>
        .
      </p>

      {write.reason && (
        <div className="mt-4">
          <RestrictionNote reason={write.reason} />
        </div>
      )}

      <fieldset disabled={!write.allowed} className="min-w-0">
        <div className="mt-4">
          <ToggleSwitch
            checked={enabled}
            onChange={(next) => {
              setDirty(true);
              setEnabled(next);
            }}
            label="Let callers reach your team"
            hint="When off, callers who ask for a person get a call-back."
          />
        </div>

        {nobodyChosen && (
          <p role="status" className={`mt-4 ${NOTICE_BASE} ${NOTICE_BAR.warn}`}>
            Nobody is chosen to take calls. Callers get a call-back.
          </p>
        )}
        {needsHours && data.remediation && (
          <p role="status" className={`mt-4 ${NOTICE_BASE} ${NOTICE_BAR.warn}`}>
            {data.remediation}
          </p>
        )}
        {quietNote && <p className="mt-3 text-sm text-ink-muted">{quietNote}</p>}
        {enabled && !dirty && onDuty && (
          <p className="mt-3 text-sm text-ink-muted">
            Right now, callers reach <strong className="font-medium text-ink">{onDuty}</strong>.
          </p>
        )}

        {profile.data.contacts.length === 0 ? (
          <EmptyState illustration={<EmptySketch kind="numbers" />}
            className="mt-4"
            message="Nobody can take calls yet."
            hint="Add them to your business profile first."
            action={
              <Link href={contactsHref} className={SECONDARY_BUTTON_SM}>
                Add people
              </Link>
            }
          />
        ) : (
          <ul className="mt-4 divide-y divide-line border-y border-line">
            {rows.map((row, index) => (
              <HandoverRow
                key={row.key}
                row={row}
                index={index}
                last={index === rows.length - 1}
                contact={contacts.get(row.contact_id)}
                onChange={(patch) =>
                  change(rows.map((r, i) => (i === index ? { ...r, ...patch } : r)))
                }
                onMove={(to) => change(move(rows, index, to))}
                onRemove={() => change(rows.filter((_, i) => i !== index))}
              />
            ))}
          </ul>
        )}

        <div className="mt-3 flex flex-wrap items-end gap-2">
          {available.length > 0 && (
            <>
              <label className="block min-w-0">
                <span className={FIELD_LABEL}>Add someone</span>
                <select
                  className={FIELD}
                  value={adding}
                  onChange={(event) => setAdding(event.target.value)}
                >
                  <option value="">Choose a person</option>
                  {available.map((contact) => (
                    <option key={contact.id} value={contact.id}>
                      {contact.label}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={adding === ""}
                onClick={() => {
                  change([
                    ...rows,
                    { key: `new-${adding}-${rows.length}`, contact_id: adding, active: true, note: "" },
                  ]);
                  setAdding("");
                }}
              >
                <Plus aria-hidden className="h-3.5 w-3.5" />
                Add
              </button>
            </>
          )}
          <ActionButton
            status={saveFeedback.status}
            successLabel="Saved"
            disabled={saveFeedback.status === "idle" && !dirty}
            onClick={() => {
              if (dirty) save.mutate(payload, { onSuccess: () => setDirty(false) });
            }}
          >
            Save the list
          </ActionButton>
          {dirty && (
            <span className="text-xs text-ink-faint">
              Not saved yet. Applies once it is put live.
            </span>
          )}
        </div>
      </fieldset>

      {save.error && <ProblemNotice error={save.error} />}

      <HowItWorks
        items={[
          "The first available person is rung. If they miss it, the agent books a call-back.",
          "Callers go straight through. Your team member is not briefed first.",
          "Switch someone off while they are away. They keep their place in the order.",
          ...(data.platform_note ? [data.platform_note] : []),
          "To pass callers to another of your agents, add its number to your business profile.",
        ]}
      />

      {data.recent.length > 0 && (
        <div className="mt-5">
          <h4 className="text-sm font-semibold text-ink">Recent handovers</h4>
          <ul className="mt-2 space-y-2 text-sm">
            {data.recent.map((attempt) => (
              <li key={attempt.id} className="border-b border-line py-2 last:border-b-0">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium">{attempt.member ?? "Someone since removed"}</span>
                  <span className="text-xs text-ink-faint">{formatIST(attempt.started_at)}</span>
                </div>
                <p className="mt-1 text-ink-muted">{attempt.explanation}</p>
                {attempt.second_recording_at_platform && (
                  <p className="mt-1 text-xs text-ink-faint">
                    Recorded separately. Kept like the rest of the call.
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

