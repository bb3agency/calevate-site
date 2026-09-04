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
 * The copy on this panel says both, in the client's words, once. It does not repeat them
 * per row, and it does not soften them.
 *
 * ## Why the whole list saves at once
 *
 * The ORDER is the product, so "move Priya above Ravi and switch Ravi off while he is
 * away" is one intention. Four requests over rows can half-apply into two people at the
 * same position or a roster that is briefly empty — and if a call lands in that instant, a
 * caller is told nobody is available. One PUT, one draft, one Save.
 *
 * ## Why the verdict is above the list and not under it
 *
 * "Is this working right now" is the question an owner opens this panel with, and it is
 * not answerable from a list of names: it depends on the switch, on who is active, and on
 * the clock. The server answers it and sends the sentence that fixes it; this renders the
 * server's words rather than composing its own, so the screen and the publish can never
 * describe different states.
 */

import { History, PhoneForwarded, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import {
  FIELD,
  FIELD_LABEL,
  NOTICE_TONES,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  SectionHeading,
  Skeleton,
  ToggleSwitch,
  formatIST,
} from "@/components/ui";
import {
  useHandoff,
  useSetHandoff,
  type Agent,
  type HandoffIn,
  type HandoffOut,
} from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";

/** One row of the draft. `key` is local and only ever identifies a row while editing. */
type Draft = {
  key: string;
  label: string;
  phone_e164: string;
  active: boolean;
  note: string;
};

function toDraft(members: HandoffOut["members"]): Draft[] {
  return members.map((member, index) => ({
    key: `${member.id}-${index}`,
    label: member.label,
    phone_e164: member.phone_e164,
    active: member.active,
    note: member.note ?? "",
  }));
}

function move(rows: Draft[], from: number, to: number): Draft[] {
  if (to < 0 || to >= rows.length) return rows;
  const next = [...rows];
  const [row] = next.splice(from, 1);
  next.splice(to, 0, row);
  return next;
}

export function Handover({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const handoff = useHandoff(session, agent.id);
  const save = useSetHandoff(session, agent.id);

  const [enabled, setEnabled] = useState(false);
  const [rows, setRows] = useState<Draft[]>([]);
  const [dirty, setDirty] = useState(false);

  /*
   * THE SERVER'S ANSWER SEEDS THE DRAFT, and only while the draft is clean. A refetch
   * lands every thirty seconds (the verdict is a function of the clock), and one that
   * overwrote a half-typed phone number would lose an edit the owner is in the middle of.
   */
  useEffect(() => {
    if (!handoff.data || dirty) return;
    setEnabled(handoff.data.enabled);
    setRows(toDraft(handoff.data.members));
  }, [handoff.data, dirty]);

  if (handoff.isLoading) return <Skeleton rows={4} />;
  if (handoff.error)
    return <ProblemNotice error={handoff.error} onRetry={() => void handoff.refetch()} />;
  if (!handoff.data) return null;

  const data = handoff.data;
  const edit = (index: number, patch: Partial<Draft>) => {
    setDirty(true);
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };
  const payload: HandoffIn = {
    enabled,
    // The trigger stays as the account has it: this panel does not edit it, and sending
    // the effective default would silently turn "use the default" into a saved override
    // that stops following it.
    trigger: data.trigger,
    members: rows.map((row) => ({
      label: row.label.trim(),
      phone_e164: row.phone_e164.trim(),
      active: row.active,
      note: row.note.trim() || null,
      hours: null,
    })),
  };

  return (
    <section>
      <SectionHeading icon={<PhoneForwarded className="h-3.5 w-3.5" />}>
        Putting a caller through to a person
      </SectionHeading>

      <p className="mt-2 text-sm text-ink-muted">
        When someone asks to speak to a person, your agent rings the first person on this
        list who is available and connects the caller to them. Everyone here is tried in
        order — the second person is rung when the first is switched off or outside their
        hours, not when they miss the call.
      </p>

      {/* THE TWO LIMITS, STATED ONCE AND PLAINLY. Neither is a footnote: a client who
          believed the person answering hears a summary first would tell their own callers
          so. See the module docstring. */}
      <NoticeBox tone="neutral" className="mt-3">
        <p>
          The person taking the call is not told anything before they pick up — the phone
          system we use puts the caller straight through. What was said is on this page and
          on the call the moment it ends.
        </p>
        <p className="mt-2">
          If nobody answers, we do not try the next person on the same call: the agent
          offers your caller a call-back instead, and books it for the next time we are
          allowed to ring them.
        </p>
      </NoticeBox>

      <div className="mt-4">
        <ToggleSwitch
          checked={enabled}
          onChange={(next) => {
            setDirty(true);
            setEnabled(next);
          }}
          label="Let this agent put callers through"
          hint="Off means callers who ask for a person are offered a call-back instead."
        />
      </div>

      {/* THE VERDICT, IN THE SERVER'S OWN WORDS. Five causes, four of them a minute's work
          — and the sentence that fixes each one comes from the same place the publish
          reads, so the screen cannot say "working" while the publish disagrees. */}
      {data.unavailable_reason ? (
        <NoticeBox tone="warn" className="mt-4">
          <p className="font-medium">Nobody is available to take a call right now.</p>
          {data.remediation && <p className="mt-1">{data.remediation}</p>}
        </NoticeBox>
      ) : (
        <p className={`mt-4 rounded-md px-3 py-2 text-sm ${NOTICE_TONES.ok}`}>
          A caller asking for a person right now would reach{" "}
          <strong>
            {data.members.find((member) => member.id === data.on_duty_member_id)?.label ??
              "the first person on this list"}
          </strong>
          .
        </p>
      )}

      <ul className="mt-4 space-y-3">
        {rows.map((row, index) => (
          <li key={row.key} className="rounded-lg border border-line p-3">
            <div className="flex items-start gap-3">
              <span className="mt-2 text-xs font-semibold text-ink-faint">{index + 1}</span>
              <div className="grid flex-1 gap-2 sm:grid-cols-2">
                <label className="block">
                  <span className={FIELD_LABEL}>Name</span>
                  <input
                    className={FIELD}
                    value={row.label}
                    maxLength={120}
                    onChange={(event) => edit(index, { label: event.target.value })}
                  />
                </label>
                <label className="block">
                  <span className={FIELD_LABEL}>Mobile number</span>
                  <input
                    className={FIELD}
                    value={row.phone_e164}
                    inputMode="tel"
                    placeholder="+919876543210"
                    onChange={(event) => edit(index, { phone_e164: event.target.value })}
                  />
                </label>
                <label className="block sm:col-span-2">
                  <span className={FIELD_LABEL}>Note (optional)</span>
                  <input
                    className={FIELD}
                    value={row.note}
                    maxLength={500}
                    placeholder="Evenings only, ask for the manager first"
                    onChange={(event) => edit(index, { note: event.target.value })}
                  />
                </label>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <ToggleSwitch
                checked={row.active}
                onChange={(next) => edit(index, { active: next })}
                label="Available"
                hint="Switch off while they are away — they keep their place in the order."
              />
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={index === 0}
                onClick={() => {
                  setDirty(true);
                  setRows((current) => move(current, index, index - 1));
                }}
              >
                Move up
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={index === rows.length - 1}
                onClick={() => {
                  setDirty(true);
                  setRows((current) => move(current, index, index + 1));
                }}
              >
                Move down
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-label={`Remove ${row.label || "this person"}`}
                onClick={() => {
                  setDirty(true);
                  setRows((current) => current.filter((_, i) => i !== index));
                }}
              >
                <Trash2 aria-hidden className="h-3.5 w-3.5" />
                Remove
              </button>
            </div>
          </li>
        ))}
      </ul>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          onClick={() => {
            setDirty(true);
            setRows((current) => [
              ...current,
              {
                key: `new-${current.length}-${Date.now()}`,
                label: "",
                phone_e164: "",
                active: true,
                note: "",
              },
            ]);
          }}
        >
          <Plus aria-hidden className="h-3.5 w-3.5" />
          Add someone
        </button>
        <button
          type="button"
          className={PRIMARY_BUTTON}
          disabled={!dirty || save.isPending}
          onClick={() => {
            save.mutate(payload, { onSuccess: () => setDirty(false) });
          }}
        >
          {save.isPending ? "Saving…" : "Save the list"}
        </button>
        {dirty && (
          <span className="text-xs text-ink-faint">
            Not saved yet. Changes reach your callers the next time this agent is published.
          </span>
        )}
      </div>

      {/* THE SERVER'S REFUSALS VERBATIM — a duplicated number, an empty list with the
          switch on, a number that is not in international format. Each is a sentence the
          owner can act on, and paraphrasing one here would be a second wording of a rule
          that has one. */}
      {save.error && <ProblemNotice error={save.error} />}

      {data.recent.length > 0 && (
        <div className="mt-5">
          <SectionHeading icon={<History className="h-3.5 w-3.5" />}>Recent handovers</SectionHeading>
          <ul className="mt-2 space-y-2 text-sm">
            {data.recent.map((attempt) => (
              <li key={attempt.id} className="rounded-md border border-line px-3 py-2">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium">{attempt.member ?? "Someone since removed"}</span>
                  <span className="text-xs text-ink-faint">{formatIST(attempt.started_at)}</span>
                </div>
                <p className="mt-1 text-ink-muted">{attempt.explanation}</p>
                {attempt.second_recording_at_platform && (
                  /* SAID ON THE SCREEN because a client answering a deletion request has
                     to know it exists: the phone system records the second call separately
                     and Calevate does not hold that recording. */
                  <p className="mt-1 text-xs text-ink-faint">
                    The phone system recorded this second call separately. Calevate does not
                    hold that recording — ask us if someone asks you to delete it.
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
