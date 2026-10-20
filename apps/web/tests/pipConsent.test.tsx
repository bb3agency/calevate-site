import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { PipSwitch } from "@/components/copilot/workspace/PipSwitch";
import { API_BASE, type Session } from "@/lib/api/client";
import type { PipConsent } from "@/lib/copilot/conversation";
import { useCopilotSurface, useCopilotSurfaceHolder } from "@/lib/copilot/registry";

import { expectNoA11yViolations } from "./a11y";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
}));

/**
 * D-788: Pip is off for a client account until its owner turns it on. The owner sees the
 * disclosure and one tick; everyone else sees who can turn it on; once it is on, a phone
 * number in a question goes out as typed and the old "take the personal details out"
 * refusal is gone. The real panel and hook run; only `fetch` is stubbed.
 */

const SESSION: Session = { orgSlug: "acme" };
const NUMBER = "8019857559";
const TEXT = "When Pip is on, what anyone on your team types to Pip is sent to the AI models.\n\nBy turning Pip on you confirm the business may share it.";

function consentOf(overrides: Partial<PipConsent>): PipConsent {
  return {
    status: "required",
    version: "1",
    text: TEXT,
    text_sha256: "a".repeat(64),
    can_accept: true,
    accepted_at: null,
    can_withdraw: false,
    withdrawn_at: null,
    ...overrides,
  };
}

let consent: PipConsent = consentOf({});
const consentBodies: unknown[] = [];
const askBodies: Record<string, unknown>[] = [];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

beforeEach(() => {
  consentBodies.length = 0;
  askBodies.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      if (path.startsWith("/v1/copilot/consent")) {
        consentBodies.push(JSON.parse(String(init?.body)));
        consent = consentOf({ status: "accepted", can_accept: false, accepted_at: "2026-10-15T05:00:00Z" });
        return json(consent, 201);
      }
      if (path.startsWith("/v1/copilot/conversation")) {
        return json({ turns: [], has_more: false, answering: false, uploads_available: false, consent });
      }
      if (path.startsWith("/v1/copilot/ask")) {
        askBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        const encoder = new TextEncoder();
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(encoder.encode('event: text\ndata: {"delta":"Calling them now."}\n\n'));
              controller.enqueue(encoder.encode('event: done\ndata: {"disclosure":null,"metered":true}\n\n'));
              controller.close();
            },
          }),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        );
      }
      throw new Error(`unexpected request: ${path}`);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function Screen() {
  useCopilotSurface({ route: "/c/acme/leads", title: "Leads", realm: "client", fields: [], apply: () => {} });
  return null;
}

function PanelMount() {
  const holder = useCopilotSurfaceHolder();
  if (holder === null) return null;
  return <CopilotPanel session={SESSION} holder={holder} realm="client" labelledBy="t-panel" />;
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <h2 id="t-panel">Pip</h2>
      <Screen />
      <PanelMount />
    </QueryClientProvider>,
  );
}

const askBox = () => screen.queryByLabelText("Your question about this screen");

describe("the owner turns Pip on", () => {
  it("shows the disclosure with the full pages, and nothing to ask with", async () => {
    consent = consentOf({});
    const { container } = renderPanel();

    await screen.findByText(/sent to the AI models/);
    expect(askBox()).toBeNull();
    for (const name of ["Privacy Policy", "Data Processing Addendum", "Sub-processors", "Terms of Service"]) {
      expect(screen.getByRole("link", { name })).toBeTruthy();
    }
    expect((screen.getByRole("button", { name: "Turn on Pip" }) as HTMLButtonElement).disabled).toBe(true);
    await expectNoA11yViolations(container, "Pip consent step for the owner");
  });

  it("records the version and hash it showed, then opens the ask box", async () => {
    consent = consentOf({});
    renderPanel();

    const tick = await screen.findByRole("checkbox", { name: /turning Pip on for everyone/ });
    fireEvent.click(tick);
    const button = screen.getByRole("button", { name: "Turn on Pip" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    await act(async () => {
      fireEvent.click(button);
    });

    await waitFor(() => expect(askBox()).not.toBeNull());
    expect(consentBodies).toEqual([{ version: "1", text_sha256: "a".repeat(64) }]);
  });

  it("asks again when the disclosure changed materially", async () => {
    consent = consentOf({ status: "outdated" });
    renderPanel();
    await screen.findByText("Pip needs turning on again");
    expect(askBox()).toBeNull();
  });
});

describe("a team member who is not the owner", () => {
  it("is told the owner turns Pip on, and is offered no checkbox", async () => {
    consent = consentOf({ can_accept: false });
    const { container } = renderPanel();

    await screen.findByText("Pip is off for this account");
    expect(screen.getByText(/The account owner needs to turn Pip on first/)).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(askBox()).toBeNull();
    await expectNoA11yViolations(container, "Pip locked for a team member");
  });
});

describe("once Pip is on", () => {
  it("sends a phone number as typed, with no refusal to take it out", async () => {
    consent = consentOf({ status: "accepted", can_accept: false });
    renderPanel();

    await waitFor(() => expect(askBox()).not.toBeNull());
    fireEvent.change(askBox()!, { target: { value: `ok call this number ${NUMBER}` } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    });

    await screen.findByText("Calling them now.");
    expect(askBodies[0]?.question).toBe(`ok call this number ${NUMBER}`);
    expect(screen.queryByText(/personal details out/i)).toBeNull();
    expect(screen.queryByText("Pip is off for this account")).toBeNull();
  });
});

describe("the owner turns Pip off (D-839)", () => {
  function renderSwitch() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <PipSwitch session={SESSION} />
      </QueryClientProvider>,
    );
  }

  function stubConsent(current: PipConsent, afterOff: PipConsent): string[] {
    const posts: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input).replace(API_BASE, "");
        if (init?.method === "POST" && path === "/v1/copilot/consent/withdraw") {
          posts.push(path);
          return json(afterOff, 201);
        }
        if (path === "/v1/copilot/consent") return json(current);
        throw new Error(`unexpected request: ${path}`);
      }),
    );
    return posts;
  }

  it("asks before turning Pip off, then shows it off with the way back on", async () => {
    const on = consentOf({ status: "accepted", can_accept: false, can_withdraw: true, accepted_at: "2026-10-15T05:00:00Z" });
    const off = consentOf({ status: "withdrawn", can_accept: true, withdrawn_at: "2026-10-20T05:00:00Z" });
    const posts = stubConsent(on, off);
    renderSwitch();

    fireEvent.click(await screen.findByRole("button", { name: "Turn Pip off" }));
    expect(posts).toEqual([]);
    const dialog = await screen.findByRole("dialog", { name: "Turn Pip off for everyone?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Turn Pip off" }));
    await waitFor(() => expect(posts).toEqual(["/v1/copilot/consent/withdraw"]));
    expect(await screen.findByText(/Turned off on/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Turn on Pip" })).toBeTruthy();
  });

  it("tells anyone but the owner who can turn it off", async () => {
    stubConsent(consentOf({ status: "accepted", can_accept: false, can_withdraw: false }), consentOf({}));
    renderSwitch();
    expect(await screen.findByText("Only the account owner can turn it off.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Turn Pip off" })).toBeNull();
  });
});
