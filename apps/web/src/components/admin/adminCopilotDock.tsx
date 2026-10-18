"use client";

import { useMemo } from "react";

import { ADMIN_NAV } from "@/app/admin/adminNav";
import { CopilotDock } from "@/components/copilot/CopilotDock";
import { adminSession } from "@/lib/api/admin";

/*
 * The operator console's dock, kept apart from `CopilotDock` so the admin API client and the
 * admin sidebar are not in the client console's first load: the client layout imports the
 * dock, and a module's every import ships with it.
 */

/**
 * The admin console's twin of `lib/copilot/navigate.ts::resolveDestination` (D-694): the
 * server sends an admin route CONSTANT (`apps/api/copilot/admin_screens.py`), and it is
 * accepted only if it is one of the admin sidebar's own entries — the same two-closed-lists
 * argument as the client's.
 */
export function resolveAdminDestination(route: string): string | null {
  const known = ADMIN_NAV.flatMap((group) => group.items.map((item) => item.href));
  return known.includes(route) ? route : null;
}

/** Mounted by `app/admin/layout.tsx`. `adminSession()` takes no org — an operator's
 *  session is not scoped to one tenant, and the screens that are name it in the path. */
export function AdminCopilotDock() {
  // HELD, because `adminSession()` BUILDS A NEW OBJECT on every call
  // (`lib/authn/realmSessions.ts::adminRealmSession` returns an object literal). Called
  // inline it changed identity on every render of this component, and `session` is a
  // dependency of `ask`, `reset` and the confirm mutation inside the panel — so all three
  // were rebuilt on every render, and anything that ever memoises on them would have been
  // silently defeated. The credential itself is read lazily through `session.token()`, so
  // holding the wrapper holds nothing stale.
  const session = useMemo(() => adminSession(), []);
  return (
    <CopilotDock
      session={session}
      realm="admin"
      navigation={{ slug: "", href: (path) => path, resolve: resolveAdminDestination }}
    />
  );
}
