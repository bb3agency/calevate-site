import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { KnowledgeDeliveryPanel } from "@/app/admin/tenants/[tenantId]/KnowledgeDeliveryPanel";
import type { AgentDelivery } from "@/lib/api/admin";

import { problem, renderAdminPage, type Routes } from "./harness";

/**
 * The OPERATOR's view of what a client's phone is answering from.
 *
 * ## What is actually at risk
 *
 * This panel exists because `KnowledgeQueue` ends at Publish and a publish is not a
 * delivery: `kb/pack.refresh_published_pack` survives a storage failure on purpose,
 * keeping the old pointer, so every screen shows the new words while the phone quotes the
 * old ones. An operator who has just worked the queue to empty is the one person
 * positioned to catch that, and only if this panel tells them the truth.
 *
 * ## Why the wording is asserted, and asserted as DIFFERENT from the client's
 *
 * The client's card says what to DO ("Not live", "Publish again"). This one names the
 * MECHANISM — which sweep owes work, whether anything is coming — because an operator is
 * diagnosing rather than being reassured. If the two ever converged on one vocabulary,
 * one of the two audiences would be reading the wrong screen: the client would be handed
 * "gloss pending", or the operator would lose the only distinction that tells them
 * whether to wait or to investigate.
 *
 * ## The full pack id
 *
 * The client sees a readable prefix; the operator needs the whole value, because it IS
 * the object key in the bucket (`pack_object_key`) and a truncated one cannot be looked
 * up. That asymmetry is deliberate and is asserted, since "shorten it, it looks untidy"
 * is a plausible future edit that would silently remove the panel's diagnostic value.
 */

const SLUG = "sri-traders";
const AGENT_ID = "0192f0aa-5555-7000-8000-000000000001";
const PACK_ID = "3f7a91c4d2e58b06a1f4c93e77b25d8091ac6e3f4b120d8e5a97c3f61b04d2e7";

const ADMIN_ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000cc",
  role: "operator",
  permissions: ["admin:tenants"],
};

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

function renderPanel(delivery: unknown, over: Routes = {}) {
  return renderAdminPage(<KnowledgeDeliveryPanel slug={SLUG} />, {
    [ADMIN_ME_PATH]: ADMIN_ME,
    "/v1/kb/delivery": delivery,
    ...over,
  });
}

describe("the operator's view of what a client's agents are answering from", () => {
  it("names the mechanism, not the client's instruction", async () => {
    const { container } = renderPanel({
      items: [row({ state: "preparing", awaiting_translation: 2 })],
      not_delivered_count: 0,
    });

    await screen.findByText("Gloss pending");
    expect(container.textContent).toContain("the gloss sweep still owes this agent work");
    // The client's copy must not leak into the operator's panel: "nothing for you to do"
    // is advice to the business owner, and an operator acting on it would stop looking.
    expect(container.textContent).not.toContain("nothing for you to do");
  });

  it("calls a pack that will never heal itself stale, and says no sweep is coming", async () => {
    const { container } = renderPanel({
      items: [row({ state: "not_delivered", awaiting_translation: 0 })],
      not_delivered_count: 1,
    });

    await screen.findByText("Stale");
    expect(container.textContent).toContain("nothing is queued, so no sweep is coming");
    expect(container.textContent).toContain("1 stale");
  });

  it("gives the operator the whole pack id, not the client's readable prefix", async () => {
    const { container } = renderPanel({
      items: [row({ state: "not_delivered" })],
      not_delivered_count: 1,
    });

    await screen.findByText("Stale");
    // The whole value, because it is the object key in the bucket.
    expect(container.textContent).toContain(PACK_ID);
  });

  it("does not call an account with nothing published a fault", async () => {
    const { container } = renderPanel({
      items: [row({ state: "no_knowledge", pack_id: null, live_chunks: 0 })],
      not_delivered_count: 0,
    });

    await screen.findByText("Nothing published");
    expect(container.textContent).toContain("the agent answers not_found, correctly");
    expect(container.textContent).not.toContain("Stale");
  });

  it("shows an em dash rather than inventing a date it was never given", async () => {
    // A pack recorded before migration f4b18c7d2e59 carries a pointer and no timestamp.
    const { container } = renderPanel({
      items: [row({ last_reached_at: null })],
      not_delivered_count: 0,
    });

    await screen.findByText("In sync");
    expect(container.textContent).toContain("—");
    expect(container.textContent).not.toContain("1970");
    expect(container.textContent).not.toContain("Invalid");
  });

  it("reports a failed read as a failure, never as a client with no agents", async () => {
    const { container } = renderPanel(problem(503, { title: "Service unavailable" }));

    await screen.findByRole("alert");
    // An operator told "No agents" over a failed read closes the tab believing this
    // client has nothing to check — which is the state this whole panel exists to catch.
    expect(container.textContent).not.toContain("No agents");
    expect(container.textContent).not.toContain("In sync");
  });
});
