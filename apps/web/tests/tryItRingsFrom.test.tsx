import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TryIt } from "@/app/c/[slug]/agents/[agentId]/sections/tryIt";
import type { TrialPanel } from "@/lib/api/trialCalls";

import { OWNER_ME, agentRow } from "./fixtures/sharedReads";
import { noReply, renderClientPage } from "./harness";

/**
 * WHERE AN AGENT'S TEST CALL RINGS FROM (D-1020): a paying account with a number of its own
 * hears it from that number, one with none from our test number, and a call that fell back to
 * our test number because both calling slots were busy says so.
 */

afterEach(cleanup);

const AGENT = agentRow({
  id: "agent-out",
  name: "Varsha",
  direction: "outbound",
  published: true,
});

function paidPanel(): TrialPanel {
  return {
    on_trial: false,
    paid_test_calls: true,
    status: null,
    ends_at: null,
    days_remaining: null,
    free_minutes: null,
    minutes_used: 0,
    minutes_left: null,
    calls_today: 0,
    daily_cap: 10,
    max_call_seconds: 180,
    own_number_max_call_seconds: 900,
    pledge_accepted: true,
    shared_line: true,
    needs_number: false,
    can_call: true,
    blocked_reason: null,
  };
}

const RINGS_FROM = "/v1/trial/rings-from?agent_id=agent-out";

async function tryIt(
  ownNumber: string | null,
  extra: Record<string, unknown> = {},
) {
  return renderClientPage(
    <TryIt
      agent={AGENT}
      slug="acme"
      onTrial={false}
      number="98765 43210"
      onNumber={() => {}}
    />,
    {
      "/v1/trial": paidPanel(),
      [RINGS_FROM]: { own_number: ownNumber },
      ...extra,
    },
  );
}

describe("an agent's test call on a paying account", () => {
  it("names the account's own number when it has one", async () => {
    await tryIt("+919876543210");
    await waitFor(() =>
      expect(
        screen.getByText(
          "Varsha rings you from your number +91 98765 43210. Billed like any call.",
        ),
      ).toBeTruthy(),
    );
  });

  it("says our test number when the account has no number yet", async () => {
    await tryIt(null);
    await waitFor(() =>
      expect(
        screen.getByText(
          "Varsha rings you from our test number. Billed like any call.",
        ),
      ).toBeTruthy(),
    );
  });

  it("says before the call that it rings from our test number when both setups are in use", async () => {
    await tryIt(null, {
      [RINGS_FROM]: { own_number: null, setups_busy: true, unavailable: null },
    });
    await waitFor(() =>
      expect(
        screen.getByText(
          "Varsha rings you from our test number: both your calling setups are in use. Billed like any call.",
        ),
      ).toBeTruthy(),
    );
  });

  it("says why it cannot ring at all, never that its own number will ring", async () => {
    const why =
      "Test calls need a free calling setup. Your account can have 2, and both are in use: 2 agents.";
    await tryIt(null, {
      [RINGS_FROM]: { own_number: null, setups_busy: false, unavailable: why },
    });
    await waitFor(() => expect(screen.getByText(why)).toBeTruthy());
    expect(screen.queryByText(/rings you from your number/)).toBeNull();
  });

  it("says why a call rang from our test number when both slots were busy", async () => {
    await tryIt("+919876543210", {
      "POST /v1/trial/calls": {
        status: "queued",
        call_handle: "out_1",
        blocked_reason: null,
        blocked_rule: null,
        call_id: "call-1",
        caller_number: "+918045678901",
        shared_fallback: true,
      },
      "/v1/me": OWNER_ME,
      // The transcript under the call is its own test's.
      "/v1/calls/call-1": noReply(),
      "/v1/trial/calls/call-1": {
        id: "call-1",
        agent_id: "agent-out",
        agent_name: "Varsha",
        status: "queued",
        status_source: "call",
        placed_at: new Date().toISOString(),
        started_at: null,
        duration_s: null,
        outcome_tag: null,
        business_outcome_label: null,
        headline: null,
        caller_number: "+918045678901",
      },
    });
    const ring = await screen.findByRole("button", { name: /Ring my phone/ });
    fireEvent.click(ring);
    expect(
      await screen.findByText(
        "Rang from our test number: both your calling slots were busy.",
      ),
    ).toBeTruthy();
  });
});
