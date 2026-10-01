"use client";

import { useState } from "react";
import { CircleCheck } from "lucide-react";

import { PRIMARY_BUTTON, ProblemNotice, RestrictionNote } from "@/components/ui";
import { needsAction, useAcceptAgreement, type LegalReadiness } from "@/lib/api/agreements";
import { useClientSession } from "@/lib/api/session";

/**
 * The tick and the button — or the sentence saying why there is neither.
 *
 * The statement text and its version are the server's and are posted back exactly as they
 * arrived: the stored `statement_version` is evidence only while the text it names can be
 * produced, and a sentence living in this component could not be. A console showing a
 * stale build is REFUSED (`legal_statement_not_current`), never recorded.
 */
export function AcceptPanel({ readiness }: { readiness: LegalReadiness }) {
  const session = useClientSession();
  const accept = useAcceptAgreement(session);
  const [ticked, setTicked] = useState(false);

  const outstanding = readiness.documents.filter(
    (doc) => doc.blocking && needsAction(doc),
  );

  if (outstanding.length === 0) {
    return (
      <p className="mt-3 flex items-center gap-2 text-sm text-ink-muted">
        <CircleCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
        Every agreement here has been accepted at its current version. We will
        ask again when one of them changes in a way that needs it.
      </p>
    );
  }

  if (!readiness.can_accept) {
    return (
      <div className="mt-4">
        <RestrictionNote reason={readiness.can_accept_reason} />
      </div>
    );
  }

  /**
   * One POST per document, in order, stopping at the first refusal.
   *
   * `mutateAsync` in a loop rather than four parallel calls: the response to each one is
   * the WHOLE screen, so concurrent writes would race to seed the cache and the last to
   * land would win with the oldest view. Sequential, the final response is the true final
   * state. A refusal (a version that moved under an open tab) leaves the earlier rows
   * recorded, which is what actually happened.
   */
  const submit = async () => {
    try {
      for (const doc of outstanding) {
        await accept.mutateAsync({
          slug: doc.slug,
          version: doc.version,
          statementVersion: readiness.acceptance_statement_version,
        });
      }
    } catch {
      // Swallowed HERE and nowhere else, and it is not a swallowed error: the refusal is
      // already on `accept.error` and is rendered below, verbatim, with its remediation.
      // What this catch stops is the loop's own rejection escaping into an unhandled
      // promise — `mutateAsync` rejects as well as recording, unlike `mutate` — which in
      // a browser is a console error nobody sees and in the suite is an unhandled
      // rejection that can fail an unrelated test.
      return;
    }
    setTicked(false);
  };

  return (
    <div className="mt-4">
      <label className="flex items-start gap-3 text-sm text-ink">
        <input
          type="checkbox"
          checked={ticked}
          onChange={(event) => setTicked(event.target.checked)}
          className="mt-1 h-4 w-4 shrink-0"
        />
        <span>{readiness.acceptance_statement}</span>
      </label>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={!ticked || accept.isPending}
          onClick={() => void submit()}
          className={PRIMARY_BUTTON}
        >
          <CircleCheck className="h-4 w-4" aria-hidden="true" />
          {accept.isPending
            ? "Recording…"
            : `Accept ${outstanding.length} agreement${outstanding.length === 1 ? "" : "s"}`}
        </button>
        <span className="text-xs text-ink-faint">
          We record which documents you accepted, at which version, and when.
        </span>
      </div>
      {accept.error ? (
        <div className="mt-3">
          <ProblemNotice error={accept.error} />
        </div>
      ) : null}
    </div>
  );
}

