import { cleanup, render, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TrialStrip } from "@/app/c/[slug]/TrialBanner";
import { activeTrial, trialEndsAt, trialTimeLeft, walletState } from "@/lib/api/wallet";

import { activeTrialBlock, prepaidWallet } from "./fixtures/sharedReads";

/**
 * The client's own view of a trial (D-536): a strip on every screen saying calls are on
 * us and until when, a countdown that switches to hours on the last day, and a top-up
 * prompt only in those last 24 hours.
 *
 * The end instant in the fixture is 2026-10-10T17:28:00Z, which is 10 Oct, 10:58 pm in
 * India — the founder's own example. Every clock here is passed in, so the countdown is
 * asserted against a known instant rather than whenever the suite happens to run.
 */

afterEach(cleanup);

const CREDITS = "/c/acme/billing?tab=credits";
const ENDS = new Date("2026-10-10T17:28:00Z");
const hoursBefore = (hours: number) => new Date(ENDS.getTime() - hours * 3_600_000);

/** An EMPTY prepaid wallet on a trial — the founder's screenshot: ₹0.00 and "running low". */
function onTrial(over: Partial<NonNullable<ReturnType<typeof activeTrialBlock>>> = {}) {
  return prepaidWallet({
    balance_inr: "0.00",
    is_low: true,
    // The server's own verdict during a trial: the credit gate is bypassed.
    outbound_stopped: false,
    minutes_left: null,
    trial: activeTrialBlock(over),
  });
}

describe("the trial strip", () => {
  it("says the account is on a free trial, until when in IST, and how many days are left", () => {
    const { container } = render(
      <TrialStrip wallet={onTrial()} creditsHref={CREDITS} now={hoursBefore(70)} />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("You're on a free trial until 10 Oct, 10:58 pm IST — 3 days left.");
    expect(text).toContain("Calls are on us until then");
    expect(text).toContain("an empty balance does not stop your agents making or answering calls");
    // Not the last day: no top-up prompt yet.
    expect(text).not.toContain("Add credit");
    expect(container.querySelector('[role="status"]')).not.toBeNull();
  });

  it("counts in hours on the last day and asks for a top-up, with a link to add credit", () => {
    const { container } = render(
      <TrialStrip
        wallet={onTrial({ days_remaining: 1 })}
        creditsHref={CREDITS}
        now={hoursBefore(5)}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Your free trial ends 10 Oct, 10:58 pm IST — 5 hours left.");
    expect(text).toContain("Add credit now so calls carry on when the trial ends.");
    const link = within(container).getByRole("link", { name: "Add credit" });
    expect(link.getAttribute("href")).toBe(CREDITS);
  });

  it("does not ask an invoiced account to top up a wallet it does not have", () => {
    const { container } = render(
      <TrialStrip
        wallet={{ ...onTrial({ days_remaining: 1 }), prepaid: false }}
        creditsHref={CREDITS}
        now={hoursBefore(2)}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("2 hours left");
    expect(text).toContain("billed on your monthly invoice as usual");
    expect(within(container).queryByRole("link")).toBeNull();
  });

  it("renders nothing with no trial, with an ended trial, or before the wallet has loaded", () => {
    for (const wallet of [
      prepaidWallet(),
      prepaidWallet({
        trial: activeTrialBlock({
          active: false,
          status: "expired",
          days_remaining: null,
          ended_at: "2026-10-10T17:28:00Z",
        }),
      }),
      undefined,
    ]) {
      const { container } = render(<TrialStrip wallet={wallet} creditsHref={CREDITS} />);
      expect(container.textContent).toBe("");
      cleanup();
    }
  });

  it("never names a supplier or a cost", () => {
    const { container } = render(
      <TrialStrip wallet={onTrial({ days_remaining: 1 })} creditsHref={CREDITS} now={hoursBefore(3)} />,
    );
    const text = (container.textContent ?? "").toLowerCase();
    for (const word of ["cost to", "vobiz", "cartesia", "gnani", "sarvam", "pipecat"]) {
      expect(text).not.toContain(word);
    }
  });
});

describe("the wallet's trial state", () => {
  it("is `trial`, not `low`, for an empty wallet while a trial runs", () => {
    expect(walletState(onTrial())).toBe("trial");
    // The control: the same empty wallet with no trial IS low.
    expect(walletState(prepaidWallet({ balance_inr: "0.00", is_low: true }))).toBe("low");
  });

  it("follows the server's `active`, so a trial past its end that nobody has swept is over", () => {
    const stale = prepaidWallet({
      balance_inr: "0.00",
      is_low: true,
      outbound_stopped: true,
      trial: activeTrialBlock({ active: false, days_remaining: null }),
    });
    expect(activeTrial(stale)).toBeNull();
    expect(walletState(stale)).toBe("stopped");
  });

  it("uses the server's rounded-up day count and splits only the last day into hours", () => {
    const trial = activeTrialBlock();
    expect(trialTimeLeft({ ...trial, days_remaining: 2 }, hoursBefore(30)).text).toBe("2 days left");
    expect(trialTimeLeft({ ...trial, days_remaining: 1 }, hoursBefore(23.5))).toEqual({
      lastDay: true,
      text: "24 hours left",
    });
    expect(trialTimeLeft({ ...trial, days_remaining: 1 }, hoursBefore(0.2))).toEqual({
      lastDay: true,
      text: "1 hour left",
    });
    expect(trialEndsAt(trial)).toBe("10 Oct, 10:58 pm IST");
  });
});
