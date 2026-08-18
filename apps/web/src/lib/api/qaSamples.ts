"use client";

/**
 * The QA sampling queue — our weekly 5% spot-check (`/v1/admin/qa-samples`, admin realm).
 *
 * SURFACES §1 asks for a spot-check of ~5% of calls per client per week with the queue
 * surfaced in admin. `apps/api/quality/sampling.py` argues the draw: a keyed hash rather
 * than `random()`, the frame stored beside the sample, and a unique constraint so nothing
 * is silently re-sampled. What this module holds is the console's half.
 *
 * Three properties of the API kept rather than smoothed over:
 *
 * - **The draw's evidence is on every row and belongs on screen.** `population`,
 *   `target`, `selection_rank` and `selection_seed` are what turn "we sample 5%" from a
 *   claim into something a client can check, so the queue prints them instead of showing
 *   a tidy list of calls that appear to have been chosen by taste.
 * - **The transcript a reviewer reads is REDACTED, and the API offers no other kind.**
 *   The detail response embeds the same `CallDetailOut` the client's own call screen
 *   receives, with `redacted: true` on every turn. There is no raw variant on that
 *   router: raw transcript text has exactly ONE route in this product, role-checked and
 *   audit-logged, and nothing here reaches for it (hard rule 5).
 * - **A verdict is written once.** A second reviewer gets a 409, not a silent overwrite,
 *   so the mutation surfaces the refusal rather than pretending the click worked.
 *
 * `adminSession` is imported from `./admin` rather than rebuilt: that file owns the
 * admin realm's credential (TRD §11 — two realms, no shared session
 * logic), and a second builder here would be the second place a realm can be got wrong.
 *
 * Types are the GENERATED ones, aliased from `schema.d.ts`. `QaVerdict` is derived from
 * the field that carries it rather than re-declared, so the verdict vocabulary has one
 * definition: the server's enum. That matters because `VERDICTS` below is keyed by it —
 * a re-declared union would let the server grow a fourth verdict that this table has no
 * entry for, and the screen would render nothing for it rather than failing to compile.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

export const QA_SAMPLES_PATH = "/v1/admin/qa-samples";
export const QA_SAMPLES_QUERY_KEY = ["admin", "qa-samples"] as const;

type Schemas = components["schemas"];

export type QaSample = Schemas["QaSampleOut"];
export type QaSampleDetail = Schemas["QaSampleDetailOut"];
export type QaVerdict = NonNullable<QaSample["verdict"]>;

/** What each verdict means to the person picking one — and what it commits us to. */
export const VERDICTS: Record<QaVerdict, { label: string; meaning: string; tone: string }> = {
  clean: {
    label: "Clean",
    meaning: "The agent did what it was approved to do on this call.",
    tone: "ok",
  },
  concern: {
    label: "Concern",
    meaning: "Nothing was recorded wrongly, but something is worth a second look.",
    tone: "warn",
  },
  defect: {
    label: "Defect",
    meaning:
      "A detail wrong or invented, the disclosure missed, or something identifying left in a transcript. Raise it — this is the number the client's monthly report leads with.",
    tone: "stop",
  },
};

export function useQaSamples(pending: boolean): UseQueryResult<QaSample[]> {
  return useQuery({
    queryKey: [...QA_SAMPLES_QUERY_KEY, { pending }],
    queryFn: () =>
      apiRequest<QaSample[]>(adminSession(), `${QA_SAMPLES_PATH}?pending=${pending}`),
    // A shared work list two reviewers can be in at once — a row a colleague has just
    // reviewed should stop being offered. Same reason and same interval as the hold
    // queue, and the server does the same per-tenant walk, so not harder than that.
    refetchInterval: 60_000,
  });
}

export function useQaSample(sampleId: string): UseQueryResult<QaSampleDetail> {
  return useQuery({
    queryKey: [...QA_SAMPLES_QUERY_KEY, sampleId],
    queryFn: () => apiRequest<QaSampleDetail>(adminSession(), `${QA_SAMPLES_PATH}/${sampleId}`),
    enabled: Boolean(sampleId),
    /*
     * Every read of this route writes an `audit_log` row (it discloses one tenant's call
     * to somebody outside that tenant), and the trail has to count OPENINGS: not fewer,
     * which understates who saw what, and not more, which buries the real reads under
     * background churn. That is three settings, not one.
     *
     * `staleTime: Infinity` + the two `refetchOn*: false` kill the automatic reads. A
     * timer or a tab regaining focus is not a reviewer asking, and turning one review
     * into a page of audit entries makes the trail unreadable — the same argument
     * `kyc_routes.py` makes for not auditing a poll, solved here from the other end.
     *
     * `refetchOnMount: "always"` is what keeps the DELIBERATE read counted, and it is
     * why an infinite staleTime is not the whole answer. TanStack reads `true` as
     * "refetch on mount if stale", which under this staleTime is never; `"always"`
     * refetches on every mount regardless of staleness (TanStack Query v5
     * `refetchOnMount`). Without it a reviewer who worked two samples and came back to
     * the first was served from the cache — the screen remounts, the request does not
     * happen — and the audit log recorded one disclosure where there had been two.
     * SEC-COMP §5 says admin reads are ALWAYS audited, and a cache is not an exception
     * that rule grants. `tests/qaSampling.test.tsx` drives two mounts through one
     * `QueryClient` and counts the requests.
     */
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: "always",
    staleTime: Infinity,
  });
}

export function useReviewQaSample(sampleId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (verdict: QaVerdict) =>
      apiRequest<QaSample>(adminSession(), `${QA_SAMPLES_PATH}/${sampleId}/review`, {
        method: "POST",
        body: { verdict },
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: QA_SAMPLES_QUERY_KEY }),
  });
}
