"use client";

import { useState } from "react";
import { CircleCheck } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice, RestrictionNote } from "@/components/ui";
import { needsAction, useAcceptAgreement, type LegalReadiness } from "@/lib/api/agreements";
import { useClientSession } from "@/lib/api/session";

import { AGREEMENTS_COPY as COPY, acceptLabel } from "./copy";
import { WhyTip } from "./_ui/WhyTip";

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
  const acceptFeedback = useActionFeedback(accept, { errorDisplay: "inline" });
  const [ticked, setTicked] = useState(false);

  const outstanding = readiness.documents.filter(
    (doc) => doc.blocking && needsAction(doc),
  );

  if (outstanding.length === 0) {
    return (
      <p className="mt-4 flex flex-wrap items-center gap-x-2 text-meta text-ink-muted">
        <CircleCheck className="h-4 w-4 shrink-0 text-brand-strong" aria-hidden="true" />
        {COPY.allAccepted}
        <WhyTip about="when we ask again" label="More">
          <p>{COPY.allAcceptedWhy}</p>
        </WhyTip>
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
    <form
      noValidate
      className="mt-5 rounded-card border border-line bg-surface p-4 sm:p-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (ticked && !accept.isPending) void submit();
      }}
    >
      <h3 className="text-meta font-semibold text-ink-muted">{COPY.agreeHeading}</h3>
      {/* The statement is legal text: shown whole, word for word, never shortened. The
          whole sentence is the tap target, not the 20px box beside it, and the box scrolls
          inside itself if a future statement runs long on a phone. */}
      <label className="mt-2 flex max-h-72 cursor-pointer items-start gap-3 overflow-y-auto overscroll-contain rounded-md border border-line p-3 text-body leading-relaxed text-ink hover:bg-ink/[0.03]">
        <input
          type="checkbox"
          checked={ticked}
          onChange={(event) => setTicked(event.target.checked)}
          className="mt-0.5 h-5 w-5 shrink-0 cursor-pointer accent-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
        />
        <span className="[text-wrap:pretty]">{readiness.acceptance_statement}</span>
      </label>
      {accept.error ? (
        <div className="mt-4">
          <ProblemNotice error={accept.error} />
        </div>
      ) : null}
      <div className="mt-4 flex flex-wrap items-center justify-end gap-x-5 gap-y-3 border-t border-line pt-4">
        <p className="mr-auto min-w-0 basis-56 grow text-meta text-ink-muted">
          {COPY.recordNote}
        </p>
        <ActionButton
          type="submit"
          status={acceptFeedback.status}
          disabled={!ticked}
          pendingLabel={COPY.pending}
          successLabel={COPY.success}
          className="max-sm:w-full"
        >
          {acceptLabel(outstanding.length)}
        </ActionButton>
      </div>
    </form>
  );
}
