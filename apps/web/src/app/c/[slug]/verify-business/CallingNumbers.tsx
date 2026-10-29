"use client";

import { useId, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatPhone,
} from "@/components/ui";
import {
  shortDay,
  todayIST,
  useCallingNumbers,
  useDeclareCallingNumbers,
  type CallingNumberDeclaration,
} from "@/lib/api/autodialerNotice";
import type { Session } from "@/lib/api/client";
import { useWriteAccess, type WriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText, type CopilotFact, type CopilotFillItem } from "@/lib/copilot/types";

/** The anchor the announcement, the readiness rows and the launch screen link to. */
export const CALLING_NUMBERS_ANCHOR = "calling-numbers";

/**
 * Calling numbers (D-941): the numbers automated calls come from, declared in advance.
 *
 * Every verdict here is the server's: `effective`, `blocker` and `enforced` come from the
 * dial gate's own predicate. Shown to an account whose agents place calls, or that has
 * declared before; an answering-only account has nothing to declare.
 */
export function CallingNumbers({ pageFacts }: { pageFacts: CopilotFact[] }) {
  const { session } = useClientRealm();
  const declaration = useCallingNumbers(session);
  const write = useWriteAccess(session, "org:manage", "declare calling numbers");
  // Declaring is the business's own statement; the server refuses it from a view-as session.
  const access: WriteAccess = session.impersonateOrg
    ? { allowed: false, reason: "Only your business can declare its calling numbers.", unknown: false }
    : write;

  if (declaration.isLoading) return <Skeleton rows={3} />;
  if (declaration.error || !declaration.data) {
    return (
      <div id={CALLING_NUMBERS_ANCHOR} className="scroll-mt-24">
        <ProblemNotice
          error={declaration.error ?? new Error("Your calling numbers did not load.")}
          onRetry={() => void declaration.refetch()}
        />
      </div>
    );
  }
  const data = declaration.data;
  if (!data.applies && !data.recorded) return null;
  return (
    <div id={CALLING_NUMBERS_ANCHOR} className="scroll-mt-24">
      <Card title="Calling numbers">
        <DeclarationBody session={session} data={data} access={access} pageFacts={pageFacts} />
      </Card>
    </div>
  );
}

function DeclarationBody({
  session,
  data,
  access,
  pageFacts,
}: {
  session: Session;
  data: CallingNumberDeclaration;
  access: WriteAccess;
  pageFacts: CopilotFact[];
}) {
  const [editing, setEditing] = useState(false);
  const declared = data.effective && data.blocker === null;
  if (declared && !editing) {
    return (
      <div className="space-y-3">
        <ul className="space-y-1 text-sm text-ink">
          {data.declared_clis.map((number) => (
            <li key={number} className="tabular-nums">
              {formatPhone(number)}
            </li>
          ))}
        </ul>
        {data.notified_on && (
          <p className={FIELD_HINT}>Declared on {shortDay(data.notified_on)}.</p>
        )}
        {access.allowed && (
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setEditing(true)}>
            Change
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <DeclarationStatus data={data} />
      <DeclarationForm session={session} data={data} access={access} pageFacts={pageFacts} />
    </div>
  );
}

/** Where the account stands, in one notice: due by a date, paused, or a later start date. */
function DeclarationStatus({ data }: { data: CallingNumberDeclaration }) {
  const day = shortDay(data.enforced_from);
  if (data.blocker?.rule === "a2p_declaration_not_yet_effective") {
    return (
      <NoticeBox tone="neutral" title="Declared from a later date">
        {data.blocker.reason}
      </NoticeBox>
    );
  }
  if (data.enforced && data.blocker) {
    return (
      <NoticeBox tone="stop" title="Outgoing calls are paused. Declare your numbers.">
        {data.blocker.reason}
      </NoticeBox>
    );
  }
  if (data.blocker) {
    return (
      <NoticeBox tone="warn" title={`Declare your calling numbers before ${day}`}>
        <p>From {day}, only declared numbers can place calls.</p>
        <p>Incoming calls still work.</p>
      </NoticeBox>
    );
  }
  return null;
}

/** Every number the account rents, then any declared number it no longer rents. */
function candidateNumbers(data: CallingNumberDeclaration): string[] {
  const all = [...data.rented_numbers];
  for (const number of data.declared_clis) if (!all.includes(number)) all.push(number);
  return all;
}

const DATE_FIELD = "calling-numbers-date";
const REFERENCE_FIELD = "calling-numbers-reference";
const NUMBERS_FIELD = "calling-numbers-list";

function DeclarationForm({
  session,
  data,
  access,
  pageFacts,
}: {
  session: Session;
  data: CallingNumberDeclaration;
  access: WriteAccess;
  pageFacts: CopilotFact[];
}) {
  const declare = useDeclareCallingNumbers(session);
  const feedback = useActionFeedback(declare, { errorDisplay: "inline" });
  const candidates = candidateNumbers(data);
  // Prefilled: a rented number is ticked unless an earlier declaration left it out.
  const [ticked, setTicked] = useState<string[]>(() =>
    data.recorded && data.declared_clis.length > 0
      ? candidates.filter((number) => data.declared_clis.includes(number) || data.undeclared_clis.includes(number))
      : candidates,
  );
  const [declaredOn, setDeclaredOn] = useState(todayIST());
  const [reference, setReference] = useState(data.notice_reference ?? "");
  const [confirmed, setConfirmed] = useState(false);
  const dateId = DATE_FIELD;
  const referenceId = REFERENCE_FIELD;
  const numbersId = useId();

  // While the form is open it is the innermost surface, so it carries the page's facts.
  // Pip may fill the date and the reference; the numbers are read so it can name them, and
  // the attestation and the press stay the person's.
  useCopilotSurface({
    route: "/c/{slug}/verify-business",
    title: "Verify your business",
    realm: "client",
    fields: [
      { id: DATE_FIELD, label: "Declared on (the day the numbers were declared)", type: "date", value: declaredOn, writable: access.allowed },
      { id: REFERENCE_FIELD, label: "Reference for the declaration (optional)", type: "text", value: reference, writable: access.allowed },
      {
        id: NUMBERS_FIELD,
        label: "Calling numbers ticked to declare",
        type: "textarea",
        value: ticked.join("\n"),
        writable: false,
        personal: "phone",
      },
    ],
    facts: pageFacts,
    apply: (items: CopilotFillItem[]) => {
      for (const item of items) {
        if (item.field_id === DATE_FIELD) setDeclaredOn(asText(item.value));
        if (item.field_id === REFERENCE_FIELD) setReference(asText(item.value));
      }
    },
  });

  const toggle = (number: string, on: boolean) =>
    setTicked((current) => (on ? [...current, number] : current.filter((n) => n !== number)));
  const missing = data.undeclared_clis.filter((number) => !ticked.includes(number));

  return (
    <div className="space-y-4">
      <RestrictionNote reason={access.reason} />
      <fieldset className="space-y-2" aria-describedby={numbersId}>
        <legend className={FIELD_LABEL}>Numbers your calls come from</legend>
        {candidates.length === 0 ? (
          <p id={numbersId} className={FIELD_HINT}>
            No numbers yet. Get a number first, then declare it here.
          </p>
        ) : (
          <p id={numbersId} className={FIELD_HINT}>
            Untick any number that never places calls.
          </p>
        )}
        {candidates.map((number) => (
          <label key={number} className="flex items-center gap-3 text-sm text-ink touch:min-h-11">
            <input
              type="checkbox"
              className="h-4 w-4 shrink-0 accent-brand-strong touch:h-5 touch:w-5"
              checked={ticked.includes(number)}
              disabled={!access.allowed}
              onChange={(event) => toggle(number, event.target.checked)}
            />
            <span className="tabular-nums">{formatPhone(number)}</span>
          </label>
        ))}
        {missing.length > 0 && (
          <p className="text-sm text-warn">
            {missing.length === 1
              ? "An agent's number is unticked. Its calls will be refused."
              : `${missing.length} agent numbers are unticked. Their calls stop.`}
          </p>
        )}
      </fieldset>
      <div>
        <label htmlFor={dateId} className={FIELD_LABEL}>
          Declared on
        </label>
        <input
          id={dateId}
          type="date"
          className={`${FIELD} sm:w-48`}
          value={declaredOn}
          disabled={!access.allowed}
          onChange={(event) => setDeclaredOn(event.target.value)}
        />
      </div>
      <div>
        <label htmlFor={referenceId} className={FIELD_LABEL}>
          Reference (optional)
        </label>
        <input
          id={referenceId}
          type="text"
          className={FIELD}
          maxLength={200}
          value={reference}
          disabled={!access.allowed}
          onChange={(event) => setReference(event.target.value)}
        />
      </div>
      <label className="flex items-start gap-3 text-sm text-ink touch:min-h-11">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 shrink-0 accent-brand-strong touch:h-5 touch:w-5"
          checked={confirmed}
          disabled={!access.allowed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span className="max-w-prose">{data.attestation_text}</span>
      </label>
      <ActionButton
        status={feedback.status}
        disabled={!access.allowed || !confirmed || ticked.length === 0 || !declaredOn}
        onClick={() =>
          feedback.run({
            numbers: ticked,
            declaredOn,
            reference,
            attestationVersion: data.attestation_version,
            attestationSha256: data.attestation_sha256,
          })
        }
        className="w-full justify-center sm:w-auto"
        pendingLabel="Declaring…"
        successLabel="Declared"
      >
        Declare numbers
      </ActionButton>
      <ProblemNotice error={declare.error} />
    </div>
  );
}
