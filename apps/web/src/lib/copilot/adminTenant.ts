import type { CopilotSurface } from "./types";

const TENANT_PAGE = /^\/admin\/tenants\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\/|$)/i;

/**
 * Which client account an ADMIN-realm question is about, or `undefined`.
 *
 * The surface's own `tenantId` first; otherwise the account in the address, because every
 * page under `/admin/tenants/{id}` is about that one client whether or not its screen
 * thought to say so. The server validates the id against the directory before using it
 * (`copilot/admin_routes._viewed_tenant`), so a stale or hand-typed one is refused, never
 * trusted. The client realm never sends one: its account comes from the session.
 */
export function adminTenantOf(surface: CopilotSurface, pathname: string): string | undefined {
  if (surface.realm !== "admin") return undefined;
  if (surface.tenantId) return surface.tenantId;
  return TENANT_PAGE.exec(pathname)?.[1];
}
