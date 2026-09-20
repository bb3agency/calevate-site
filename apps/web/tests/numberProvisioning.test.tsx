import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PhoneNumberPage from "@/app/c/[slug]/phone-number/page";
import type { Me } from "@/lib/api/client";
import { PATHS } from "@/lib/api/numberProvisioning";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderClientPage, stillLoading, type Routes } from "./harness";

/**
 * GETTING A PHONE NUMBER, AND THE STATE EVERY CLIENT IS ACTUALLY IN.
 *
 * Five properties, each a way this screen could mislead somebody who cannot afford to be
 * misled:
 *
 * - **A deployment that may not sell says so in the SERVER's words.** Buying is refused
 *   today because no written reseller authorisation is recorded
 *   (`apps/api/campaigns/provisioning.py`), and the API answers one sentence whichever
 *   gate is shut so the shape of an error publishes nothing about our paperwork. A dead
 *   button or an empty state would leave a client waiting for something not coming.
 * - **A recurring charge is stated before it is incurred.** The figure goes through
 *   `formatINR`, which formats the server's decimal DIGITS and never parses them (hard
 *   rule 7); `formatterGuard.test.ts` makes the hand-rolled spelling unwriteable and this
 *   checks the rendering that guard cannot see.
 * - **A double submit buys one number.** The key is minted per ATTEMPT, so both presses
 *   carry the same one and the API answers the second with the first purchase.
 * - **Verification gates ACTIVATION, not the sale.** An unverified client may buy and is
 *   told what they are getting; they are not refused something the API allows.
 * - **Choosing to call OUT must not imply a freedom the number does not have.**
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["calls:read", "leads:read", "org:read", "org:manage", "wallet:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

/** `self_serve_purchase_refused()` — the sentence every closed gate answers with. */
const REFUSAL =
  "A phone number cannot be bought from this screen. Numbers are arranged with your " +
  "account manager as part of setting your agent up.";

const REMEDIATION =
  "Talk to us and we will arrange the number, or bring one you already hold.";

const STATEMENT = "I confirm that my business is the sender of these calls.";

function operatorLed(): unknown {
  return problem(422, {
    type: "https://calevate.tech/problems/number_purchase_is_operator_led",
    detail: REFUSAL,
    remediation: REMEDIATION,
  });
}

function kyc(verified: boolean): unknown {
  return {
    recorded: verified,
    is_verified: verified,
    number_purchase_available: false,
    status: verified ? "accepted" : "not_started",
  };
}

/** `OfferedNumberOut`. The price is deliberately over ₹1,00,000 — see the price test. */
function offer(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    e164: "+918041234500",
    region: "Karnataka",
    locality: "Bengaluru",
    series: "standard",
    inr_per_month: "149900.00",
    ...over,
  };
}

function holder(recorded: boolean): unknown {
  return recorded
    ? {
        recorded: true,
        holder_type: "business",
        holder_name: "Acme Dental",
        holder_email: "owner@example.com",
      }
    : { recorded: false, holder_type: null, holder_name: null, holder_email: null };
}

/** One number the client already holds, which is what the assignment panel hangs off. */
function heldNumbers(): unknown {
  return [
    {
      id: "num-1",
      e164: "+918041234567",
      series: "standard",
      dlt_status: "registered",
      supplied_by_us: false,
      answerable: true,
    },
  ];
}

/** The screen when this deployment MAY sell. `extra` overrides any entry. */
function routes(extra: Routes = {}): Routes {
  return {
    "/v1/me": OWNER,
    "/v1/campaigns/numbers": heldNumbers(),
    "/v1/agents": [{ id: "agent-1", name: "Reception", status: "live" }],
    "/v1/numbers/num-1/sender-attestation": {
      attested: false,
      applicable: true,
      statement: STATEMENT,
      statement_version: "2026-09-20",
    },
    "/v1/compliance/kyc": kyc(true),
    "/v1/billing/wallet": { prepaid: true, balance_inr: "200000.00" },
    [PATHS.available]: [offer()],
    [PATHS.holder]: holder(true),
    ...extra,
  };
}

describe("a deployment that may not supply a number says so", () => {
  const closed = routes({ [PATHS.available]: operatorLed() });

  it("renders the server's own sentence and its remediation", async () => {
    const { container } = await renderClientPage(<PhoneNumberPage />, closed);

    expect(await screen.findByText(REFUSAL)).toBeTruthy();
    expect(screen.getByText(REMEDIATION)).toBeTruthy();
    await expectNoA11yViolations(container, "phone-number: cannot supply");
  });

  it("offers no way to buy and asks for no registrant details", async () => {
    await renderClientPage(<PhoneNumberPage />, closed);

    await screen.findByText(REFUSAL);
    expect(screen.queryByRole("button", { name: /buy this number/i })).toBeNull();
    // Collecting a permanent registration for a number that cannot be sold would be
    // asking for something we have no use for.
    expect(screen.queryByLabelText(/full name/i)).toBeNull();
  });

  it("still sends an unverified client somewhere they can act", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({ [PATHS.available]: operatorLed(), "/v1/compliance/kyc": kyc(false) }),
    );

    const link = await screen.findByRole("link", { name: /verify your business/i });
    expect(link.getAttribute("href")).toBe("/c/acme/verification");
  });

  it("refuses rather than guessing when it could not ask at all", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({ [PATHS.available]: problem(503, { detail: "Upstream is down." }) }),
    );

    expect(await screen.findByText("Upstream is down.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /buy this number/i })).toBeNull();
  });

  it("shows a skeleton rather than a refusal while the answer is in flight", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({ [PATHS.available]: stillLoading() }),
    );

    expect(await screen.findByText(/loading what we can supply/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /buy this number/i })).toBeNull();
  });
});

describe("browsing what is on offer", () => {
  it("prices the month through the shared rupee formatter", async () => {
    const { container } = await renderClientPage(<PhoneNumberPage />, routes());

    // `formatINR("149900.00")`: Indian grouping and two paise, from the digits the server
    // sent. `₹149900.00` is what a template literal would have printed.
    expect(await screen.findByText(/₹1,49,900\.00 a month/)).toBeTruthy();
    expect(container.textContent).toContain("₹2,00,000.00");
  });

  it("says who the number will be registered to, and that it is permanent", async () => {
    await renderClientPage(<PhoneNumberPage />, routes({ [PATHS.holder]: holder(false) }));

    expect(
      await screen.findByText(/registered to your business, not to Calevate/i),
    ).toBeTruthy();
    expect(screen.getByText(/cannot be changed later/i)).toBeTruthy();
  });

  it("will not sell until the registrant is on file", async () => {
    await renderClientPage(<PhoneNumberPage />, routes({ [PATHS.holder]: holder(false) }));

    const buy = await screen.findByRole("button", { name: /buy this number/i });
    expect(buy.hasAttribute("disabled")).toBe(true);
    expect(buy.getAttribute("title")).toMatch(/registered to first/i);
  });

  it("records the registrant once, with the type it was told", async () => {
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes({
        [PATHS.holder]: holder(false),
        [`POST ${PATHS.holder}`]: holder(true),
      }),
    );

    fireEvent.click(await screen.findByLabelText(/an individual/i));
    fireEvent.change(screen.getByLabelText(/full name/i), {
      target: { value: "Acme Dental" },
    });
    fireEvent.change(screen.getByLabelText(/email address/i), {
      target: { value: "owner@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save these details/i }));

    await waitFor(() => {
      const post = calls.find((call) => call.method === "POST" && call.path === PATHS.holder);
      expect(post).toBeTruthy();
      expect(JSON.parse(post!.body ?? "{}")).toEqual({
        holder_type: "individual",
        holder_name: "Acme Dental",
        holder_email: "owner@example.com",
      });
    });
    expect(await screen.findByText(/it cannot be changed/i)).toBeTruthy();
  });

  it("sells to an unverified client and says what they are getting", async () => {
    await renderClientPage(<PhoneNumberPage />, routes({ "/v1/compliance/kyc": kyc(false) }));

    expect(
      await screen.findByText(/will not be able to make or take calls until your business is verified/i),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /buy this number/i }).hasAttribute("disabled"),
    ).toBe(false);
  });
});

describe("buying", () => {
  const purchased = {
    id: "num-2",
    e164: "+918041234500",
    series: "standard",
    direction: "inbound",
    inr_per_month: "149900.00",
    activated: false,
  };

  async function openConfirmation(extra: Routes = {}) {
    const render = await renderClientPage(<PhoneNumberPage />, routes(extra));
    await screen.findByText(/₹1,49,900\.00 a month/);
    fireEvent.click(screen.getByRole("button", { name: /buy this number/i }));
    return render;
  }

  function confirmButton(): HTMLElement {
    return within(screen.getByRole("dialog")).getByRole("button", {
      name: /buy this number/i,
    });
  }

  it("states the recurring charge and the balance before it is incurred", async () => {
    await openConfirmation();

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("₹1,49,900.00 every month");
    expect(dialog.textContent).toContain("₹2,00,000.00 before this purchase");
    expect(dialog.textContent).toMatch(/registered to Acme Dental/);
  });

  it("sends the number and what it is for", async () => {
    const { calls } = await openConfirmation({ [`POST ${PATHS.purchase}`]: purchased });

    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText(/^both/i));
    fireEvent.click(confirmButton());

    await waitFor(() => {
      const post = calls.find(
        (call) => call.method === "POST" && call.path === PATHS.purchase,
      );
      expect(post).toBeTruthy();
      expect(JSON.parse(post!.body ?? "{}")).toEqual({
        e164: "+918041234500",
        country: "IN",
        direction: "both",
      });
    });
  });

  it("carries one idempotency key across a double submit", async () => {
    // NEVER ANSWERS, which is the only way to reach the double-submit window: a route
    // that settles closes the dialog before a second press can land.
    const { calls } = await openConfirmation({
      [`POST ${PATHS.purchase}`]: stillLoading(),
    });

    const confirm = confirmButton();
    fireEvent.click(confirm);
    fireEvent.click(confirm);

    await waitFor(() => {
      const posts = calls.filter(
        (call) => call.method === "POST" && call.path === PATHS.purchase,
      );
      expect(posts.length).toBeGreaterThan(0);
      const keys = new Set(posts.map((post) => post.headers["Idempotency-Key"]));
      expect(keys.size).toBe(1);
      expect([...keys][0]).toBeTruthy();
    });
  });

  it("turns not enough credit into a top-up rather than a fault", async () => {
    await openConfirmation({
      [`POST ${PATHS.purchase}`]: problem(402, {
        type: "https://calevate.tech/problems/number_insufficient_credit",
        detail: "Your calling credit does not cover the first month.",
      }),
    });

    fireEvent.click(confirmButton());

    const dialog = await screen.findByRole("dialog");
    await waitFor(() =>
      expect(dialog.textContent).toContain(
        "Your calling credit does not cover the first month.",
      ),
    );
    expect(
      within(dialog).getByRole("link", { name: /top up credit/i }).getAttribute("href"),
    ).toBe("/c/acme/billing?tab=credits");
  });

  it("reports a bought number that cannot ring yet, with the way to fix it", async () => {
    await openConfirmation({
      "/v1/compliance/kyc": kyc(false),
      [`POST ${PATHS.purchase}`]: purchased,
    });

    fireEvent.click(confirmButton());

    expect(await screen.findByText("+918041234500 is yours")).toBeTruthy();
    expect(
      screen.getByText(/cannot be put on an agent, until your business is verified/i),
    ).toBeTruthy();
    expect(
      screen.getAllByRole("link", { name: /verify your business/i })[0].getAttribute("href"),
    ).toBe("/c/acme/verification");
  });
});

describe("choosing what a number is used for", () => {
  it("offers answering, calling out, and both", async () => {
    await renderClientPage(<PhoneNumberPage />, routes());

    expect(await screen.findByLabelText(/answer calls to this number/i)).toBeTruthy();
    expect(screen.getByLabelText(/call out from this number/i)).toBeTruthy();
    expect(screen.getByLabelText(/^both/i)).toBeTruthy();
  });

  it("says nothing extra while only answering is chosen", async () => {
    await renderClientPage(<PhoneNumberPage />, routes());

    await screen.findByLabelText(/answer calls to this number/i);
    expect(screen.queryByText(/confirmed that your business is the sender/i)).toBeNull();
  });

  it("points calling out at the confirmation rather than restating it", async () => {
    await renderClientPage(<PhoneNumberPage />, routes());

    fireEvent.click(await screen.findByLabelText(/call out from this number/i));

    const note = await screen.findByText(
      /confirmed that your business is the sender of those calls/i,
    );
    expect(note.textContent).toMatch(/marketing campaigns need a 140-series number/i);
    // The statement itself belongs to the attestation panel and is not duplicated here.
    expect(screen.getAllByText(STATEMENT).length).toBe(1);
  });

  it("tells the voice platform which agent and which legs", async () => {
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes({
        [`POST ${PATHS.assign("num-1")}`]: {
          number_id: "num-1",
          agent_id: "agent-1",
          bound: 1,
          released: 0,
          failed: 0,
          unsupported: 0,
        },
      }),
    );

    fireEvent.change(await screen.findByLabelText(/the agent that uses it/i), {
      target: { value: "agent-1" },
    });
    fireEvent.click(screen.getByLabelText(/^both/i));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      const post = calls.find((call) => call.path === PATHS.assign("num-1"));
      expect(post).toBeTruthy();
      expect(JSON.parse(post!.body ?? "{}")).toEqual({
        agent_id: "agent-1",
        direction: "both",
      });
    });
    expect(await screen.findByText(/that agent now uses this number/i)).toBeTruthy();
  });

  it("does not report a binding the voice platform refused", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({
        [`POST ${PATHS.assign("num-1")}`]: {
          number_id: "num-1",
          agent_id: "agent-1",
          bound: 0,
          released: 0,
          failed: 1,
          unsupported: 0,
        },
      }),
    );

    fireEvent.change(await screen.findByLabelText(/the agent that uses it/i), {
      target: { value: "agent-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    expect(
      await screen.findByText(/did not accept that, so this number is not on an agent/i),
    ).toBeTruthy();
  });
});
