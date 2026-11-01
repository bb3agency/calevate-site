"use client";

import { useSearchParams } from "next/navigation";

import { KnowledgeScreen } from "./KnowledgeScreen";

/**
 * The route is chrome and nothing else (UX-DOCTRINE §6): a page module may export only
 * `default` (D-196), so the screen it mounts is where the work lives.
 *
 * Keyed on the query string because the screen seeds its tab and focused question from
 * `?tab=` and `?question=` once, at mount: a Pip link to `?question=…` followed while this
 * screen is showing would change the URL and leave the view where it was.
 */
export default function KnowledgePage() {
  const query = useSearchParams().toString();
  return <KnowledgeScreen key={query} />;
}
