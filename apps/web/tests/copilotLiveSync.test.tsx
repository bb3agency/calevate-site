import { readFileSync } from "node:fs";
import { join } from "node:path";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { API_BASE, type Session } from "@/lib/api/client";
import { newTurnId } from "@/lib/copilot/conversation";
import { useCopilotSurface, useCopilotSurfaceHolder } from "@/lib/copilot/registry";
import { ALL_LIVE_FAMILIES, familiesFor } from "@/lib/live/topics";
import { useLiveUpdates } from "@/lib/live/useLiveUpdates";

import { nothingNoticed } from "./copilotNotesStub";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

/**
 * ONE CONVERSATION ON EVERY DEVICE, LIVE (D-782).
 *
 * A fake API holds the stored conversation and the person's live streams. "Another device"
 * is the test writing to that store and sending the `conversation` note the server sends
 * after each write; "this device" is a mounted panel with the live stream the client layout
 * mounts. Nothing here reloads, focuses or polls: every change on screen came through the
 * note and the authorised refetch it triggers.
 */

const SESSION: Session = { orgSlug: "acme" };
const NOTE = 'event: change\ndata: {"topic":"conversation","at":"2026-10-15T09:00:00Z"}\n\n';
const READY = 'event: ready\ndata: {"heartbeat_s":20,"max_age_s":1800}\n\n';

type Stored = { id: string; role: "user" | "assistant"; content: string };

/** The server: stored turns, whether Pip is answering, and every open live stream. */
function fakeApi() {
  const encoder = new TextEncoder();
  const server = {
    turns: [] as Stored[],
    answering: false,
    streams: new Set<ReadableStreamDefaultController<Uint8Array>>(),
    conversationReads: 0,
    /** What the server does after a write: one note on each of this person's streams. */
    announce() {
      for (const stream of server.streams) stream.enqueue(encoder.encode(NOTE));
    },
    /** End every open stream, as a server restart or a phone going to sleep does. */
    dropStreams() {
      for (const stream of server.streams) stream.close();
      server.streams.clear();
    },
    /** Held until the test lets the answer finish. */
    release: null as null | (() => void),
  };

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace(API_BASE, "");
      const notes = nothingNoticed(path);
      if (notes) return notes;
      const method = init?.method ?? "GET";
      if (path === "/v1/live") {
        let mine: ReadableStreamDefaultController<Uint8Array> | null = null;
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            mine = controller;
            server.streams.add(controller);
            controller.enqueue(encoder.encode(READY));
          },
          cancel() {
            if (mine !== null) server.streams.delete(mine);
          },
        });
        init?.signal?.addEventListener("abort", () => {
          if (mine !== null) server.streams.delete(mine);
        });
        return new Response(body, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        });
      }
      if (path.startsWith("/v1/copilot/conversation") && method === "GET") {
        server.conversationReads += 1;
        return Response.json({
          turns: server.turns.map((turn) => ({
            ...turn,
            screen_route: "/c/[slug]/leads",
            said_at: "2026-10-15T09:00:00+00:00",
          })),
          has_more: false,
          answering: server.answering,
        });
      }
      if (path.startsWith("/v1/copilot/conversation") && method === "DELETE") {
        const cleared = server.turns.length;
        server.turns = [];
        server.announce();
        return Response.json({ cleared });
      }
      if (path.startsWith("/v1/copilot/ask")) {
        // The server's order (D-782): store the question, mark answering, announce; stream;
        // store the answer, settle, announce; then `done`.
        const asked = JSON.parse(String(init?.body)) as {
          question: string;
          turn_ids: { question: string; answer: string };
        };
        server.turns.push({ id: asked.turn_ids.question, role: "user", content: asked.question });
        server.answering = true;
        server.announce();
        const finish = new Promise<void>((resolve) => {
          server.release = resolve;
        });
        return new Response(
          new ReadableStream<Uint8Array>({
            async start(controller) {
              controller.enqueue(encoder.encode('event: text\ndata: {"delta":"Eleven."}\n\n'));
              await finish;
              server.turns.push({ id: asked.turn_ids.answer, role: "assistant", content: "Eleven." });
              server.answering = false;
              server.announce();
              controller.enqueue(encoder.encode('event: done\ndata: {"metered":true}\n\n'));
              controller.close();
            },
          }),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        );
      }
      return Response.json({});
    }),
  );
  return server;
}

function Screen() {
  useCopilotSurface({
    route: "/c/[slug]/leads",
    title: "Leads",
    realm: "client",
    fields: [],
    apply: () => undefined,
  });
  return <div id="main-content" tabIndex={-1} />;
}

function PanelMount() {
  const holder = useCopilotSurfaceHolder();
  if (holder === null) return null;
  return (
    <CopilotPanel
      session={SESSION}
      holder={holder}
      realm="client"
      labelledBy="copilot-title"
      onClose={() => undefined}
    />
  );
}

/** What `app/c/[slug]/layout.tsx` mounts once: the client realm's live stream. */
function Live() {
  useLiveUpdates(SESSION, "/v1/live");
  return null;
}

async function openDevice() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <QueryClientProvider client={client}>
        <Live />
        <Screen />
        <PanelMount />
      </QueryClientProvider>,
    );
  });
  return within(view.container);
}

const LIVE = { timeout: 3_000 };

/** A turn said on another device: stored, then announced — never typed into this panel. */
function sayElsewhere(
  server: ReturnType<typeof fakeApi>,
  turn: Omit<Stored, "id">,
  { answering = false } = {},
) {
  server.turns.push({ id: newTurnId(), ...turn });
  server.answering = answering;
  server.announce();
}

async function ask(device: Awaited<ReturnType<typeof openDevice>>, question: string) {
  fireEvent.change(device.getByLabelText("Your question about this screen"), {
    target: { value: question },
  });
  await act(async () => {
    fireEvent.submit(device.getByRole("button", { name: "Ask" }).closest("form")!);
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a question asked on another device", () => {
  it("appears here within the coalescing window, then Pip at work, then the answer", async () => {
    const server = fakeApi();
    const device = await openDevice();
    await waitFor(() => expect(server.streams.size).toBe(1));

    sayElsewhere(server, { role: "user", content: "how many leads came in today" }, { answering: true });

    const question = await device.findByText("how many leads came in today", undefined, LIVE);
    // The console's live entrance, the one every arriving row gets.
    expect(question.className).toContain("live-enter");
    const working = await device.findByText("Pip is thinking…", undefined, LIVE);
    expect(working.className).toContain("text-shimmer");
    // Pip's own mark, at work (`pip-lift`), beside the line.
    expect(working.parentElement?.querySelector(".pip-lift")).not.toBeNull();

    sayElsewhere(server, { role: "assistant", content: "Eleven leads came in today." });

    const answer = await device.findByText("Eleven leads came in today.", undefined, LIVE);
    // Revealed block by block, as an answer streaming on this device is.
    expect(answer.closest("p")?.className).toContain("answer-reveal");
    await waitFor(() => expect(device.queryByText("Pip is thinking…")).toBeNull(), LIVE);
    expect(device.getAllByText("how many leads came in today")).toHaveLength(1);
  });

  it("does not animate what was already stored when the panel opened", async () => {
    const server = fakeApi();
    server.turns.push({ id: newTurnId(), role: "user", content: "an older question" });
    server.turns.push({ id: newTurnId(), role: "assistant", content: "An older answer." });
    const device = await openDevice();

    const older = await device.findByText("an older question");
    expect(older.className).not.toContain("live-enter");
    const olderAnswer = await device.findByText("An older answer.");
    expect(olderAnswer.closest("p")?.className).not.toContain("answer-reveal");
  });

  it("forgets the conversation here when it is cleared there", async () => {
    const server = fakeApi();
    server.turns.push({ id: newTurnId(), role: "user", content: "something to forget" });
    const device = await openDevice();
    await device.findByText("something to forget");
    await waitFor(() => expect(server.streams.size).toBe(1));

    server.turns = [];
    server.announce();

    await waitFor(() => expect(device.queryByText("something to forget")).toBeNull(), LIVE);
  });
});

describe("two devices talking at once", () => {
  it("keeps this device's question while another device's turns arrive, then orders both as stored", async () => {
    const server = fakeApi();
    const device = await openDevice();
    await waitFor(() => expect(server.streams.size).toBe(1));

    // The phone's question is stored first; this device asks a moment later.
    sayElsewhere(server, { role: "user", content: "asked on the phone" }, { answering: true });
    await device.findByText("asked on the phone", undefined, LIVE);
    await ask(device, "asked on the desktop");
    expect(device.getAllByText("asked on the desktop")).toHaveLength(1);

    // The phone's answer lands while this device's answer is still streaming: the note
    // refetches mid-stream, and nothing this device said may vanish or double.
    sayElsewhere(server, { role: "assistant", content: "Answer for the phone." }, { answering: true });
    await device.findByText("Answer for the phone.", undefined, LIVE);
    expect(device.getAllByText("asked on the desktop")).toHaveLength(1);

    await act(async () => server.release?.());
    await waitFor(() => expect(server.answering).toBe(false));
    await waitFor(() => expect(device.queryByText("Pip is thinking…")).toBeNull(), LIVE);

    const order = device
      .getAllByText(/asked on the|Answer for the phone\.|^Eleven\.$/)
      .map((node) => node.textContent);
    expect(order).toEqual([
      "asked on the phone",
      "asked on the desktop",
      "Answer for the phone.",
      "Eleven.",
    ]);
  });

  it("shows this device's own answer once, never as 'answering elsewhere'", async () => {
    const server = fakeApi();
    const device = await openDevice();
    await waitFor(() => expect(server.streams.size).toBe(1));

    await ask(device, "how many leads");
    // The note from this device's own question refetches while it streams; the page now
    // says `answering`, which is about THIS device and must not show a second thinking line.
    await waitFor(() => expect(server.conversationReads).toBeGreaterThan(1), LIVE);
    expect(device.queryAllByText("Pip is thinking…").length).toBeLessThanOrEqual(1);

    await act(async () => server.release?.());
    await waitFor(() => expect(server.answering).toBe(false));
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(device.getAllByText("Eleven.")).toHaveLength(1);
    expect(device.getAllByText("how many leads")).toHaveLength(1);
    expect(device.queryByText("Pip is thinking…")).toBeNull();
  });
});

describe("after sleep or a dropped connection", () => {
  it("catches up on what was said while the stream was closed, with no note for it", async () => {
    const server = fakeApi();
    const device = await openDevice();
    await waitFor(() => expect(server.streams.size).toBe(1));

    // Said while this device was asleep: stored, and announced to nobody.
    server.turns.push({ id: newTurnId(), role: "user", content: "asked while you slept" });
    server.turns.push({ id: newTurnId(), role: "assistant", content: "Answered while you slept." });
    server.dropStreams();

    await device.findByText("asked while you slept", undefined, LIVE);
    await device.findByText("Answered while you slept.", undefined, LIVE);
    expect(device.getAllByText("asked while you slept")).toHaveLength(1);
  });
});

describe("the note that moves the conversation", () => {
  it("refetches the conversation and nothing else; the assistant's other feeds keep their own topic", () => {
    expect([...familiesFor(["conversation"])]).toEqual(["copilot"]);
    const assistant = familiesFor(["assistant"]);
    expect(assistant.has("copilot")).toBe(false);
    expect(assistant.has("copilot-approvals")).toBe(true);
    // A reconnect still refetches it: `ready` invalidates every live family.
    expect(ALL_LIVE_FAMILIES.has("copilot")).toBe(true);
  });
});

describe("motion", () => {
  const css = readFileSync(join(process.cwd(), "src", "app", "globals.css"), "utf8");

  it.each(["live-enter", "answer-reveal"])(
    "%s, which an arriving turn uses, moves only under prefers-reduced-motion: no-preference",
    (utility) => {
      const block = new RegExp(`@utility ${utility} \\{([\\s\\S]*?)\\n\\}`).exec(css);
      const body = block?.[1] ?? "";
      const media = body.indexOf("@media (prefers-reduced-motion: no-preference)");
      expect(media).toBeGreaterThanOrEqual(0);
      expect(body.indexOf("animation")).toBeGreaterThan(media);
    },
  );

  it("text-shimmer stops under reduced motion and forced colours", () => {
    const block = /@utility text-shimmer \{([\s\S]*?)\n\}/.exec(css);
    expect(block?.[1]).toContain(
      "@media (prefers-reduced-motion: no-preference) and (forced-colors: none)",
    );
  });
});

describe("newTurnId", () => {
  it("is a UUIDv7 that sorts by the instant it was minted", () => {
    const early = newTurnId(Date.UTC(2026, 9, 15, 9, 0, 0));
    const late = newTurnId(Date.UTC(2026, 9, 15, 9, 0, 1));
    expect(early).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(early < late).toBe(true);
    expect(early.slice(0, 13).replace("-", "")).toBe(Date.UTC(2026, 9, 15, 9, 0, 0).toString(16).padStart(12, "0"));
  });
});
