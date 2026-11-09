import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { API_BASE, type Session } from "@/lib/api/client";
import { useCopilotSurface, useCopilotSurfaceHolder } from "@/lib/copilot/registry";

import { expectNoA11yViolations } from "./a11y";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
}));

/**
 * Pip's empty panel (founder, 9 Nov 2026: "just see how chatgpt homepage looks like,
 * simple"): one question, at most three suggestions, and the ask box. Rendered beside the
 * agent's Script tab, the screen the founder was on: it autosaves a draft and has fields,
 * which is what used to add the drafts paragraph.
 */

const SESSION: Session = { orgSlug: "acme" };

function stubFetch(): string[] {
  const paths: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input).replace(API_BASE, "");
      paths.push(path);
      const body = path.startsWith("/v1/copilot/conversation")
        ? { turns: [], has_more: false, answering: false, uploads_available: true }
        : { title: "Not found", status: 404 };
      return new Response(JSON.stringify(body), {
        status: path.startsWith("/v1/copilot/conversation") ? 200 : 404,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  return paths;
}

function ScriptScreen() {
  useCopilotSurface({
    route: "/c/{slug}/agents/{agentId}/script",
    title: "Agent: script",
    realm: "client",
    fields: [{ id: "opening", label: "Opening line", type: "textarea", value: "" }],
    saves: "autosave",
    liveStep: "Put it live",
    apply: () => undefined,
  });
  return null;
}

function PanelMount({ request }: { request?: { prompt: string; nonce: number } }) {
  const holder = useCopilotSurfaceHolder();
  if (holder === null) return null;
  return (
    <CopilotPanel
      session={SESSION}
      holder={holder}
      realm="client"
      placement="side"
      labelledBy="pip-title"
      onClose={() => undefined}
      request={request ?? null}
    />
  );
}

function renderPanel(request?: { prompt: string; nonce: number }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ScriptScreen />
      <PanelMount request={request} />
    </QueryClientProvider>,
  );
}

describe("Pip's empty panel", () => {
  it("shows one question, at most three suggestions and the ask box, and nothing else", async () => {
    const paths = stubFetch();
    const { container } = renderPanel();
    const panel = await screen.findByRole("dialog");

    expect(await within(panel).findByText("What can I help with?")).toBeTruthy();
    const chips = within(panel).getByRole("region", { name: "Questions you could ask" });
    const asked = within(chips).getAllByRole("button");
    expect(asked.length).toBeGreaterThan(0);
    expect(asked.length).toBeLessThanOrEqual(3);
    expect(within(panel).getByRole("textbox")).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Ask" })).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Attach files" })).toBeTruthy();

    // Gone: the drafts and undo paragraph, the keyboard hint, the screen's model-facing
    // title, and Pip's notes (which live on the dashboard now and are not even read here).
    const text = panel.textContent ?? "";
    expect(text).not.toMatch(/saved as a draft/i);
    expect(text).not.toMatch(/Small changes happen at once/);
    expect(text).not.toMatch(/Enter to send/);
    expect(text).not.toMatch(/Agent: script/);
    expect(within(panel).queryByRole("region", { name: /noticed/ })).toBeNull();
    expect(paths.some((p) => p.startsWith("/v1/copilot/notes"))).toBe(false);

    // The keys are still told to a screen reader.
    const box = within(panel).getByRole("textbox");
    const described = (box.getAttribute("aria-describedby") ?? "")
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ");
    expect(described).toMatch(/Enter sends/);

    await expectNoA11yViolations(container, "Pip's empty panel");
  });

  it("still puts a screen's request in the box without sending it", async () => {
    const paths = stubFetch();
    renderPanel({ prompt: "Draft the whole script for this agent.", nonce: 1 });
    const box = await screen.findByRole("textbox");
    await waitFor(() => expect((box as HTMLTextAreaElement).value).toBe("Draft the whole script for this agent."));
    expect(paths.some((p) => p.startsWith("/v1/copilot/ask"))).toBe(false);
  });
});
