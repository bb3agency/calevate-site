"use client";

/**
 * Admin-realm client and hooks — a SEPARATE session from the client realm.
 *
 * TRD §11 and D-37: two Clerk applications, two session cookies, no shared session
 * logic. That separation is why this file exists at all rather than a `realm` flag on
 * the client-realm session: a flag is one bad conditional away from an admin token
 * being used on a client surface, and vice versa.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminRealmSession } from "@/lib/auth/adminRealm";

import type { CampaignSummary } from "./campaigns";
import { apiRequest, type GrantSource, type Session } from "./client";
// Types, the endpoint path and the request shaper only — never a client-realm session.
// The two realms share vocabulary so an operator and a client name the same document
// the same way; they share no session logic (TRD §11), which is why the session each
// hook below presents is built here.
import {
  FIRST_CAMPAIGN_REVIEW_PATH,
  toDecisionBody,
  type FirstCampaignDecisionIn,
  type FirstCampaignDecisionOut,
  type FirstCampaignHold,
} from "./firstCampaign";
import {
  CLIENT_HEALTH_PATH,
  CLIENT_HEALTH_QUERY_KEY,
  type ClientHealth,
} from "./clientHealth";
import { HOLDS_PATH, HOLDS_QUERY_KEY, type HeldTenant } from "./holds";
import { KYC_PATH, toRecordBody, type KycRecord, type KycRecordIn } from "./kyc";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type TenantSummary = Schemas["TenantSummary"];
export type CreateOrgIn = Schemas["CreateOrgIn"];
export type CreateOrgOut = Schemas["CreateOrgOut"];
export type InviteOut = Schemas["InviteOut"];
/** One redeemable invitation, address masked (`admin/routes.py::PendingInviteOut`). */
export type PendingInviteOut = Schemas["PendingInviteOut"];
export type PlatformState = Schemas["PlatformStateOut"];
export type KbSource = Schemas["SourceOut"];
export type KbChunk = Schemas["ChunkOut"];

/**
 * The admin realm's session — an ADMIN Clerk token, or `dev:admin:` locally.
 *
 * The credential is chosen in `lib/auth/adminRealm.tsx`, which owns this realm's Clerk
 * application; the choice is `NEXT_PUBLIC_AUTH_MODE`, never a guess (`lib/auth/mode.ts`).
 * The local path is the one the API enforces two conditions for — `APP_ENV=local` AND no
 * Clerk secret for this realm (`core/auth.py::_verify_dev_token`) — and it carries
 * `dev:admin:` so a client token can never be pasted into an admin surface by accident.
 *
 * This function keeps its name and signature because twenty-five call sites (and one
 * file owned by another change) build their session through it: what changed is which
 * credential comes back, not where sessions come from.
 */
export function adminSession(orgSlug = ""): Session {
  return adminRealmSession(orgSlug);
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

interface MintedGrant {
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

async function mint(slug: string): Promise<MintedGrant> {
  // `adminSession()`, never `viewAsSession()`: minting is an admin-realm act, and the
  // API refuses a mint made from inside another account's session (no chained
  // delegation). Passing the impersonating session here would be an infinite regress
  // as well as a refusal.
  const minted = await apiRequest<MintResponse>(adminSession(), IMPERSONATION_GRANT_PATH, {
    method: "POST",
    body: { slug },
  });
  return { grant: minted.grant, expiresAtMs: Date.parse(minted.expires_at) };
}

function impersonationGrant(slug: string): GrantSource {
  return async () => {
    const cached = grantCache.get(slug);
    if (cached && cached.expiresAtMs - Date.now() > GRANT_REFRESH_MARGIN_MS) {
      return (await cached.pending).grant;
    }
    // Installed BEFORE the first await, so concurrent callers see this entry rather
    // than the stale one they would each have replaced.
    const entry: CachedGrant = { pending: mint(slug), expiresAtMs: Number.POSITIVE_INFINITY };
    grantCache.set(slug, entry);
    try {
      const minted = await entry.pending;
      entry.expiresAtMs = minted.expiresAtMs;
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

export function useTenants(): UseQueryResult<TenantSummary[]> {
  return useQuery({
    queryKey: ["admin", "tenants"],
    queryFn: () => apiRequest<TenantSummary[]>(adminSession(), "/v1/admin/tenants"),
    refetchInterval: 60_000,
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
    refetchInterval: 60_000,
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
    refetchInterval: 120_000,
  });
}

export function useTenant(tenantId: string): UseQueryResult<TenantSummary> {
  return useQuery({
    queryKey: ["admin", "tenant", tenantId],
    queryFn: () => apiRequest<TenantSummary>(adminSession(), `/v1/admin/tenants/${tenantId}`),
    enabled: Boolean(tenantId),
  });
}

export function useCreateTenant() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateOrgIn) =>
      apiRequest<CreateOrgOut>(adminSession(), "/v1/admin/tenants", {
        method: "POST",
        body: payload,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "tenants"] }),
  });
}

export function useInvite() {
  return useMutation({
    mutationFn: ({ tenantId, email, role }: { tenantId: string; email: string; role: string }) =>
      apiRequest<InviteOut>(adminSession(), `/v1/admin/tenants/${tenantId}/invitations`, {
        method: "POST",
        body: { email, role },
      }),
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

export function usePlatformState(): UseQueryResult<PlatformState> {
  return useQuery({
    queryKey: ["admin", "platform"],
    queryFn: () => apiRequest<PlatformState>(adminSession(), "/v1/ops/platform"),
    refetchInterval: 30_000,
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
      apiRequest<TmRegistration>(adminSession(), "/v1/ops/platform/tm-registration", {
        method: "POST",
        body: payload,
        // The header names the DIRECTION of this write, and the rule is copied from
        // the route verbatim (`ops/routes.py`: `"record_tm_registration" if
        // payload.status == "active"`). That is a property of the request we are
        // sending, not a judgement about what counts as live — the server owns that,
        // and a mismatched header is refused rather than assumed.
        confirmAction:
          payload.status === "active" ? "record_tm_registration" : "withdraw_tm_registration",
      }),
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
      apiRequest<Schemas["apps__api__admin__routes__KycRecordOut"]>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/kyc`,
        { method: "POST", body: toRecordBody(payload) },
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
    onSuccess: () =>
      void Promise.all([
        client.invalidateQueries({ queryKey: ["admin", "kyc"] }),
        client.invalidateQueries({ queryKey: HOLDS_QUERY_KEY }),
        client.invalidateQueries({ queryKey: ["admin", "tenants"] }),
      ]),
  });
}

/**
 * The first-campaign hold on one account — read through impersonation, released through
 * the admin surface.
 *
 * The same D-22 split as the KB queue and KYC, and the same reason it is the only shape
 * available: there is no admin-realm READ of a tenant's review. `GET /v1/compliance/
 * first-campaign-review` is `org:read` — non-mutating, so it stays reachable inside a
 * read-only "view as client" session — and it is the endpoint that returns the SERVER's
 * `held` predicate, the one the launch gate and the dispatch tick ask. The console must
 * not re-derive that from `status`, so it reads the tenant's own view of it.
 */
export function useTenantFirstCampaignHold(slug: string): UseQueryResult<FirstCampaignHold> {
  return useQuery({
    queryKey: ["admin", "first-campaign", slug],
    queryFn: () => apiRequest<FirstCampaignHold>(viewAsSession(slug), FIRST_CAMPAIGN_REVIEW_PATH),
    enabled: Boolean(slug),
  });
}

/**
 * The tenant's campaigns, read through impersonation — the evidence list for a release.
 *
 * `GET /v1/campaigns` is `leads:read`, which the operator role holds and which is not in
 * `MUTATING_PERMISSIONS`, so an impersonating session may read it. It exists on the
 * release screen for one field: `reviewed_campaign_id`, WHICH campaign a human actually
 * read. The API validates that id inside `tenant_session`, so naming another tenant's
 * campaign is a 404 rather than a stored cross-tenant pointer — this list is how an
 * operator picks a real one rather than pasting a uuid.
 */
export function useTenantCampaigns(slug: string): UseQueryResult<CampaignSummary[]> {
  return useQuery({
    queryKey: ["admin", "campaigns", slug],
    queryFn: () => apiRequest<CampaignSummary[]>(viewAsSession(slug), "/v1/campaigns"),
    enabled: Boolean(slug),
  });
}

/**
 * Release (or refuse) an account's campaign calling — R-11's hold, audited on every call.
 *
 * `adminSession()` with the tenant in the PATH, never the impersonating session that
 * read the state above: `admin:tenants` is a MUTATING permission, so the same call made
 * with `viewAsSession` would be correctly refused by `core/auth.py`. Two sessions on one
 * screen is D-22 working, not an inconsistency.
 *
 * No `Idempotency-Key` and no `X-Confirm-Action`, because the route asks for neither.
 * The write is an upsert of one row per tenant — sending it twice records the same
 * decision — and the history that must not be lost is the `audit_log` entry per call,
 * which is the point: a release and a later withdrawal are two entries, not one edited
 * row (hard rule 4).
 */
export function useFirstCampaignDecision(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: FirstCampaignDecisionIn) =>
      apiRequest<FirstCampaignDecisionOut>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/first-campaign-review`,
        { method: "POST", body: toDecisionBody(payload) },
      ),
    // The screen re-reads the tenant's own `held` afterwards rather than trusting this
    // response: `FirstCampaignDecisionOut` carries what was decided, and whether the
    // account is now held is the GATE's answer to a different question — an `approved`
    // row on a tier the rule does not apply to is not the same fact as a released one.
    onSuccess: () =>
      void Promise.all([
        client.invalidateQueries({ queryKey: ["admin", "first-campaign"] }),
        client.invalidateQueries({ queryKey: HOLDS_QUERY_KEY }),
        client.invalidateQueries({ queryKey: ["admin", "tenants"] }),
      ]),
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
      apiRequest<PlatformState>(adminSession(), "/v1/ops/platform", {
        method: "POST",
        body: {
          ...(outboundHalted === undefined ? {} : { outbound_halted: outboundHalted }),
          ...(loadShedMode === undefined ? {} : { load_shed_mode: loadShedMode }),
          reason,
        },
        // Step-up confirmation (BACKEND-PATTERNS §7): the header must echo the action.
        // It is not the second factor — admin-realm MFA is enforced server-side on every
        // admin token (`core/auth.py::verify_token`) — and it is no longer standing in
        // for one. MFA is per SESSION; this is per ACTION, and the mis-click and the
        // drive-by are both performed by a session that has already passed MFA. See
        // `apps/api/ops/routes.py` for why removing it was rejected.
        confirmAction: platformConfirmation({ outboundHalted, loadShedMode }),
      }),
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
      apiRequest<OutboxReplayResult>(
        adminSession(),
        job === null
          ? "/v1/ops/outbox/replay"
          : `/v1/ops/outbox/replay?job=${encodeURIComponent(job)}`,
        { method: "POST", confirmAction: outboxReplayConfirmation(job) },
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
 * panel is D-22 working, the same split as KYC and the first-campaign hold.
 *
 * It recomputes; it does not un-cap. A tenant still over their ceiling comes back
 * `capped: true`, which is the route doing its job — so the screen renders the counters
 * beside the ceilings, and that answer reads as an explanation rather than a failure.
 */
export function useRecomputeSpendCap(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<SpendCapRecompute>(
        adminSession(),
        `/v1/ops/tenants/${tenantId}/spend-cap/recompute`,
        { method: "POST", confirmAction: spendCapConfirmation(tenantId) },
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
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "kb"] }),
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

export function useProvisionNumber(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: { e164: string; series: "140" | "160" | "standard" }) =>
      apiRequest<components["schemas"]["NumberCreatedOut"]>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/numbers`,
        { method: "POST", body: payload },
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "numbers"] }),
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
