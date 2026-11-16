"use client";

import Link from "next/link";

import { useClientRealm, useClientSession } from "@/lib/api/session";

import { Group } from "./KnowledgeGroup";

/**
 * WHAT ONE JOB KNOWS THAT THE OTHERS DO NOT: its own script. An agent has no script of its
 * own (founder, 16 Nov 2026); each Inbound line and each campaign has one, and only its calls
 * use it. Everything else on this page is shared by every agent (D-689), so the scripts are
 * named here and opened where they are written rather than copied in.
 */
const PLACES = [
  { id: "inbound", name: "Inbound lines", line: "What each of your numbers says when called.", path: "inbound", open: "Open Inbound" },
  { id: "campaigns", name: "Campaigns", line: "What each campaign says on the calls it makes.", path: "campaigns", open: "Open Campaigns" },
] as const;

export function AgentScripts({ query }: { query: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const q = query.trim().toLocaleLowerCase();
  const shown = PLACES.filter((place) => !q || place.name.toLocaleLowerCase().includes(q) || "script".includes(q));

  return (
    <Group
      title="Scripts"
      count={PLACES.length}
      hidden={q !== "" && shown.length === 0}
      info={<p>Each Inbound line and campaign has its own script. Everything above is shared.</p>}
    >
      <ul className="divide-y divide-line border-y border-line" aria-label="Where scripts are written">
        {shown.map((place) => (
          <li key={place.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5">
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">{place.name}</p>
              <p className="text-meta text-ink-muted">{place.line}</p>
            </div>
            <Link
              href={href(`/c/${session.orgSlug}/${place.path}`)}
              className="text-meta text-ink underline underline-offset-2 touch:inline-flex touch:min-h-11 touch:items-center"
            >
              {place.open}
            </Link>
          </li>
        ))}
      </ul>
    </Group>
  );
}
