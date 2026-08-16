import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallDetailPage from "@/app/c/[slug]/calls/[callId]/page";
import type { AiQuota } from "@/lib/api/aiQuota";
import type { Me } from "@/lib/api/client";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderClientPage, stillLoading } from "./harness";

/**
 * "Re-summarise this call" on the call detail screen (D-127 — the surface the metering,
 * the ceiling and the capability ladder were all built for and none of them reached).
 *
 * What this file pins, in the order it would hurt to get wrong:
 *
 * 1. **A fallback is never silent (G-6).** When the server says a different model wrote
 *    the answer, that sentence is ON THE SCREEN with the answer. A disclosure that
 *    reaches the response and stops at the component is the same defect as no disclosure.
 * 2. **At the ceiling the EXISTING wallet dialog is what appears.** Same dialog, same
 *    words, same server-supplied figure as the AI-help screen — asserted by driving both
 *    entry points at the amount, because a second dialog would pass every other test here.
 * 3. **Nothing is charged until a person accepts.** Asserted on the NETWORK: hitting the
 *    ceiling issues no `/extra` request, and neither does opening the dialog.
 * 4. **§52.** Loading is a skeleton, failure is a refusal, and an assistant that answered
 *    with nothing is stated in words rather than rendered as a blank panel.
 * 5. **The gate is previewed, not discovered.** A session without `org:manage` gets a
 *    disabled control with the reason beside it rather than a 403 after the click.
 */

const CALL = {
  id: "c1",
  agent_id: "a1",
  agent_name: "Reception",
  direction: "inbound",
  status: "completed",
  caller_masked: "••••••23",
  started_at: "2026-08-14T09:00:00Z",
  duration_s: 62,
  outcome_tag: "resolved",
  sentiment: "neutral",
  summary: "Caller asked about a Tuesday slot.",
  lead_id: null,
  transcript: [
    { idx: 0, speaker: "agent", text: "Namaskaram.", lang: "te", start_ms: 0, redacted: true },
  ],
  extraction: {},
  extraction_valid: true,
  has_recording: false,
  disclosure_played: true,
};

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read", "billing:read", "org:manage"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", plan_tier: "self_serve" },
} as unknown as Me;

const STAFF: Me = { ...ME, permissions: ["calls:read"] } as unknown as Me;

const AT_CEILING: AiQuota = {
  month: "2026-08",
  plan_tier: "self_serve",
  state: "ceiling_reached",
  included_inr: "100.00",
  used_inr: "100.00",
  allowance_inr: "100.00",
  remaining_inr: "0.00",
  requests_used: 214,
  // 133, not 200: ₹100 included ÷ the ₹0.75 nominal. A fixture the server could
  // not answer with is a wrong number carrying a fixture's authority.
  requests_included: 133,
  requests_remaining: 0,
  extra_purchased_inr: null,
  extra_block_inr: "500.00",
  extra_block_requests: 666,
  extra_available: true,
  extra_unavailable_reason: null,
};

/** The refusal `require_ai_assist` raises at the ceiling, as `apiRequest` will see it. */
const QUOTA_EXCEEDED = problem(422, {
  type: "https://calevate.tech/problems/ai_quota_exceeded",
  title: "Request rejected by a business rule",
  detail: "This account has used all of this month's included AI help.",
  kind: "business_rule",
  remediation: "Open AI assistance to see what more AI help costs and to add it.",
});

function page() {
  return <CallDetailPage params={Promise.resolve({ slug: "acme", callId: "c1" })} />;
}

/** The base route table every test needs: identity, the call, and the follow-up read. */
function baseRoutes(me: Me = ME): Record<string, unknown> {
  return {
    "/v1/me": me,
    "/v1/calls/c1": CALL,
    "/v1/calls/c1/callback": { eligible: false, reason: "already followed up twice" },
  };
}

async function pressAssist(): Promise<void> {
  const button = await screen.findByRole("button", { name: /Re-summarise with AI/i });
  await act(async () => {
    fireEvent.click(button);
  });
}

describe("the assistant's answer", () => {
  it("shows the summary the server returned, and does not touch the stored one", async () => {
    await renderClientPage(page(), {
      ...baseRoutes(),
      "POST /v1/calls/c1/assist": {
        summary: "Ravi wants a Tuesday appointment and will confirm by evening.",
        disclosure: null,
        metered: true,
      },
    });

    await pressAssist();

    expect(
      await screen.findByText("Ravi wants a Tuesday appointment and will confirm by evening."),
    ).toBeTruthy();
    // The FIRST pass is still on the screen, unchanged. A re-summarise is a second
    // reading (`apps/api/crm/assist.py`), and a screen that replaced one with the other
    // would make the server's decision not to persist invisible.
    expect(screen.getByText("Caller asked about a Tuesday slot.")).toBeTruthy();
    // Nothing says "this did not use any of your allowance" for a metered assist: that
    // sentence is a claim about a client's money and it is only true when it is true.
    expect(screen.queryByText(/did not use any of your AI allowance/i)).toBeNull();
  });

  it("shows the disclosure when a different model wrote the answer (G-6)", async () => {
    const disclosure =
      "This was written by Sarvam, not the assistant model, because the assistant model did not answer.";
    await renderClientPage(page(), {
      ...baseRoutes(),
      "POST /v1/calls/c1/assist": {
        summary: "Ravi wants a Tuesday appointment.",
        disclosure,
        metered: false,
      },
    });

    await pressAssist();

    // The server's own sentence, verbatim — not a paraphrase this build composed, which
    // is the whole reason `AssistCapability.disclosure` exists on the wire at all.
    expect(await screen.findByText(disclosure)).toBeTruthy();
    expect(screen.getByText(/did not use any of your AI allowance/i)).toBeTruthy();
  });

  it("states an empty answer in words rather than rendering a blank panel (§52)", async () => {
    await renderClientPage(page(), {
      ...baseRoutes(),
      "POST /v1/calls/c1/assist": { summary: "   ", disclosure: null, metered: true },
    });

    await pressAssist();

    // A completed run that produced nothing is an OUTCOME the client paid for, and an
    // empty state must not stand in for it.
    expect(await screen.findByText(/did not produce a summary for it/i)).toBeTruthy();
  });

  it("is a skeleton while it runs and a refusal when it fails", async () => {
    const loading = await renderClientPage(page(), {
      ...baseRoutes(),
      "POST /v1/calls/c1/assist": stillLoading(),
    });
    await pressAssist();
    expect(await screen.findByText("Reading the call…")).toBeTruthy();
    expect(loading.container.querySelector(".animate-pulse")).toBeTruthy();
    loading.unmount();

    await renderClientPage(page(), {
      ...baseRoutes(),
      "POST /v1/calls/c1/assist": problem(502, {
        type: "https://calevate.tech/problems/assist_provider_unavailable",
        title: "AI assistance is not available",
        detail: "This deployment cannot run the AI assistant right now.",
        kind: "dependency",
        remediation: "Try again in a few minutes; if it persists, contact support.",
      }),
    });
    await pressAssist();
    // The SERVER's remediation, rendered verbatim by `ProblemNotice` — the sentence a
    // person can act on, not "something went wrong".
    expect(await screen.findByText(/Try again in a few minutes/i)).toBeTruthy();
  });
});

describe("the ceiling", () => {
  it("opens the EXISTING wallet dialog, with the server's figure and no charge yet", async () => {
    const { calls } = await renderClientPage(page(), {
      ...baseRoutes(),
      "POST /v1/calls/c1/assist": QUOTA_EXCEEDED,
      "/v1/billing/ai-quota": AT_CEILING,
    });

    await pressAssist();

    expect(await screen.findByText(/used this month's included AI help/i)).toBeTruthy();
    // The quota is read only AFTER the ceiling is met — an owner who never hits it never
    // pays for the request (`useAiQuota(session, { enabled })`).
    await waitFor(() => {
      expect(calls.some((c) => c.path === "/v1/billing/ai-quota")).toBe(true);
    });

    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: /what more AI help costs/i }));
    });

    const dialog = await screen.findByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    // The one dialog, identified by the sentences only it says. Digits exactly as the
    // server sent them, and the honest cost of a block stated before the click.
    expect(screen.getByText("Add more AI help this month")).toBeTruthy();
    // The figure, as DIGITS, in the sentence a person reads before deciding — asserted on
    // the element rather than by text search, because the same string is also the accept
    // button's label and "one of the two is right" is not the claim.
    expect(dialog.querySelector("strong")?.textContent).toBe("₹500.00");
    expect(screen.getByRole("button", { name: /^Add ₹500\.00$/ })).toBeTruthy();
    expect(screen.getByText(/not refunded and does not carry into next month/i)).toBeTruthy();
    expect(screen.getByText("Nothing has been charged yet.")).toBeTruthy();
    // G-5, on the NETWORK rather than on the screen: opening the dialog spends nothing.
    expect(calls.filter((c) => c.path === "/v1/billing/ai-quota/extra")).toEqual([]);

    // Swept while OPEN, which the page sweep in `a11y.test.tsx` cannot do: the dialog is
    // the one control on this screen that debits a wallet, and it must be reachable and
    // named for a screen reader before it is reachable at all.
    await expectNoA11yViolations(dialog, "call detail — add more AI help dialog");
  });

  it("debits only on accept, and echoes the server's amount untouched", async () => {
    const { calls } = await renderClientPage(page(), {
      ...baseRoutes(),
      "POST /v1/calls/c1/assist": QUOTA_EXCEEDED,
      "/v1/billing/ai-quota": AT_CEILING,
      "POST /v1/billing/ai-quota/extra": {
        ...AT_CEILING,
        state: "within",
        extra_purchased_inr: "500.00",
      },
    });

    await pressAssist();
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: /what more AI help costs/i }));
    });
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: /^Add ₹500\.00$/ }));
    });

    const bought = calls.filter((c) => c.path === "/v1/billing/ai-quota/extra");
    expect(bought).toHaveLength(1);
    // A STRING, exactly as it arrived. `500` as a JSON number has already been through a
    // binary double by the time the server compares it for equality (hard rule 7).
    expect(JSON.parse(bought[0].body ?? "{}")).toEqual({ accept_amount_inr: "500.00" });
  });

  it("does not offer a purchase the server would refuse", async () => {
    await renderClientPage(page(), {
      ...baseRoutes(),
      "POST /v1/calls/c1/assist": QUOTA_EXCEEDED,
      "/v1/billing/ai-quota": {
        ...AT_CEILING,
        extra_available: false,
        extra_unavailable_reason: "already_purchased",
      },
    });

    await pressAssist();

    // The SERVER's reason, mapped to the same sentence the AI-help screen shows — one
    // switch, shared, so the two cannot start disagreeing about the same month.
    expect(await screen.findByText(/already added extra AI help this month/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /what more AI help costs/i })).toBeNull();
  });

  it("says it could not read the allowance rather than offering nothing", async () => {
    await renderClientPage(page(), {
      ...baseRoutes(),
      "POST /v1/calls/c1/assist": QUOTA_EXCEEDED,
      "/v1/billing/ai-quota": problem(503, {
        type: "https://calevate.tech/problems/service_unavailable",
        title: "Temporarily unavailable",
        detail: "The allowance could not be read.",
        kind: "transient",
        remediation: "Try again in a moment.",
      }),
    });

    await pressAssist();

    // §52's failure branch on the SECOND read. Without it, a dead billing route renders a
    // ceiling notice with no button and no explanation — indistinguishable from "there is
    // nothing you can do", which is the opposite of the truth.
    expect(await screen.findByText("The allowance could not be read.")).toBeTruthy();
  });
});

describe("the gate", () => {
  it("is previewed as a disabled control with a reason, never a 403 after the click", async () => {
    const { calls } = await renderClientPage(page(), baseRoutes(STAFF));

    const button = await screen.findByRole("button", { name: /Re-summarise with AI/i });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/Only an account owner can use AI help on this call/i)).toBeTruthy();
    await act(async () => {
      fireEvent.click(button);
    });
    expect(calls.filter((c) => c.path === "/v1/calls/c1/assist")).toEqual([]);
  });

  it("sends an Idempotency-Key, and a second press sends a different one", async () => {
    const { calls } = await renderClientPage(page(), {
      ...baseRoutes(),
      "POST /v1/calls/c1/assist": { summary: "Again.", disclosure: null, metered: true },
    });

    await pressAssist();
    await pressAssist();

    const sent = calls.filter((c) => c.path === "/v1/calls/c1/assist");
    expect(sent).toHaveLength(2);
    // The server REQUIRES the header (a repeat is a second payment to Google), and the
    // key is per ATTEMPT: two deliberate presses are two attempts, so a key reused across
    // them would answer the second ask with the first answer forever.
    const keys = sent.map((c) => c.headers["idempotency-key"] ?? c.headers["Idempotency-Key"]);
    expect(keys.every(Boolean)).toBe(true);
    expect(new Set(keys).size).toBe(2);
  });
});
