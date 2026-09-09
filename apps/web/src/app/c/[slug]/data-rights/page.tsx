"use client";

import { useDeletionRequests } from "@/lib/api/dataRights";
import { Term } from "@/lib/glossary";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { Erasure } from "./Erasure";
import { Register } from "./Register";
import { SubjectExport } from "./SubjectExport";

/**
 * Data rights (DPDP §11, SEC-COMP §4) — the screen for the two requests a data principal
 * can make of a client, and the certificate that answers the second one.
 *
 * All three endpoints behind this shipped built, audited, worker-backed and producing
 * proof certificates, with ZERO callers. A client honouring someone's rights therefore
 * did it by curl or by emailing us — for an obligation that has a statutory clock on it.
 * That is what this closes; it is a compliance surface, not a convenience.
 *
 * The screen is three sibling modules, one per subject (UX-DOCTRINE §6), in the order a
 * client meets them — ask what we hold, ask us to erase it, then check what happened:
 *
 * - `SubjectExport.tsx` — what we hold about a person, and why the file is never painted
 *   on screen.
 * - `Erasure.tsx` — the irreversible act, its consequences stated above the button.
 * - `Register.tsx` — the account's own register and the proof certificates, read from the
 *   server rather than from this browser's memory.
 */
export default function DataRightsPage() {
  const session = useClientSession();
  /*
   * The SAME read `Register` makes, shared through the query cache rather than
   * fetched twice. Declared here and not in the card for the reason `settings/models`
   * gives: child effects commit before their parent's, so the innermost registration
   * wins — one declaration per screen, and it belongs where the launcher is wanted on
   * every state including the loading and failed ones.
   */
  const requests = useDeletionRequests(session);

  /*
   * THIS SCREEN, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * ## Nothing here is writable, and nothing personal leaves
   *
   * The two boxes on this screen take a phone number, and what they do with it is build a
   * file containing everything this account holds about that person, or erase them. Those
   * are the two acts on this console with a statutory clock and no undo, and they are
   * addressed at a named human being — so neither box is declared at all, and the phrase
   * ERASE the erasure form makes a person type is the ceremony this deliberately leaves
   * alone. Filling in either from a model's guess is not a feature.
   *
   * ## The register IS declared, because the numbers in it are already one-way hashed
   *
   * `subject_ref` is a hash, not a number, and the screen says so — but even that is not
   * sent: the assistant is told how many requests there are and how they are progressing,
   * which is what an owner answering a regulator's question needs, and the register
   * itself stays on the screen.
   *
   * §52 IS CARRIED INTO THE FACT rather than flattened: "this account has been asked to
   * erase nobody" is an answer a client could repeat to a regulator, and "we could not
   * read the register" is not. The assistant must not be able to confuse them either.
   */
  useCopilotSurface({
    route: "/c/{slug}/data-rights",
    title: "Data rights",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: requests.data
          ? "the erasure register below has loaded"
          : requests.error
            ? "the register failed to load — this is NOT evidence that nobody has asked to be erased"
            : "still loading",
      },
      ...(requests.data
        ? [
            { key: "requests_total", label: "Erasure requests on the register", value: String(requests.data.length) },
            {
              key: "requests_pending",
              label: "Of those, still running",
              value: String(requests.data.filter((request) => request.status === "pending").length),
            },
            {
              key: "requests_completed",
              label: "Of those, completed",
              value: String(requests.data.filter((request) => request.status === "completed").length),
            },
            {
              key: "requests_with_certificate",
              label: "Requests with an erasure certificate on file",
              value: String(requests.data.filter((request) => request.has_certificate).length),
            },
          ]
        : []),
    ],
    apply: noFill,
  });

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Under India&rsquo;s data protection law a person can ask you what you hold about
        them, and can ask you to erase it. You are the{" "}
        <Term id="dataFiduciary" />{" "}
        and Calevate holds the records on your behalf, so both requests are answered from
        here. Every request below is recorded against your account, so there is a lasting
        record of who asked and when.
      </p>

      <SubjectExport session={session} />
      <Erasure session={session} />
      <Register session={session} />
    </div>
  );
}
