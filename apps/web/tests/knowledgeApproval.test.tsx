import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import type { Me } from "@/lib/api/client";
import type { KbSource } from "@/lib/api/kb";

import { expectTextCount, renderClientPage } from "./harness";

/**
 * The knowledge approval gate (FLOWS §7), ranked third.
 *
 * The gate exists because the agent speaks under the CLIENT'S PE registration: whatever
 * a source says, a caller hears as the business saying it. So nothing a client submits
 * reaches an agent until someone here approves and publishes it, and this screen is the
 * only place the client learns where their submission stands.
 *
 * The decision the screen encodes is a two-step ladder, and the interesting thing about
 * it is that the second step is NOT `status`:
 *
 *     is_active  →  "Live"          (the agent is saying this now)
 *     otherwise  →  status copy     ("In review", "Approved, not live yet", …)
 *
 * `approved` and `live` are different facts, separated by a publish that has not
 * happened yet. Collapsing them — keying the badge on `status === "approved"` — is the
 * exact divergence FLOWS §7 exists to prevent, and it is invisible to a type checker
 * because both fields are on every row. A client told "Live" about text no caller will
 * hear will assume the agent is answering with it, and stop chasing the publish.
 *
 * The reverse error is just as reachable and lands the other way: a source that IS live
 * showing its old status would have a client resubmitting text the agent already says.
 */

const AGENT_ID = "0192f0aa-5555-7000-8000-000000000001";

const ME: Me = {
  impersonating: false,
  permissions: ["agents:read", "kb:write"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const AGENT = { id: AGENT_ID, name: "Front desk", status: "live" };

function source(over: Partial<KbSource> = {}): KbSource {
  return {
    id: "0192f0aa-6666-7000-8000-000000000001",
    agent_id: AGENT_ID,
    name: "Opening hours",
    kind: "text",
    status: "pending_approval",
    version: 3,
    chunks: 4,
    is_active: false,
    published_at: null,
    ...over,
  } as KbSource;
}

async function renderKnowledge(sources: KbSource[]) {
  return await renderClientPage(<KnowledgePage />, {
    "/v1/me": ME,
    "/v1/agents": [AGENT],
    "/v1/kb/sources": sources,
  });
}

describe("the approval gate as the client sees it", () => {
  it("does not call an approved-but-unpublished source live", async () => {
    // THE case this file exists for. The reviewer has said yes; the publish has not
    // run. The agent is still answering with the previous version, and the client must
    // not be told otherwise.
    const { container } = await renderKnowledge([
      source({ status: "approved", is_active: false, published_at: null }),
    ]);

    await screen.findByText("Opening hours");
    expect(container.textContent).toContain("Approved, not live yet");
    expect(container.textContent).not.toContain("Live");
    expect(container.textContent).toContain("not live yet");
  });

  it("says a submission is in review rather than showing an approval control", async () => {
    // Approval is an admin action (D-22) and `lib/api/kb.ts` deliberately has no
    // mutation for it. A button here would 403, and — worse — would suggest a client
    // can wave their own text through the gate.
    const { container } = await renderKnowledge([source({ status: "pending_approval" })]);

    await screen.findByText("Opening hours");
    expect(container.textContent).toContain("In review");
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /publish/i })).toBeNull();
    expect(container.textContent).not.toContain("Live");
  });

  it("calls a live source live, and lets its stale status go", async () => {
    // `is_active` wins. A published source carrying an older status string must not be
    // shown as anything but live, or the client resubmits what the agent already says.
    const { container } = await renderKnowledge([
      source({ status: "approved", is_active: true, published_at: "2026-07-20T06:00:00Z" }),
    ]);

    await screen.findByText("Opening hours");
    expectTextCount(container, "Live", 1);
    expect(container.textContent).not.toContain("Approved, not live yet");
    expect(container.textContent).not.toContain("not live yet");
  });

  it("tells a client their submission was refused, in words and not in silence", async () => {
    const { container } = await renderKnowledge([source({ status: "rejected" })]);

    await screen.findByText("Opening hours");
    expect(container.textContent).toContain("Not accepted");
    expect(container.textContent).not.toContain("Live");
  });

  it("does not let a superseded version read as the one in force", async () => {
    // Two rows, one topic, and the difference between them is the whole gate. A client
    // reading "Live" beside v3 would think their new text is what callers hear.
    const { container } = await renderKnowledge([
      source({ id: "old", name: "Opening hours", version: 2, status: "archived", is_active: true }),
      source({ id: "new", name: "Opening hours", version: 3, status: "pending_approval" }),
    ]);

    await screen.findByText("v3");
    // Exactly one row is live, and exactly one is queued behind the gate.
    expectTextCount(container, "Live", 1);
    expectTextCount(container, "In review", 1);
    expect(container.textContent).not.toContain("Replaced by a newer version");
  });

  it("fails VISIBLE on a status this build cannot name", async () => {
    // `SourceOut.status` is plain `string` on the wire. A state we have no copy for is
    // shown as itself — a client whose submission is stuck in an unfamiliar state still
    // has to be able to see that it is stuck, and quote the word to support.
    const { container } = await renderKnowledge([source({ status: "withdrawn_by_reviewer" })]);

    await screen.findByText("Opening hours");
    expect(container.textContent).toContain("withdrawn_by_reviewer");
    expect(container.textContent).not.toContain("Live");
    // The `Object.prototype` failure this app has a whole module about: a bare index
    // would have rendered a stringified function into the badge's class list.
    expect(container.innerHTML).not.toContain("native code");
  });
});
