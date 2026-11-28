"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";

import { CommandPalette, type CommandItem } from "@/components/interior/command-palette";
import { formatIST } from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useCampaigns } from "@/lib/api/campaigns";
import { useInboundLines } from "@/lib/api/inboundLines";
import { useFind } from "@/lib/api/leadNotes";
import { useClientRealm } from "@/lib/api/session";
import { useLeadNouns } from "@/lib/businessCapabilities";
import { outcomeWords } from "@/lib/callReview";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { openAssistant } from "@/lib/copilot/launcher";

import { stageLabel } from "./leads/StatusSelect";

/** A row either opens a screen or hands the words to Pip. */
type Destination = CommandItem & { href?: string; ask?: string };

const CALLS = "Calls";
const AGENTS = "Agents";
const CAMPAIGNS = "Campaigns";
const LINES = "Inbound lines";
const SCREENS = "Screens";
const PIP = ASSISTANT_NAME;

/** How many agents, campaigns or lines are listed before anything is typed. */
const BEFORE_TYPING = 4;

/**
 * Find (W7.4): Ctrl/Cmd+K, or the search button in the bar, opens one box for a person, one
 * of their calls, an agent, a campaign, an inbound line or a screen, with "Ask Pip" last.
 *
 * People and calls come from `POST /v1/find`, which matches a name, the last digits of a
 * number and a Telugu name typed in English letters; the term travels in the body and
 * only ever reaches a URL as an id. Agents, campaigns and lines are the lists their own
 * screens already read, ranked here. Every row only opens a screen; nothing is changed
 * from this box.
 */
export function ClientFind({ slug }: { slug: string }) {
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
        aria-label="Find a person, call or screen"
        className="press flex h-9 w-9 shrink-0 items-center justify-center gap-2 rounded-md text-ink-muted hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 touch:h-11 touch:w-11 lg:w-52 lg:justify-start lg:border lg:border-line lg:bg-surface lg:px-2.5 dark:hover:bg-white/5"
      >
        <Search aria-hidden className="h-4 w-4 shrink-0" />
        <span className="hidden flex-1 text-left text-body lg:inline">Find</span>
        <kbd aria-hidden className="hidden rounded border border-line px-1.5 font-mono text-meta text-ink-faint lg:inline">
          {shortcut}
        </kbd>
      </button>
      {open && <FindBody slug={slug} onClose={() => setOpen(false)} />}
    </>
  );
}

function FindBody({ slug, onClose }: { slug: string; onClose: () => void }) {
  const router = useRouter();
  const { session, href } = useClientRealm();
  const nouns = useLeadNouns();
  const [query, setQuery] = useState("");
  const [term, setTerm] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setTerm(query.trim()), 200);
    return () => clearTimeout(timer);
  }, [query]);

  const found = useFind(session, term);
  const agents = useAgents(session);
  const campaigns = useCampaigns(session);
  const lines = useInboundLines(session);
  const people = nouns.Leads;

  const items = useMemo<Destination[]>(() => {
    const out: Destination[] = [];
    // A server match is kept by the local ranker: the term rides along as a keyword, since
    // "7345" or "srinivas" is not in the label a match is drawn with.
    const matched = found.data && term ? found.data : null;
    for (const person of matched?.people ?? []) {
      out.push({
        id: `person-${person.lead_id}`,
        group: people,
        label: person.name ?? "No name given",
        hint: `ends ${person.phone_last4} · ${stageLabel(person.status)}`,
        keywords: term,
        href: `/c/${slug}/leads/${person.lead_id}`,
      });
    }
    if (matched?.calls_shown) {
      for (const call of matched.calls) {
        out.push({
          id: `call-${call.call_id}`,
          group: CALLS,
          label: `${call.name ?? `Ends ${call.phone_last4}`} · ${formatIST(call.at)}`,
          hint:
            outcomeWords({ outcome_tag: call.outcome_tag ?? null, business_outcome_label: call.business_outcome_label ?? null }) ??
            (call.direction === "outbound" ? "Outgoing" : "Incoming"),
          keywords: term,
          href: `/c/${slug}/calls/${call.call_id}`,
        });
      }
    }
    const take = <T,>(rows: T[] | undefined) => (term ? (rows ?? []) : (rows ?? []).slice(0, BEFORE_TYPING));
    for (const agent of take(agents.data)) {
      out.push({ id: `agent-${agent.id}`, group: AGENTS, label: agent.name, href: `/c/${slug}/agents/${agent.id}` });
    }
    for (const campaign of take(campaigns.data)) {
      out.push({
        id: `campaign-${campaign.id}`,
        group: CAMPAIGNS,
        label: campaign.name,
        href: `/c/${slug}/campaigns/${campaign.id}`,
      });
    }
    for (const line of take(lines.data)) {
      out.push({
        id: `line-${line.id}`,
        group: LINES,
        label: line.name,
        hint: line.agent_name,
        href: `/c/${slug}/inbound/${line.id}`,
      });
    }
    for (const screen of matched?.screens ?? []) {
      out.push({
        id: `screen-${screen.route}`,
        group: SCREENS,
        label: screen.name,
        hint: screen.group ?? undefined,
        keywords: term,
        href: screen.route.replace("{slug}", slug),
      });
    }
    if (query.trim()) {
      const words = query.trim();
      out.push({ id: "ask-pip", group: PIP, label: `Ask ${ASSISTANT_NAME}: ${words}`, keywords: words, ask: words });
    }
    return out;
  }, [found.data, term, query, agents.data, campaigns.data, lines.data, slug, people]);

  const groups = [people, CALLS, AGENTS, CAMPAIGNS, LINES, SCREENS, PIP];

  const footer =
    term && found.error
      ? `${people} and calls could not be searched right now. The rest still works.`
      : term && found.isFetching
        ? "Searching…"
        : !term
          ? "Type a name, the last 4 digits of a number, or a screen."
          : null;

  return (
    <CommandPalette
      label="Find a person, call or screen"
      placeholder="Name, last 4 digits, or a screen"
      emptyLabel="Nothing matches. Try the last 4 digits of their number."
      items={items}
      groups={groups}
      query={query}
      onQueryChange={setQuery}
      footer={footer}
      onClose={onClose}
      onSelect={(item) => {
        const row = item as Destination;
        onClose();
        if (row.ask) openAssistant({ prompt: row.ask });
        else if (row.href) router.push(href(row.href));
      }}
    />
  );
}
