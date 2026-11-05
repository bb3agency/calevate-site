"use client";

import Link from "next/link";

import { DAYS, DAY_LABELS, type BusinessProfile } from "@/lib/api/businessProfile";
import { useClientRealm, useClientSession } from "@/lib/api/session";

import { Group } from "./KnowledgeGroup";

interface Basic {
  label: string;
  value: string;
}

/**
 * The rest of what every agent is told from the business details, beside the offers and
 * common questions `ProfileKnowledge` lists: the same parts, in the same order, that
 * `tenancy/business_profile.fact_lines` writes into every agent's facts (hours, each
 * address, the team, the booking rules). Contact numbers are not among them: they never
 * reach an agent. Read-only here; Business details is where they change.
 */
export function profileBasics(profile: BusinessProfile): Basic[] {
  const basics: Basic[] = [];
  // One row for the week, as the agents get one line for it.
  const week = DAYS.flatMap((day) => {
    const hours = profile.hours.find((h) => h.day === day);
    if (!hours) return [];
    const time = hours.closed || !hours.opens || !hours.closes ? "Closed" : `${hours.opens}–${hours.closes}`;
    return [`${DAY_LABELS[day]} ${time}`];
  });
  if (week.length > 0) basics.push({ label: "Hours", value: week.join("\n") });
  for (const branch of profile.branches) {
    basics.push({ label: branch.label || "Address", value: branch.address });
  }
  for (const person of profile.staff) {
    basics.push({ label: person.role || "Team", value: person.name });
  }
  if (profile.booking_rules?.trim()) {
    basics.push({ label: "Booking rules", value: profile.booking_rules.trim() });
  }
  return basics;
}

/** How many of these the agents are told: one per row, as `fact_lines` writes them. */
export function basicsCount(profile: BusinessProfile | undefined): number {
  return profile ? profileBasics(profile).length : 0;
}

export function BusinessBasics({ profile, query }: { profile: BusinessProfile; query: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const all = profileBasics(profile);
  const q = query.trim().toLocaleLowerCase();
  const shown = q
    ? all.filter((b) => b.label.toLocaleLowerCase().includes(q) || b.value.toLocaleLowerCase().includes(q))
    : all;
  return (
    <Group
      title="Hours, places and team"
      count={basicsCount(profile)}
      hidden={q !== "" && shown.length === 0}
      info={<p>From your business details. Every agent is told these.</p>}
      status={
        <Link
          href={href(`/c/${session.orgSlug}/settings/business`)}
          className="text-meta text-ink-muted underline underline-offset-2 touch:inline-flex touch:min-h-11 touch:items-center"
        >
          Business details
        </Link>
      }
    >
      {all.length === 0 ? (
        <p className="text-meta text-ink-muted">No hours or address yet.</p>
      ) : (
        <dl className="divide-y divide-line border-y border-line">
          {shown.map((basic, index) => (
            <div key={`${basic.label}-${index}`} className="grid gap-x-4 gap-y-0.5 py-2.5 sm:grid-cols-[10rem_1fr]">
              <dt className="text-meta text-ink-muted">{basic.label}</dt>
              <dd className="whitespace-pre-line text-sm text-ink tabular-nums [overflow-wrap:anywhere]">
                {basic.value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </Group>
  );
}
