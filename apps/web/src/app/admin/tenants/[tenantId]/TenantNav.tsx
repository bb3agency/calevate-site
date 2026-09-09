"use client";

import {
  BrainCircuit,
  Building2,
  CalendarX2,
  Coins,
  Eye,
  FileCheck2,
  Flag,
  IndianRupee,
  KeyRound,
  Power,
  ReceiptIndianRupee,
  ShieldCheck,
  Wallet,
} from "lucide-react";

import { viewAsHref } from "@/lib/api/session";

import { NavLink } from "./controls";

/**
 * Every screen this client's record continues on, and why each is a screen rather than a
 * panel here. The reasons are kept beside the links because they are the argument for the
 * shape of this whole surface: a panel that needs its own unsaved state, its own audited
 * write or its own history is a route, not a card.
 */
export function TenantNav({ tenantId, slug }: { tenantId: string; slug: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      {/* The telecom gate in front of everything below: no verification, no number
          on any tier, and no outbound dialling at all on a self-serve account. It
          gets its own screen rather than a panel here because it is an audited
          write with four fields an auditor will ask about, and because the current
          record has to be read from the tenant's own view of it. */}
      <NavLink href={`/admin/tenants/${tenantId}/kyc`} icon={<ShieldCheck className="h-4 w-4" />}>
        Identity (KYC)
      </NavLink>
      {/* The other human-decision gate, and the only one that had no screen at all:
          `POST .../first-campaign-review` was reachable by curl and nothing else. It
          is a sibling of KYC rather than a panel here for the same reasons — an
          audited compliance decision with a note an auditor will read, over a state
          that has to be read from the tenant's own view of it. */}
      <NavLink
        href={`/admin/tenants/${tenantId}/first-campaign-review`}
        icon={<FileCheck2 className="h-4 w-4" />}
      >
        Campaign review
      </NavLink>
      <NavLink
        href={`/admin/tenants/${tenantId}/invoice`}
        icon={<ReceiptIndianRupee className="h-4 w-4" />}
      >
        Invoice
      </NavLink>
      {/* WHERE the margin card below came from, per agent and per call. Its own screen
          rather than another panel here because it is three tables that grow with the
          month, and because it is the operator's half of the screen the client reads
          at /c/<slug>/spend — one attribution, two audiences, so a support call is two
          people looking at the same rupees. */}
      <NavLink href={`/admin/tenants/${tenantId}/spend`} icon={<Coins className="h-4 w-4" />}>
        Spend
      </NavLink>
      {/* What the invoice above is DERIVED FROM. `plans` had no writer at all until
          this screen landed, so every number on the invoice rested on a row somebody
          had inserted by hand. Its own screen because a plan change is an audited,
          dated agreement with a history an operator has to be able to read. */}
      <NavLink
        href={`/admin/tenants/${tenantId}/commercials`}
        icon={<IndianRupee className="h-4 w-4" />}
      >
        Commercials
      </NavLink>
      {/* The wallet the commercial terms are drawn down against, and the ONLY path
          money takes INTO an account. Its own screen because the ledger has to be
          visible before the write — a blind form over an append-only ledger is how a
          double credit happens — and because nothing on it can be undone. */}
      <NavLink
        href={`/admin/tenants/${tenantId}/credits`}
        icon={<Wallet className="h-4 w-4" />}
      >
        Credits
      </NavLink>
      {/* Beta features and debug views, per client (SURFACES §1). Its own screen
          rather than a panel here because each flag needs three facts beside it — the
          platform default, this client's override, and the resolved answer — and a
          row that showed only the last one would read as a switch nobody set. */}
      <NavLink
        href={`/admin/tenants/${tenantId}/feature-flags`}
        icon={<Flag className="h-4 w-4" />}
      >
        Feature flags
      </NavLink>
      {/* Which model this client's agents think with, and what a minute of it costs
          them. Beside Commercials rather than under Feature flags because it is a
          PRICE as much as a setting — and its own screen for the same reason the
          flags are: the choice needs the platform default, this client's own choice
          and the resolved answer beside it, plus a rate against every option. */}
      <NavLink
        href={`/admin/tenants/${tenantId}/llm-model`}
        icon={<BrainCircuit className="h-4 w-4" />}
      >
        Language model
      </NavLink>
      {/* The client's OWN record — name, notice address, vertical. First of the three
          account-management screens because it is the one an operator reaches for
          most: a typo in a business name is the commonest correction there is, and
          until D-546 the PATCH behind it had no caller at all. */}
      <NavLink
        href={`/admin/tenants/${tenantId}/profile`}
        icon={<Building2 className="h-4 w-4" />}
      >
        Business details
      </NavLink>
      {/* Who holds a key to this account right now, and re-cutting one. Its own screen
          rather than a panel here because it is STATE before it is a button — when the
          last link went and how many have gone is what turns "they have not signed up"
          into a decision — and because the address correction needs its own note field
          and its own disclosure. */}
      <NavLink
        href={`/admin/tenants/${tenantId}/invitations`}
        icon={<KeyRound className="h-4 w-4" />}
      >
        Invitations
      </NavLink>
      {/* Suspend / reactivate. Separate from everything above because it is the one
          control here that stops a client's outbound dialling outright. */}
      <NavLink
        href={`/admin/tenants/${tenantId}/lifecycle`}
        icon={<Power className="h-4 w-4" />}
      >
        Account state
      </NavLink>
      {/* Ending the relationship: close now, erase after the grace window, undo in
          between. The ONE way to close a client since D-546 — the Account state
          dropdown used to offer a second one that told the client nothing and had no
          way back. Its own screen because a closed account has to show what happens
          next and by when, which is a countdown rather than a control. */}
      <NavLink
        href={`/admin/tenants/${tenantId}/closure`}
        icon={<CalendarX2 className="h-4 w-4" />}
      >
        Closing the account
      </NavLink>
      {/* `?view=admin` tells the client-realm shell to build the IMPERSONATING
          session (admin token + X-Impersonate-Org) instead of a client one — see
          lib/api/session.tsx. Without it the link handed over a client token the
          operator does not have, so `me.impersonating` was always false and the
          read-only banner never appeared. The marker selects a credential; it
          grants nothing, and the API verifies the admin identity regardless.

          "read-only" is now IN THE LABEL rather than only in a `title` a mouse has
          to find and a keyboard never will. D-22 is the promise this link makes, and
          a promise that only appears on hover is not one the operator has read. */}
      <NavLink
        href={viewAsHref(slug)}
        icon={<Eye className="h-4 w-4" />}
        title="Read-only. Every page view is recorded in the audit log."
      >
        View as client (read-only)
      </NavLink>
    </div>
  );
}
