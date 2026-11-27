/**
 * THE WAY BACK FROM A JOB'S PAGE (a campaign or an inbound line), redesign plan §1.
 *
 * A job is an agent's work, so its page leads back to that agent ("Agents › Anjali"): the
 * agent home lists its jobs, and an owner who opened one from there returns there. A page
 * opened from the jobs' own list carries `?from=list` and leads back to the list. The route
 * itself never changes, so every existing link keeps working.
 */

/** The query a list row adds so the job page leads back to the list. */
export const FROM_LIST = "from=list";

export type JobBack = { href: string; label: string };

export function jobBack({
  from,
  agentId,
  agentName,
  list,
  agentHref,
}: {
  /** The page's `?from=` value. */
  from: string | null;
  agentId: string | null | undefined;
  agentName: string | null | undefined;
  /** The jobs' own list, the way back when no agent can be named. */
  list: JobBack;
  agentHref: (agentId: string) => string;
}): JobBack {
  if (from === "list" || !agentId || !agentName?.trim()) return list;
  return { href: agentHref(agentId), label: `Agents › ${agentName.trim()}` };
}
