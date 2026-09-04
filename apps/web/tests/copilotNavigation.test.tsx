import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { CopilotDock } from "@/components/copilot/CopilotDock";
import { MAIN_CONTENT_ID } from "@/components/ui";
import { API_BASE, type Session } from "@/lib/api/client";
import { resolveDestination } from "@/lib/copilot/navigate";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { unsavedWork } from "@/lib/copilot/unsaved";
import { noFill, type CopilotSurface } from "@/lib/copilot/types";

/**
 * THE ASSISTANT TAKES SOMEBODY TO A SCREEN — the browser's half of D-524.
 *
 * The client asked "take me to billing page" and was told "I cannot take you to the billing
 * page". The server now decides the destination; this file is about the two things only this
 * side can get right:
 *
 * 1. **A route the console does not have never reaches the router.** The frame carries a
 *    template and it is resolved against `lib/clientNav.ts` — the same list the sidebar
 *    renders — so an absolute URL, a protocol-relative one or a path nobody has moves nobody.
 * 2. **Unsaved work is asked about first.** The server knows a form exists; only the browser
 *    knows whether it is dirty, and the answer when it cannot tell is to ask.
 *
 * Everything drives the REAL dock, the REAL panel and the REAL conversation hook. Only
 * `fetch` and the router are replaced.
 */

const nav = vi.hoisted(() => ({ pathname: "/c/acme/leads", pushed: [] as string[] }));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: (path: string) => nav.pushed.push(path),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const SESSION: Session = { orgSlug: "acme" };

/** The frame the server sends for "take me to billing". Every string is its own. */
const TO_CREDITS = {
  tool: "open_screen",
  screen: "Calling credit",
  route: "/c/{slug}/credits",
  where: "Calling credit, under Settings & account in the left sidebar",
  detail: "Opening Calling credit, under Settings & account in the left sidebar.",
  reversal: "Your browser's back button brings you back to this screen.",
};

function sse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );
}

/** An answer that opens a screen: the model's sentence, the frame, then `done`. */
function navigationChunks(frame: Record<string, unknown> = TO_CREDITS): string[] {
  return [
    'event: text\ndata: {"delta":"Opening Calling credit for you."}\n\n',
    `event: navigate\ndata: ${JSON.stringify(frame)}\n\n`,
    'event: done\ndata: {"disclosure":null,"metered":true}\n\n',
  ];
}

function stubAsk(chunks: string[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input).replace(API_BASE, "");
      if (path.startsWith("/v1/copilot/ask")) return sse(chunks);
      throw new Error(`unexpected request: ${path}`);
    }),
  );
}

/** A screen that declares itself however this test needs, beside the real dock. */
function Mount({ surface, children }: { surface: CopilotSurface | null; children?: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      {/* The skip-link target the shells give every screen, and what a copilot navigation
          moves focus to. Present here for the same reason it is present there. */}
      <main id={MAIN_CONTENT_ID} tabIndex={-1} />
      <Declare surface={surface} />
      {children}
      <CopilotDock
        session={SESSION}
        realm="client"
        navigation={{ slug: "acme", href: (path) => path }}
      />
    </QueryClientProvider>
  );
}

function Declare({ surface }: { surface: CopilotSurface | null }) {
  useCopilotSurface(surface);
  return null;
}

const READ_ONLY: CopilotSurface = {
  route: "/c/{slug}/leads",
  title: "Leads",
  realm: "client",
  fields: [],
  apply: noFill,
};

const HAS_A_FORM: CopilotSurface = {
  route: "/c/{slug}/agents/new",
  title: "Build an agent",
  realm: "client",
  fields: [{ id: "a-name", label: "Agent name", type: "text", value: "" }],
  apply: noFill,
};

async function openDock() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Ask about this screen" }));
  });
}

async function ask(question: string) {
  fireEvent.change(screen.getByLabelText("Your question about this screen"), {
    target: { value: question },
  });
  await act(async () => {
    fireEvent.submit(screen.getByRole("button", { name: "Ask" }).closest("form")!);
  });
}

async function askToBeTaken(surface: CopilotSurface, chunks = navigationChunks()) {
  nav.pushed.length = 0;
  stubAsk(chunks);
  render(<Mount surface={surface} />);
  await openDock();
  await ask("take me to billing page");
}

// --- where the assistant is allowed to send somebody -------------------------------------

describe("resolving a destination", () => {
  it("substitutes the slug and returns an in-app path", () => {
    expect(resolveDestination("/c/{slug}/credits", "acme")).toBe("/c/acme/credits");
    expect(resolveDestination("/c/{slug}", "acme")).toBe("/c/acme");
    expect(resolveDestination("/c/{slug}/settings/team", "acme")).toBe("/c/acme/settings/team");
  });

  it("REFUSES ANYTHING THAT IS NOT A SCREEN THIS CONSOLE HAS", () => {
    // The open-redirect test on this side. `//evil.example` is the one that matters: it
    // looks like a path and is a different ORIGIN, and a `router.push` of it leaves the
    // product. Membership of `clientNavigation()` is what makes the class unreachable
    // rather than filtered — none of these is one of its 28 constants.
    expect(resolveDestination("//evil.example", "acme")).toBeNull();
    expect(resolveDestination("https://evil.example/c/{slug}/credits", "acme")).toBeNull();
    expect(resolveDestination("/c/{slug}/../../admin/ops", "acme")).toBeNull();
    expect(resolveDestination("/c/{slug}/not-a-screen", "acme")).toBeNull();
    expect(resolveDestination("/admin/ops", "acme")).toBeNull();
    // A path with the slug already substituted is not a template and is refused too: the
    // wire's contract is the template, and accepting both would be two ways in.
    expect(resolveDestination("/c/acme/credits", "acme")).toBeNull();
  });
});

// --- would leaving throw work away? -------------------------------------------------------

describe("unsaved work", () => {
  it("lets a read-only screen through — which is most of the console", () => {
    expect(unsavedWork(READ_ONLY, 0).ask).toBe(false);
  });

  it("ASKS when the screen has a form and has not said whether it is dirty", () => {
    // The conservative reading, and the whole point of the module: asking when there was
    // nothing to lose costs a click, not asking when there was costs the work.
    const verdict = unsavedWork(HAS_A_FORM, 0);
    expect(verdict.ask).toBe(true);
    expect(verdict.reason).toContain("hasn't been saved");
  });

  it("BELIEVES A SCREEN THAT DECLARES ITSELF, in both directions", () => {
    expect(unsavedWork({ ...HAS_A_FORM, unsaved: false }, 0).ask).toBe(false);
    expect(unsavedWork({ ...READ_ONLY, unsaved: true }, 0).ask).toBe(true);
  });

  it("asks on a screen that never described itself, because that is the one state nothing can rule out", () => {
    expect(unsavedWork({ ...READ_ONLY, undeclared: true }, 0).ask).toBe(true);
  });

  it("ASKS WHEN THE ASSISTANT ITSELF JUST FILLED THE FORM, whatever the screen says", () => {
    // Certain rather than cautious: those values are unsaved by construction, and an
    // assistant that filled a form and then navigated away would have undone its own answer.
    const verdict = unsavedWork({ ...HAS_A_FORM, unsaved: false }, 3);
    expect(verdict.ask).toBe(true);
    expect(verdict.reason).toContain("3 fields");
  });
});

// --- the whole seam, through the real dock ------------------------------------------------

describe('"take me to billing page"', () => {
  it("OPENS CALLING CREDIT, says so, and announces where it went", async () => {
    await askToBeTaken(READ_ONLY);

    expect(nav.pushed).toEqual(["/c/acme/credits"]);
    // The receipt, in the server's own words — and no route path anywhere a person reads.
    expect(screen.getByText(TO_CREDITS.detail)).toBeTruthy();
    expect(screen.getByText(TO_CREDITS.reversal)).toBeTruthy();
    expect(document.body.textContent).not.toContain("/c/acme/credits");
    // WHAT A SCREEN-READER USER HEARS. Nothing else in this console announces a route
    // change, so a move nobody clicked for has to say where it went.
    expect(screen.getByText("Opened Calling credit, under Settings & account in the left sidebar.")).toBeTruthy();
    // …and where the caret is when they get there: the skip-link target, not the sidebar.
    // One frame, because the focus move waits for the router's own commit rather than
    // guessing a delay — see `CopilotDock`.
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
    });
    expect(document.activeElement?.id).toBe(MAIN_CONTENT_ID);
  });

  it("ASKS FIRST when the screen has a form on it, and STAYING moves nobody", async () => {
    await askToBeTaken(HAS_A_FORM);

    expect(nav.pushed).toEqual([]);
    expect(screen.getByRole("dialog", { name: "Open Calling credit?" })).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Stay here" }));
    });
    expect(nav.pushed).toEqual([]);
    // The receipt goes with the refusal: "Opening Calling credit" stops being true the
    // moment they say no.
    expect(screen.queryByText(TO_CREDITS.detail)).toBeNull();
  });

  it("moves them when they answer the question with yes", async () => {
    await askToBeTaken(HAS_A_FORM);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Open Calling credit" }));
    });
    expect(nav.pushed).toEqual(["/c/acme/credits"]);
  });

  it("MOVES NOBODY when the destination is not a screen this console has", async () => {
    // Belt to the server's braces. Nothing is shown about it: the answer beside it has
    // already named the screen in words, and a person who did nothing wrong should not be
    // handed a defect message.
    // Template-SHAPED, so it gets past the cheap guard and has to be refused by membership
    // of the console's own nav list — which is the check that carries the property.
    await askToBeTaken(
      READ_ONLY,
      navigationChunks({ ...TO_CREDITS, route: "/c/{slug}/../../admin/ops" }),
    );
    expect(nav.pushed).toEqual([]);
  });

  it("does not move anybody before the answer has finished arriving", async () => {
    // The frame arrives BEFORE the model's closing sentence. Navigating on receipt would
    // close the panel, abort the stream, and lose the sentence the person was charged for.
    nav.pushed.length = 0;
    let release: (() => void) | null = null;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const encoder = new TextEncoder();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(
          new ReadableStream<Uint8Array>({
            async start(controller) {
              controller.enqueue(encoder.encode(`event: navigate\ndata: ${JSON.stringify(TO_CREDITS)}\n\n`));
              await held;
              controller.enqueue(
                encoder.encode('event: done\ndata: {"disclosure":null,"metered":true}\n\n'),
              );
              controller.close();
            },
          }),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        );
      }),
    );
    render(<Mount surface={READ_ONLY} />);
    await openDock();
    const asked = ask("take me to billing page");
    await act(async () => {
      await Promise.resolve();
    });
    expect(nav.pushed).toEqual([]);
    release!();
    await asked;
    expect(nav.pushed).toEqual(["/c/acme/credits"]);
  });
});
