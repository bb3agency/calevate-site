/**
 * The languages this account's agents may speak, as the server decides them (D-855).
 *
 * Tamil, Kannada, Malayalam and Marathi are in the generated union but held back until the
 * console switches each one on, so a picker cannot list `LANGUAGE_NAMES` and must ask.
 * While the answer loads (or if it fails) the three every account is offered are shown,
 * which is never wider than what the server accepts.
 */
import { useQuery } from "@tanstack/react-query";

import { LANGUAGE_CHOICES, LANGUAGE_NAMES } from "@/lib/agentState";

import type { AgentLanguage } from "./agents";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type AgentLanguagesOut = components["schemas"]["AgentLanguagesOut"];

export interface LanguageChoice {
  value: AgentLanguage;
  label: string;
}

export const agentLanguageKeys = {
  all: (org: string) => ["agent-languages", org] as const,
};

/** The choices a language picker offers this account, in the server's order. */
export function useAgentLanguageChoices(session: Session): LanguageChoice[] {
  const query = useQuery({
    queryKey: agentLanguageKeys.all(session.orgSlug),
    queryFn: () => apiRequest<AgentLanguagesOut>(session, "/v1/agents/languages"),
    staleTime: 5 * 60_000,
  });
  if (!query.data) return LANGUAGE_CHOICES;
  return query.data.languages.map(({ tag }) => ({ value: tag, label: LANGUAGE_NAMES[tag] }));
}
