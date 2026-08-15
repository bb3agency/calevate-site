"use client";

/**
 * The leads data layer — ownership, history, and the list filter that needs both.
 *
 * **Why the leads hooks live here and not beside `useMe` in `hooks.ts`.** The list keeps
 * gaining filters, and a filter that a hook's type does not name is a filter that cannot
 * be sent — `hooks.ts::useLeads` declared `{status, search, limit, offset}` and nothing
 * more while the API had grown three more. Each time the answer has been to REPLACE the
 * hook and move its one caller (`app/c/[slug]/leads`) in the same change, never to add a
 * second one beside it.
 *
 * Everything is aliased from the GENERATED schema, never hand-written: the drift this
 * repo has already paid for once (a local `UsagePanel` interface that quietly lost
 * `overage_rate_inr`) is the reason. The ONE exception is the block at the foot of this
 * file, which is marked, dated and carries its own removal instructions.
 *
 * **`useLeads(filters)` is gone and `useLeadsUnderLens(lens)` replaced it**, in the same
 * change and with the same one caller moved — a saved view names a filter set AND a
 * column selection, and the export has to be able to send the identical thing, so the
 * thing has to be one object with one serializer (`lensQuery`). Keeping the old hook
 * beside the new one would have been two ways to ask one question, which is where the
 * screen and the file start to disagree. `useExportLeads` moved here from `hooks.ts` for
 * the same reason: it takes the same lens or it is not an export of what you are looking
 * at. The query KEY still starts `["leads", orgSlug, ...]`, so the invalidations in
 * `hooks.ts` keep matching across the move.
 */

import { useCallback, useState } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type LeadList = Schemas["LeadListOut"];
export type Lead = Schemas["LeadOut"];
export type LeadStatus = Lead["status"];
/** One colleague. Ids and display names only — the API sends no email (tenancy/routes.py). */
export type Member = Schemas["MemberOut"];
export type LeadTimeline = Schemas["LeadTimelineOut"];
export type LeadTimelineEvent = Schemas["LeadTimelineEventOut"];

/** The leads list polls slowly — a lead lands with the post-call pipeline, not live. */
const SLOW_INTERVAL_MS = 60_000;

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export function useLead(session: Session, leadId: string): UseQueryResult<Lead> {
  return useQuery({
    queryKey: ["lead", session.orgSlug, leadId],
    queryFn: () => apiRequest<Lead>(session, `/v1/leads/${leadId}`),
    enabled: Boolean(leadId),
  });
}

/**
 * One lead's history (ROADMAP M3).
 *
 * NO `placeholderData` and no fallback anywhere: an empty timeline and a timeline whose
 * request failed are different sentences, and the screen has to be able to tell them
 * apart from the query alone (BUILD-LOG §52 — "loading is a skeleton, failure is a
 * refusal, and neither is a number, a state, or an empty state").
 */
export function useLeadTimeline(
  session: Session,
  leadId: string,
  limit = 50,
): UseQueryResult<LeadTimeline> {
  return useQuery({
    queryKey: ["lead-timeline", session.orgSlug, leadId, limit],
    queryFn: () =>
      apiRequest<LeadTimeline>(session, `/v1/leads/${leadId}/timeline${query({ limit })}`),
    enabled: Boolean(leadId),
  });
}

/**
 * The account's team, for the assignee picker.
 *
 * `staleTime` is generous because a team changes when somebody accepts an invitation,
 * which is not a thing that happens while a table is open.
 */
export function useMembers(session: Session): UseQueryResult<Member[]> {
  return useQuery({
    queryKey: ["members", session.orgSlug],
    queryFn: () => apiRequest<Member[]>(session, "/v1/members"),
    staleTime: 5 * 60_000,
  });
}

/**
 * One inline edit of one lead — status, name, or owner.
 *
 * **This replaced `useUpdateLeadStatus` (hooks.ts) and `useAssignLead`, and moved both
 * callers in the same change.** They were two hooks issuing the same `PATCH
 * /v1/leads/{id}` with two invalidation sets and two error channels, which is the
 * "two ways of doing one thing" defect and it had a visible cost: a row could only ever
 * surface ONE of them, so a failed status edit and a failed assignment competed for the
 * same pixel. One mutation means one place a row's failure can be reported.
 *
 * `assigned_to: null` is sent as an explicit `null` and MUST stay one: the API tells
 * "unassign" from "leave the owner alone" by whether the key is present in the body
 * (`crm.routes.patch_lead`), so dropping the key when the value is null — which is what
 * a helper that strips undefined-ish values would do — would silently turn every
 * unassignment into a no-op that answered 200. That is why the edit is spread into the
 * body verbatim rather than rebuilt field by field.
 */
export interface LeadEdit {
  /** Present key = change the owner; an explicit `null` = unassign. */
  assigned_to?: string | null;
  status?: LeadStatus;
  name?: string;
}

export function useEditLead(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ leadId, edit }: { leadId: string; edit: LeadEdit }) =>
      apiRequest<Lead>(session, `/v1/leads/${leadId}`, { method: "PATCH", body: edit }),
    onSuccess: (_lead, { leadId }) => {
      // Invalidate rather than patch: an edit also writes a timeline row, the server may
      // have moved the lead itself (a hot-lead rule fires on the pipeline side), and the
      // list's status counts are computed over the filtered set — so a screen filtered to
      // "assigned to me" has to re-ask rather than re-render.
      void client.invalidateQueries({ queryKey: ["leads", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["dashboard", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["lead", session.orgSlug, leadId] });
      void client.invalidateQueries({ queryKey: ["lead-timeline", session.orgSlug, leadId] });
    },
  });
}

/** What a row needs to know about its own edit: is mine in flight, and did mine fail. */
export interface RowEditing {
  edit: (leadId: string, edit: LeadEdit) => void;
  /** The failure THIS row's last edit met, or null. */
  errorFor: (leadId: string) => unknown;
  pendingFor: (leadId: string) => boolean;
}

/**
 * The same mutation, with the failure kept ON THE ROW that caused it.
 *
 * The defect this exists to close: an inline edit that fails and reverts is a lie the
 * user cannot see. The `<select>` snaps back to the old value — because the row is
 * re-rendered from a cache the server never changed — and unless something says so, the
 * only evidence is a value that did not stick. A single page-level `ProblemNotice` is
 * not enough on a hundred-row table: it says an edit failed without saying WHICH, so a
 * client who changed four rows in a row cannot tell which three took.
 *
 * `pendingFor` is per-row for the same reason the dispatch button is: `mutation.isPending`
 * is one flag for the whole table, so using it directly disables every other row's
 * controls while one row is saving.
 *
 * The error map is keyed by lead id and cleared on that lead's next success, so a fixed
 * row stops complaining without the client reloading.
 */
export function useLeadRowEdit(session: Session): RowEditing {
  const mutation = useEditLead(session);
  const [errors, setErrors] = useState<Record<string, unknown>>({});

  const edit = useCallback(
    (leadId: string, patch: LeadEdit) => {
      mutation.mutate(
        { leadId, edit: patch },
        {
          onError: (error) => setErrors((prev) => ({ ...prev, [leadId]: error })),
          onSuccess: () =>
            setErrors((prev) => {
              // `Object.hasOwn`, not `in`: `in` walks the prototype chain, which is the
              // defect `lib/lookup.ts` exists for and the lint rule forbids.
              if (!Object.hasOwn(prev, leadId)) return prev;
              const next = { ...prev };
              delete next[leadId];
              return next;
            }),
        },
      );
    },
    [mutation],
  );

  return {
    edit,
    // `Object.hasOwn`, not `errors[leadId]`: `errors` is a plain object literal and a
    // lead id is a uuid, so the prototype chain cannot actually be reached here — but
    // `lib/lookup.ts` exists because this app has already shipped that bug once, and a
    // guarded read costs nothing.
    errorFor: (leadId: string) => (Object.hasOwn(errors, leadId) ? errors[leadId] : null),
    pendingFor: (leadId: string) =>
      mutation.isPending && mutation.variables?.leadId === leadId,
  };
}

/**
 * The lead-table lens types, aliased from the generated client like everything else in
 * this file. They were hand-written while the slice was in flight and the snapshot had
 * not been regenerated; that block is gone, and with it the one place in this app that
 * was a claim about the server TypeScript could not check.
 *
 * `LeadListWithColumns` in particular is now just `LeadListOut`: the intersection it used
 * to describe — the generated list type PLUS three hand-declared fields — exists in the
 * generator's own output now, so keeping the intersection would re-introduce exactly the
 * drift it was carefully written to contain.
 */
export type LeadColumn = Schemas["LeadColumnOut"];
export type LeadFacets = Schemas["LeadFacetsOut"];
export type SavedView = Schemas["SavedViewOut"];
export type LeadListWithColumns = Schemas["LeadListOut"];

/**
 * Everything that decides WHICH ROWS and WHICH COLUMNS — one object, because the screen,
 * the facet counts and the CSV export all have to be looking at the same thing.
 *
 * `fields` is the faceted half: key → selected values. It serializes to repeated `f=`
 * parameters, which is the shape the API takes (`crm.routes._parse_field_filters`).
 */
export interface LeadLens {
  status?: string;
  search?: string;
  assigned_to?: string;
  agent_id?: string;
  /** Extraction-schema key → selected values. OR within a key, AND across keys. */
  fields?: Record<string, string[]>;
  /** Column keys in display order. `undefined` = the client has chosen nothing. */
  columns?: string[];
}

/**
 * `LeadLens` → query string, in ONE function used by the list, the facets and the export.
 *
 * That is the whole "mirrored in CSV export" requirement on this side: the file cannot
 * disagree with the screen about the filters if there is only one place that spells them.
 * `paging` is separate because the export has none and the facets ignore it.
 */
export function lensQuery(lens: LeadLens, paging: { limit?: number; offset?: number } = {}): string {
  const search = new URLSearchParams();
  const scalars: Record<string, string | number | undefined> = {
    status: lens.status,
    search: lens.search,
    assigned_to: lens.assigned_to,
    agent_id: lens.agent_id,
    ...paging,
  };
  for (const [key, value] of Object.entries(scalars)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  if (lens.columns?.length) search.set("columns", lens.columns.join(","));
  for (const [key, values] of Object.entries(lens.fields ?? {})) {
    for (const value of values) search.append("f", `${key}:${value}`);
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/** The leads list, under a lens. Replaces `useLeads`'s filter object one caller at a time. */
export function useLeadsUnderLens(
  session: Session,
  lens: LeadLens,
  paging: { limit?: number; offset?: number } = {},
): UseQueryResult<LeadListWithColumns> {
  const qs = lensQuery(lens, paging);
  return useQuery({
    queryKey: ["leads", session.orgSlug, qs],
    queryFn: () => apiRequest<LeadListWithColumns>(session, `/v1/leads${qs}`),
    refetchInterval: SLOW_INTERVAL_MS,
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
  });
}

/**
 * The facet rail and its counts.
 *
 * A SEPARATE query from the list, matching the server's split: the counts change when
 * the filters change and not when the page does, so folding them into the list would
 * recompute up to eight aggregates on every scroll. No `placeholderData`: a stale count
 * beside a fresh table is a number nobody sent.
 */
export function useLeadFacets(session: Session, lens: LeadLens): UseQueryResult<LeadFacets> {
  // Columns do not change the counts, so they are stripped from the key — otherwise
  // opening the column chooser would refetch the whole rail.
  const qs = lensQuery({ ...lens, columns: undefined });
  return useQuery({
    queryKey: ["lead-facets", session.orgSlug, qs],
    queryFn: () => apiRequest<LeadFacets>(session, `/v1/leads/facets${qs}`),
  });
}

export function useSavedViews(session: Session): UseQueryResult<SavedView[]> {
  return useQuery({
    queryKey: ["lead-views", session.orgSlug],
    queryFn: async () =>
      (await apiRequest<{ items: SavedView[] }>(session, "/v1/leads/views")).items,
  });
}

export interface SavedViewBody {
  name: string;
  filters: {
    status?: string | null;
    agent_id?: string | null;
    assigned_to_me?: boolean;
    fields?: Record<string, string[]>;
  };
  columns?: string[] | null;
}

export function useSaveView(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ viewId, body }: { viewId?: string; body: SavedViewBody }) =>
      apiRequest<SavedView>(
        session,
        viewId ? `/v1/leads/views/${viewId}` : "/v1/leads/views",
        { method: viewId ? "PATCH" : "POST", body },
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["lead-views", session.orgSlug] });
    },
  });
}

export function useDeleteView(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (viewId: string) =>
      apiRequest<void>(session, `/v1/leads/views/${viewId}`, { method: "DELETE" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["lead-views", session.orgSlug] });
    },
  });
}

/**
 * The bulk-action wire types, aliased from the generated client.
 *
 * `scope` is the field worth reading twice: it is the SERVER's record of which set ran —
 * the ticked rows or every lead the filters match — and the summary sentence is built
 * from it rather than from what the screen believed it sent. `unchanged` is a SUCCESS
 * bucket (already in the target state, D-65) and must never be rendered as failure.
 */
export type LeadBulkFailure = Schemas["LeadBulkFailureOut"];
export type LeadBulkResult = Schemas["LeadBulkOut"];
export type LeadBulkBody = Schemas["LeadBulkIn"];
export type LeadBulkAction = LeadBulkBody["action"];

/**
 * One action over many leads (SURFACES §2).
 *
 * The LENS goes in the query string and the ACTION goes in the body, which is not an
 * arbitrary split: `lensQuery` is the one place this app spells "which rows", shared with
 * the table, the facet counts and the CSV export, and a filter-scoped bulk action has to
 * mean the same set as the table it was launched from. A second spelling in the body
 * would be the drift that whole arrangement exists to prevent.
 *
 * `columns` is stripped before serialising: which COLUMNS you were looking at cannot
 * narrow which ROWS an action touches, and sending them would put a meaningless
 * parameter on a write.
 *
 * No `Idempotency-Key`: the write is already idempotent (status and owner are
 * single-value fields, and a re-run reports `unchanged`), which is what `POST
 * /v1/leads/bulk`'s own docstring argues. A key here would be ceremony over a property
 * the server already has.
 */
export function useBulkLeads(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ lens, body }: { lens: LeadLens; body: LeadBulkBody }) =>
      apiRequest<LeadBulkResult>(
        session,
        `/v1/leads/bulk${lensQuery({ ...lens, columns: undefined })}`,
        { method: "POST", body },
      ),
    onSuccess: () => {
      // Every count on this screen — the total, the stage badges, the facet counts — is
      // computed server-side over the filtered set, so a batch that moved rows between
      // stages invalidates all three rather than being patched into the cache.
      void client.invalidateQueries({ queryKey: ["leads", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["lead-facets", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["dashboard", session.orgSlug] });
    },
  });
}

/**
 * CSV export — `calls:read_raw` (owners only; the file carries FULL phone numbers),
 * fetched WITH the session headers, and narrowed by THE SAME LENS as the screen.
 *
 * It cannot be a plain `<a href>`: the API authenticates every request from the
 * Authorization and X-Org-Slug headers, which a browser navigation does not carry, so a
 * link answers with a 401 problem+json instead of a file. Fetching it here and handing
 * the browser a blob keeps the download while letting a refusal render through
 * ProblemNotice like every other error.
 *
 * **It takes a `LeadLens`, and that is the whole point of this slice.** The version this
 * replaces accepted `agent_id` alone while the endpoint had grown four more filters, so
 * a client who narrowed the table to "hot" and pressed Export downloaded every contact
 * in the account with full numbers, and the screen had to carry a warning saying so.
 * Same object, same `lensQuery`, so the file is the table.
 *
 * **The byte-order mark is added HERE and not on the server, and that is the same split
 * `core/spreadsheet_safety.py` makes**: one hazard, two renderings, each written for the
 * consumer that will actually open the bytes. Excel does not sniff UTF-8 — a `.csv` with
 * no mark is decoded in the machine's legacy code page, so on a Telugu-first product
 * every name in the file arrives as mojibake and the client's own data looks like we
 * corrupted it. The API RESPONSE stays clean UTF-8 with no mark, because a script reading
 * `/v1/leads/export.csv` would otherwise find a stray U+FEFF welded to its first header
 * cell — the bug the mark causes when it is applied to the wrong consumer. This branch is
 * definitionally the human-opens-it-in-a-spreadsheet path: it exists only to hand the
 * browser a file to save. `tests/leadsExportEncoding.test.tsx` asserts the BYTES, because
 * `Blob.text()` runs the spec's UTF-8 decode and strips the mark it is checking for.
 *
 * Written as an ESCAPE and never as a pasted glyph: U+FEFF is zero-width, so in source it
 * is indistinguishable from nothing at all and the next reader cannot tell a deliberate
 * mark from an accident of somebody's editor. Same reasoning as the full-width formula
 * leaders in `core/spreadsheet_safety.py`.
 */
const BOM = "\uFEFF";

export function useExportLeads(session: Session) {
  return useMutation({
    mutationFn: (lens: LeadLens) =>
      apiRequest<string>(session, `/v1/leads/export.csv${lensQuery(lens)}`),
    onSuccess: (csv) => {
      const url = URL.createObjectURL(new Blob([BOM, csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `leads-${new Date().toISOString().slice(0, 10)}.csv`;
      // In the document and revoked a tick later: a detached anchor is a no-op in
      // some browsers, and revoking synchronously can cancel the save.
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    },
  });
}
