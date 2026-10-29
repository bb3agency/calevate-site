import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/arc/toast";
import { ChartCard } from "@/components/copilot/ChartCard";
import { ChartView } from "@/components/copilot/ChartView";
import { PinnedCards } from "@/components/copilot/PinnedCards";
import type { Session } from "@/lib/api/client";
import { openHref, specCsv, specTable, type ChartSpec } from "@/lib/copilot/charts";
import { askCopilot, type CopilotAskBody } from "@/lib/copilot/stream";

import { renderClientPage } from "./harness";

/**
 * Pip's charts (D-934): the `chart` frame is parsed into a spec, drawn with the console's
 * chart components (each with its table fallback), pinned to the home at once with Undo,
 * opened on the screen that shows the same set, and copied as CSV.
 */

const SESSION: Session = { orgSlug: "acme" };

const BY_DAY: ChartSpec = {
  chart: "calls_by_day",
  args: { days: 3 },
  kind: "stacked_bar",
  title: "Calls each day",
  unit: "calls",
  x: { label: "Day", bucket: "day", labels: ["2026-10-27", "2026-10-28", "2026-10-29"] },
  series: [
    { key: "answered", label: "Answered", values: ["4", "0", "2"] },
    { key: "missed", label: "Missed", values: ["1", "0", "1"] },
  ],
  columns: [],
  rows: [],
  total: "8",
  counted: "Every call 27 Oct to 29 Oct 2026 (IST), by IST day. Test calls left out.",
  window_from: "2026-10-27",
  window_to: "2026-10-29",
  shown: null,
  of: null,
  open: { screen: "Calls", path: "/calls", query: {} },
};

const HOT: ChartSpec = {
  chart: "hot_leads",
  args: { days: 30 },
  kind: "table",
  title: "Hot leads",
  unit: "leads",
  x: null,
  series: [],
  columns: [
    { key: "lead", label: "Lead", numeric: false },
    { key: "calls", label: "Calls", numeric: true },
  ],
  rows: [
    ["=Ravi, Kumar", "3"],
    ["Sita", "1"],
  ],
  total: "14",
  counted: "Every lead whose status is hot now.",
  window_from: null,
  window_to: null,
  shown: 2,
  of: 14,
  open: { screen: "Leads", path: "/leads", query: { status: "hot" } },
};

const SPEND: ChartSpec = {
  ...BY_DAY,
  chart: "spend_by_day",
  kind: "bar",
  title: "Spend each day",
  unit: "inr",
  series: [{ key: "spent", label: "Spent (₹)", values: ["10.50", "0", "2.00"] }],
  total: "12.50",
};

afterEach(() => vi.unstubAllGlobals());

describe("chart specs", () => {
  it("turns a table spec into CSV with spreadsheet formulas disarmed", () => {
    expect(specCsv(HOT)).toBe('Lead,Calls\n"\'=Ravi, Kumar",3\nSita,1');
    expect(specCsv(BY_DAY).split("\n")[1]).toBe("2026-10-27,4,1");
  });

  it("shows money with the rupee sign in the table fallback", () => {
    expect(specTable(SPEND).rows[0]).toEqual(["27 Oct", "₹10.5"]);
  });

  it("opens the realm's own screen with the same filter, and nothing else", () => {
    expect(openHref(HOT, "client", "acme")).toBe("/c/acme/leads?status=hot");
    expect(openHref({ ...BY_DAY, open: { screen: "Health", path: "/health", query: {} } }, "admin", "")).toBe(
      "/admin/health",
    );
    expect(openHref({ ...BY_DAY, open: { screen: "x", path: "//evil.example", query: {} } }, "client", "acme")).toBeNull();
  });
});

describe("drawing", () => {
  it("draws a table spec as a real table with its cut said", async () => {
    await renderClientPage(<ChartView spec={HOT} />, {});
    expect(screen.getByRole("columnheader", { name: "Calls" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "Sita" })).toBeTruthy();
    expect(screen.getByText(/Top 2 of 14/)).toBeTruthy();
  });

  it("draws a bar spec with the chart's own table fallback", async () => {
    await renderClientPage(<ChartView spec={BY_DAY} />, {});
    fireEvent.click(screen.getByRole("button", { name: /Show as table/ }));
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.getAllByText("27 Oct").length).toBeGreaterThan(0);
  });
});

describe("the panel's chart card", () => {
  it("pins at once, and Undo takes the same card off", async () => {
    const { calls } = await renderClientPage(
      <ToastProvider>
        <ChartCard spec={BY_DAY} session={SESSION} realm="client" />
      </ToastProvider>,
      {
        "POST /v1/copilot/pins": { id: "p1", chart: "calls_by_day", args: { days: 3 }, title: "Calls each day", position: 0 },
        "DELETE /v1/copilot/pins/p1": { id: "p1", chart: "calls_by_day", args: { days: 3 }, title: "Calls each day", position: 0 },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /Pin “Calls each day” to the home screen/ }));
    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST" && c.path === "/v1/copilot/pins");
      expect(JSON.parse(String(post?.body))).toEqual({
        chart: "calls_by_day",
        args: { days: 3 },
        title: "Calls each day",
      });
    });
    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "DELETE" && c.path === "/v1/copilot/pins/p1")).toBe(true),
    );
    expect(screen.getByRole("link", { name: /Open in Calls/ }).getAttribute("href")).toBe("/c/acme/calls");
  });
});

describe("pinned cards on the home", () => {
  it("re-runs each card and says so when the viewer may not see it", async () => {
    await renderClientPage(
      <ToastProvider>
        <PinnedCards session={SESSION} realm="client" canEdit={false} />
      </ToastProvider>,
      {
        "/v1/copilot/pins": {
          max_pins: 12,
          pins: [
            { id: "p1", chart: "calls_by_day", args: { days: 3 }, title: "Daily calls", position: 0 },
            { id: "p2", chart: "spend_by_day", args: { days: 3 }, title: "Spend", position: 1 },
          ],
        },
        "/v1/copilot/pins/p1/card": { pin: { id: "p1" }, spec: BY_DAY, refused: null },
        "/v1/copilot/pins/p2/card": {
          pin: { id: "p2" },
          spec: null,
          refused: "You do not have permission to see this (billing:read). Ask the account owner.",
        },
      },
    );
    expect(await screen.findByText("Daily calls")).toBeTruthy();
    expect(await screen.findByText(/billing:read/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull();
  });

  it("moves a card up and removes one with Undo", async () => {
    const { calls } = await renderClientPage(
      <ToastProvider>
        <PinnedCards session={SESSION} realm="client" canEdit />
      </ToastProvider>,
      {
        "/v1/copilot/pins": {
          max_pins: 12,
          pins: [
            { id: "p1", chart: "calls_by_day", args: { days: 3 }, title: "Daily calls", position: 0 },
            { id: "p2", chart: "hot_leads", args: { days: 30 }, title: "Hot", position: 1 },
          ],
        },
        "/v1/copilot/pins/p1/card": { pin: { id: "p1" }, spec: BY_DAY, refused: null },
        "/v1/copilot/pins/p2/card": { pin: { id: "p2" }, spec: HOT, refused: null },
        "PUT /v1/copilot/pins/order": {
          max_pins: 12,
          pins: [
            { id: "p2", chart: "hot_leads", args: { days: 30 }, title: "Hot", position: 1 },
            { id: "p1", chart: "calls_by_day", args: { days: 3 }, title: "Daily calls", position: 2 },
          ],
        },
        "DELETE /v1/copilot/pins/p1": { id: "p1", chart: "calls_by_day", args: { days: 3 }, title: "Daily calls", position: 0 },
        "POST /v1/copilot/pins/p1/restore": { id: "p1", chart: "calls_by_day", args: { days: 3 }, title: "Daily calls", position: 0 },
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Move “Hot” up" }));
    await waitFor(() => {
      const put = calls.find((c) => c.method === "PUT");
      expect(JSON.parse(String(put?.body))).toEqual({ ids: ["p2", "p1"] });
    });
    fireEvent.click(screen.getByRole("button", { name: "Remove “Daily calls”" }));
    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/copilot/pins/p1/restore")).toBe(true),
    );
  });
});

describe("the chart frame", () => {
  it("hands a chart frame to onChart and ignores one with nothing to draw", async () => {
    const encoder = new TextEncoder();
    const body = [
      `event: chart\ndata: ${JSON.stringify(BY_DAY)}\n\n`,
      'event: chart\ndata: {"title":"no chart name"}\n\n',
      'event: done\ndata: {"disclosure":null,"metered":true}\n\n',
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              for (const chunk of body) controller.enqueue(encoder.encode(chunk));
              controller.close();
            },
          }),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        ),
      ),
    );
    const charts: ChartSpec[] = [];
    const ask: CopilotAskBody = {
      screen: { route: "/c/acme", title: "Home", realm: "client" },
      question: "chart my calls",
      fields: [],
      facts: [],
      history: [],
    };
    await act(async () => {
      await askCopilot(SESSION, ask, {
        onText: () => undefined,
        onFill: () => undefined,
        onProposal: () => undefined,
        onAction: () => undefined,
        onNavigate: () => undefined,
        onStep: () => undefined,
        onDone: () => undefined,
        onChart: (spec) => charts.push(spec),
      });
    });
    expect(charts.map((c) => c.chart)).toEqual(["calls_by_day"]);
  });
});
