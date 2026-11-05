/**
 * Ops > Call words (G-C2): the founder edits the words the call checks listen for.
 *
 *   GET /v1/ops/call-words        every word list, what is in force and what ships
 *   GET /v1/ops/call-words/{key}  one list and its history
 *   PUT /v1/ops/call-words/{key}  save it, or put the shipped list back (step-up)
 *
 * A save reaches every check within a minute, so it carries the `X-Confirm-Action` string
 * the server names in each entry's `confirmation`.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { adminSession, confirmedAdminRequest } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type CallWordsList = Schemas["CallWordsOut"];
export type CallWord = Schemas["CallWordOut"];
export type CallWordDetail = Schemas["CallWordDetailOut"];
export type CallWordValue = CallWord["value"];

export const CALL_WORDS_PATH = "/v1/ops/call-words";

/** Not org-scoped: the lists belong to the platform. */
export const callWordsKeys = {
  all: ["admin", "ops", "call-words"] as const,
  entry: (key: string) => ["admin", "ops", "call-words", key] as const,
};

export function useCallWords(enabled = true) {
  return useQuery({
    queryKey: callWordsKeys.all,
    queryFn: () => apiRequest<CallWordsList>(adminSession(), CALL_WORDS_PATH),
    enabled,
  });
}

export function useCallWord(key: string | null, enabled = true) {
  return useQuery({
    queryKey: callWordsKeys.entry(key ?? ""),
    queryFn: () =>
      apiRequest<CallWordDetail>(adminSession(), `${CALL_WORDS_PATH}/${encodeURIComponent(key ?? "")}`),
    enabled: enabled && key !== null,
  });
}

export interface CallWordChange {
  key: string;
  /** The whole list in its shipped shape; null puts the shipped list back. */
  value: CallWordValue | null;
  note: string;
  /** The server's own `confirmation`, echoed back. */
  confirmation: string;
}

export function useChangeCallWord() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value, note, confirmation }: CallWordChange) =>
      confirmedAdminRequest<CallWordDetail>(
        `${CALL_WORDS_PATH}/${encodeURIComponent(key)}`,
        {
          method: "PUT",
          body: { value, note: note.trim() ? note.trim() : null },
          confirmAction: confirmation,
        },
        "Changing the words the call checks listen for.",
      ),
    onSuccess: (detail) => {
      client.setQueryData(callWordsKeys.entry(detail.key), detail);
      void client.invalidateQueries({ queryKey: callWordsKeys.all, exact: true });
    },
  });
}

/**
 * The entry as the editor's one text box holds it: a pattern as it is, a list one word per
 * line, a table as JSON. `textToValue` is its inverse for the entry's shape.
 */
export function valueToText(shape: CallWord["shape"], value: CallWordValue): string {
  if (shape === "pattern") return typeof value === "string" ? value : "";
  if (shape === "list") return Array.isArray(value) ? value.join("\n") : "";
  return JSON.stringify(value, null, 2);
}

export type ParsedValue = { ok: true; value: CallWordValue } | { ok: false; reason: string };

export function textToValue(shape: CallWord["shape"], text: string): ParsedValue {
  if (shape === "pattern") return { ok: true, value: text.trim() };
  if (shape === "list") {
    // A blank line inside a list keeps its place (some lists are read by position); blank
    // lines at the end are only the editor's.
    const lines = text.split("\n").map((line) => line.trim());
    while (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
    return { ok: true, value: lines };
  }
  try {
    const parsed: unknown = JSON.parse(text);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, reason: "A table is written as { \"language\": … }." };
    }
    return { ok: true, value: parsed as CallWordValue };
  } catch {
    return { ok: false, reason: "This is not valid JSON. Check the quotes, commas and brackets." };
  }
}

/** Which part of the product reads a group of lists, in the founder's words. */
export const GROUP_LABELS: Readonly<Record<string, string>> = {
  turn_checks: "Mistakes on real calls",
  detection: "Questions to answer",
  call_language: "Language of a call summary",
  offline_extractor: "Reading details without the AI model",
  optout: "Do not call me again",
  opening_notices: "AI and recording notices",
  script_lint: "Script checks",
  teach_questions: "Setup questions",
  test_conversations: "Practice runs",
};
