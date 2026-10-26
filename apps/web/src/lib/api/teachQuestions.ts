"use client";

/**
 * Questions to answer (D-893, `apps/api/teach/questions.py`): what callers asked that no
 * agent knew, what practice callers need, and what setup leaves open, one list, most asked
 * first. A draft answer comes with its source; a question whose draft is being written says
 * `drafting`, and the list looks again shortly until it is written.
 *
 * Answering saves a fact every agent uses on its next call and closes the topic's gaps, so
 * it touches the facts, the gaps, the struggles list, readiness and the practice run's
 * "Add your prices first" note: all are refreshed after.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { livePoll } from "@/lib/live/liveStatus";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type TeachQuestion = Schemas["TeachQuestionOut"];
export type TeachQuestions = Schemas["TeachQuestionsOut"];
export type QuestionSettled = Schemas["QuestionSettledOut"];

/** The topic key of the question practice callers need (prices), used by "Add prices" links. */
export const PRICES_QUESTION = "pricing";

/** The query a link sets to open the Questions to answer list on one question. */
export const QUESTION_PARAM = "question";
/** The Knowledge page's query for its Questions to answer view, with no one question. */
export const QUESTIONS_TAB = "tab=questions";

/** The Knowledge page's Questions to answer view, open on `key` when one is named. */
export function knowledgeQuestionsHref(slug: string, key?: string | null): string {
  return `/c/${slug}/knowledge?${key ? `${QUESTION_PARAM}=${encodeURIComponent(key)}` : QUESTIONS_TAB}`;
}

export function teachQuestionsKey(slug: string, agentId?: string) {
  return ["teach-questions", slug, agentId ?? "all"] as const;
}

/** How soon to look again while a draft is being written. */
const DRAFTING_POLL_MS = 4_000;

export function useTeachQuestions(
  session: Session,
  agentId?: string,
): UseQueryResult<TeachQuestions> {
  const query = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
  return useQuery({
    queryKey: teachQuestionsKey(session.orgSlug, agentId),
    queryFn: () => apiRequest<TeachQuestions>(session, `/v1/teach/questions${query}`),
    // While a draft is being written, look every few seconds when the live stream is down;
    // when it is up, the worker's write announces itself (`teach_questions` is a
    // `knowledge_gaps` table in `apps/api/live/topics.py`).
    refetchInterval: livePoll((q: { state: { data?: TeachQuestions } }) =>
      q.state.data?.items.some((item) => item.drafting) ? DRAFTING_POLL_MS : 60_000,
    ),
  });
}

/** Every read a settled question changes. */
const AFTER_SETTLE = [
  "teach-questions",
  "knowledge-gaps",
  "kb-knows",
  "kb",
  "readiness",
  "script-tests",
  "dashboard",
] as const;

export function refreshAfterSettle(client: QueryClient, slug: string): void {
  for (const family of AFTER_SETTLE) void client.invalidateQueries({ queryKey: [family, slug] });
}

/** Take `key` out of every cached list at once; the snapshot puts it back on failure. */
function dropQuestion(client: QueryClient, slug: string, key: string) {
  const snapshot = client.getQueriesData<TeachQuestions>({ queryKey: ["teach-questions", slug] });
  for (const [queryKey, list] of snapshot) {
    if (!list) continue;
    const items = list.items.filter((item) => item.key !== key);
    if (items.length !== list.items.length) {
      client.setQueryData<TeachQuestions>(queryKey, { items, open_count: items.length });
    }
  }
  return snapshot;
}

function useSettle<V extends { key: string }>(
  session: Session,
  send: (vars: V) => Promise<QuestionSettled>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationKey: ["teach-question-settle", session.orgSlug],
    mutationFn: send,
    onMutate: async (vars: V) => {
      await client.cancelQueries({ queryKey: ["teach-questions", session.orgSlug] });
      return { snapshot: dropQuestion(client, session.orgSlug, vars.key) };
    },
    onError: (_error, _vars, context) => {
      context?.snapshot.forEach(([queryKey, list]) => client.setQueryData(queryKey, list));
    },
    onSettled: () => refreshAfterSettle(client, session.orgSlug),
  });
}

export function useAnswerQuestion(session: Session) {
  return useSettle(session, ({ key, answer }: { key: string; answer: string }) =>
    apiRequest<QuestionSettled>(
      session,
      `/v1/teach/questions/${encodeURIComponent(key)}/answer`,
      { method: "POST", body: { answer } },
    ),
  );
}

export function useDismissQuestion(session: Session) {
  return useSettle(session, ({ key, reason }: { key: string; reason: string | null }) =>
    apiRequest<QuestionSettled>(
      session,
      `/v1/teach/questions/${encodeURIComponent(key)}/dismiss`,
      { method: "POST", body: { reason } },
    ),
  );
}
