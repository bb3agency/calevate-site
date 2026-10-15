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

import { livePoll } from "@/lib/live/liveStatus";
import { hasKey } from "@/lib/lookup";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

export const QA_SAMPLES_PATH = "/v1/admin/qa-samples";
export const QA_SAMPLES_QUERY_KEY = ["admin", "qa-samples"] as const;
/** The list reads, apart from the detail read: invalidating these never re-reads a call. */
const QUEUE_QUERY_KEY = [...QA_SAMPLES_QUERY_KEY, "queue"] as const;

type Schemas = components["schemas"];

export type QaSample = Schemas["QaSampleOut"];
export type QaSampleDetail = Schemas["QaSampleDetailOut"];
export type QaQueuePage = Schemas["QaQueuePage"];
export type QaQueueClient = Schemas["QaQueueClient"];
export type QaVerdict = NonNullable<QaSample["verdict"]>;

/** What each verdict means to the person picking one — and what it commits us to. */
export const VERDICTS: Record<QaVerdict, { label: string; meaning: string; tone: string }> = {
  clean: {
    label: "Clean",
    meaning: "The agent did what it was set up to do on this call.",
    tone: "ok",
  },
  concern: {
    label: "Concern",
    meaning: "Nothing was wrong, but something is worth a second look.",
    tone: "warn",
  },
  defect: {
    label: "Defect",
    meaning:
      "A detail wrong or made up, the AI disclosure missed, or something personal left visible. Defects lead the client's monthly quality report.",
    tone: "stop",
  },
};

/** Which calls the queue lists. */
export type QueueStatus = "waiting" | "reviewed" | "all";
export type QueueOrder = "oldest" | "newest";

/**
 * The queue's filters, as the URL holds them, so a filtered view can be shared and
 * survives a refresh. `client` is a tenant id; `week` is a draw week's IST Monday.
 */
export interface QueueFilters {
  status: QueueStatus;
  verdict: QaVerdict | null;
  client: string | null;
  week: string | null;
  order: QueueOrder;
  page: number;
}

export const QUEUE_PAGE_SIZE = 50;
/** The API answers pages up to this offset (`sampling.QUEUE_WINDOW_MAX` less one page). */
export const QUEUE_MAX_OFFSET = 900;

export const DEFAULT_FILTERS: QueueFilters = {
  status: "waiting",
  verdict: null,
  client: null,
  week: null,
  order: "oldest",
  page: 1,
};

const STATUSES: readonly QueueStatus[] = ["waiting", "reviewed", "all"];

export function filtersFromSearch(search: URLSearchParams): QueueFilters {
  const status = search.get("status");
  const verdict = search.get("verdict");
  const page = Number.parseInt(search.get("page") ?? "1", 10);
  return {
    status: STATUSES.includes(status as QueueStatus) ? (status as QueueStatus) : "waiting",
    verdict: verdict !== null && hasKey(VERDICTS, verdict) ? verdict : null,
    client: search.get("client") || null,
    week: search.get("week") || null,
    order: search.get("order") === "newest" ? "newest" : "oldest",
    page: Number.isFinite(page) && page > 1 ? page : 1,
  };
}

/** The query string for `filters`, leaving out every default so a plain queue has none. */
export function filtersToSearch(filters: QueueFilters): string {
  const search = new URLSearchParams();
  if (filters.status !== "waiting") search.set("status", filters.status);
  if (filters.verdict) search.set("verdict", filters.verdict);
  if (filters.client) search.set("client", filters.client);
  if (filters.week) search.set("week", filters.week);
  if (filters.order !== "oldest") search.set("order", filters.order);
  if (filters.page > 1) search.set("page", String(filters.page));
  return search.toString();
}

function scope(search: URLSearchParams, filters: Pick<QueueFilters, "client" | "week">) {
  if (filters.client) search.set("tenant_id", filters.client);
  if (filters.week) search.set("week", filters.week);
}

/** The API path for one page of the queue under `filters`. */
export function queuePath(filters: QueueFilters): string {
  const search = new URLSearchParams({
    status: filters.status,
    order: filters.order,
    limit: String(QUEUE_PAGE_SIZE),
    offset: String(Math.min((filters.page - 1) * QUEUE_PAGE_SIZE, QUEUE_MAX_OFFSET)),
  });
  // A verdict narrows only what has one; the console never pairs it with "waiting".
  if (filters.verdict && filters.status !== "waiting") search.set("verdict", filters.verdict);
  scope(search, filters);
  return `${QA_SAMPLES_PATH}?${search.toString()}`;
}

/**
 * The API path for the next calls to review under the same client and week — two, so
 * the review screen can skip the call it is showing.
 */
export function nextWaitingPath(filters: Pick<QueueFilters, "client" | "week">): string {
  const search = new URLSearchParams({ status: "waiting", order: "oldest", limit: "2", offset: "0" });
  scope(search, filters);
  return `${QA_SAMPLES_PATH}?${search.toString()}`;
}

export function useQaQueue(filters: QueueFilters): UseQueryResult<QaQueuePage> {
  const path = queuePath(filters);
  return useQuery({
    queryKey: [...QUEUE_QUERY_KEY, path],
    queryFn: () => apiRequest<QaQueuePage>(adminSession(), path),
    // A shared work list two reviewers can be in at once — a row a colleague has just
    // reviewed should stop being offered. Same reason and same interval as the hold
    // queue, and the server does the same per-tenant walk, so not harder than that.
    refetchInterval: livePoll(60_000),
    placeholderData: keepPreviousData,
  });
}

/**
 * The first waiting call under `filters`' client and week other than `skip`, or null
 * when nothing is waiting. `undefined` while it is being read.
 */
export function useNextWaiting(
  filters: Pick<QueueFilters, "client" | "week">,
  { skip, enabled = true }: { skip?: string; enabled?: boolean } = {},
): { next: QaSample | null | undefined; query: UseQueryResult<QaQueuePage> } {
  const path = nextWaitingPath(filters);
  const query = useQuery({
    queryKey: [...QUEUE_QUERY_KEY, path],
    queryFn: () => apiRequest<QaQueuePage>(adminSession(), path),
    enabled,
  });
  const next = query.data ? (query.data.items.find((row) => row.id !== skip) ?? null) : undefined;
  return { next, query };
}

export function useQaSample(sampleId: string): UseQueryResult<QaSampleDetail> {
  return useQuery({
    // Its own family, outside `admin/qa-samples`, so a live note about the queue never
    // invalidates an open review (an invalidation refetches whatever staleTime says).
    queryKey: ["admin", "qa-sample", sampleId],
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
    // The queue only. The detail query is left alone: every read of it writes an audit
    // row, and the POST's answer already says what was recorded.
    onSuccess: () => void client.invalidateQueries({ queryKey: QUEUE_QUERY_KEY }),
  });
}
