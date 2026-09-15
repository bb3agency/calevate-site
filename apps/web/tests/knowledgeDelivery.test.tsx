import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import type { Me } from "@/lib/api/client";
import type { AgentDelivery, DeliveryList } from "@/lib/api/kb";

import { problem, renderClientPage, stillLoading, type Routes } from "./harness";

/**
 * "Is what I published actually on the phone?" — the card, in every state it has.
 *
 * WHY EACH STATE IS WORTH A TEST RATHER THAN A SNAPSHOT. The four states are not four
 * decorations on one message; they are four different INSTRUCTIONS, and the two ways this
 * card can be wrong are both silent:
 *
 * - It can tell a client to do nothing while their agent answers callers from knowledge
 *   they corrected an hour ago (`not_delivered` rendered as calm).
 * - It can tell a client something is broken when it is not — a brand-new account that has
 *   published nothing (`no_knowledge`), or one inside the ordinary post-publish wait
 *   (`preparing`). Both produce support tickets about a working system, and both teach the
 *   client to ignore the card, which costs the first case its only reader.
 *
 * So every test below asserts the ACTION the client is given, not just a label. The
 * failure states get the most attention because they are the ones nobody sees in
 * development: a screen is built against the happy fixture and shipped.
 *
 * The last two are about the card's OWN failures. A read that failed must not render as
 * "nothing taught yet" — an empty-looking card over a failed fetch is the same lie
 * `knowledgeApproval.test.tsx` documents for the submitted list, and here it would tell a
 * client their agent knows nothing when we merely could not find out.
 */

const AGENT_ID = "0192f0aa-5555-7000-8000-000000000001";
const PACK_ID = "3f7a91c4d2e58b06a1f4c93e77b25d8091ac6e3f4b120d8e5a97c3f61b04d2e7";

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "kb:write"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const AGENT = { id: AGENT_ID, name: "Front desk", status: "live" };

function row(over: Partial<AgentDelivery> = {}): AgentDelivery {
  return {
    agent_id: AGENT_ID,
    agent_name: "Front desk",
    state: "live",
    pack_id: PACK_ID,
    live_chunks: 4,
    awaiting_translation: 0,
    last_reached_at: "2026-09-15T04:30:00Z",
    ...over,
  };
}

function list(...items: AgentDelivery[]): DeliveryList {
  return {
    items,
    not_delivered_count: items.filter((item) => item.state === "not_delivered").length,
  };
}

async function renderDelivery(delivery: unknown, over: Routes = {}) {
  return await renderClientPage(<KnowledgePage />, {
    "/v1/me": ME,
    "/v1/agents": [AGENT],
    "/v1/kb/sources": [],
    "/v1/kb/uploads": [],
    "/v1/kb/staff-curation": { staff_may_curate_knowledge: false },
    "/v1/kb/delivery": delivery,
    ...over,
  });
}

describe("whether published knowledge has reached the agent", () => {
  it("tells a client their knowledge is live, and since when", async () => {
    const { container } = await renderDelivery(list(row()));

    await screen.findByText(/Everything you have published is on this agent/);
    // The DATE is the point: "live" without it cannot tell a client whether what the agent
    // holds is the version they published an hour ago or the one from last week.
    expect(container.textContent).toContain("It has been answering from it since 15 Sep");
  });

  it("does not claim a date it was not given", async () => {
    // A pack recorded before migration f4b18c7d2e59 carries a pointer and no timestamp.
    // The card must drop the clause rather than render "since —" or an epoch.
    const { container } = await renderDelivery(list(row({ last_reached_at: null })));

    await screen.findByText(/Everything you have published is on this agent/);
    expect(container.textContent).not.toContain("since");
    expect(container.textContent).not.toContain("1970");
    expect(container.textContent).not.toContain("Invalid");
    expect(container.textContent).not.toContain("NaN");
  });

  it("asks a client to WAIT while knowledge is being prepared, and does not alarm them", async () => {
    const { container } = await renderDelivery(
      list(row({ state: "preparing", awaiting_translation: 2, live_chunks: 5 })),
    );

    await screen.findByText(/We are preparing 2 of your 5 facts/);
    expect(container.textContent).toContain("Getting ready");
    expect(container.textContent).toContain("nothing for you to do");
    // The ordinary post-publish wait must not be dressed as a fault, or the badge that
    // matters stops being read. No alarm count is claimed for it either.
    expect(container.textContent).not.toContain("Not live");
    expect(container.textContent).not.toContain("not live");
  });

  it("tells a client their agent is answering from OLD knowledge, and what to do", async () => {
    // THE STATE THE WHOLE SURFACE EXISTS FOR. The publish succeeded everywhere else and
    // the pack never reached the agent, which until now reached the client as silence.
    const { container } = await renderDelivery(list(row({ state: "not_delivered" })));

    await screen.findByText(/has not reached this agent/);
    expect(container.textContent).toContain("Not live");
    expect(container.textContent).toContain("still answering callers from the version before it");
    // Both halves of the instruction: the retry they can do themselves, and the escape
    // hatch for when it does not work. One without the other is a dead end.
    expect(container.textContent).toContain("Publish any document on this agent again");
    expect(container.textContent).toContain("send us the reference");
    // Something exact for support to look up — and only the readable prefix on screen.
    expect(container.textContent).toContain(PACK_ID.slice(0, 12));
    expect(container.textContent).not.toContain(PACK_ID);
  });

  it("counts the agents that are not live, from the server's own tally", async () => {
    const { container } = await renderDelivery({
      items: [row({ state: "not_delivered" })],
      // Deliberately DISAGREEING with the rows: the badge reads the server's count, taken
      // over the whole roster, so a truncated or filtered page can never shrink the number
      // a client is alerted by.
      not_delivered_count: 3,
    });

    await screen.findByText(/has not reached this agent/);
    expect(container.textContent).toContain("3 not live");
  });

  it("does not call a brand-new account broken", async () => {
    // The ordering trap, from the screen's side: an account that has published nothing must
    // read as an empty account, never as a failure. `apps/api/kb/delivery.py` argues the
    // same case where the state is decided.
    const { container } = await renderDelivery(
      list(row({ state: "no_knowledge", pack_id: null, live_chunks: 0 })),
    );

    await screen.findByText(/This agent has nothing published yet/);
    expect(container.textContent).toContain("Nothing taught yet");
    expect(container.textContent).toContain("Add a fact or a document above");
    expect(container.textContent).not.toContain("Not live");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says nothing about the phone while it is still asking", async () => {
    const { container } = await renderDelivery(stillLoading());

    // A skeleton, not a verdict. Rendering "Nothing taught yet" under a request that has
    // not landed is the empty-state-over-a-pending-read lie in its first form.
    await waitFor(() => expect(container.textContent).toContain("On the phone"));
    expect(container.textContent).not.toContain("Nothing taught yet");
    expect(container.textContent).not.toContain("Everything you have published");
    expect(container.textContent).not.toContain("Not live");
  });

  it("reports a failed read as a failure, not as an agent that knows nothing", async () => {
    const { container } = await renderDelivery(problem(503, { title: "Service unavailable" }));

    await screen.findByRole("alert");
    // The distinction that matters: we could not FIND OUT. Saying "nothing taught yet" here
    // would be a statement about the client's knowledge base made out of our own outage.
    expect(container.textContent).not.toContain("Nothing taught yet");
    expect(container.textContent).not.toContain("Everything you have published");
    expect(container.textContent).not.toContain("Not live");
  });
});
