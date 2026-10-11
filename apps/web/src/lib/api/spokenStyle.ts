/**
 * Ops > Spoken style (D-744): the founder reviews how agents speak each language.
 *
 *   GET  /v1/ops/spoken-style                     every language: review state and counts
 *   GET  /v1/ops/spoken-style/{language}          one language, entry by entry
 *   POST /v1/ops/spoken-style/{language}/entries  approve, edit, add or retire one entry
 *   POST /v1/ops/spoken-style/{language}/publish  publish to every live agent (step-up)
 *
 * An entry change only touches the working copy; publishing is what reaches callers, so it
 * alone carries the `X-Confirm-Action` string the server names in `publish_confirmation`.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type SpokenStyleList = Schemas["SpokenStyleOut"];
export type LanguageSummary = Schemas["LanguageSummaryOut"];
export type LanguageStyle = Schemas["LanguageOut"];
export type StyleEntry = Schemas["EntryOut"];
export type StyleValue = Schemas["EntryValue"];
export type EntryKind = StyleEntry["kind"];
export type EntryAction = Schemas["EntryChangeIn"]["action"];

export const SPOKEN_STYLE_PATH = "/v1/ops/spoken-style";

/** Not org-scoped: the table belongs to the platform, not to a client. */
export const spokenStyleKeys = {
  all: ["admin", "ops", "spoken-style"] as const,
  language: (tag: string) => ["admin", "ops", "spoken-style", tag] as const,
};

export function useSpokenStyles(enabled = true) {
  return useQuery({
    queryKey: spokenStyleKeys.all,
    queryFn: () => apiRequest<SpokenStyleList>(adminSession(), SPOKEN_STYLE_PATH),
    enabled,
  });
}

export function useSpokenStyle(tag: string | null, enabled = true) {
  return useQuery({
    queryKey: spokenStyleKeys.language(tag ?? ""),
    queryFn: () =>
      apiRequest<LanguageStyle>(adminSession(), `${SPOKEN_STYLE_PATH}/${encodeURIComponent(tag ?? "")}`),
    enabled: enabled && tag !== null,
  });
}

export interface EntryChange {
  kind: EntryKind;
  action: EntryAction;
  key?: string | null;
  value?: StyleValue | null;
}

function useLanguageWrite<I>(tag: string, send: (input: I) => Promise<LanguageStyle>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: (view) => {
      client.setQueryData(spokenStyleKeys.language(tag), view);
      void client.invalidateQueries({ queryKey: spokenStyleKeys.all, exact: true });
    },
  });
}

export function useChangeEntry(tag: string) {
  return useLanguageWrite(tag, (change: EntryChange) =>
    apiRequest<LanguageStyle>(
      adminSession(),
      `${SPOKEN_STYLE_PATH}/${encodeURIComponent(tag)}/entries`,
      { method: "POST", body: change },
    ),
  );
}

export interface PublishInput {
  reviewerName: string;
  note: string;
  /** The server's own `publish_confirmation`, echoed back. */
  confirmation: string;
}

export function usePublishSpokenStyle(tag: string) {
  return useLanguageWrite(tag, ({ reviewerName, note, confirmation }: PublishInput) =>
    apiRequest<LanguageStyle>(
      adminSession(),
      `${SPOKEN_STYLE_PATH}/${encodeURIComponent(tag)}/publish`,
      {
        method: "POST",
        body: { reviewer_name: reviewerName, note: note.trim() ? note.trim() : null },
        confirmAction: confirmation,
      },
    ),
  );
}

/** What each kind of entry is, in the reviewer's words, in the order the screen lists them. */
export const KIND_LABELS: Record<EntryKind, { title: string; hint: string }> = {
  register: {
    title: "How the language is spoken",
    hint: "The one line every agent in this language carries.",
  },
  swap: {
    title: "Formal word, and what people say",
    hint: "Ticked ones go into every agent's instructions; all of them guide the script writer and the tests.",
  },
  filler: {
    title: "Tags and fillers",
    hint: "Spoken tags and light fillers, used where they help.",
  },
  number_rule: {
    title: "Numbers, prices and times",
    hint: "How a number is written so the voice says it the way people do.",
  },
  punctuation: {
    title: "Writing for a voice",
    hint: "Sentence and punctuation rules the voice depends on.",
  },
  example: {
    title: "Example exchanges",
    hint: "How a call sounds for each business type. Style only, never facts.",
  },
  opening: {
    title: "Opening lines",
    hint: "A new agent's greeting. {business} becomes the business's name.",
  },
};

export const KIND_ORDER: EntryKind[] = [
  "register",
  "swap",
  "filler",
  "number_rule",
  "punctuation",
  "example",
  "opening",
];

/** Kinds a reviewer may add to; the others exist once per language and are edited. */
export const ADDABLE_KINDS: ReadonlySet<EntryKind> = new Set<EntryKind>([
  "swap",
  "filler",
  "number_rule",
  "punctuation",
  "example",
]);

/** "Reviewed by Sri on 11 Oct 2026", or null before anything was published. */
export function reviewStamp(view: Pick<LanguageSummary, "reviewed_by" | "reviewed_on">): string | null {
  if (!view.reviewed_by || !view.reviewed_on) return null;
  const date = new Date(`${view.reviewed_on}T00:00:00+05:30`);
  const shown = Number.isNaN(date.getTime())
    ? view.reviewed_on
    : date.toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "Asia/Kolkata",
      });
  return `Reviewed by ${view.reviewed_by} on ${shown}`;
}

/** The entry's value as one line of text, for the list. */
export function entrySummary(kind: EntryKind, value: StyleValue | null | undefined): string {
  if (!value) return "";
  if (kind === "swap") return `${value.formal ?? ""} → ${value.spoken ?? ""}`;
  if (kind === "example") {
    return (value.turns ?? [])
      .map((turn) => `${turn.speaker === "agent" ? "Agent" : "Caller"}: ${turn.text}`)
      .join("\n");
  }
  if (kind === "filler" && value.use) return `${value.text ?? ""} (${value.use})`;
  return value.text ?? "";
}
