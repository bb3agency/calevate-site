"use client";

/**
 * Admin-realm client and hooks — a SEPARATE session from the client realm.
 *
 * TRD §11 and D-37: two REALMS, two `__Host-` session cookies, no shared session
 * logic. (It read "two Clerk applications" until D-177 removed the identity vendor;
 * the separation is ours now and is enforced by `lib/authn/`, not by a vendor's
 * account boundary.) That separation is why this file exists at all rather than a `realm` flag on
 * the client-realm session: a flag is one bad conditional away from an admin token
 * being used on a client surface, and vice versa.
 */

import { livePoll } from "@/lib/live/liveStatus";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminRealmSession } from "@/lib/authn/realmSessions";
import { codeOf, needsReauthentication } from "@/lib/authn/problems";
import { withActionCode } from "@/lib/authn/stepUpPrompt";
import { adminConsoleUrl } from "@/lib/consoleOrigin";

import type { CampaignSummary } from "./campaigns";
import { apiRequest, type GrantSource, type Session } from "./client";
import {
  CLIENT_HEALTH_PATH,
  CLIENT_HEALTH_QUERY_KEY,
  type ClientHealth,
  type TenantHealth,
} from "./clientHealth";
// The wallet's query key only — no session, no request shaper. A tier change decides
// whether this client HAS a wallet, so the screen that shows one must re-read after it.
import { HOLDS_PATH, HOLDS_QUERY_KEY, type HeldTenant } from "./holds";
import {
  KYC_PATH,
  toRecordBody,
  type KycRecord,
  type KycRecordIn,
} from "./kyc";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type TenantSummary = Schemas["TenantSummary"];
export type CreateOrgIn = Schemas["CreateOrgIn"];
export type CreateOrgOut = Schemas["CreateOrgOut"];
export type InviteOut = Schemas["InviteOut"];
/** One redeemable invitation, address masked (`admin/routes.py::PendingInviteOut`). */
export type PendingInviteOut = Schemas["PendingInviteOut"];
/** What a resend did — the new expiry and the send count (`admin/routes.py::ResendInviteOut`). */
export type ResendInviteOut = Schemas["ResendInviteOut"];
export type PlatformState = Schemas["PlatformStateOut"];
export type KbSource = Schemas["SourceOut"];
export type KbChunk = Schemas["ChunkOut"];

/**
 * The admin realm's session — the `__Host-calevate_admin_session` cookie, or
 * `dev:admin:<uuid>` locally.
 *
 * The credential is chosen in `lib/authn/realmSessions.ts`; the choice is
 * `NEXT_PUBLIC_AUTH_MODE`, never a guess (`lib/authn/mode.ts`). The local path is the one
 * the API enforces two conditions for — `APP_ENV=local` AND no `PLATFORM_KEK`
 * (`core/auth.py::_verify_dev_token`) — and it carries `dev:admin:` so a client token can
 * never be pasted into an admin surface by accident.
 *
 * This function keeps its name and signature because twenty-five call sites build their
 * session through it: what changed is which credential comes back, not where sessions
 * come from.
 */
export function adminSession(orgSlug = ""): Session {
  return adminRealmSession(orgSlug);
}

/**
 * The `X-Confirm-Action` strings of the operator writes D-731 put behind step-up, copied
 * VERBATIM from the API (`admin/routes.py`, `members_routes.py`, `flags/routes.py`,
 * `billing/*_routes.py`, `engine_workspace_routes.py`, `copilot/admin_routes.py`).
 */
export const CREATE_TENANT_CONFIRMATION = "create_tenant";
export const RECONCILE_PAYMENTS_CONFIRMATION = "reconcile_payments";
export const inviteMemberConfirmation = (tenantId: string) => `invite_member:${tenantId}`;
export const readdressInvitationConfirmation = (tenantId: string, invitationId: string) =>
  `readdress_invitation:${tenantId}:${invitationId}`;
export const provisionNumberConfirmation = (tenantId: string) => `provision_number:${tenantId}`;
export const recordEngineNumberConfirmation = (tenantId: string) =>
  `record_engine_number:${tenantId}`;
export const recordKycConfirmation = (tenantId: string) => `record_kyc:${tenantId}`;
export const kycReviewConfirmation = (tenantId: string, decision: "approve" | "reject") =>
  `kyc_review:${tenantId}:${decision}`;
export const clearDigiLockerConfirmation = (tenantId: string) =>
  `clear_digilocker_requirement:${tenantId}`;
export const engineRefConfirmation = (tenantId: string, numberId: string) =>
  `set_engine_ref:${tenantId}:${numberId}`;
export const memberRoleConfirmation = (tenantId: string, userId: string) =>
  `change_member_role:${tenantId}:${userId}`;
export const featureFlagConfirmation = (tenantId: string, flag: string) =>
  `set_feature_flag:${tenantId}:${flag}`;
export const feeWaiverConfirmation = (tenantId: string) => `waive_platform_fee:${tenantId}`;
export const feePaymentConfirmation = (tenantId: string, chargeId: string) =>
  `record_fee_payment:${tenantId}:${chargeId}`;
export const recordPaymentConfirmation = (tenantId: string) => `record_payment:${tenantId}`;
export const endTrialConfirmation = (tenantId: string, outcome: string) =>
  `end_trial:${tenantId}:${outcome}`;
export const workspaceProvisionConfirmation = (tenantId: string) =>
  `provision_workspace:${tenantId}`;
export const workspaceOffboardConfirmation = (tenantId: string) =>
  `offboard_workspace:${tenantId}`;
export const buyNumberConfirmation = (tenantId: string) => `buy_number:${tenantId}`;
export const releaseNumberConfirmation = (tenantId: string, numberId: string) =>
  `release_number:${tenantId}:${numberId}`;
export const forgetNumberConfirmation = (tenantId: string, numberId: string) =>
  `forget_number:${tenantId}:${numberId}`;
export const undoCopilotConfirmation = (actionId: string) => `undo_copilot_action:${actionId}`;
export const moveNumberConfirmation = (tenantId: string, numberId: string) =>
  `move_number:${tenantId}:${numberId}`;
export const TRIAL_LINE_CONFIRMATION = "set_up_trial_line";
export const callLinesConfirmation = (tenantId: string) => `set_call_lines:${tenantId}`;
export const llmDefaultConfirmation = (tenantId: string) => `set_llm_default:${tenantId}`;

/**
 * A confirmed operator write (D-731): sends `X-Confirm-Action`, and when the API answers
 * that the second factor is stale, asks for a code and sends the request once more.
 *
 * The retry is safe because every step-up gate refuses before it does any work
 * (`apps/api/core/stepup.py`), so the first attempt changed nothing.
 */
export function confirmedAdminRequest<T>(
  path: string,
  options: NonNullable<Parameters<typeof apiRequest>[2]> & { confirmAction: string },
  reason: string,
): Promise<T> {
  return confirmedRequest<T>(adminSession(), path, options, reason);
}

/** `confirmedAdminRequest` for a hook handed its session (the admin session, or a test's). */
export function confirmedRequest<T>(
  session: Session,
  path: string,
  options: NonNullable<Parameters<typeof apiRequest>[2]> & { confirmAction: string },
  reason: string,
): Promise<T> {
  return withActionCode(
    options.confirmAction,
    reason,
    () => apiRequest<T>(session, path, options),
    needsReauthentication,
  );
}

/* --- D-22 view-as: the grant, and where it comes from ------------------------------
 *
 * This file used to build an impersonating session by setting one header and nothing
 * else, and the server used to accept exactly that. The consequence was that
 * `admin.impersonation_started` — the "session start audit-logged" half of D-22 — was
 * absent for every real session: nothing forced an operator through the endpoint that
 * wrote it, and this console never called it.
 *
 * Now the API refuses `X-Impersonate-Org` unless it is accompanied by a short-lived
 * grant naming this operator and this tenant, and minting that grant IS what writes the
 * row. So the two sides moved together: a console that only set the header would now be
 * refused on every read, and a server that only required the grant would be a console
 * with no client screens.
 *
 * WHAT LIVES HERE AND WHY IT IS NOT A HOOK. `viewAsSession(slug)` is called from ~15
 * places, several of them outside React's render path (`lib/api/publishing.ts` builds
 * query options; `lib/api/session.tsx` builds a session inside a `useMemo`), and it must
 * stay synchronous — making it a hook would mean rewriting every caller and would still
 * not help `session.tsx`, which has only a slug and no tenant id. So the grant is
 * resolved the way the bearer token already is: a function on the session, asked once
 * per request (`client.ts::GrantSource`). The cache below is what keeps that from being
 * a mint per request.
 */

/** The mint endpoint. A POST because the RESPONSE is credential-shaped. */
export const IMPERSONATION_GRANT_PATH = "/v1/admin/impersonation-grants";

/**
 * The renewal endpoint — the ONLY grant route the client console may call (D-730).
 * Starting a view-as session is accepted from the operator console's origin alone.
 */
export const IMPERSONATION_RENEW_PATH = "/v1/admin/impersonation-grants/renew";

/** The operator console page that starts a view-as session and hands it over (D-730). */
export const VIEW_AS_START_PATH = "/admin/view-as";

/**
 * The URL-fragment keys the operator console hands a fresh grant over in. A FRAGMENT,
 * because it never leaves the browser: it is not sent to any server, so it reaches no
 * access log and no `Referer`. The receiving page strips it on arrival.
 */
export const HANDOFF_GRANT_KEY = "vg";
export const HANDOFF_EXPIRES_KEY = "ve";

/**
 * Per-tab copy of each slug's grant, so a reload continues the session instead of sending
 * the operator back through the operator console. `sessionStorage`, never `localStorage`: the grant is
 * worthless without the operator's own cookie, and it should not outlive the tab.
 */
const GRANT_STORAGE_PREFIX = "calevate:view-as-grant:";

/**
 * Re-mint this long before the grant expires.
 *
 * Not zero, because "expired" would then be discovered as a failed read in front of an
 * operator, and a clock a few seconds off would make it happen at random. Sixty seconds
 * is comfortably more than any clock skew the API tolerates
 * (`core/impersonation.py::GRANT_CLOCK_SKEW_S`, 5s) and small enough that a fifteen
 * minute grant is still ~4 mints an hour — the ledger-volume budget the TTL was chosen
 * against.
 */
const GRANT_REFRESH_MARGIN_MS = 60_000;

export interface MintedGrant {
  grant: string;
  expiresAtMs: number;
}

interface CachedGrant {
  pending: Promise<MintedGrant>;
  /**
   * Readable SYNCHRONOUSLY, and `Infinity` while the mint is still in flight.
   *
   * That is what makes the freshness decision race-free. If staleness could only be
   * learned by awaiting the promise, every concurrent caller would await the same stale
   * entry, all conclude "stale" at once, and all re-mint — six audit rows for one
   * refresh, which is precisely the ledger volume the TTL was chosen to bound. Reading
   * it synchronously means the first caller replaces the entry before any other observes
   * it, and the rest queue on the replacement.
   */
  expiresAtMs: number;
  /**
   * The grant itself, once the mint settled — readable SYNCHRONOUSLY for the same reason
   * `expiresAtMs` is, and needed for the same kind of reason.
   *
   * A re-mint sends the grant it is replacing as `renew`, which is what lets the API
   * extend the view-as session on its original clock (`core/impersonation.VIEW_AS_MAX_AGE`). Reading it off the promise would mean
   * awaiting before installing the replacement entry, which is exactly the window the
   * synchronous read above exists to close.
   */
  grant?: string;
}

/**
 * One in-flight-or-settled mint per slug.
 *
 * The PROMISE is cached, not the result, so the six queries a screen opens at once
 * produce ONE mint and therefore ONE `admin.impersonation_started` row rather than six.
 * A failed mint drops out of the cache so the next read retries instead of replaying a
 * rejection forever.
 */
const grantCache = new Map<string, CachedGrant>();

/** Drop every cached grant. For tests, and for a sign-out that changes who "we" are. */
export function clearImpersonationGrants(): void {
  grantCache.clear();
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const key = sessionStorage.key(i);
      if (key?.startsWith(GRANT_STORAGE_PREFIX)) sessionStorage.removeItem(key);
    }
  } catch {
    // Storage unavailable: there is nothing kept to drop.
  }
}

/**
 * What the mint returns, from the generated schema.
 *
 * `grant` is a short-lived delegation token bound to this tenant and this operator; it is
 * NOT a credential on its own and never travels in `Authorization`. That is what makes
 * revocation lag one request rather than one token lifetime — the operator's own admin
 * row and role are re-read on every request beside it.
 */
type MintResponse = Schemas["ImpersonationGrantOut"];

function storeGrant(slug: string, minted: MintedGrant): void {
  try {
    sessionStorage.setItem(GRANT_STORAGE_PREFIX + slug, JSON.stringify(minted));
  } catch {
    // Storage unavailable (private mode, blocked site data): the session still works for
    // this page load; a reload asks the operator console again.
  }
}

function storedGrant(slug: string): MintedGrant | undefined {
  try {
    const raw = sessionStorage.getItem(GRANT_STORAGE_PREFIX + slug);
    if (raw === null) return undefined;
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof (parsed as MintedGrant).grant === "string" &&
      typeof (parsed as MintedGrant).expiresAtMs === "number"
    ) {
      return parsed as MintedGrant;
    }
  } catch {
    // Unreadable or unavailable: treated as no grant.
  }
  return undefined;
}

/**
 * The grant the operator console handed this page in its URL fragment, if any. Read once
 * and STRIPPED from the address bar, so it is not left in history or a screenshot.
 */
function adoptHandoffGrant(slug: string): MintedGrant | undefined {
  if (typeof window === "undefined" || window.location.hash.length < 2) return undefined;
  const params = new URLSearchParams(window.location.hash.slice(1));
  const grant = params.get(HANDOFF_GRANT_KEY);
  const expiresAtMs = Number(params.get(HANDOFF_EXPIRES_KEY));
  if (!grant || !Number.isFinite(expiresAtMs)) return undefined;
  params.delete(HANDOFF_GRANT_KEY);
  params.delete(HANDOFF_EXPIRES_KEY);
  const rest = params.toString();
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${window.location.search}${rest ? `#${rest}` : ""}`,
  );
  const minted = { grant, expiresAtMs };
  storeGrant(slug, minted);
  return minted;
}

/**
 * Whether this page is on the CLIENT console's hostname while the operator console lives
 * on another. There the API refuses to START a view-as session (D-730), so a page that has
 * no grant to renew sends the operator back to the operator console instead.
 */
function onClientConsoleOrigin(): boolean {
  if (typeof window === "undefined") return false;
  const admin = adminConsoleUrl("/");
  if (!/^https?:\/\//.test(admin)) return false;
  return new URL(admin).origin !== window.location.origin;
}

/** Where a client-console page goes to re-enter `slug` through the operator console. */
export function viewAsStartUrl(slug: string, path = ""): string {
  const query = new URLSearchParams({ slug });
  if (path) query.set("path", path);
  return adminConsoleUrl(`${VIEW_AS_START_PATH}?${query.toString()}`);
}

function reenterFromOperatorConsole(slug: string): never {
  const prefix = `/c/${slug}`;
  const here = window.location.pathname;
  const path = here.startsWith(prefix) ? here.slice(prefix.length) : "";
  window.location.assign(viewAsStartUrl(slug, path));
  throw new Error("This view-as session has ended. Opening it again from the operator console.");
}

async function postStart(slug: string): Promise<MintedGrant> {
  // `adminSession()`, never `viewAsSession()`: minting is an admin-realm act, and the
  // API refuses a mint made from inside another account's session (no chained
  // delegation).
  const minted = await apiRequest<MintResponse>(adminSession(), IMPERSONATION_GRANT_PATH, {
    method: "POST",
    body: { slug },
  });
  return { grant: minted.grant, expiresAtMs: Date.parse(minted.expires_at) };
}

async function postRenew(slug: string, renew: string): Promise<MintedGrant> {
  const minted = await apiRequest<MintResponse>(adminSession(), IMPERSONATION_RENEW_PATH, {
    method: "POST",
    body: { slug, renew },
  });
  return { grant: minted.grant, expiresAtMs: Date.parse(minted.expires_at) };
}

/**
 * Start a view-as session for `slug` on the operator console. No code is asked for
 * (D-791): the operator's admin session and `admin:impersonate` are what the API checks.
 */
export async function startViewAs(slug: string): Promise<MintedGrant> {
  const minted = await postStart(slug);
  storeGrant(slug, minted);
  return minted;
}

/**
 * One grant: a renewal of the one held when there is one, else a fresh start (D-210,
 * D-791). A renewal refused as out of window or not this operator's starts again on the
 * operator console, and sends a client-console page back there to do it.
 */
async function mint(slug: string, renew: string | undefined): Promise<MintedGrant> {
  if (renew !== undefined) {
    try {
      const renewed = await postRenew(slug, renew);
      storeGrant(slug, renewed);
      return renewed;
    } catch (error) {
      // Out of window, or a grant from another operator or tenant: the session has to be
      // started again. Anything else (a network failure) is reported as it is.
      if (codeOf(error) !== "view_as_renewal_refused") throw error;
    }
  }
  if (onClientConsoleOrigin()) reenterFromOperatorConsole(slug);
  return await startViewAs(slug);
}

function impersonationGrant(slug: string): GrantSource {
  return async () => {
    let cached = grantCache.get(slug);
    if (cached === undefined) {
      // A fresh page: the grant the operator console just handed over, or this tab's copy
      // from before a reload.
      const seeded = adoptHandoffGrant(slug) ?? storedGrant(slug);
      if (seeded !== undefined) {
        cached = {
          pending: Promise.resolve(seeded),
          expiresAtMs: seeded.expiresAtMs,
          grant: seeded.grant,
        };
        grantCache.set(slug, cached);
      }
    }
    if (cached && cached.expiresAtMs - Date.now() > GRANT_REFRESH_MARGIN_MS) {
      return (await cached.pending).grant;
    }
    // Installed BEFORE the first await, so concurrent callers see this entry rather
    // than the stale one they would each have replaced.
    const entry: CachedGrant = {
      pending: mint(slug, cached?.grant),
      expiresAtMs: Number.POSITIVE_INFINITY,
    };
    grantCache.set(slug, entry);
    try {
      const minted = await entry.pending;
      entry.expiresAtMs = minted.expiresAtMs;
      entry.grant = minted.grant;
      return minted.grant;
    } catch (error) {
      // A rejected promise left in the cache would turn one failed mint into a
      // permanently broken account page. Guarded on identity so a retry that has
      // already installed its own entry is not evicted by this one's failure.
      if (grantCache.get(slug) === entry) grantCache.delete(slug);
      throw error;
    }
  };
}

/**
 * A READ-ONLY "view as client" session (D-22) — addressed by slug, authorised by grant.
 *
 * Read-only is enforced SERVER-side whatever this file does: `requires()` refuses every
 * mutating permission to an impersonating principal. The grant does not change that and
 * is not meant to — it closes the other half, which is that entering a tenant used to
 * leave no record of anyone having been let in.
 */
export function viewAsSession(slug: string): Session {
  return {
    ...adminSession(slug),
    orgSlug: slug,
    impersonateOrg: slug,
    impersonationGrant: impersonationGrant(slug),
  };
}

/** How the directory may be ordered. The server refuses anything else by name. */
export type DirectorySort = "recent" | "oldest" | "name" | "name_desc";

/** How many accounts one page of the directory holds. */
export const DIRECTORY_PAGE_SIZE = 25;

export interface TenantDirectoryQuery {
  /** Substring of the business name or the slug. */
  q?: string;
  status?: string;
  planTier?: string;
  sort?: DirectorySort;
  offset?: number;
}

/** One page of the roster, and the size of the set it is a page of. */
export type TenantDirectoryPage = Schemas["TenantDirectoryPage"];

/**
 * The client directory — a PAGE of it, narrowed by whatever the operator asked for.
 *
 * This used to fetch every account on the platform and let the browser do the rest, which
 * is the shape `admin/service.py::tenant_overview` describes as N+1 by construction: the
 * server opened one tenant-scoped session per client to build a list nobody read past the
 * first screen of. The search, the filters and the page are the server's now, so a request
 * costs the accounts it asked for.
 *
 * **EVERY PARAMETER IS PART OF THE CACHE KEY.** A directory keyed only on "tenants" would
 * serve the previous search's rows for a moment on each keystroke, which on this screen
 * reads as the wrong client appearing under the right name.
 *
 * The poll survives the migration and keeps its reason: this is a shared screen, accounts
 * are created and suspended by colleagues, and sixty seconds is the same interval the hold
 * queue uses for the same reason.
 */
export function useTenants(query: TenantDirectoryQuery = {}): UseQueryResult<TenantDirectoryPage> {
  const { q = "", status = "", planTier = "", sort = "recent", offset = 0 } = query;
  // ONLY WHAT DIFFERS FROM THE DEFAULT goes on the wire, so an unnarrowed directory is
  // the bare path. `DIRECTORY_PAGE_SIZE` and `sort` are omitted when they match what the
  // route already applies (`admin/routes.py`: `limit=25`, `sort=recent`) — the two
  // spellings agree, and sending them anyway would make every request carry three
  // parameters that change nothing and make the commonest path unreadable in a log.
  const search = new URLSearchParams();
  if (q.trim()) search.set("q", q.trim());
  if (status) search.set("status", status);
  if (planTier) search.set("plan_tier", planTier);
  if (sort !== "recent") search.set("sort", sort);
  if (offset > 0) {
    search.set("offset", String(offset));
    // The page size travels with a non-zero offset and only there: the server derives the
    // window from both, so an offset computed against 25 must not be sent to a route
    // whose default has moved.
    search.set("limit", String(DIRECTORY_PAGE_SIZE));
  }
  const suffix = search.toString();
  const path = suffix ? `/v1/admin/tenants?${suffix}` : "/v1/admin/tenants";
  return useQuery({
    queryKey: ["admin", "tenants", { q: q.trim(), status, planTier, sort, offset }],
    queryFn: () => apiRequest<TenantDirectoryPage>(adminSession(), path),
    refetchInterval: livePoll(60_000),
    // The rows of the previous page stay on screen while the next one loads, so paging
    // and typing do not blank the table between answers.
    placeholderData: (previous) => previous,
  });
}

/**
 * The ops work list — every account waiting on a human (R-11's two gates).
 *
 * `adminSession()`, not `viewAsSession()`: this is a CROSS-tenant read that no single
 * tenant's session can answer, and D-22's read-through-impersonation split is about a
 * tenant's own data. The route is `org:read` rather than `admin:tenants` on purpose
 * (`holds_routes.py`: reading a work list is not acting on it), so both admin roles can
 * open the queue while each remedy on it keeps its own permission.
 *
 * A one-minute poll, matching `useTenants` and for the same reason rather than a copied
 * number: this is a shared queue two operators work at once, and a row a colleague has
 * just cleared should stop being offered. It is not cheap enough to poll harder — the
 * server walks each self-serve tenant's own RLS session, N+1 by construction and argued
 * as such in `admin/holds.py`.
 */
export function useHeldTenants(): UseQueryResult<HeldTenant[]> {
  return useQuery({
    queryKey: HOLDS_QUERY_KEY,
    queryFn: () => apiRequest<HeldTenant[]>(adminSession(), HOLDS_PATH),
    refetchInterval: livePoll(60_000),
  });
}

/**
 * The client health board — every account with something wrong, worst first.
 *
 * `adminSession()`, not `viewAsSession()`: this is a CROSS-tenant read no single tenant's
 * session can answer, and D-22's read-through-impersonation split is about a tenant's own
 * data. `org:read` rather than `admin:tenants` for the reason `useHeldTenants` states
 * (`health_routes.py`: reading a triage list is not acting on it), so both admin roles can
 * open the board while every remedy on it keeps its own permission.
 *
 * **Two minutes, not one.** The hold queue polls at sixty seconds because it is a shared
 * work list two operators race on. This is not: it is a judgement about the last SEVEN
 * DAYS, so nothing on it changes inside a minute, and it is materially more expensive —
 * the server walks each live tenant's own RLS session and `admin/health.py` records the
 * measurement (~6.5ms per account) rather than asserting it is cheap. Polling this as hard
 * as the queue would buy no freshness and cost real database time.
 */
export function useClientHealth(): UseQueryResult<ClientHealth[]> {
  return useQuery({
    queryKey: CLIENT_HEALTH_QUERY_KEY,
    queryFn: () => apiRequest<ClientHealth[]>(adminSession(), CLIENT_HEALTH_PATH),
    refetchInterval: livePoll(120_000),
  });
}

/**
 * ONE client's health (`GET /v1/admin/client-health/{id}`): the board's judgement for that
 * account, read inside its own tenant session and recorded as a direct admin read. The top
 * of the client's overview reads it rather than walking the whole board for one row.
 */
export function useTenantHealth(tenantId: string): UseQueryResult<TenantHealth> {
  return useQuery({
    queryKey: [...CLIENT_HEALTH_QUERY_KEY, tenantId],
    queryFn: () =>
      apiRequest<TenantHealth>(adminSession(), `${CLIENT_HEALTH_PATH}/${encodeURIComponent(tenantId)}`),
    enabled: tenantId !== "",
    refetchInterval: livePoll(120_000),
  });
}

export function useTenant(tenantId: string): UseQueryResult<TenantSummary> {
  return useQuery({
    queryKey: ["admin", "tenant", tenantId],
    queryFn: () => apiRequest<TenantSummary>(adminSession(), `/v1/admin/tenants/${tenantId}`),
    enabled: Boolean(tenantId),
  });
}

/**
 * The tenant record as already read by the tenant layout, WITHOUT a fetch of its own.
 *
 * For a page mounted after the layout settled the read. A second `useTenant` observer
 * refetches an ERRORED query on mount, which reports `pending` to the layout too: on the
 * one route the layout mounts despite a 404 (an erased client's Closing page), that
 * unmounts the page, the refetch 404s again, and the two loop. `enabled: false` reads the
 * cache reactively and never fetches.
 */
export function useCachedTenant(tenantId: string): UseQueryResult<TenantSummary> {
  return useQuery({
    queryKey: ["admin", "tenant", tenantId],
    queryFn: () => apiRequest<TenantSummary>(adminSession(), `/v1/admin/tenants/${tenantId}`),
    enabled: false,
  });
}
export function useCreateTenant() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateOrgIn) =>
      confirmedAdminRequest<CreateOrgOut>(
        "/v1/admin/tenants",
        { method: "POST", body: payload, confirmAction: CREATE_TENANT_CONFIRMATION },
        "Creating a new client.",
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "tenants"] }),
  });
}

export function useInvite() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      tenantId,
      email,
      role,
      name,
      phone,
    }: {
      tenantId: string;
      email: string;
      role: string;
      /** The invitee's name and mobile, kept with the invitation for their account. */
      name?: string | null;
      phone?: string | null;
    }) =>
      confirmedAdminRequest<InviteOut>(
        `/v1/admin/tenants/${tenantId}/invitations`,
        {
          method: "POST",
          body: { email, role, name: name ?? null, phone_e164: phone ?? null },
          confirmAction: inviteMemberConfirmation(tenantId),
        },
        "Inviting someone into this client's account.",
      ),
    // The Invitations screen tells the operator the new link "appears in the list above",
    // and that list is `useTenantInvitations`, which has no poll of its own.
    onSuccess: (_data, { tenantId }) =>
      client.invalidateQueries({ queryKey: ["admin", "invitations", tenantId] }),
  });
}

/**
 * The keys to a client's account that exist in somebody's inbox right now.
 *
 * Masked addresses — an operator has to RECOGNISE a pending invite to cancel the right
 * one, not read it. This read is what makes the duplicate refusal actionable across
 * sessions: the wizard remembers the invitation IT minted, and this covers the case it
 * cannot — a colleague issued the first link, or it was issued from another tab.
 */
export function useTenantInvitations(tenantId: string): UseQueryResult<PendingInviteOut[]> {
  return useQuery({
    queryKey: ["admin", "invitations", tenantId],
    queryFn: () =>
      apiRequest<PendingInviteOut[]>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/invitations`,
      ),
    enabled: Boolean(tenantId),
  });
}

/**
 * Cancel an unused invitation from the console.
 *
 * The exit from the refusal `useInvite` can now hit: minting a SECOND live token for one
 * address is refused (`invitation_already_pending`), and the revoke that already existed
 * is client-realm — useless for the wizard's owner invite, which is issued before anybody
 * can sign in. Without this, an operator whose first token was lost was locked out of
 * that address for 72 hours.
 *
 * 204, so there is no body to type. A revoke that races an acceptance answers 404 and
 * arrives as problem+json: the person is a member now, and that is a different act.
 */
export function useRevokeTenantInvitation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ tenantId, invitationId }: { tenantId: string; invitationId: string }) =>
      apiRequest<void>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/invitations/${invitationId}`,
        { method: "DELETE" },
      ),
    onSuccess: (_data, { tenantId }) =>
      client.invalidateQueries({ queryKey: ["admin", "invitations", tenantId] }),
  });
}

/**
 * Send an unredeemed invitation's link AGAIN — the founder's own ask, verbatim: *"the
 * invite link can be re-sent via the admin panel for a client business until that mail
 * sets up their business"* (D-538).
 *
 * The route, the token rotation, the two-minute/ten-send rate limit and the audit row all
 * shipped with D-538 and NOTHING IN THIS CONSOLE CALLED THEM, so the requirement was met
 * by an endpoint an operator had no way to reach. This is that button's client.
 *
 * It rotates the token on the SAME row, so the previous link dies in the statement that
 * mints the new one — which is why this is not "revoke, then invite again" and why the
 * list has to be refetched: `expires_at`, `last_sent_at` and `send_count` all moved.
 *
 * THE ADDRESS CORRECTION HALF IS OFFERED (D-546), because without it a mistyped address
 * has no repair anywhere in the console — every self-service recovery mails the mailbox
 * that does not work. It carries its OWN ceremony on the Invitations screen: a separate
 * control, a required note saying how the address was established, and the server recording
 * it as an operator ATTESTATION (`admin.invitation_readdressed`) rather than as a verified
 * mailbox. Sending `email` without `attestation` is a 422 by design.
 */
export function useResendTenantInvitation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      tenantId,
      invitationId,
      email,
      attestation,
    }: {
      tenantId: string;
      invitationId: string;
      /** A CORRECTED address. Omitted means "send it again to the one on file". */
      email?: string;
      /** How that address was established out of band. Required with `email`. */
      attestation?: string;
    }) => {
      const path = `/v1/admin/tenants/${tenantId}/invitations/${invitationId}/resend`;
      // A corrected address mails a live owner key to a new mailbox, so it carries the
      // confirmation issuing an invitation does; a plain resend sends nothing new.
      return email
        ? confirmedAdminRequest<ResendInviteOut>(
            path,
            {
              method: "POST",
              body: { email, attestation },
              confirmAction: readdressInvitationConfirmation(tenantId, invitationId),
            },
            "Sending this invitation to a corrected address.",
          )
        : apiRequest<ResendInviteOut>(adminSession(), path, { method: "POST", body: {} });
    },
    onSuccess: (_data, { tenantId }) =>
      client.invalidateQueries({ queryKey: ["admin", "invitations", tenantId] }),
  });
}

export function usePlatformState(): UseQueryResult<PlatformState> {
  return useQuery({
    queryKey: ["admin", "platform"],
    queryFn: () => apiRequest<PlatformState>(adminSession(), "/v1/ops/platform"),
    refetchInterval: livePoll(30_000),
  });
}

/**
 * Calevate's OWN telemarketer registration (SEC-COMP §3, company half).
 *
 * `is_live` is read, never computed here. "Is `submitted` good enough?" is the exact
 * question the server answers for both this response and `launch_blockers` from one
 * property (`ops.service.TmRegistration.is_live`), and a console that re-derived it
 * would eventually disagree with the gate — showing a green platform while every
 * tenant's launch was refused, or the reverse.
 */
export type TmRegistration = Schemas["TmRegistrationOut"];
export type TmRegistrationIn = Schemas["TmRegistrationIn"];
export type TmStatus = TmRegistrationIn["status"];

export function useSetTmRegistration() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: TmRegistrationIn) =>
      confirmedAdminRequest<TmRegistration>(
        "/v1/ops/platform/tm-registration",
        {
          method: "POST",
          body: payload,
          // The header names the DIRECTION of this write, and the rule is copied from
          // the route verbatim (`ops/routes.py`: `"record_tm_registration" if
          // payload.status == "active"`). That is a property of the request we are
          // sending, not a judgement about what counts as live — the server owns that,
          // and a mismatched header is refused rather than assumed.
          confirmAction:
            payload.status === "active" ? "record_tm_registration" : "withdraw_tm_registration",
        },
        "Changing the platform's telemarketer registration.",
      ),
    // The platform query carries `tm_registration`, so the panel above the form
    // re-reads the SERVER's `is_live` rather than assuming the write made it live.
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "platform"] }),
  });
}

/**
 * The CLIENT's Principal Entity registration, and its link to us as Telemarketer.
 *
 * Operator-only by design, and the reason is worth stating where the hook lives: the
 * launch gate reads these two statuses, so a client who could set them would be
 * clearing their own compliance blocker with a form. There is no client-realm route
 * for this, and there should never be one.
 */
export type DltRegistrationIn = Schemas["DltRegistrationIn"];
export type DltRegistrationOut = Schemas["DltRegistrationOut"];
export type PeStatus = DltRegistrationIn["status"];
export type TmLinkStatus = DltRegistrationIn["tm_link_status"];

export function useRecordDltRegistration(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: DltRegistrationIn) =>
      apiRequest<DltRegistrationOut>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/dlt-registration`,
        { method: "POST", body: payload },
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "tenant", tenantId] }),
  });
}

/**
 * Subscriber KYC (R-11's last gate) — read through impersonation, written admin-realm.
 *
 * The same D-22 split as the KB queue and the campaign prerequisites, and here it is
 * not merely consistent, it is the only shape available: there is no admin-realm READ
 * of a tenant's KYC. `GET /v1/compliance/kyc` is `org:read` — non-mutating, therefore
 * reachable inside a read-only "view as client" session — and the API's authors made it
 * that permission precisely so a support person looking at a blocked account can see
 * it. So the operator console reads the tenant's own view of their own record.
 *
 * The WRITE goes to the admin surface with the tenant in the PATH. It is the audited
 * one (`kyc.recorded`), it stamps `verified_by_admin_id` from the admin session and
 * `verified_at` from the database clock, and it has no client-realm twin on purpose.
 *
 * That split is also why this is not one hook: an impersonating session would be
 * correctly refused the write, and an admin session cannot resolve the tenant's own
 * `/v1/compliance/kyc` without the impersonation header.
 */
export function useTenantKyc(slug: string): UseQueryResult<KycRecord> {
  return useQuery({
    queryKey: ["admin", "kyc", slug],
    queryFn: () => apiRequest<KycRecord>(viewAsSession(slug), KYC_PATH),
    enabled: Boolean(slug),
  });
}

export function useRecordKyc(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: KycRecordIn) =>
      confirmedAdminRequest<Schemas["apps__api__admin__routes__KycRecordOut"]>(
        `/v1/admin/tenants/${tenantId}/kyc`,
        {
          method: "POST",
          body: toRecordBody(payload),
          confirmAction: recordKycConfirmation(tenantId),
        },
        "Recording this client's verification.",
      ),
    // Prefix invalidation, so the panel re-reads what is now STORED rather than
    // echoing back what this screen just sent. `record_kyc` COALESCEs blank fields
    // against the filed row, so the response body is not the resulting record — the
    // failure `DltRegistrationPanel` has to live with because its endpoint has no GET.
    //
    // The queue and the directory are invalidated too, because this write is one of the
    // two things that empties a row off them: `read_tenant_holds` composes the list from
    // `kyc_blocker` itself, so a verification recorded here removes the account from the
    // work list and from the `holds` flag on its directory row. Without this an operator
    // clears a gate and walks back to a queue still offering it.
    //
    // The review panel on the same page (`["admin", "tenant-kyc", id]`), the review queue
    // and the readiness rows (under `["admin", "tenant", id]`) read the same record under
    // keys `["admin", "kyc"]` does not prefix, so they are named here.
    onSuccess: () =>
      void Promise.all([
        client.invalidateQueries({ queryKey: ["admin", "kyc"] }),
        client.invalidateQueries({ queryKey: ["admin", "tenant-kyc", tenantId] }),
        client.invalidateQueries({ queryKey: ["admin", "kyc-reviews"] }),
        client.invalidateQueries({ queryKey: ["admin", "tenant", tenantId] }),
        client.invalidateQueries({ queryKey: HOLDS_QUERY_KEY }),
        client.invalidateQueries({ queryKey: ["admin", "tenants"] }),
        // An unverified identity is one of `outbound_blocked`'s causes on the health board.
        client.invalidateQueries({ queryKey: CLIENT_HEALTH_QUERY_KEY }),
      ]),
  });
}

/**
 * The tenant's campaigns, read through impersonation — the list the DND scrub screen
 * records a scrub against.
 *
 * `GET /v1/campaigns` is `leads:read`, which the operator role holds and which is not in
 * `MUTATING_PERMISSIONS`, so an impersonating session may read it.
 */
export function useTenantCampaigns(slug: string): UseQueryResult<CampaignSummary[]> {
  return useQuery({
    queryKey: ["admin", "campaigns", slug],
    queryFn: () => apiRequest<CampaignSummary[]>(viewAsSession(slug), "/v1/campaigns"),
    enabled: Boolean(slug),
  });
}

/** The four modes `PlatformStateIn.load_shed_mode` accepts, from the GENERATED schema so
 * that a mode added server-side breaks `tsc` here rather than being silently unofferable. */
export type LoadShedMode = NonNullable<Schemas["PlatformStateIn"]["load_shed_mode"]>;

/** One state transition of the global row: either half, or both, plus its reason. */
export interface PlatformTransition {
  outboundHalted?: boolean;
  loadShedMode?: LoadShedMode;
  reason: string;
}

/**
 * The step-up string for ONE transition — the console's mirror of `ops/routes.py`'s
 * `platform_confirmation`, built in ONE place here for the reason it is built in one
 * place there.
 *
 * The API refuses any header that does not name the exact move being made, and it names
 * three different moves: halting every tenant's dialling, releasing that halt, and moving
 * the load-shed mode. A single string across all three (the retired `set_platform_state`)
 * meant a header captured for a routine shedding tweak authorised lifting the global
 * halt. The load-shed string carries its TARGET MODE for the same reason the spend-cap
 * string carries its tenant: consent to `reduced` is not consent to `maintenance`.
 *
 * A request that does both halves joins them with `+`, halt half first — the fixed order
 * the server builds and compares against, not a detail this side may choose.
 *
 * Exported so `tests/ops.test.tsx` can pin the literals: these strings are an ops
 * PROCEDURE that two runbooks print, so a reformat here has to fail a test rather than
 * quietly leave the console sending a header the API refuses.
 */
export function platformConfirmation(transition: {
  outboundHalted?: boolean;
  loadShedMode?: LoadShedMode;
}): string {
  const parts: string[] = [];
  if (transition.outboundHalted !== undefined) {
    parts.push(transition.outboundHalted ? "halt_outbound" : "release_outbound");
  }
  if (transition.loadShedMode !== undefined) {
    parts.push(`set_load_shed:${transition.loadShedMode}`);
  }
  // No transition ⇒ no header, and the server refuses the BODY with
  // `platform_state_no_change` before it ever looks at the confirmation. Every form in
  // the console sends at least one half, so this is unreachable rather than handled.
  return parts.join("+");
}

/**
 * Move the global row — the big red switch, the load-shed mode, or both at once.
 *
 * ONE hook for both halves rather than one per switch, because the confirmation rule
 * spans them: a request that halts AND sheds needs both strings joined, and a second hook
 * that knew only its own half would send a header the API refuses the moment anyone
 * combined them. The API models this as one endpoint with one confirmation function; so
 * does this.
 *
 * Only the halves actually being moved are sent. `PlatformStateIn` forbids extra fields
 * and reads an absent one as "leave it alone", so omitting is how the console says "I am
 * not touching the load-shed mode" — and it is what keeps the halt request's body
 * identical to what it was before this hook grew a second half.
 */
export function useSetPlatformState() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ outboundHalted, loadShedMode, reason }: PlatformTransition) =>
      confirmedAdminRequest<PlatformState>(
        "/v1/ops/platform",
        {
          method: "POST",
          body: {
            ...(outboundHalted === undefined ? {} : { outbound_halted: outboundHalted }),
            ...(loadShedMode === undefined ? {} : { load_shed_mode: loadShedMode }),
            reason,
          },
          // Step-up confirmation (BACKEND-PATTERNS §7): the header must echo the action,
          // and a stale second factor opens the code prompt rather than failing.
          confirmAction: platformConfirmation({ outboundHalted, loadShedMode }),
        },
        "Changing the platform-wide calling state.",
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "platform"] }),
  });
}

/**
 * How deep the outbox DLQ is, what is in it, and how old the head of it is.
 *
 * It rides `GET /v1/ops/platform` rather than an endpoint of its own — `PlatformStateOut`
 * argues that choice where the field is declared. What matters on this side: it arrives
 * with the platform read, so it is unreadable exactly when that read is, and the panel
 * has to say "we could not read the depth" rather than render a zero.
 */
export type DeadLetterQueue = Schemas["DeadLetterQueueOut"];

/**
 * How far the platform's live agents have drifted from what we published (D-123).
 *
 * Rides `GET /v1/ops/platform` for `DeadLetterQueue`'s reasons, and is unreadable exactly
 * when that read is — so the panel says so rather than rendering a reassuring zero.
 *
 * EVERY FIELD IS REQUIRED ON THE WIRE. `EngineDriftOut` declares no defaults, which is
 * what keeps these non-optional in `schema.d.ts`: an optional `out_of_sync` would be read
 * through `?? 0`, and a `0` that means "the field was missing" is exactly the conflation
 * this panel exists to prevent.
 */
export type EngineDrift = Schemas["EngineDriftOut"];

/**
 * How far the KNOWLEDGE on the voice platform has drifted from what we approved (D-158).
 *
 * The same measurement as `EngineDrift`, on a different object: that one answers "is the
 * agent CONFIGURED as we published", this one answers "is it answering from the text a
 * human approved". They come from two sweeps on two schedules, and each carries its own
 * `oldest_checked_at` — a healthy agent sweep must not be able to vouch for a KB sweep
 * that has died, which is why these are two types and not more columns on one.
 *
 * EVERY FIELD IS REQUIRED ON THE WIRE, for `EngineDrift`'s reason.
 */
export type KbDrift = Schemas["KbDriftOut"];

/**
 * The step-up string for an UNSCOPED dead-letter replay — every job, every tenant.
 *
 * `ops/routes.py`'s `OUTBOX_REPLAY_CONFIRMATION`, mirrored, and it stays this exact
 * literal because `runbooks/webhook-delivery-failures.md` §3 prints it for the curl
 * fallback. Pinned by `tests/ops.test.tsx` for the same reason the other two strings are:
 * a reformat here has to fail a test rather than quietly leave the console — or an
 * operator following the runbook — sending a header the API refuses.
 */
export const OUTBOX_REPLAY_CONFIRMATION = "replay_dead_letters";

/**
 * The step-up string for ONE replay, bound to the scope it will use.
 *
 * This was a bare constant, on the argument that nothing about the action varied: there
 * was one global dead-letter queue and so no target for a `:<suffix>` to bind. The replay
 * now takes an optional `job`, so that is no longer true and the string moves with it —
 * a header reading `replay_dead_letters` on a request that replays only the CRM webhooks
 * describes an action other than the one being performed, and (the dangerous direction) a
 * header captured for one job must not authorise a redelivery of everything.
 *
 * `null` keeps the unsuffixed literal, which is what makes the runbook's curl and this
 * console's "all jobs" choice the same request. The shape is `spendCapConfirmation`'s,
 * for the same reason: the suffix carries the part of the action an operator could get
 * wrong by replaying a header they already had.
 */
export function outboxReplayConfirmation(job: string | null): string {
  return job === null ? OUTBOX_REPLAY_CONFIRMATION : `${OUTBOX_REPLAY_CONFIRMATION}:${job}`;
}

/**
 * Flip dead-lettered outbox messages back to pending — up to 100 per run, oldest first,
 * for EVERY tenant (`reliability.service.replay_dead_letters`).
 *
 * IT SENDS THE HEADER, and it is the same header the console has always collected the
 * typed word for. This hook used to send none, correctly reading it off a route that
 * accepted none — and the route was wrong, not the hook: `replay_dead_letters` has no
 * tenant predicate (`outbox_messages` carries no `tenant_id`), and what the next dispatch
 * tick does with the rows it moves is re-send other people's customer data into other
 * people's systems. That is the most outward-facing write in this console and it was the
 * only one reachable by a single unconfirmed POST.
 *
 * `job` scopes the run to one kind of side effect and travels in the QUERY STRING, where
 * the route wants it — the scope is part of this request's identity rather than its
 * content, so it belongs somewhere an access log records. `null` means every job.
 *
 * A `step_up_required` refusal therefore means the console and the API disagree about the
 * string — a version skew, not an operator error — and the ops screen renders it as that
 * rather than as a red generic failure the operator would answer by clicking again.
 *
 * IT INVALIDATES THE PLATFORM READ, which it did not have to before: the dead-letter
 * depth now rides `GET /v1/ops/platform` (`PlatformStateOut.outbox_dead_letters`), so
 * without this the panel would print a fresh "12 moved" beside a depth measured before
 * they moved — two numbers about the same queue from two instants, which is the defect
 * that read exists to prevent.
 */
export type OutboxReplayResult = Schemas["ReplayOut"];

export function useReplayOutbox() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (job: string | null) =>
      confirmedAdminRequest<OutboxReplayResult>(
        job === null
          ? "/v1/ops/outbox/replay"
          : `/v1/ops/outbox/replay?job=${encodeURIComponent(job)}`,
        { method: "POST", confirmAction: outboxReplayConfirmation(job) },
        "Replaying failed deliveries.",
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "platform"] }),
  });
}

/**
 * Recompute the audit hash chain and report the first broken link.
 *
 * A GET behind `useMutation`, deliberately, and the alternative was considered: TanStack
 * v5's documented lazy-query shape is `useQuery({ enabled: false })` + `refetch()`. It is
 * the wrong tool here because it CACHES. A verification is the outcome of one walk at one
 * instant, not server state to be kept fresh — and a cached "chain intact" verdict
 * re-rendered an hour later, from a run nobody remembers asking for, is exactly the false
 * assurance this control exists to remove. A mutation holds no cache, so the verdict on
 * screen belongs to the run the operator just triggered and to no other, and
 * `submittedAt` stamps when that was.
 * (tanstack.com/query/latest/docs/framework/react/guides/disabling-queries)
 *
 * It writes nothing and takes no confirmation — see the screen for why demanding one for
 * a read would be friction that teaches operators to type past confirmations.
 */
export type AuditChainVerdict = Schemas["ChainVerifyOut"];
/** One broken link inside a verdict — `link` (wrong neighbour) or `content` (edited). */
export type ChainBreak = Schemas["ChainBreakOut"];

export function useVerifyAuditChain() {
  return useMutation({
    mutationFn: () => apiRequest<AuditChainVerdict>(adminSession(), "/v1/ops/audit/verify"),
  });
}

/**
 * The step-up string for ONE tenant's spend-cap recompute — `ops/routes.py`'s
 * `spend_cap_confirmation`, mirrored.
 *
 * Bound to the TENANT and not merely to the verb, which is the property worth keeping in
 * a named function on this side too: a confirmation sent for one client cannot be
 * replayed against another. `runbooks/calls-stopped.md` §2 prints this literal for the
 * curl fallback and `tests/ops_spend_cap_recompute_test.py` pins it server-side.
 */
export type SpendCapRecompute = Schemas["SpendCapRecomputeOut"];

export function spendCapConfirmation(tenantId: string): string {
  return `recompute_spend_cap:${tenantId}`;
}

/**
 * Re-derive ONE client's `spend_state.capped` from the counters already metered this
 * month against the ceiling now in force.
 *
 * `adminSession()` with the tenant in the PATH, never `viewAsSession`: `ops:manage` is in
 * `MUTATING_PERMISSIONS`, so the same call made with an impersonating session would be
 * correctly refused (D-22). The panel that reads this client's ceilings DOES impersonate,
 * because that read is `billing:read` and has no admin-realm twin — two sessions on one
 * panel is D-22 working, the same split as KYC.
 *
 * It recomputes; it does not un-cap. A tenant still over their ceiling comes back
 * `capped: true`, which is the route doing its job — so the screen renders the counters
 * beside the ceilings, and that answer reads as an explanation rather than a failure.
 */
export function useRecomputeSpendCap(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      confirmedAdminRequest<SpendCapRecompute>(
        `/v1/ops/tenants/${tenantId}/spend-cap/recompute`,
        { method: "POST", confirmAction: spendCapConfirmation(tenantId) },
        "Recomputing this client's spend cap.",
      ),
    // The flag is on three screens at once. `TenantSummary.capped` carries it on this
    // client's own page and on the directory, and `CapsOut.capped` carries it on the
    // ceilings panel beside the button — invalidated by the PREFIX of `capsKey`
    // (`lib/api/caps.ts`), because this hook holds the tenant id and that key is built
    // from the slug. Without all three, an operator releases a client and walks back to a
    // screen still badged "capped".
    onSuccess: () =>
      void Promise.all([
        client.invalidateQueries({ queryKey: ["admin", "tenant", tenantId] }),
        client.invalidateQueries({ queryKey: ["admin", "tenants"] }),
        client.invalidateQueries({ queryKey: ["billing-caps"] }),
        // `spend_cap_near` on the health board reads the same ceiling.
        client.invalidateQueries({ queryKey: CLIENT_HEALTH_QUERY_KEY }),
      ]),
  });
}

/**
 * The queue is READ through impersonation (allowed, audited) and DECIDED through the
 * admin surface (D-22: no acting-as). Two different sessions is the decision, not an
 * inconsistency — an approve call made with the impersonation session would be
 * correctly refused.
 */
export function useTenantKbQueue(slug: string, status = "pending_approval") {
  return useQuery({
    queryKey: ["admin", "kb", slug, status],
    queryFn: () =>
      apiRequest<KbSource[]>(viewAsSession(slug), `/v1/kb/sources?status=${status}`),
    enabled: Boolean(slug),
  });
}

export function useKbPreview(slug: string, sourceId: string | null) {
  return useQuery({
    queryKey: ["admin", "kb-preview", slug, sourceId],
    queryFn: () =>
      apiRequest<KbChunk[]>(viewAsSession(slug), `/v1/kb/sources/${sourceId}/preview`),
    enabled: Boolean(sourceId),
  });
}

export function useKbDecision(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      sourceId,
      decision,
      reason,
    }: {
      sourceId: string;
      decision: "approve" | "reject" | "publish";
      reason?: string;
    }) =>
      apiRequest<Record<string, unknown>>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/kb/${sourceId}/${decision}`,
        {
          method: "POST",
          body: decision === "reject" ? { reason: reason ?? "Not suitable" } : undefined,
        },
      ),
    // The health board's `knowledge_waiting` signal counts the same queue. Named here
    // because the `knowledge` live topic does not carry the board.
    onSuccess: () =>
      void Promise.all([
        client.invalidateQueries({ queryKey: ["admin", "kb"] }),
        client.invalidateQueries({ queryKey: CLIENT_HEALTH_QUERY_KEY }),
      ]),
  });
}

/**
 * Campaign prerequisites — the two things every client campaign stalls on until an
 * operator does them (SEC-COMP §3). Read through impersonation, written through the
 * admin surface: same D-22 split as the KB queue, for the same reason.
 */
export function useTenantNumbers(slug: string) {
  return useQuery({
    queryKey: ["admin", "numbers", slug],
    queryFn: () =>
      apiRequest<components["schemas"]["NumberOut"][]>(
        viewAsSession(slug),
        "/v1/campaigns/numbers",
      ),
    enabled: Boolean(slug),
  });
}

export function useTenantTemplates(slug: string) {
  return useQuery({
    queryKey: ["admin", "templates", slug],
    queryFn: () =>
      apiRequest<components["schemas"]["TemplateOut"][]>(
        viewAsSession(slug),
        "/v1/campaigns/templates",
      ),
    enabled: Boolean(slug),
  });
}

/**
 * RECORDS a number already held on the voice platform — it buys nothing. The name
 * follows the route's own `provision_number`, which means "make it usable in the platform",
 * not "obtain it".
 *
 * `provider` is required by the route, and `direction` decides whether the dial gate will
 * present the number on an outbound call (`number_inbound_only` otherwise), so both are
 * the operator's to state rather than left to a server default.
 */
export type ProvisionNumberBody = Omit<components["schemas"]["ProvisionNumberIn"], "agent_id">;

export function useProvisionNumber(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: ProvisionNumberBody) =>
      confirmedAdminRequest<components["schemas"]["NumberCreatedOut"]>(
        `/v1/admin/tenants/${tenantId}/numbers`,
        { method: "POST", body: payload, confirmAction: provisionNumberConfirmation(tenantId) },
        "Recording a number for this client.",
      ),
    // **NO `agent_id`, DELIBERATELY, THOUGH THE ROUTE ACCEPTS ONE (D-576).** The console
    // has exactly ONE way to decide which agent answers a number — the attach control on
    // the numbers screen — and it works at any time, including one second after this
    // returns. Offering the choice here as well would be a second way to do one thing
    // (CLAUDE.md), at the moment the operator knows least, on the field whose one wrong
    // value used to burn the E.164 permanently: `phone_numbers.e164` is globally UNIQUE
    // and `release_number` refuses a client-owned connection. `provision_number`'s own
    // docstring calls `agent_id = null` "the ordinary onboarding order".
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["admin", "numbers"] });
      // The admin cost/attachment list is a different key and is the list this write is
      // usually made from — without this the new row simply does not appear.
      void client.invalidateQueries({ queryKey: ["admin", "number-costs"] });
    },
  });
}

export function useSetNumberDltStatus(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      numberId,
      dltStatus,
    }: {
      numberId: string;
      dltStatus: "pending" | "registered" | "blocked";
    }) =>
      apiRequest<Record<string, string>>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/numbers/${numberId}/dlt-status`,
        { method: "POST", body: { dlt_status: dltStatus } },
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "numbers"] }),
  });
}

export function useRegisterTemplate(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      classification: "promotional" | "transactional" | "service";
      body: string;
      dlt_ref?: string | null;
    }) =>
      apiRequest<Record<string, string>>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/dlt-templates`,
        { method: "POST", body: payload },
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "templates"] }),
  });
}

export function useSetTemplateStatus(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      templateId,
      status,
      dltRef,
    }: {
      templateId: string;
      status: "approved" | "rejected" | "submitted";
      dltRef?: string;
    }) =>
      apiRequest<Record<string, string>>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/dlt-templates/${templateId}/status`,
        { method: "POST", body: { status, ...(dltRef ? { dlt_ref: dltRef } : {}) } },
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "templates"] }),
  });
}

/**
 * Per-client margin (D-12). Admin realm only — `unit_cost_paid` is our supplier
 * pricing, and the client-facing usage panel deliberately does not carry it.
 *
 * `margin_pct` is null — not "0" — when there is no revenue to divide by, and the
 * panel keeps that distinction: "not billed yet" is a different statement from "0%".
 */
export type Margin = Schemas["MarginOut"];

export function useMargin(tenantId: string): UseQueryResult<Margin> {
  return useQuery({
    queryKey: ["admin", "margin", tenantId],
    queryFn: () => apiRequest<Margin>(adminSession(), `/v1/admin/tenants/${tenantId}/margin`),
    enabled: Boolean(tenantId),
  });
}

/** The tenant's agents, read through impersonation (same D-22 split as the KB queue):
 * the admin console needs agent ids to link to prompt history, and reading what
 * agents exist is a read like any other. */
export function useTenantAgents(slug: string) {
  return useQuery({
    queryKey: ["admin", "agents", slug],
    queryFn: () =>
      apiRequest<components["schemas"]["AgentOut"][]>(viewAsSession(slug), "/v1/agents"),
    enabled: Boolean(slug),
  });
}
