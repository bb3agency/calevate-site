import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { firstPeriodSentence } from "@/app/c/[slug]/phone-number/OwnNumbers";
import PhoneNumberPage from "@/app/c/[slug]/phone-number/page";
import VerifyBusinessPage from "@/app/c/[slug]/verify-business/page";
import type { Me } from "@/lib/api/client";
import { OWN_NUMBERS_PATHS, type OwnNumbersStatus } from "@/lib/api/ownNumbers";

import { expectNoA11yViolations } from "./a11y";
import { DLT_NOT_RECORDED, KYC_NOT_STARTED } from "./fixtures/sharedReads";
import { problem, renderClientPage, type ApiCall, type Routes } from "./harness";
import { NO_FORWARDING_ROUTES } from "./fixtures/forwarding";

/**
 * A phone number in the business's own name (D-693), on the client's phone-number screen.
 *
 * - Each step the server names is drawn as that step, never as a button the purchase gate
 *   will refuse.
 * - A press of Buy is ONE request key, reused on "press Buy again", so a retry finishes the
 *   same purchase instead of renting a second number.
 * - The confirmation claims a charge only when `first_period` says one happened.
 * - Releasing warns that it is permanent and that this month is not refunded.
 * - White label: no screen here names the company that hosts the calls.
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

const NUMBER_ID = "0192f0aa-7777-7000-8000-000000000abc";

function status(over: Partial<OwnNumbersStatus> = {}): OwnNumbersStatus {
  return {
    available: true,
    paid: true,
    trial: null,
    step: "ready",
    blocker: null,
    account_setup: "active",
    kyc_status: "verified",
    business_status: "accepted",
    business_review_note: null,
    business_submitted_at: "2026-10-08T09:41:12Z",
    can_send_business_details: false,
    inr_per_month: "499.00",
    ...over,
  };
}

function offer(n: number) {
  return { number: `91801234567${n}`, e164: `+91801234567${n}`, city: "Hyderabad", inr_per_month: "499.00" };
}

const FIRST_PAGE = `${OWN_NUMBERS_PATHS.available("Hyderabad", "", null)}`;
const SECOND_PAGE = `${OWN_NUMBERS_PATHS.available("Hyderabad", "", "c2")}`;

function routes(own: OwnNumbersStatus, extra: Routes = {}): Routes {
  return {
    "/v1/me": OWNER,
    ...NO_FORWARDING_ROUTES,
    "/v1/campaigns/numbers": [],
    "/v1/agents": [{ id: "agent-1", name: "Reception", status: "live" }],
    [OWN_NUMBERS_PATHS.status]: own,
    [OWN_NUMBERS_PATHS.cities]: [
      { name: "Hyderabad", available: 12 },
      { name: "Bengaluru", available: 3 },
    ],
    [FIRST_PAGE]: { numbers: [offer(1), offer(2)], next_cursor: "c2" },
    [SECOND_PAGE]: { numbers: [offer(3)], next_cursor: null },
    ...extra,
  };
}

function bodies(calls: ApiCall[], path: string): Record<string, unknown>[] {
  return calls
    .filter((call) => call.method === "POST" && call.path === path)
    .map((call) => JSON.parse(call.body ?? "null") as Record<string, unknown>);
}

/** A control gated on the account's permissions, once `/v1/me` has answered. */
async function enabledButton(name: string | RegExp): Promise<HTMLButtonElement> {
  const button = (await screen.findByRole("button", { name })) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  return button;
}

async function search() {
  fireEvent.change(await screen.findByLabelText("City"), { target: { value: "Hyderabad" } });
  fireEvent.click(screen.getByRole("button", { name: "Show numbers" }));
  await enabledButton("Buy +91 80123 45671");
}

/** An unpaid account on a free trial: the server refuses numbers with the add-credit step. */
function onTrial(over: Partial<OwnNumbersStatus> = {}): OwnNumbersStatus {
  return status({
    paid: false,
    trial: "running",
    step: "add_credit",
    blocker: "trial_numbers_unavailable",
    account_setup: "not_provisioned",
    business_status: null,
    business_submitted_at: null,
    ...over,
  });
}

const CREDITS_HREF = "/c/acme/billing?tab=credits";

describe("what the page shows for the account's state", () => {
  it("on a trial: says calls use the shared number, offers credit, and marks no step next", async () => {
    await renderClientPage(<PhoneNumberPage />, routes(onTrial()));
    expect(await screen.findByRole("heading", { name: "Your own phone number comes after the trial" })).toBeTruthy();
    expect(screen.getByText(/Trial calls use a shared number/)).toBeTruthy();
    const credit = screen.getAllByRole("link", { name: "Add credit" });
    expect(credit).toHaveLength(1);
    expect(credit[0].getAttribute("href")).toContain(CREDITS_HREF);
    // The verification already done shows as Done, so it does not read as lost.
    expect(screen.getByText("After you add credit")).toBeTruthy();
    expect(screen.getByText("Done")).toBeTruthy();
    expect(screen.queryByText("Next step")).toBeNull();
    expect(screen.queryByText("Waiting")).toBeNull();
    expect(screen.queryByText("Not sent yet.")).toBeNull();
    expect(screen.queryByRole("button", { name: /Send/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show numbers" })).toBeNull();
    // The flow says the trial itself, so the generic trial notice is not repeated above it.
    expect(screen.queryByText("Add credit to go live")).toBeNull();
  });

  it("on a trial with the business unverified: offers no verification, which opens after credit", async () => {
    await renderClientPage(<PhoneNumberPage />, routes(onTrial({ kyc_status: "not_started" })));
    await screen.findByRole("heading", { name: "Your own phone number comes after the trial" });
    // The server refuses every verification write on a trial (`trial_kyc_unavailable`).
    expect(screen.queryByRole("link", { name: "Verify your business" })).toBeNull();
    expect(screen.queryByText(/already verified/)).toBeNull();
    expect(screen.getByText("Needs your certificate and the owner's ID.")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "Add credit" })).toHaveLength(1);
    expect(screen.queryByText("Next step")).toBeNull();
  });

  it("after a trial that ended unpaid: says credit comes first, with credit the one action", async () => {
    await renderClientPage(<PhoneNumberPage />, routes(onTrial({ trial: "ended" })));
    expect(await screen.findByRole("heading", { name: "Add credit to get your own phone number" })).toBeTruthy();
    expect(
      screen.getByText(
        "Your trial has ended. Add credit to get a number.",
      ),
    ).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "Add credit" })[0].getAttribute("href")).toContain(CREDITS_HREF);
    expect(screen.queryByText("Next step")).toBeNull();
    expect(screen.queryByRole("button", { name: /Send/ })).toBeNull();
  });

  it("with no trial and nothing paid: asks for credit, since the calling account comes with it", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(
        status({
          paid: false,
          trial: null,
          step: "workspace",
          blocker: "engine_workspace_not_provisioned",
          account_setup: "not_provisioned",
          business_status: null,
        }),
      ),
    );
    expect(await screen.findByRole("heading", { name: "Add credit to get your own phone number" })).toBeTruthy();
    expect(screen.getByText("Add credit to get your own number.")).toBeTruthy();
    expect(screen.queryByText("Your calling account is being set up")).toBeNull();
    expect(screen.queryByText(/trial/)).toBeNull();
  });

  it("once paid: shows the three steps with the server's step marked next", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status({ step: "business_details", business_status: null, can_send_business_details: true })),
    );
    const next = await screen.findByText("Next step");
    expect(next.closest("li")?.textContent).toContain("Business details for phone numbers");
    expect(screen.getAllByText("Next step")).toHaveLength(1);
    expect(screen.queryByRole("link", { name: "Add credit" })).toBeNull();
  });

  it("has no violations on a trial", async () => {
    const { container } = await renderClientPage(<PhoneNumberPage />, routes(onTrial()));
    await screen.findByRole("heading", { name: "Your own phone number comes after the trial" });
    await expectNoA11yViolations(container, "phone-number: on a trial");
  });
});

describe("the three steps, as the server names them", () => {
  it("says the calling account is being set up, and asks nothing of the client", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status({ step: "workspace", account_setup: "pending", business_status: null })),
    );
    expect(await screen.findByText("Your calling account is being set up")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Send business details/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show numbers" })).toBeNull();
    // A verified business with the account still being set up has nothing to do next: the
    // details cannot be sent until the calling account exists.
    expect(screen.queryByText("Next step")).toBeNull();
  });

  it("sends an unverified business to verify first, with the later steps waiting", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status({ step: "verify_business", kyc_status: "not_started", business_status: null })),
    );
    const link = await screen.findByRole("link", { name: "Verify your business" });
    expect(link.getAttribute("href")).toContain("/c/acme/verify-business");
    expect(screen.getAllByText("Waiting")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /Send/ })).toBeNull();
  });

  it("sends the business details when nothing has been sent yet", async () => {
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes(status({ step: "business_details", business_status: null, can_send_business_details: true }), {
        [`POST ${OWN_NUMBERS_PATHS.businessDetails}`]: {
          business_status: "submitted",
          business_review_note: null,
        },
      }),
    );
    expect(await screen.findByText("Not sent yet.")).toBeTruthy();
    fireEvent.click(await enabledButton("Send business details"));
    await waitFor(() =>
      expect(calls.filter((call) => call.method === "POST" && call.path === OWN_NUMBERS_PATHS.businessDetails))
        .toHaveLength(1),
    );
  });

  it("says the details are being checked", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status({ step: "business_details", business_status: "submitted" })),
    );
    expect(await screen.findByText(/Being checked/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Send/ })).toBeNull();
  });

  it("shows a rejection's review note and offers to fix and send again", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(
        status({
          step: "business_details",
          business_status: "rejected",
          business_review_note: "The name on the certificate does not match.",
          can_send_business_details: true,
        }),
      ),
    );
    expect(await screen.findByText("The name on the certificate does not match.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Fix the details" }).getAttribute("href")).toBe("/c/acme/verify-business");
    expect((await enabledButton("Send the details again")).disabled).toBe(false);
  });

  it("offers no send while the server says the details may not be sent", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status({ step: "business_details", business_status: "rejected", can_send_business_details: false })),
    );
    expect(await screen.findByText("Not approved.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Send/ })).toBeNull();
  });

  it("words an expired approval and offers to send again", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status({ step: "business_details", business_status: "expired", can_send_business_details: true })),
    );
    expect(await screen.findByText("Approval lapsed. Send the details again.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Send the details again" })).toBeTruthy();
  });

  it("sends a suspended approval to us, never to a resend the server refuses", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(
        status({
          step: "business_details",
          business_status: "suspended",
          business_review_note: "Approval withdrawn by the authority.",
          can_send_business_details: false,
        }),
      ),
    );
    expect(await screen.findByText("Approval withdrawn. Please contact us.")).toBeTruthy();
    expect(screen.getByText("Approval withdrawn by the authority.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Fix the details" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Send/ })).toBeNull();
  });

  it("says numbers are not on sale yet while no price is set", async () => {
    await renderClientPage(<PhoneNumberPage />, routes(status({ step: "price", inr_per_month: null })));
    expect(await screen.findByText("Not on sale yet. We will tell you.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show numbers" })).toBeNull();
  });
});

describe("buying a number", () => {
  it("pages through the numbers with the cursor and shows our monthly price", async () => {
    const { calls } = await renderClientPage(<PhoneNumberPage />, routes(status()));
    await search();
    expect(screen.getAllByText(/₹499(\.00)? a month/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("button", { name: "Buy +91 80123 45673" })).toBeTruthy();
    expect(calls.some((call) => call.path === SECOND_PAGE)).toBe(true);
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("searches again when the same search is pressed after it failed", async () => {
    let failing = true;
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes(status(), {
        [FIRST_PAGE]: () =>
          failing
            ? problem(503, { type: "about:blank", title: "Unavailable", status: 503, detail: "Search failed." })
            : { numbers: [offer(1)], next_cursor: null },
      }),
    );
    fireEvent.change(await screen.findByLabelText("City"), { target: { value: "Hyderabad" } });
    fireEvent.click(screen.getByRole("button", { name: "Show numbers" }));
    await screen.findByText("Search failed.");
    failing = false;
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "Show numbers" }) as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: "Show numbers" }));
    await enabledButton("Buy +91 80123 45671");
    expect(calls.filter((call) => call.path === FIRST_PAGE)).toHaveLength(2);
  });

  it("reuses one request key when Buy is pressed again after an unconfirmed purchase", async () => {
    let attempt = 0;
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes(status(), {
        [`POST ${OWN_NUMBERS_PATHS.purchase}`]: () => {
          attempt += 1;
          return attempt === 1
            ? problem(409, {
                type: "https://calevate.tech/problems/engine_number_purchase_unconfirmed",
                detail: "The purchase could not be confirmed.",
              })
            : {
                number_id: NUMBER_ID,
                e164: "+918012345671",
                inr_per_month: "499.00",
                attachment: "applied",
                replayed: false,
                first_period: "charged",
              };
        },
      }),
    );
    await search();
    fireEvent.click(screen.getByRole("button", { name: "Buy +91 80123 45671" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/₹499(\.00)? a month while you keep it/)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/The agent that answers it/), {
      target: { value: "agent-1" },
    });
    expect(within(dialog).getByText("Calls to it reach Reception.")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Buy this number" }));
    expect(await within(dialog).findByText(/Press Buy again/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Buy this number" }));

    expect(
      await screen.findByText(/₹499(\.00)? charged now, then monthly\./),
    ).toBeTruthy();
    const sent = bodies(calls, OWN_NUMBERS_PATHS.purchase);
    expect(sent).toHaveLength(2);
    expect(sent[0]).toEqual({
      number: "918012345671",
      agent_id: "agent-1",
      direction: "both",
      request_key: sent[0].request_key,
    });
    expect(sent[0].request_key).toMatch(/^[A-Za-z0-9_-]{8,100}$/);
    expect(sent[1].request_key).toBe(sent[0].request_key);
    // Buying takes the emailed code for this account, as Pip's purchase does (D-893).
    const confirms = calls
      .filter((call) => call.path === OWN_NUMBERS_PATHS.purchase)
      .map((call) => call.headers["X-Confirm-Action"]);
    expect(confirms).toHaveLength(2);
    for (const confirm of confirms) expect(confirm).toMatch(/^buy_number:[a-z0-9-]+$/);
  });

  it("mints a fresh key for a fresh press of Buy", async () => {
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes(status(), {
        [`POST ${OWN_NUMBERS_PATHS.purchase}`]: problem(409, {
          type: "https://calevate.tech/problems/engine_number_unavailable",
          detail: "Taken.",
        }),
      }),
    );
    await search();
    fireEvent.click(screen.getByRole("button", { name: "Buy +91 80123 45671" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Buy this number" }));
    // The server sends this code for any refusal of the number, so the copy names both causes.
    expect(await screen.findByText(/Taken, or your details are in review/)).toBeTruthy();
    expect(screen.getByText(/Nothing charged/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Buy +91 80123 45672" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Buy this number" }));
    await waitFor(() => expect(bodies(calls, OWN_NUMBERS_PATHS.purchase)).toHaveLength(2));
    const [first, second] = bodies(calls, OWN_NUMBERS_PATHS.purchase);
    expect(second.request_key).not.toBe(first.request_key);
  });

  it("offers a top-up when the credit cannot cover the first month", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status(), {
        [`POST ${OWN_NUMBERS_PATHS.purchase}`]: problem(402, {
          type: "https://calevate.tech/problems/number_insufficient_credit",
          detail: "Not enough credit.",
        }),
      }),
    );
    await search();
    fireEvent.click(screen.getByRole("button", { name: "Buy +91 80123 45671" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Buy this number" }));
    expect(await screen.findByText(/Not enough credit for the first month/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Top up credit" })).toBeTruthy();
  });

  async function buyAnswering(answer: Record<string, unknown>) {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status(), {
        [`POST ${OWN_NUMBERS_PATHS.purchase}`]: {
          number_id: NUMBER_ID,
          e164: "+918012345671",
          inr_per_month: "499.00",
          ...answer,
        },
      }),
    );
    await search();
    fireEvent.click(screen.getByRole("button", { name: "Buy +91 80123 45671" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Buy this number" }));
    await screen.findByText("+91 80123 45671 is yours");
  }

  it("says an earlier request already bought it, and claims no charge, on a replay", async () => {
    await buyAnswering({ attachment: "unchanged", replayed: true, first_period: "replayed" });
    expect(screen.getByText("Your earlier try already bought this number.")).toBeTruthy();
    expect(screen.queryByText(/charged now/)).toBeNull();
  });

  it("says the agent must be published again when the number cannot reach it", async () => {
    await buyAnswering({ attachment: "other_workspace", replayed: false, first_period: "charged" });
    expect(screen.getByText("Publish the agent again, then pick it below.")).toBeTruthy();
  });

  it("keeps only digits in the search, ten at most, so the server never refuses it", async () => {
    const searched = OWN_NUMBERS_PATHS.available("Hyderabad", "9180123456", null);
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes(status(), { [searched]: { numbers: [], next_cursor: null } }),
    );
    fireEvent.change(await screen.findByLabelText("City"), { target: { value: "Hyderabad" } });
    const digits = screen.getByLabelText("Digits it contains (optional)") as HTMLInputElement;
    fireEvent.change(digits, { target: { value: "+91 80-1234 5678 99" } });
    expect(digits.value).toBe("9180123456");
    expect(digits.maxLength).toBe(10);
    expect(digits.inputMode).toBe("numeric");
    fireEvent.click(screen.getByRole("button", { name: "Show numbers" }));
    await waitFor(() =>
      expect(calls.some((call) => call.path === searched)).toBe(true),
    );
  });
});

describe("what the confirmation says was charged", () => {
  it.each([
    ["charged", /^₹499(\.00)? charged now, then monthly\.$/],
    ["invoiced", /^₹499(\.00)? a month\. First month on your next invoice\.$/],
    ["trial", /^₹499(\.00)? a month\. Free until your trial ends\.$/],
    ["closed", /^₹499(\.00)? a month\.$/],
    ["before_first_period", /^₹499(\.00)? a month\.$/],
    [null, /^₹499(\.00)? a month\.$/],
  ] as const)("words %s", (period, wording) => {
    expect(firstPeriodSentence(period, "499.00")).toMatch(wording);
  });

  it("claims no charge for a replayed purchase", () => {
    const sentence = firstPeriodSentence("replayed", "499.00");
    expect(sentence).not.toMatch(/charged/);
    expect(sentence).toBe("Your earlier try already bought this number.");
  });
});

describe("releasing a number", () => {
  const held = [
    {
      id: NUMBER_ID,
      e164: "+918012345671",
      series: "standard",
      dlt_status: "pending",
      supplied_by_us: true,
      answerable: true,
      agent_id: null,
      direction: "both",
      releasable: true,
    },
  ];

  it("offers no Release on a number the server will not let this account release", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status(), {
        "/v1/campaigns/numbers": [{ ...held[0], releasable: false }],
      }),
    );
    expect(await screen.findByText("+91 80123 45671")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Release this number" })).toBeNull();
  });

  it("warns that it is permanent and this month is not refunded, then releases", async () => {
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes(status(), {
        "/v1/campaigns/numbers": held,
        [`POST ${OWN_NUMBERS_PATHS.release(NUMBER_ID)}`]: { number_id: NUMBER_ID, released: true },
      }),
    );
    fireEvent.click(await enabledButton("Release this number"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Permanent. It stops ringing now./)).toBeTruthy();
    expect(within(dialog).getByText(/Anyone may take it next/)).toBeTruthy();
    expect(within(dialog).getByText(/No refund for this month\. The monthly charge stops\./)).toBeTruthy();
    expect(bodies(calls, OWN_NUMBERS_PATHS.release(NUMBER_ID))).toHaveLength(0);

    fireEvent.click(within(dialog).getByRole("button", { name: "Release it for good" }));
    expect(await screen.findByText(/is released\. Its monthly charge has stopped\./)).toBeTruthy();
    expect(bodies(calls, OWN_NUMBERS_PATHS.release(NUMBER_ID))).toEqual([{ confirm: true }]);
  });
});

describe("a held number (D-860)", () => {
  const heldNumber = {
    id: NUMBER_ID,
    e164: "+918012345671",
    series: "standard",
    dlt_status: "pending",
    supplied_by_us: true,
    answerable: false,
    agent_id: "agent-1",
    direction: "both",
    releasable: true,
    held: true,
    // 18:30 UTC on the 6th is the start of the 7th in India.
    release_at: "2026-11-06T18:30:00Z",
  };

  it("says calls stopped and the IST day it is released, with credit the one action", async () => {
    const { container } = await renderClientPage(
      <PhoneNumberPage />,
      routes(status(), { "/v1/campaigns/numbers": [heldNumber] }),
    );
    expect(
      await screen.findByText("Calls stopped. Released on Saturday, 7 November unless you top up."),
    ).toBeTruthy();
    expect(screen.getByText("Calls stopped")).toBeTruthy();
    const topUp = screen.getAllByRole("link", { name: "Add credit" });
    expect(topUp.some((link) => link.getAttribute("href") === CREDITS_HREF)).toBe(true);
    // Not the "still connecting it" sentence: nothing is being connected.
    expect(screen.queryByText(/we are still\s+connecting it/)).toBeNull();
    await expectNoA11yViolations(container, "phone-number: a held number");
  });

  it("says so without a date while the date is still being worked out", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status(), { "/v1/campaigns/numbers": [{ ...heldNumber, release_at: null }] }),
    );
    expect(await screen.findByText("Calls stopped. Released soon unless you top up.")).toBeTruthy();
  });
});

describe("white label", () => {
  it("names no vendor anywhere on the journey, the search or the confirmation", async () => {
    const { container } = await renderClientPage(
      <PhoneNumberPage />,
      routes(
        status({
          step: "ready",
          business_status: "accepted",
        }),
      ),
    );
    await search();
    fireEvent.click(screen.getByRole("button", { name: "Buy +91 80123 45671" }));
    await screen.findByRole("dialog");
    expect(document.body.textContent ?? "").not.toMatch(/thinnest/i);
    expect(container.textContent ?? "").toMatch(/calling account|phone number/i);
  });

  it("names no vendor in any refusal or step state", async () => {
    for (const own of [
      status({ step: "workspace", account_setup: "plan_limit" }),
      status({ step: "business_details", business_status: "rejected", business_review_note: "Fix it." }),
      status({ step: "price", inr_per_month: null }),
    ]) {
      const { unmount } = await renderClientPage(<PhoneNumberPage />, routes(own));
      await screen.findByText("Get a phone number in your business's name");
      expect(document.body.textContent ?? "").not.toMatch(/thinnest/i);
      unmount();
    }
  });
});

describe("accessibility", () => {
  it("has no violations with the journey ready and numbers listed", async () => {
    const { container } = await renderClientPage(<PhoneNumberPage />, routes(status()));
    await search();
    await expectNoA11yViolations(container, "phone-number: own numbers journey");
  });

  it("has no violations with a rejected application", async () => {
    const { container } = await renderClientPage(
      <PhoneNumberPage />,
      routes(
        status({
          step: "business_details",
          business_status: "rejected",
          business_review_note: "The name does not match.",
          can_send_business_details: true,
        }),
      ),
    );
    await screen.findByText("The name does not match.");
    await expectNoA11yViolations(container, "phone-number: business details rejected");
  });
});

describe("the step card on Verify your business", () => {
  it("leads to phone numbers once the business is verified", async () => {
    await renderClientPage(<VerifyBusinessPage />, {
      "/v1/me": OWNER,
      ...NO_FORWARDING_ROUTES,
      "/v1/compliance/kyc": KYC_NOT_STARTED,
      "/v1/compliance/dlt-registration": DLT_NOT_RECORDED,
      "/v1/compliance/outbound-pledge": {
        version: 1,
        pledge_text: "We do not cold-call.",
        text_sha256: "0".repeat(64),
        is_current: true,
        accepted_version: 1,
        accepted_at: "2026-10-01T00:00:00Z",
      },
      [OWN_NUMBERS_PATHS.status]: status({ step: "business_details", business_status: "submitted" }),
    });
    expect(await screen.findByText("Phone numbers in your business's name")).toBeTruthy();
    expect(screen.getByText("Next: approval of your business details.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to phone numbers" }).getAttribute("href")).toContain(
      "/c/acme/phone-number",
    );
    expect(document.body.textContent ?? "").not.toMatch(/thinnest/i);
  });

  it("says the number comes after credit on a trial", async () => {
    await renderClientPage(<VerifyBusinessPage />, {
      "/v1/me": OWNER,
      ...NO_FORWARDING_ROUTES,
      "/v1/compliance/kyc": KYC_NOT_STARTED,
      "/v1/compliance/dlt-registration": DLT_NOT_RECORDED,
      "/v1/compliance/outbound-pledge": {
        version: 1,
        pledge_text: "We do not cold-call.",
        text_sha256: "0".repeat(64),
        is_current: true,
        accepted_version: 1,
        accepted_at: "2026-10-01T00:00:00Z",
      },
      [OWN_NUMBERS_PATHS.status]: onTrial(),
    });
    expect(await screen.findByText("Add credit first to get your own number.")).toBeTruthy();
  });
});
