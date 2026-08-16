import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import KnowledgePage from "@/app/c/[slug]/knowledge/page";
import type { Me } from "@/lib/api/client";
import type { KbSource } from "@/lib/api/kb";

import {
  expectTextCount,
  problem,
  renderClientPage,
  type ProblemResponse,
  type Routes,
} from "./harness";

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
 *
 * The second half of the file is about the same gate under FAILURE and under a session
 * that may not submit. Both produce a screen that looks calm and says the wrong thing:
 * an empty "Submitted" panel over a failed read tells a client their queued change was
 * never queued, and a live-looking submit button tells a `staff` user to write two
 * hundred words for a 403.
 */

const AGENT_ID = "0192f0aa-5555-7000-8000-000000000001";
const SOURCE_ID = "0192f0aa-6666-7000-8000-000000000001";

const ME: Me = {
  impersonating: false,
  permissions: ["agents:read", "kb:write"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

/**
 * The other client-realm role. `staff` holds `agents:read` and NOT `kb:write`
 * (core/rbac.py), so it may read every source on this screen and submit none.
 */
const STAFF: Me = { ...ME, role: "staff", permissions: ["agents:read"] };

/** D-22: every MUTATING permission is refused an impersonating principal, `kb:write` included. */
const OPERATOR_VIEWING: Me = { ...ME, impersonating: true };

const AGENT = { id: AGENT_ID, name: "Front desk", status: "live" };

function source(over: Partial<KbSource> = {}): KbSource {
  return {
    id: SOURCE_ID,
    agent_id: AGENT_ID,
    name: "Opening hours",
    kind: "text",
    status: "pending_approval",
    version: 3,
    chunks: 4,
    is_active: false,
    published_at: null,
    ...over,
  };
}

async function renderKnowledge(sources: KbSource[] | ProblemResponse, over: Routes = {}) {
  return await renderClientPage(<KnowledgePage />, {
    "/v1/me": ME,
    "/v1/agents": [AGENT],
    "/v1/kb/sources": sources,
    ...over,
  });
}

/** The one control on the screen, found the way a client finds it. */
function submitButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /submit for review/i }) as HTMLButtonElement;
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

describe("the gate when we cannot read it, or cannot write to it", () => {
  it("never says 'nothing submitted' about a list it could not read", async () => {
    // THE dangerous sentence on this screen. A client whose text is sitting in the
    // approval queue, shown an empty panel headed "Submitted", concludes the submission
    // was lost — and either submits it again or rings us about a queue that is working.
    // The panel is absent entirely; the refusal above is the whole answer.
    const { container } = await renderKnowledge(
      problem(503, { title: "Service unavailable", detail: "We could not read your submissions." }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain("Nothing submitted yet");
    expect(screen.queryByText("Submitted")).toBeNull();
    expect(container.textContent).not.toContain("Live");
  });

  it("does not read a failed agent list as an account with no agents", async () => {
    // The same defect one query over: `agents.data ?? []` cannot tell "this account has
    // no agent" from "we could not ask". Only the first is a fact about the client, and
    // only the server may state it. The form is dead either way — so it says why.
    const { container } = await renderKnowledge([source()], {
      "/v1/agents": problem(500, { title: "Upstream failure" }),
    });

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain("There is no agent on this account yet");
    expect(submitButton().disabled).toBe(true);
  });

  it("disables the submit control for a role the route refuses, and says which", async () => {
    // `POST /v1/kb/sources` is `kb:write`, which `staff` does not hold (core/rbac.py).
    // The button used to render live for them: the 403 arrived after the client had
    // typed the text, and it reads as a fault in the product rather than as a rule.
    const { container } = await renderKnowledge([source()], { "/v1/me": STAFF });

    await screen.findByText("Opening hours");
    expect(submitButton().disabled).toBe(true);
    expect(container.textContent).toContain("Only an account owner can add knowledge to this account.");
    // The reason travels with the control as well: on a phone the note at the top of the
    // screen is nowhere near the button that is refusing to work.
    expect(submitButton().title).toContain("Only an account owner");
    // Reading is `agents:read` and stays open — a staff user still sees the queue.
    expect(container.textContent).toContain("In review");
  });

  it("disables the submit control inside a read-only view-as session (D-22)", async () => {
    const { container } = await renderKnowledge([source()], { "/v1/me": OPERATOR_VIEWING });

    await screen.findByText("Opening hours");
    expect(submitButton().disabled).toBe(true);
    expect(container.textContent).toContain("viewing this account read-only");
    expect(container.textContent).toContain("Do it from the admin console instead.");
  });

  it("does not render a failed preview as a submission with nothing in it", async () => {
    // The preview answers "what will the agent actually say", so an empty box is read as
    // "the text I pasted arrived blank" — and a client who believes that deletes the
    // source and starts again, losing their place in the queue. Loading, failure and a
    // genuinely empty source were all one silent branch: `(chunks.data ?? []).map(...)`.
    const { container } = await renderKnowledge([source()], {
      [`/v1/kb/sources/${SOURCE_ID}/preview`]: problem(503, { title: "Service unavailable" }),
    });

    await screen.findByText("Opening hours");
    fireEvent.click(screen.getByRole("button", { name: /preview/i }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain(
      "There is nothing in this submission for the agent to say.",
    );
  });

  it("says which agent a source belongs to, and guesses at none", async () => {
    // Knowledge is filed against ONE agent and `list_sources` returns every agent's
    // sources together, so a two-agent account cannot otherwise tell whether the answer
    // it is waiting on belongs to the receptionist or to the outbound agent.
    const named = await renderKnowledge([source()]);
    await screen.findByText("Opening hours");
    expect(named.container.textContent).toContain("Front desk");
    named.unmount();

    // With the agent list unreadable the row says nothing rather than something: a
    // source attributed to the wrong agent is worse than one attributed to none.
    const unnamed = await renderKnowledge([source()], {
      "/v1/agents": problem(500, { title: "Upstream failure" }),
    });
    await screen.findByText("Opening hours");
    expect(unnamed.container.textContent).not.toContain("Front desk");
  });
});
