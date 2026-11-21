/**
 * The languages this account's agents may speak, as the server decides them (D-855): the
 * three every account is offered plus any staged language the console switched on for it,
 * ordered with the platform's default language first. Every language picker, every
 * "starts in" default and every list of languages a screen offers reads this, never a
 * fixed list, so a Tamil-first account is offered Tamil the moment the server offers it.
 *
 * The server's `name` is the label, so a picker and the copilot's confirmation card name a
 * language with one string.
 */
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { LANGUAGE_NAMES } from "@/lib/languageNames";

import type { AgentLanguage } from "./agents";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type AgentLanguagesOut = components["schemas"]["AgentLanguagesOut"];

export interface LanguageChoice {
  value: AgentLanguage;
  label: string;
}

export interface AgentLanguages {
  /** What a picker offers, in the server's order. */
  choices: LanguageChoice[];
  /** The same, as tags. */
  tags: AgentLanguage[];
  /** The account's starting language (the server's first), or null until it has answered. */
  defaultTag: AgentLanguage | null;
  /** Whether `choices` is the server's answer. Until then it is the three every account is
   *  offered, which is never wider than the server accepts, and a form must not take its
   *  default from it. */
  loaded: boolean;
  /** Whether the read has finished, answered or failed: a screen that must not hold its
   *  default forever waits on this, and on a failure starts from `tags` as they stand. */
  settled: boolean;
}

/** Shown while the answer loads or if it fails: the three always offered. Never a default. */
const WHILE_LOADING: readonly AgentLanguage[] = ["te-IN", "hi-IN", "en-IN"];

export const agentLanguageKeys = {
  all: (org: string) => ["agent-languages", org] as const,
};

/** The server's list for one response, as choices. Exported for screens that already hold
 *  the response. */
export function choicesFrom(data: AgentLanguagesOut): LanguageChoice[] {
  return data.languages.map(({ tag, name }) => ({ value: tag, label: name || LANGUAGE_NAMES[tag] }));
}

export function useAgentLanguages(session: Session): AgentLanguages {
  const query = useQuery({
    queryKey: agentLanguageKeys.all(session.orgSlug),
    queryFn: () => apiRequest<AgentLanguagesOut>(session, "/v1/agents/languages"),
    staleTime: 5 * 60_000,
  });
  const data = query.data;
  const settled = !query.isPending;
  return useMemo(() => {
    if (!data) {
      return {
        choices: WHILE_LOADING.map((value) => ({ value, label: LANGUAGE_NAMES[value] })),
        tags: [...WHILE_LOADING],
        defaultTag: null,
        loaded: false,
        settled,
      };
    }
    const choices = choicesFrom(data);
    return { choices, tags: choices.map((c) => c.value), defaultTag: choices[0]?.value ?? null, loaded: true, settled };
  }, [data, settled]);
}

/** The choices a language picker offers this account, in the server's order. */
export function useAgentLanguageChoices(session: Session): LanguageChoice[] {
  return useAgentLanguages(session).choices;
}
