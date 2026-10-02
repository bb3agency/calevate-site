import type { ComponentType } from "react";
import {
  AudioLines,
  BellRing,
  Building2,
  CalendarClock,
  ClipboardCheck,
  Coins,
  Gauge,
  HeartPulse,
  Hourglass,
  KeyRound,
  PhoneOff,
  ShieldUser,
  SlidersHorizontal,
  UserPlus,
} from "lucide-react";

/**
 * The admin console's page list: the sidebar renders it, the header title is derived from
 * it, and the command palette offers it. It lives outside `layout.tsx` because a route file
 * may export only Next's own conventions (D-196), and the palette needs the same list.
 */

export interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  /**
   * The permission the screen behind this entry actually needs — the one its own routes
   * declare (`openapi_extra=permission_meta(...)`), not a guess about seniority.
   */
  permission: string;
  /** What the entry lets you do, completing "…so you cannot ___" in the refusal. */
  action: string;
  /**
   * ABSENT for a session that may not use it, rather than shown and dead — the ONE
   * exception to this shell's standing doctrine, and `renderItem` argues why it is
   * granted to exactly one surface.
   *
   * It also inverts which side of the unknown the entry falls on: a hidden entry is
   * rendered on `allowed` (the server has SAID yes) rather than on `!refused`, because
   * `refused` is false while the identity read is in flight and after it fails — so
   * keying on it would show this entry to every normal admin for the whole of that
   * window, which is exactly what the flag exists to prevent.
   */
  hideUnlessAllowed?: true;
}

export interface NavGroup {
  /** Null for the primary group, which carries no heading. */
  heading: string | null;
  items: NavItem[];
}

/**
 * ONE list. The sidebar renders it and the header title is derived from it, so a screen
 * that is renamed cannot keep its old name in the header — the defect a second copy
 * always eventually produces.
 *
 * The health board and the hold queue sit beside Clients rather than being reachable only
 * from a client row, and for the same reason in both cases: the account quietly failing,
 * or held on a gate nobody has looked at, is precisely the one nobody navigates to
 * (`admin/health.py`, `admin/holds.py`). Discovery must not depend on already knowing
 * which client to open.
 *
 * Each entry carries the PERMISSION its screen needs, taken from the routes that screen
 * calls: the directory and the wizard are `admin:tenants` (`admin/routes.py`), the health
 * board and the hold queue are `org:read` (their modules argue why a read of a work list
 * is not the authority to act on it), and Operations is `ops:manage` — which only
 * `superadmin` holds (`core/rbac.py`), so every route that screen calls refuses an
 * `operator`. That entry is the reason this list grew a permission column at all: it was
 * offered to every admin role, and an operator following it got a page that is nothing
 * but a 403.
 */
export const ADMIN_NAV: NavGroup[] = [
  {
    heading: null,
    items: [
      {
        href: "/admin",
        label: "Clients",
        icon: Building2,
        permission: "admin:tenants",
        action: "open the client directory",
      },
      {
        href: "/admin/health",
        label: "Client health",
        icon: HeartPulse,
        permission: "org:read",
        action: "open the client health board",
      },
      {
        // The money twin of the health board, and it sits beside it for that reason: one
        // answers "which client is broken", this answers "which client is costing us
        // money", and an operator opening the console in the morning wants both.
        // `billing:read` is what `GET /v1/admin/spend` requires — the same permission the
        // per-client margin card needs — so an admin role without it meets a sentence
        // here rather than a 403 on the page.
        href: "/admin/spend",
        label: "Money board",
        icon: Coins,
        permission: "billing:read",
        action: "open the fleet money board",
      },
      {
        href: "/admin/holds",
        label: "Held accounts",
        icon: Hourglass,
        permission: "org:read",
        action: "open the hold queue",
      },
      {
        href: "/admin/qa-sampling",
        label: "Call quality checks",
        icon: ClipboardCheck,
        permission: "org:read",
        action: "open the call quality checks",
      },
    ],
  },
  {
    heading: "Onboarding",
    items: [
      {
        href: "/admin/new",
        label: "New client",
        icon: UserPlus,
        permission: "admin:tenants",
        action: "create clients",
      },
    ],
  },
  {
    heading: "Platform",
    items: [
      {
        href: "/admin/ops",
        label: "Operations",
        icon: SlidersHorizontal,
        permission: "ops:manage",
        action: "open the operations console",
      },
      {
        // THE OPS CONFIG PANEL, WHICH HAD NO NAME IN THIS LIST UNTIL NOW. "Only super
        // admin has access to ops config panel and it should be added to the sidebar in
        // the super admin login" (the founder, correcting D-457). The three panels behind
        // it — platform settings, vendor credentials, key management — used to sit at the
        // bottom of Operations, so the surface every vendor key is installed on was
        // findable only by scrolling the screen you open when calls have stopped. It has
        // its own route now (`/admin/ops/config`), because a nav entry needs a
        // destination and two entries on one path would make `currentNavItem` decide the
        // header title and the highlight by a tie-break.
        //
        // `platform:config` is the permission its primary read carries
        // (`GET /v1/ops/config`, `apps/api/ops/config_routes.py`) — NOT `ops:manage`,
        // which is the entry above and a different authority. The credential panels on
        // the same screen gate themselves on `platform:secrets`, which is narrower still,
        // so a session holding one and not the other gets the screen and a withheld card.
        //
        // AND IT IS THE ONE HIDDEN ENTRY IN EITHER SHELL. See `renderItem`.
        href: "/admin/ops/config",
        label: "Platform configuration",
        icon: KeyRound,
        permission: "platform:config",
        action: "change platform configuration or install vendor credentials",
        hideUnlessAllowed: true,
      },
      {
        // WHICH VOICES THIS PLATFORM OFFERS (D-588, and the ADD form that replaced its
        // curation screen — D-590). Its own entry rather than a panel on
        // Operations, for the two rows below's reason — discovery — and one of its own.
        // The founder asked for a "Voices section" by name; and the operator who has just
        // cloned a voice on the voice platform is looking for the place that makes it
        // selectable, not scrolling a screen of incident switches to find it. The
        // longest-match title rule below means `/admin/ops/voices` keeps this name instead
        // of inheriting "Operations".
        //
        // `ops:manage` is the permission every route the screen calls carries
        // (`apps/api/ops/voice_curation_routes.py`, and the refresh in `ops/routes.py`).
        href: "/admin/ops/voices",
        label: "Voices",
        icon: AudioLines,
        permission: "ops:manage",
        action: "add and manage the voices this platform offers",
      },
      {
        // PLANNED MAINTENANCE. Its own entry rather than a panel on Operations, for the
        // reason the two rows below have theirs — discovery under pressure. An operator
        // about to take the platform down is following `runbooks/maintenance-window.md`,
        // and the screen they need shows a DRAIN that is counting down; burying it in a
        // page of platform switches is how somebody ends up forcing a window because they
        // could not find the numbers. The longest-match title rule below means
        // `/admin/ops/maintenance` keeps this name instead of inheriting "Operations".
        //
        // `ops:manage` is the permission every route on the surface carries
        // (`apps/api/ops/maintenance_routes.py`).
        href: "/admin/ops/maintenance",
        label: "Planned maintenance",
        icon: CalendarClock,
        permission: "ops:manage",
        action: "schedule or end a platform maintenance window",
      },
      {
        // Its own entry rather than a panel on Operations, and the reason is discovery
        // rather than layout: whoever is handling a regulator's complaint is following
        // `runbooks/dnc-complaint.md`, not scrolling a screen of platform switches — and
        // the longest-match title rule below means `/admin/ops/dnc` keeps this name
        // instead of inheriting "Operations".
        href: "/admin/ops/dnc",
        label: "Do-not-call list",
        icon: PhoneOff,
        permission: "ops:manage",
        action: "change the platform-wide do-not-call list",
      },
      {
        // THE ALERT BOARD (D-591). Its own entry, and this one is not a convenience: until
        // it existed the ONLY place an alarm had ever been readable was the founder's
        // inbox, every code mailed, and an inbox cannot answer "is anything broken right
        // now" — it sorts by arrival. Now only the loudest rung emails and every other
        // alarm is here and nowhere else, so an entry buried inside Operations would be a
        // screen nobody could find holding the only copy of most of what goes wrong.
        //
        // ABOVE the read-only reports below it, because it is the one an operator opens
        // when something is wrong rather than when they are curious.
        //
        // `ops:manage` is the permission the route carries (`apps/api/ops/routes.py`).
        href: "/admin/ops/alerts",
        label: "Alerts",
        icon: BellRing,
        permission: "ops:manage",
        action: "read what the platform has raised alarms about",
      },
      {
        // Same argument as the row above: OPERATIONS §2 gate 4 sends an
        // operator to this read to find out what D-449 actually bought, and it pointed at a
        // curl until this screen existed. Somebody paging on a slow call is not going
        // to scroll the platform switches to find it.
        href: "/admin/ops/engine-latency",
        label: "Voice response time",
        icon: Gauge,
        permission: "ops:manage",
        action: "read the voice response-time report",
      },
      {
        // LAST IN THE PLATFORM GROUP, and it is the only entry in either shell that is
        // superadmin-only for a reason other than blast radius: `admin:operators` is the
        // permission that edits the role table, so a normal admin who could reach it
        // could grant themselves the other three in one request (`core/rbac.py`). The
        // entry is still SHOWN and dead rather than hidden — this shell's standing
        // doctrine, argued at `renderItem` — because "open Admin accounts and add her"
        // is a sentence one operator says to another, and an entry that is simply absent
        // reads as a broken build.
        href: "/admin/operators",
        label: "Admin accounts",
        icon: ShieldUser,
        permission: "admin:operators",
        action: "manage who may use this console",
      },
    ],
  },
];
