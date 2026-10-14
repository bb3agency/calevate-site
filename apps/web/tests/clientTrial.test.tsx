import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { TrialChipView, TrialStrip, trialStripClosedKey, trialView } from "@/app/c/[slug]/TrialBanner";
import { activeTrial, trialEndsAt, trialTimeLeft, walletState } from "@/lib/api/wallet";

import { activeTrialBlock, prepaidWallet } from "./fixtures/sharedReads";

/**
 * The client's own view of a trial (D-536, D-697): a chip in the top bar while it runs,
 * a countdown that switches to hours on the last day, and a strip above the bar only when
 * the trial needs acting on.
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

describe("the trial strip above the top bar", () => {
  beforeEach(() => window.localStorage.clear());

  it("stays away on an ordinary trial day: the chip in the bar carries the trial", () => {
    const { container } = render(
      <TrialStrip wallet={onTrial()} slug="acme" creditsHref={CREDITS} now={hoursBefore(70)} />,
    );
    expect(container.textContent).toBe("");
  });

  it("says the trial ends today on its last IST day, with a link to add credit", () => {
    // 10 Oct, 5:58 pm IST: five hours before the 10:58 pm end, the same Indian day.
    const { container } = render(
      <TrialStrip wallet={onTrial({ days_remaining: 1 })} slug="acme" creditsHref={CREDITS} now={hoursBefore(5)} />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Your trial ends today.");
    expect(text).toContain("Add credit to keep your agents answering.");
    expect(within(container).getByRole("link", { name: "Add credit" }).getAttribute("href")).toBe(CREDITS);
  });

  it("says tomorrow when the last 24 hours cross midnight in India", () => {
    // 9 Oct, 11:58 pm IST: 23 hours before the end, which falls on the next Indian day.
    const { container } = render(
      <TrialStrip wallet={onTrial({ days_remaining: 1 })} slug="acme" creditsHref={CREDITS} now={hoursBefore(23)} />,
    );
    expect(container.textContent).toContain("Your trial ends tomorrow.");
  });

  it("warns when under a tenth of the free minutes are left", () => {
    const wallet = onTrial({ test_calls_only: true, free_minutes: 100, minutes_left: 9 });
    const { container } = render(
      <TrialStrip wallet={wallet} slug="acme" creditsHref={CREDITS} now={hoursBefore(70)} />,
    );
    expect(container.textContent).toContain("Only 9 free minutes left.");
    cleanup();
    const plenty = onTrial({ test_calls_only: true, free_minutes: 100, minutes_left: 10 });
    const again = render(<TrialStrip wallet={plenty} slug="acme" creditsHref={CREDITS} now={hoursBefore(70)} />);
    expect(again.container.textContent).toBe("");
  });

  it("does not ask an invoiced account to top up a wallet it does not have", () => {
    const { container } = render(
      <TrialStrip
        wallet={{ ...onTrial({ days_remaining: 1 }), prepaid: false }}
        slug="acme"
        creditsHref={CREDITS}
        now={hoursBefore(2)}
      />,
    );
    expect(container.textContent).toContain("calls go on your monthly invoice");
    expect(within(container).queryByRole("link")).toBeNull();
  });

  it("closes until the next IST day, remembered for this account", () => {
    const now = hoursBefore(5);
    const { container } = render(
      <TrialStrip wallet={onTrial({ days_remaining: 1 })} slug="acme" creditsHref={CREDITS} now={now} />,
    );
    fireEvent.click(within(container).getByRole("button", { name: "Close until tomorrow" }));
    expect(container.textContent).toBe("");
    expect(trialStripClosedKey("acme", now)).toBe("calevate:trial-strip-closed:acme:2026-10-10");
    expect(window.localStorage.getItem("calevate:trial-strip-closed:acme:2026-10-10")).toBe("1");
    cleanup();
    // Same day: stays closed. The next IST day: back.
    const same = render(
      <TrialStrip wallet={onTrial({ days_remaining: 1 })} slug="acme" creditsHref={CREDITS} now={hoursBefore(4)} />,
    );
    expect(same.container.textContent).toBe("");
    cleanup();
    const other = render(
      <TrialStrip wallet={onTrial({ days_remaining: 1 })} slug="other" creditsHref={CREDITS} now={hoursBefore(4)} />,
    );
    expect(other.container.textContent).toContain("Your trial ends today.");
  });

  it("renders nothing with no trial, a converted trial, or before the wallet has loaded", () => {
    for (const wallet of [
      prepaidWallet(),
      prepaidWallet({
        trial: activeTrialBlock({ active: false, status: "expired", days_remaining: null, ended_at: "2026-10-10T17:28:00Z" }),
      }),
      undefined,
    ]) {
      const { container } = render(<TrialStrip wallet={wallet} slug="acme" creditsHref={CREDITS} />);
      expect(container.textContent).toBe("");
      cleanup();
    }
  });
});

describe("the trial chip in the top bar", () => {
  it("reads Trial, days and minutes, and its panel gives the end, minutes, test calls and the way on", () => {
    const wallet = onTrial({ test_calls_only: true, free_minutes: 1000, minutes_left: 997, days_remaining: 4 });
    const view = trialView(wallet);
    if (view === null) throw new Error("expected a trial");
    render(
      <TrialChipView view={view} creditsHref={CREDITS} open callsToday={{ used: 2, cap: 10 }} now={hoursBefore(90)} />,
    );
    const chip = screen.getByRole("button", { name: /Free trial/ });
    expect(chip.textContent).toContain("Trial · 4 days · 997 min");
    expect(chip.textContent).toContain("Trial · 4d");
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    const panel = screen.getByRole("dialog", { name: "Your free trial" });
    const text = panel.textContent ?? "";
    expect(text).toContain("10 Oct, 10:58 pm IST");
    expect(text).toContain("997 of 1000");
    expect(text).toContain("2 of 10");
    expect(text).toContain("open once you add credit");
    expect(within(panel).getByRole("link", { name: "Add credit" }).getAttribute("href")).toBe(CREDITS);
  });

  it("says the trial has ended once a test-calls trial runs out unpaid, and goes straight to credits", () => {
    const view = trialView(
      prepaidWallet({ trial: activeTrialBlock({ active: false, status: "expired", days_remaining: null, test_calls_only: true }) }),
    );
    if (view === null) throw new Error("expected an ended trial");
    render(<TrialChipView view={view} creditsHref={CREDITS} />);
    // One next step, so the bar item is that step: a link straight to credits, no panel.
    const chip = screen.getByRole("link", { name: "Free trial ended. Add credit" });
    expect(chip.getAttribute("href")).toBe(CREDITS);
    expect(chip.textContent).toContain("Trial ended");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("never names a supplier or a cost", () => {
    const view = trialView(onTrial({ days_remaining: 1 }));
    if (view === null) throw new Error("expected a trial");
    const { baseElement } = render(<TrialChipView view={view} creditsHref={CREDITS} open now={hoursBefore(3)} />);
    const text = (baseElement.textContent ?? "").toLowerCase();
    for (const word of ["cost to", "cartesia", "sarvam", "plivo", "thinnest"]) {
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
