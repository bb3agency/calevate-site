"use client";

import { useState } from "react";

import { RestrictionNote } from "@/components/ui";
import {
  DNC_LIST_LIMIT,
  MAX_NUMBERS_PER_ADD,
  parsePastedNumbers,
  useDncList,
  type DncSource,
} from "@/lib/api/dnc";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { AddNumbers } from "./AddNumbers";
import { CheckNumber } from "./CheckNumber";
import { SuppressedList } from "./SuppressedList";
import { SOURCE_OPTIONS } from "./sources";

/**
 * Do not call (SEC-COMP §3, hard rule 5) — the suppression list made visible.
 *
 * `/v1/dnc` shipped without a screen, which meant the live list the compliance gate reads
 * on every dispatch could only be written by us. This is the client's own way in, and it
 * is three sibling modules in the order somebody actually uses them (UX-DOCTRINE §6):
 *
 * - `CheckNumber.tsx` — the question people arrive with, answerable by every session.
 * - `AddNumbers.tsx` — suppressing, which needs `leads:dispatch`.
 * - `SuppressedList.tsx` — the list itself, and the one control that takes a number off.
 *
 * Each of those carries the API decision it must not paper over; what stays here is the
 * form state the assistant declaration reads, because a declaration made inside the Add
 * card would vanish for the read-only session that most needs the assistant.
 *
 * Adding and removing both need `leads:dispatch` — the same authority that lets someone
 * cause a call, because suppressing a number is that decision in the other direction.
 * `staff` does not hold it. ⚠ THIS SAID "an impersonating operator is refused every
 * mutating permission (D-22)" AND THAT IS REVERSED: `leads:dispatch` is writable in a
 * view-as session, so support can suppress a number while the client is on the phone and
 * the audit row names the operator. Checking a number is `leads:read`, so it is
 * deliberately NOT gated: it is the question people arrive with, and it stays answerable
 * to every viewer, which is exactly when someone is asking it.
 *
 * A failed `/v1/me` once silently deleted the Add form and said nothing — the permission
 * test was hand-rolled, so "we could not find out" and "you may not" rendered identically,
 * as an empty space. It goes through `useWriteAccess`, the one place in this app that
 * answers "may this session write".
 */
export default function DoNotCallPage() {
  const session = useClientSession();
  const entries = useDncList(session);
  const write = useWriteAccess(session, "leads:dispatch", "add or remove numbers on this list");

  const [paste, setPaste] = useState("");
  const [source, setSource] = useState<DncSource>("manual");
  const [phone, setPhone] = useState("");

  const parsed = parsePastedNumbers(paste);
  const tooMany = parsed.length > MAX_NUMBERS_PER_ADD;

  const rows = entries.data;
  const truncated = rows !== undefined && rows.length >= DNC_LIST_LIMIT;

  /*
   * THE DO-NOT-CALL LIST, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * ## Every number on this screen stays on this device
   *
   * The list, the check box and the paste box are all phone numbers — the exact data hard
   * rule 6 and D-127 G-2 name first. The two inputs are declared `personal` so they leave
   * as `«PHONE_1»` / `«PRIVATE_1»` placeholders, and NOT ONE ROW of the list is declared
   * at any redaction: the assistant is told how many numbers are suppressed and why, which
   * is what "is this list working" needs, and nothing that could identify one of them.
   *
   * ## And neither input is writable
   *
   * This is the compliance surface where a wrong value is a call that should not have
   * happened (TCCCPR), in either direction: a number the assistant invented onto the list
   * silently stops a real customer being rung, and one it invented into the check box
   * answers a question about somebody else. Both are typed by a person or not at all.
   *
   * The REASON is writable, because it is a four-value enum describing a decision the
   * person has already made — and the form still says out loud that only "Added by your
   * team" can be undone, which is the part that matters and which nothing here changes.
   */
  useCopilotSurface({
    route: "/c/{slug}/do-not-call",
    title: "Do-not-call list",
    realm: "client",
    fields: [
      {
        id: "dnc-check-number",
        label: "Number being checked",
        type: "text",
        value: phone,
        writable: false,
        personal: "phone",
        help: "Typed by the reader. The assistant is told whether the box is filled in, never what is in it.",
      },
      {
        id: "dnc-paste",
        label: "Numbers pasted to suppress",
        type: "textarea",
        value: paste,
        writable: false,
        personal: "text",
        help: `A human-supplied list. ${parsed.length} number(s) parsed so far.`,
      },
      {
        id: "dnc-source",
        label: "Why these numbers are being suppressed",
        type: "select",
        value: source,
        options: SOURCE_OPTIONS.map((option) => ({
          value: option.value,
          label: `${option.label} — ${option.note}`,
        })),
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: rows
          ? "the suppressed list below has loaded"
          : entries.error
            ? "the list failed to load, so no number is shown"
            : "still loading",
      },
      {
        key: "suppressed_count",
        label: "Numbers on the list",
        value: rows === undefined ? "not known" : truncated ? `${rows.length} shown, which is the display ceiling — there may be more` : String(rows.length),
      },
      {
        key: "by_reason",
        label: "Why they are suppressed, by count",
        // Counted over the four KNOWN reasons rather than accumulated into a keyed
        // object: a tally keyed by a server string is `src/lib/lookup.ts`'s hazard in a
        // write position, and the reasons are a fixed set the form already enumerates.
        value: rows
          ? rows.length === 0
            ? "nothing is suppressed"
            : SOURCE_OPTIONS.map(
                (option) =>
                  `${option.label}: ${rows.filter((entry) => entry.source === option.value).length}`,
              ).join(", ")
          : "not known",
      },
      { key: "paste_parsed", label: "Numbers parsed out of the paste box", value: String(parsed.length) },
      {
        key: "paste_over_limit",
        label: "Is the pasted list over the per-add ceiling?",
        value: tooMany ? `yes — the ceiling is ${MAX_NUMBERS_PER_ADD} per add` : "no",
      },
      {
        key: "may_change",
        label: "May this session add or remove numbers?",
        value: write.allowed ? "yes" : `no — ${write.reason ?? "no reason given"}`,
      },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id !== "dnc-source") continue;
        const next = SOURCE_OPTIONS.find((option) => option.value === asText(item.value));
        if (next !== undefined) setSource(next.value);
      }
    },
  });

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Numbers your agents will never dial. The list is checked live before every single
        call, so anything added here takes effect straight away — including for a campaign
        that is already running.
      </p>

      <RestrictionNote reason={write.reason} />

      {/* Checking comes first: it is the question someone actually arrives with
          ("did we stop calling this person?"), and it is the one thing everyone with
          access to the account may do. */}
      <CheckNumber session={session} phone={phone} onPhoneChange={setPhone} />

      {write.allowed && (
        <AddNumbers
          session={session}
          paste={paste}
          onPasteChange={setPaste}
          source={source}
          onSourceChange={setSource}
          parsed={parsed}
        />
      )}

      <SuppressedList session={session} canSuppress={write.allowed} />
    </div>
  );
}
