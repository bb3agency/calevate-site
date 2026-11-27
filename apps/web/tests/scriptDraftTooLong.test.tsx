/**
 * A Pip draft whose Keep is refused as too long for calls (founder, 27 Nov 2026: the owner
 * read the button's "Try again" as "ask Pip again" and kept pressing it). A refusal another
 * press cannot cure never wears "Try again"; a too-long draft offers a shorter one instead.
 * And the script's length against its target, on the campaign and line script screens.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActionButton } from "@/components/arc/feedback";
import { SHORTER_ASK, ScriptDraftLive } from "@/components/scriptDraft/ScriptDraftLive";
import { ScriptSizeMeter, scriptSizeOf } from "@/components/scriptDraft/ScriptSizeMeter";
import { API_BASE, type Session } from "@/lib/api/client";
import type { DraftChange } from "@/lib/scriptDraft/stream";

import { expectNoA11yViolations } from "./a11y";

const SESSION: Session = { orgSlug: "acme" };

afterEach(() => {
  vi.unstubAllGlobals();
});

const CHANGES: DraftChange[] = [
  { path: "opening_line", label: "Opening line", op: "changed", before: "Hello.", after: "Namaste, Sunrise Homes here." },
];

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

const READY = [
  frame("phase", { phase: "writing", detail: null }),
  frame("phase", { phase: "ready", detail: null }),
  frame("diff", { changes: CHANGES, proposal_id: "p1" }),
];

const TOO_LONG = {
  type: "urn:calevate:business_rule/engine_prompt_too_long",
  title: "This script is too long for the calling system",
  detail: "Your script is 412 characters too long for the calling system; shorten it to put it live.",
  kind: "business_rule",
  retryable: false,
};

const UNAVAILABLE = {
  type: "urn:calevate:dependency/engine_unavailable",
  title: "Calls are not answering",
  detail: "We could not reach the calling system.",
  kind: "dependency",
  retryable: true,
};

type Sent = { method: string; path: string; body: unknown };

/** The draft stream and routes for one holder; keep-live answers `keepReply`. */
function stubRoutes(keepReply: () => Response) {
  const sent: Sent[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      const method = init?.method ?? "GET";
      sent.push({ method, path, body: typeof init?.body === "string" ? JSON.parse(init.body) : null });
      if (path.endsWith("/script-draft/stream")) {
        const encoder = new TextEncoder();
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              for (const event of READY) controller.enqueue(encoder.encode(event));
              controller.close();
            },
          }),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        );
      }
      if (path.endsWith("/keep-live")) return keepReply();
      if (method === "DELETE") return new Response(null, { status: 204 });
      if (method === "POST" && path.endsWith("/proposal")) return json({ id: "p2", status: "drafting" }, 202);
      return json({});
    }),
  );
  return sent;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": status < 300 ? "application/json" : "application/problem+json" },
  });

function withQuery(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Buttons showing their error face with "Try again" on it (every face is in the DOM; only the status picks one). */
function wearingTryAgain(container: HTMLElement): string[] {
  return [...container.querySelectorAll<HTMLButtonElement>('button[data-status="error"]')]
    .filter((button) => button.textContent?.includes("Try again"))
    .map((button) => button.getAttribute("aria-label") ?? button.textContent ?? "");
}

async function pressKeep(holder: { kind: "campaign" | "inbound_line"; id: string }) {
  const { container } = render(withQuery(<ScriptDraftLive session={SESSION} holder={holder} proposalId="p1" />));
  const keep = await screen.findByRole("button", { name: "Keep" });
  await act(async () => {
    fireEvent.click(keep);
  });
  return container;
}

describe("Keep refused as too long", () => {
  it("never shows Try again, and offers a shorter draft and Discard instead of Keep", async () => {
    stubRoutes(() => json(TOO_LONG, 422));
    const container = await pressKeep({ kind: "campaign", id: "c1" });
    expect(await screen.findByRole("heading", { name: "Too long for calls" })).toBeTruthy();
    expect(wearingTryAgain(container)).toEqual([]);
    expect(screen.queryByRole("button", { name: "Keep" })).toBeNull();
    expect(screen.getByRole("button", { name: "Ask Pip for a shorter one" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Discard" })).toBeTruthy();
    // The measured sentence is behind Why, not in the main line; no code anywhere.
    expect(screen.getByText("This draft is longer than a call can take, so it cannot go live.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Why" })).toBeTruthy();
    expect(screen.getByText(TOO_LONG.detail)).toBeTruthy();
    expect(container.textContent).not.toContain("engine_prompt_too_long");
    await expectNoA11yViolations(container, "script draft too long");
  });

  it("the shorter draft is a new request for the whole script, which replaces this one", async () => {
    const sent = stubRoutes(() => json(TOO_LONG, 422));
    await pressKeep({ kind: "campaign", id: "c1" });
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Ask Pip for a shorter one" }));
    });
    const asked = sent.filter((s) => s.method === "POST" && s.path === "/v1/campaigns/c1/script/proposal");
    expect(asked).toHaveLength(1);
    expect(asked[0].body).toEqual(SHORTER_ASK);
    // Asking does not keep or discard anything first.
    expect(sent.filter((s) => s.path.endsWith("/keep-live"))).toHaveLength(1);
    expect(sent.some((s) => s.method === "DELETE")).toBe(false);
  });

  it("Discard still discards the draft", async () => {
    const sent = stubRoutes(() => json(TOO_LONG, 422));
    await pressKeep({ kind: "campaign", id: "c1" });
    await screen.findByRole("heading", { name: "Too long for calls" });
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Discard" }));
    });
    expect(sent.some((s) => s.method === "DELETE" && s.path === "/v1/campaigns/c1/script/proposal/p1")).toBe(true);
    expect(await screen.findByText("Discarded. Your script stays as it was.")).toBeTruthy();
  });

  it("an Inbound line asks through its own request route", async () => {
    const sent = stubRoutes(() => json(TOO_LONG, 422));
    await pressKeep({ kind: "inbound_line", id: "l1" });
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Ask Pip for a shorter one" }));
    });
    expect(sent.some((s) => s.method === "POST" && s.path === "/v1/inbound-lines/l1/proposal")).toBe(true);
  });
});

describe("other refusals of Keep", () => {
  it("a failure a retry can cure keeps Try again on Keep", async () => {
    stubRoutes(() => json(UNAVAILABLE, 503));
    await pressKeep({ kind: "campaign", id: "c1" });
    const keep = await screen.findByRole("button", { name: "Keep" });
    await vi.waitFor(() => expect(keep.getAttribute("data-status")).toBe("error"));
    expect(keep.textContent).toContain("Try again");
    expect(screen.queryByRole("heading", { name: "Too long for calls" })).toBeNull();
  });

  it("a final refusal that is not about length keeps Keep's own label", async () => {
    stubRoutes(() =>
      json({ type: "urn:calevate:conflict/draft_not_ready", detail: "Not this draft.", kind: "conflict", retryable: false }, 409),
    );
    await pressKeep({ kind: "campaign", id: "c1" });
    const keep = await screen.findByRole("button", { name: "Keep" });
    await vi.waitFor(() => expect(keep.getAttribute("data-status")).toBe("error"));
    expect(keep.textContent).not.toContain("Try again");
  });
});

describe("ActionButton's error face", () => {
  it("says Try again only while a retry could help", () => {
    const { rerender } = render(<ActionButton status="error">Save</ActionButton>);
    expect(screen.getByRole("button", { name: "Save" }).textContent).toContain("Try again");
    rerender(
      <ActionButton status="error" retryable={false}>
        Save
      </ActionButton>,
    );
    expect(screen.getByRole("button", { name: "Save" }).textContent).not.toContain("Try again");
  });
});

describe("the script's length", () => {
  it("hides when the server sends no size, or one it cannot read", () => {
    expect(scriptSizeOf(undefined)).toBeNull();
    expect(scriptSizeOf({ size: null })).toBeNull();
    expect(scriptSizeOf({ size: { script_chars: 10 } })).toBeNull();
    expect(scriptSizeOf({ size: { script_chars: 10, target_chars: 0, limit_chars: 8000 } })).toBeNull();
    expect(scriptSizeOf({ size: { script_chars: 6812, target_chars: 7000, limit_chars: 8000 } })).toEqual({
      chars: 6812,
      target_chars: 7000,
      limit_chars: 8000,
    });
  });

  it("reads as one line against the target, with the call's limit behind a tap", () => {
    render(<ScriptSizeMeter size={{ chars: 6812, target_chars: 7000, limit_chars: 8000 }} />);
    const meter = within(screen.getByTestId("script-size"));
    expect(meter.getByText("Length: about 6,800 of 7,000 characters")).toBeTruthy();
    expect(screen.getByRole("meter", { name: "Script length" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "About length" })).toBeTruthy();
    expect(screen.getByText(/A call takes up to 8,000 characters\./)).toBeTruthy();
  });

  it("says plainly when the script is too long to go live", () => {
    render(<ScriptSizeMeter size={{ chars: 8412, target_chars: 7000, limit_chars: 8000 }} />);
    expect(screen.getByRole("meter", { name: "Script length" }).getAttribute("aria-valuetext")).toContain(
      "Too long to put live",
    );
    expect(screen.getByRole("heading", { name: "About length" })).toBeTruthy();
    expect(screen.getByText(/so this script cannot go live/)).toBeTruthy();
  });
});
