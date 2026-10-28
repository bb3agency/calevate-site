import { readFileSync } from "node:fs";
import { join } from "node:path";

import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallsPage from "@/app/c/[slug]/calls/page";
import { endedReads, liveIds, liveWords, withLive } from "@/app/c/[slug]/calls/liveRows";
import type { CallSummary, Me } from "@/lib/api/client";
import type { CallLive } from "@/lib/api/liveCalls";

import { problem, renderClientPage } from "./harness";

/**
 * Live calls in the call log (D-886). A call has its row from the dial; while it runs the row
 * says so in words, counts its length up and carries a sheen that reduced motion removes;
 * when it ends the row turns into the ended call in place, and the live read stops.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const NOW = Date.now();
const ago = (seconds: number) => new Date(NOW - seconds * 1000).toISOString();

function call(over: Partial<CallSummary> = {}): CallSummary {
  return {
    id: "c1",
    agent_id: "a1",
    agent_name: "Reception",
    direction: "inbound",
    status: "completed",
    caller_e164: "+919876543210",
    started_at: ago(3600),
    created_at: ago(3600),
    duration_s: 92,
    outcome_tag: "call_back_booked",
    summary_state: "ready",
    test_call: false,
    summary: "Caller asked for a Tuesday slot.",
    headline: "Asked for a Tuesday slot",
    lead_id: null,
    live_state: null,
    ...over,
  };
}

function dialling(over: Partial<CallSummary> = {}): CallSummary {
  return call({
    id: "live1",
    direction: "outbound",
    status: "queued",
    caller_e164: "+919812345678",
    started_at: null,
    created_at: ago(20),
    duration_s: null,
    outcome_tag: null,
    summary_state: "pending",
    summary: null,
    headline: null,
    live_state: "live",
    ...over,
  });
}

function read(over: Partial<CallLive> = {}): CallLive {
  return { id: "live1", status: "ringing", status_source: "engine", live_state: "live", started_at: null, ...over };
}

const page = <CallsPage params={Promise.resolve({ slug: "acme" })} />;

function routes(calls: unknown, over: Record<string, unknown> = {}) {
  return { "/v1/me": ME, "/v1/agents": [], "/v1/calls/views": { items: [] }, "/v1/calls?limit=100": calls, ...over };
}

describe("live rows, as data", () => {
  it("asks only about the rows the server calls live", () => {
    expect(liveIds([call(), dialling(), dialling({ id: "old", live_state: "unreported" })])).toEqual(["live1"]);
  });

  it("lays the engine's status over a silent row and keeps the row unlinked while it rings", () => {
    const [row] = withLive([dialling()], [read({ status: "in_progress", started_at: ago(30) })]);
    expect(row.live).toEqual({ state: "live", status: "in_progress", startedAt: ago(30) });
    expect(row.opens).toBe(false);
  });

  it("shows an end the engine heard first as that end, before the row has it", () => {
    const [row] = withLive([dialling()], [read({ status: "no_answer", live_state: null })]);
    expect(row.status).toBe("no_answer");
    expect(row.live).toBeNull();
    expect(endedReads([read(), read({ id: "x", live_state: null, status: "busy" })]).map((r) => r.id)).toEqual(["x"]);
  });

  it("says what is happening on the line, and an overdue end plainly", () => {
    expect(liveWords({ state: "live", status: "queued", startedAt: null })).toBe("Dialling…");
    expect(liveWords({ state: "live", status: "ringing", startedAt: null })).toBe("Ringing…");
    expect(liveWords({ state: "live", status: "in_progress", startedAt: null })).toBe("On the call");
    expect(liveWords({ state: "unreported", status: "queued", startedAt: null })).toBe("Ended — details coming");
  });

  it("an inbound call already on the line still opens its page", () => {
    const [row] = withLive([dialling({ direction: "inbound", status: "in_progress" })], []);
    expect(row.opens).toBe(true);
  });
});

describe("the call log's live rows", () => {
  it("heads the log with a ringing call: Live, Ringing…, Call in progress, a sheen, no link", async () => {
    const { container, calls } = await renderClientPage(
      page,
      routes([dialling(), call()], { "/v1/calls/live?ids=live1": [read()] }),
    );
    expect((await screen.findAllByText("Ringing…")).length).toBeGreaterThan(0);
    expect(screen.getByText("Live")).toBeTruthy();
    expect(screen.getByText("Call in progress")).toBeTruthy();
    expect(container.querySelector("[data-live-sheen]")).not.toBeNull();
    const links = Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href") ?? "");
    expect(links.some((href) => href.includes("/calls/live1"))).toBe(false);
    expect(links.some((href) => href.includes("/calls/c1"))).toBe(true);
    expect(calls.filter((c) => c.path.startsWith("/v1/calls/live")).length).toBeGreaterThan(0);
  });

  it("counts the length up from when the person picked up", async () => {
    await renderClientPage(
      page,
      routes([dialling()], {
        "/v1/calls/live?ids=live1": [read({ status: "in_progress", started_at: ago(65) })],
      }),
    );
    expect((await screen.findAllByText("On the call")).length).toBeGreaterThan(0);
    const counted = screen.getAllByText(/^1:0\d$/);
    expect(counted.length).toBeGreaterThan(0);
  });

  it("turns into the ended call in place, and stops asking", async () => {
    let ended = false;
    const { calls } = await renderClientPage(
      page,
      routes(
        () =>
          ended
            ? [dialling({ status: "completed", live_state: null, started_at: ago(50), duration_s: 41, outcome_tag: "call_back_booked", headline: "Wants a call back on Monday", summary_state: "ready" })]
            : [dialling()],
        {
          "/v1/calls/live?ids=live1": () => {
            ended = true;
            return [read({ status: "completed", status_source: "engine", live_state: null })];
          },
        },
      ),
    );
    expect(await screen.findByText("Wants a call back on Monday")).toBeTruthy();
    expect(screen.queryByText("Live")).toBeNull();
    expect(screen.queryByText("Call in progress")).toBeNull();
    // The ended row is a link to its call again and carries the outcome's mark.
    await waitFor(() => expect(document.querySelector('a[href*="/calls/live1"]')).not.toBeNull());
    expect(document.querySelector("[data-kind]")).not.toBeNull();
    const asked = calls.filter((c) => c.path.startsWith("/v1/calls/live")).length;
    expect(asked).toBe(1);
  });

  it("says so when the live read fails, and leaves the row on its own status", async () => {
    await renderClientPage(
      page,
      routes([dialling()], { "/v1/calls/live?ids=live1": problem(503, { title: "Service unavailable" }) }),
    );
    expect(await screen.findByText(/Live status paused/)).toBeTruthy();
    expect(screen.getAllByText("Dialling…").length).toBeGreaterThan(0);
  });

  it("never asks about a log with no live call, and says an overdue end plainly", async () => {
    const { calls } = await renderClientPage(
      page,
      routes([dialling({ id: "old", created_at: ago(5 * 3600), live_state: "unreported" }), call()]),
    );
    expect((await screen.findAllByText("Ended — details coming")).length).toBeGreaterThan(0);
    expect(screen.getByText("Details are on their way")).toBeTruthy();
    expect(screen.queryByText("Live")).toBeNull();
    expect(calls.some((c) => c.path.startsWith("/v1/calls/live"))).toBe(false);
  });
});

describe("the live sheen under reduced motion", () => {
  it("draws nothing unless motion is welcome, and moves on transform only", () => {
    const css = readFileSync(join(__dirname, "../src/app/globals.css"), "utf8");
    const block = css.slice(css.indexOf("@utility live-sheen"), css.indexOf("A PANE THAT REPLACES ANOTHER"));
    expect(block).toMatch(/^@utility live-sheen \{\s*display: none;/);
    expect(block).toContain("@media (prefers-reduced-motion: no-preference) and (forced-colors: none)");
    const frames = css.slice(css.indexOf("@keyframes live-sheen"), css.indexOf("@utility live-sheen"));
    expect(frames).toContain("transform");
    expect(frames).not.toMatch(/left|width|background-position/);
  });
});
