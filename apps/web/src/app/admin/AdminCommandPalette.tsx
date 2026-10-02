"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";

import { adminAccess, useAdminMe } from "@/app/admin/access";
import { ADMIN_NAV } from "@/app/admin/adminNav";
import {
  TENANT_SECTIONS,
  tenantSectionHref,
} from "@/app/admin/tenants/[tenantId]/tenantSections";
import { CommandPalette, type CommandItem } from "@/components/interior/command-palette";
import { useTenant, useTenants } from "@/lib/api/admin";
import { viewAsHref } from "@/lib/api/session";

/** What a palette row does: every one of them only navigates. */
type Destination = CommandItem & { href: string };

const CLIENTS = "Clients";
const PAGES = "Pages";
const ACTIONS = "Actions";

/** How many directory rows the palette lists before the operator has typed anything. */
const RECENT_CLIENTS = 5;
/** The directory's first page is 25; a palette is for jumping, not browsing. */
const MATCHED_CLIENTS = 8;

function tenantIdOf(pathname: string): string | null {
  return /^\/admin\/tenants\/([^/]+)/.exec(pathname)?.[1] ?? null;
}

/**
 * Ctrl/Cmd+K: jump to any client, any admin page, or a client's section (D-661).
 *
 * Read-only by construction. Every row is a link: an action row OPENS the screen where
 * the action lives with its own confirm step, never performs it from here. Clients come
 * from the directory endpoint the Clients screen already uses (`GET /v1/admin/tenants`,
 * searched server-side by name and slug) — no new read.
 */
export function AdminCommandPalette() {
  const [open, setOpen] = useState(false);
  const [isMac, setIsMac] = useState(false);

  useEffect(() => {
    setIsMac(/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent));
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((was) => !was);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const shortcut = isMac ? "⌘K" : "Ctrl K";

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-keyshortcuts="Control+K Meta+K"
        aria-label="Search clients and pages"
        className="press flex h-9 items-center gap-2 rounded-md border border-line bg-surface px-2.5 text-sm text-ink-muted hover:bg-black/5 touch:h-11 touch:min-w-11 justify-center dark:hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 sm:w-56 sm:justify-start"
      >
        <Search aria-hidden className="h-4 w-4 shrink-0" />
        <span className="hidden flex-1 text-left sm:inline">Search</span>
        <kbd aria-hidden className="hidden rounded border border-line px-1.5 font-mono text-[11px] text-ink-faint sm:inline">
          {shortcut}
        </kbd>
      </button>
      {open && <PaletteBody onClose={() => setOpen(false)} />}
    </>
  );
}

function PaletteBody({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useAdminMe();
  const [query, setQuery] = useState("");
  const [term, setTerm] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setTerm(query.trim()), 200);
    return () => clearTimeout(timer);
  }, [query]);

  const directory = useTenants({ q: term });
  const tenantId = tenantIdOf(pathname);
  const here = useTenant(tenantId ?? "");
  const client = tenantId ? here.data : undefined;

  const items = useMemo<Destination[]>(() => {
    const out: Destination[] = [];
    // No clients group at all until the directory has ANSWERED; the footer says why.
    const rows = directory.data ? directory.data.rows : [];
    for (const row of rows.slice(0, term ? MATCHED_CLIENTS : RECENT_CLIENTS)) {
      out.push({
        id: `client-${row.id}`,
        group: CLIENTS,
        label: row.name,
        hint: `/c/${row.slug}`,
        // The server already matched the term on name or slug; repeating the term as a
        // keyword keeps a server match from being dropped by the local ranker.
        keywords: `${row.slug} ${term}`,
        href: `/admin/tenants/${row.id}`,
      });
    }
    if (tenantId && client) {
      for (const section of TENANT_SECTIONS) {
        out.push({
          id: `section-${section.path || "overview"}`,
          group: client.name,
          label: section.label,
          href: tenantSectionHref(tenantId, section),
        });
      }
    }
    for (const group of ADMIN_NAV) {
      for (const item of group.items) {
        if (item.hideUnlessAllowed && !adminAccess(me, item.permission, item.action).allowed) continue;
        out.push({
          id: `page-${item.href}`,
          group: PAGES,
          label: item.label,
          hint: group.heading ?? undefined,
          href: item.href,
        });
      }
    }
    out.push({
      id: "action-new-client",
      group: ACTIONS,
      label: "Create a client",
      keywords: "new onboard add",
      href: "/admin/new",
    });
    out.push({
      id: "action-halt",
      group: ACTIONS,
      label: "Stop all outbound calls",
      hint: "Opens Operations",
      keywords: "big red switch halt kill",
      href: "/admin/ops",
    });
    if (tenantId && client) {
      out.push({
        id: "action-view-as",
        group: ACTIONS,
        label: `View ${client.name} as client (logged)`,
        keywords: "impersonate view as",
        href: viewAsHref(client.slug),
      });
      out.push({
        id: "action-credits",
        group: ACTIONS,
        label: `Add credits for ${client.name}`,
        keywords: "wallet grant money top up",
        href: `/admin/tenants/${tenantId}/credits`,
      });
    }
    return out;
  }, [directory.data, term, tenantId, client, me]);

  // On a client's page its own sections come first: that is the likeliest jump.
  const groups = [...(client ? [client.name] : []), CLIENTS, PAGES, ACTIONS];

  // A failed read and one parked offline are both "could not", never "no clients".
  const footer = directory.error || (!directory.data && !directory.isLoading)
    ? "Clients could not be searched right now. Pages and actions still work."
    : term && directory.isFetching
      ? "Searching clients…"
      : null;

  return (
    <CommandPalette
      label="Search clients and pages"
      placeholder="Search clients, pages and actions"
      emptyLabel="Nothing matches. Clients are searched by name and slug."
      items={items}
      groups={groups}
      query={query}
      onQueryChange={setQuery}
      footer={footer}
      onClose={onClose}
      onSelect={(item) => {
        const href = (item as Destination).href;
        onClose();
        if (href.startsWith("/")) router.push(href);
        else window.location.assign(href);
      }}
    />
  );
}
