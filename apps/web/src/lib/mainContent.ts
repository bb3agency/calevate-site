/**
 * The `id` every shell puts on its `<main>`, and the target of `SkipLink`.
 *
 * A constant rather than a literal in each shell because a skip link whose target `id` was
 * renamed is a skip link that silently does nothing — the anchor still renders, still
 * takes focus, and goes nowhere. It lives here, outside `components/ui.tsx`, because that
 * module is `"use client"`: a server component (the marketing shell) importing a constant
 * from it receives a client reference, not the string.
 */
export const MAIN_CONTENT_ID = "main-content";
