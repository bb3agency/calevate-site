/**
 * The autodialler notice a sender records so their outbound can go out at all.
 *
 * WHY THIS MODULE EXISTS SEPARATELY FROM `agreements.ts`. The notice shows up as a
 * readiness BLOCKER on the agreements screen, and for a while that was the only trace of
 * it anywhere — a row telling a client to record something no screen could record. The
 * read and the write belong together in one module because they are one question ("where
 * does this account stand") asked and answered, and because the write's response IS the
 * new answer.
 *
 * RECORDING IT INVALIDATES READINESS, not just this key. The notice is one of the
 * predicates `legal.readiness.readiness_rows` composes, so a successful record changes
 * the agreements screen's verdict, its blocker list and the nav badge. Writing only this
 * key would leave the client looking at a screen that still says they are blocked.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { agreementsKey } from "./agreements";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AutodialerNotice = Schemas["AutodialerNoticeOut"];

const PATH = "/v1/compliance/autodialer-notice";

export function autodialerNoticeKey(orgSlug: string) {
  return ["autodialer-notice", orgSlug] as const;
}

/**
 * What this account has on file.
 *
 * No `refetchInterval`: nothing moves without somebody on this account recording
 * something, with one exception the server already handles — a notice dated in the future
 * becomes effective on its own date, and `effective` is derived server-side from the same
 * predicate the dial gate uses rather than from a date this browser compares.
 */
export function useAutodialerNotice(
  session: Session,
): UseQueryResult<AutodialerNotice> {
  return useQuery({
    queryKey: autodialerNoticeKey(session.orgSlug),
    queryFn: () => apiRequest<AutodialerNotice>(session, PATH),
    staleTime: 60_000,
  });
}

/** What one record sends. A withdrawal carries the same three facts, by design. */
export interface RecordNoticeBody {
  accessProvider: string;
  objective: string;
  notifiedOn: string;
  noticeReference?: string | null;
  withdraw?: boolean;
}

export function useRecordAutodialerNotice(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: RecordNoticeBody) =>
      apiRequest<AutodialerNotice>(session, PATH, {
        method: "POST",
        body: {
          access_provider: body.accessProvider,
          objective: body.objective,
          notified_on: body.notifiedOn,
          notice_reference: body.noticeReference ?? null,
          withdraw: body.withdraw ?? false,
        },
      }),
    onSuccess: (next) => {
      client.setQueryData(autodialerNoticeKey(session.orgSlug), next);
      // The readiness screen composes this predicate, so its verdict and blocker list are
      // stale the moment this succeeds.
      void client.invalidateQueries({
        queryKey: agreementsKey(session.orgSlug),
      });
    },
  });
}
