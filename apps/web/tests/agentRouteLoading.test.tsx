import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import RealmLoading from "@/app/c/[slug]/loading";
import AgentsLoading from "@/app/c/[slug]/agents/loading";
import AgentLoading from "@/app/c/[slug]/agents/[agentId]/loading";
import NewAgentLoading from "@/app/c/[slug]/agents/new/loading";
import FirstRunLoading from "@/app/c/[slug]/agents/first/loading";

/**
 * A tap on a phone must change the screen at once.
 *
 * Without a `loading.tsx` in the segment, Next keeps the screen being LEFT on view until the
 * next route's JavaScript has downloaded (the navigation is a transition with no Suspense
 * boundary to fall back to). On a throttled phone (400 ms round trip, 400 kbit/s, 4x CPU) a
 * tap on an agent row changed nothing for about six seconds and New agent for two and a
 * half, which an owner reads as a dead page. With the boundaries, the route skeleton showed
 * within about a third of a second.
 */

const APP = join(__dirname, "..", "src", "app", "c", "[slug]");

describe("every agents screen has a loading boundary", () => {
  it.each([
    ["the client realm", "."],
    ["the agents list", "agents"],
    ["one agent", "agents/[agentId]"],
    ["a new agent", "agents/new"],
    ["the first run", "agents/first"],
  ])("%s", (_name, dir) => {
    expect(existsSync(join(APP, dir, "loading.tsx"))).toBe(true);
  });

  it("draws the fallback without code of its own to download", () => {
    // A client module here would be one more chunk to fetch before the skeleton can show,
    // which is the wait this boundary exists to cover.
    const source = readFileSync(
      join(__dirname, "..", "src", "components", "console", "routeLoading.tsx"),
      "utf8",
    );
    expect(source).not.toMatch(/^["']use client["']/m);
    expect(source).not.toMatch(/^import /m);
  });
});

describe("the skeleton says what is opening", () => {
  it.each([
    [RealmLoading, "Opening…"],
    [AgentsLoading, "Opening your agents…"],
    [AgentLoading, "Opening the agent…"],
    [NewAgentLoading, "Opening the new agent form…"],
    [FirstRunLoading, "Opening…"],
  ])("%#", (Loading, label) => {
    const { container } = render(<Loading />);
    expect(screen.getByRole("status").textContent).toBe(label);
    // Nothing to tab to while the screen is on its way.
    expect(container.querySelector("a, button, input, [tabindex]")).toBeNull();
  });
});
