import type { CopilotNotes } from "@/lib/copilot/notes";

const NOTHING_NOTICED: CopilotNotes = { notes: [], unread: 0 };

/**
 * Pip's notes (D-936) answered "nothing noticed", for the panel tests that stub `fetch`
 * by hand rather than through the harness (which answers the same by default). The panel
 * reads the notes on open and says so when that read fails, so a stub that throws on the
 * route would put a refusal on screen that the test is not about.
 */
export function nothingNoticed(path: string): Response | null {
  if (!/^\/v1\/(admin\/)?copilot\/notes(\?|$)/.test(path)) return null;
  return new Response(JSON.stringify(NOTHING_NOTICED), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}
