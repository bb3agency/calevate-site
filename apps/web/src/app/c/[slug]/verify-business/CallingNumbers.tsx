"use client";

import { useId, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import {
  Card,
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
  useCallingNumbers,
  useDeclareCallingNumbers,
  type CallingNumberDeclaration,
} from "@/lib/api/autodialerNotice";
import type { Session } from "@/lib/api/client";
import { useWriteAccess, type WriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill, type CopilotFact } from "@/lib/copilot/types";

/** The anchor the announcement, the readiness rows and the launch screen link to. */
export const CALLING_NUMBERS_ANCHOR = "calling-numbers";

/** The one line under the button: who registers the numbers. No provider is named (D-679). */
export const WE_REGISTER = "Calevate registers them with the telephone company for you.";

/**
 * Calling numbers (D-941, amended 30 Oct 2026): the client confirms the numbers its agents
 * call from and authorises Calevate to register them. The client files nothing itself, so
 * the form asks for no date and no reference.
 *
 * Every verdict here is the server's: `effective`, `blocker` and `enforced` come from the
 * dial gate's own predicate. Shown to an account whose agents place calls, or that has
 * confirmed before; an answering-only account has nothing to confirm.
 */
export function CallingNumbers({ pageFacts }: { pageFacts: CopilotFact[] }) {
  const { session } = useClientRealm();
  const declaration = useCallingNumbers(session);
  const write = useWriteAccess(session, "org:manage", "confirm calling numbers");
  // Confirming is the business's own act; the server refuses it from a view-as session.
  const access: WriteAccess = session.impersonateOrg
    ? { allowed: false, reason: "Only your business can confirm its calling numbers.", unknown: false }
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
  const confirmed = data.effective && data.blocker === null;
  if (confirmed && !editing) {
    return (
      <div className="space-y-3">
        <ul className="space-y-1 text-sm text-ink">
          {data.declared_clis.map((number) => (
            <li key={number} className="tabular-nums">
              {formatPhone(number)}
            </li>
          ))}
        </ul>
        {data.notified_on && <p className={FIELD_HINT}>Confirmed on {shortDay(data.notified_on)}.</p>}
        <p className={FIELD_HINT}>{WE_REGISTER}</p>
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
  // A row confirmed on an older wording covers nothing; the account confirms once more.
  const again = data.recorded && data.state === "notified" && !data.attested;
  if (data.blocker?.rule === "a2p_declaration_not_yet_effective") {
    return (
      <NoticeBox tone="neutral" title="Confirmed from a later date">
        {data.blocker.reason}
      </NoticeBox>
    );
  }
  if (data.enforced && data.blocker) {
    return (
      <NoticeBox tone="stop" title="Outgoing calls are paused. Confirm your numbers.">
        {data.blocker.reason}
      </NoticeBox>
    );
  }
  if (data.blocker) {
    return (
      <NoticeBox
        tone="warn"
        title={again ? `Confirm your calling numbers again before ${day}` : `Confirm your calling numbers before ${day}`}
      >
        <p>From {day}, only confirmed numbers can place calls.</p>
        <p>Incoming calls still work.</p>
      </NoticeBox>
    );
  }
  return null;
}

/** Every number the account rents, then any confirmed number it no longer rents. */
function candidateNumbers(data: CallingNumberDeclaration): string[] {
  const all = [...data.rented_numbers];
  for (const number of data.declared_clis) if (!all.includes(number)) all.push(number);
  return all;
}

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
  // Prefilled: a rented number is ticked unless an earlier confirmation left it out.
  const [ticked, setTicked] = useState<string[]>(() =>
    data.recorded && data.declared_clis.length > 0
      ? candidates.filter((number) => data.declared_clis.includes(number) || data.undeclared_clis.includes(number))
      : candidates,
  );
  const [confirmed, setConfirmed] = useState(false);
  const numbersId = useId();

  // While the form is open it is the innermost surface, so it carries the page's facts.
  // The numbers are read so Pip can name them; the authorisation and the press stay the
  // person's, so nothing here is writable.
  useCopilotSurface({
    route: "/c/{slug}/verify-business",
    title: "Verify your business",
    realm: "client",
    fields: [
      {
        id: NUMBERS_FIELD,
        label: "Calling numbers ticked to confirm",
        type: "textarea",
        value: ticked.join("\n"),
        writable: false,
        personal: "phone",
      },
    ],
    facts: pageFacts,
    apply: noFill,
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
            No numbers yet. Get a number first, then confirm it here.
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
      <div className="space-y-2">
        <ActionButton
          status={feedback.status}
          disabled={!access.allowed || !confirmed || ticked.length === 0}
          onClick={() =>
            feedback.run({
              numbers: ticked,
              attestationVersion: data.attestation_version,
              attestationSha256: data.attestation_sha256,
            })
          }
          className="w-full justify-center sm:w-auto"
          pendingLabel="Confirming…"
          successLabel="Confirmed"
        >
          Confirm numbers
        </ActionButton>
        <p className={FIELD_HINT}>{WE_REGISTER}</p>
      </div>
      <ProblemNotice error={declare.error} />
    </div>
  );
}
