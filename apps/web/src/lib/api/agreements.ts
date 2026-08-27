"use client";

/**
 * Agreements & readiness — the one read behind `/c/[slug]/agreements`.
 *
 * `GET /v1/legal/readiness` answers three questions at once, and it is one endpoint
 * rather than three because they are one question to the person asking: which documents
 * bind this business and where do we stand with them, what else is stopping our calls,
 * and may we operate.
 *
 * FOUR PROPERTIES OF THE API THIS MODULE KEEPS RATHER THAN SMOOTHS OVER — all four are
 * the same doctrine `lib/api/aiQuota.ts` states at the top of this directory, and it
 * binds harder here than anywhere else in the console because the subject is a compliance
 * verdict four server-side gates already compute:
 *
 * - **`may_operate` and `verdict` are the SERVER's.** A browser that re-derived "all four
 *   accepted, therefore ready" would eventually disagree with `check_dispatch`, which is
 *   the thing that actually refuses the call — and it would be wrong the moment a
 *   condition that has nothing to do with documents (a lapsed registration, an empty
 *   wallet) is what is in the way.
 * - **Each document's `state` and `headline` are the server's.** "Accepted", "needs
 *   accepting again" and "changed but not blocking" are decided by
 *   `legal.catalogue.reacceptance_required`, which knows every revision's `material`
 *   flag. This module never compares a version string.
 * - **Each blocker arrives with `actor` and `next_step` already decided.** Whose move a
 *   refusal is, is a fact about the rule, not about the screen; `legal/readiness.py`
 *   holds the table and a test holds it to rule names the code really emits.
 * - **The acceptance WORDING travels with the state.** `acceptance_statement` and
 *   `acceptance_statement_version` carry no defaults and are posted back exactly as they
 *   arrived — the same shape `whatsappAlerts.ts` uses, for the same reason: the stored
 *   `statement_version` is evidence only while the text it names can be produced, and a
 *   sentence living in a React component cannot be. A console showing a stale build is
 *   REFUSED (`legal_statement_not_current`), never recorded.
 *
 * `outstanding_documents` is likewise the server's count, so the nav badge and the page
 * cannot disagree, and adding a ninth document needs no edit here.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** The whole screen: documents, blockers, verdict, and what this caller may do. */
export type LegalReadiness = Schemas["LegalReadinessOut"];
/** One published document and where this organisation stands with it. */
export type LegalDocumentState = Schemas["LegalDocumentOut"];
/** One organisation-level condition blocking outgoing calls. */
export type ReadinessBlocker = Schemas["ReadinessRowOut"];
/** The five states a document can be in, as a union the screen switches on. */
export type DocumentState = LegalDocumentState["state"];
/** Whose move a blocker is. */
export type BlockerActor = ReadinessBlocker["actor"];

export const READINESS_PATH = "/v1/legal/readiness";
export const ACCEPTANCES_PATH = "/v1/legal/acceptances";

export function agreementsKey(orgSlug: string) {
  return ["legal-readiness", orgSlug] as const;
}

/**
 * The readiness read.
 *
 * No `refetchInterval`. Nothing on this screen moves without somebody doing something —
 * a document is published by a deploy, a registration is cleared by an operator — and a
 * page that re-read every twenty seconds would be re-asking eight predicates, one of
 * which counts campaigns, for a screen a client opens once and acts on.
 */
export function useAgreementsReadiness(session: Session): UseQueryResult<LegalReadiness> {
  return useQuery({
    queryKey: agreementsKey(session.orgSlug),
    queryFn: () => apiRequest<LegalReadiness>(session, READINESS_PATH),
    staleTime: 60_000,
  });
}

/** What one acceptance sends. Every field is echoed from the read; none is minted here. */
export interface AcceptBody {
  slug: string;
  version: string;
  statementVersion: string;
}

/**
 * Accept one agreement.
 *
 * The response IS the whole readiness screen — accepting the third of four agreements
 * changes the verdict, the blocker list and the badge — so it is written straight into
 * the cache rather than triggering a refetch. The invalidation that follows is for the
 * SHELL: the nav badge and anything else reading this key elsewhere in the app.
 */
export function useAcceptAgreement(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AcceptBody) =>
      apiRequest<LegalReadiness>(session, ACCEPTANCES_PATH, {
        method: "POST",
        body: {
          slug: body.slug,
          version: body.version,
          statement_version: body.statementVersion,
        },
      }),
    onSuccess: (next) => {
      client.setQueryData(agreementsKey(session.orgSlug), next);
      void client.invalidateQueries({ queryKey: agreementsKey(session.orgSlug) });
    },
  });
}

/**
 * Does this document still need the owner's click? Blocking or not.
 *
 * A predicate over the SERVER's `state`, never over version strings — the two states it
 * names are the two the server decides, and `changed` is included because a non-material
 * revision still wants acknowledging even though nothing is blocked by it.
 */
export function needsAction(doc: LegalDocumentState): boolean {
  return (
    doc.state === "never_accepted" ||
    doc.state === "reacceptance_required" ||
    doc.state === "changed"
  );
}
