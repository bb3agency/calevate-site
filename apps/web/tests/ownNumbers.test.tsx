import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { firstPeriodSentence } from "@/app/c/[slug]/phone-number/OwnNumbers";
import PhoneNumberPage from "@/app/c/[slug]/phone-number/page";
import VerifyBusinessPage from "@/app/c/[slug]/verify-business/page";
import type { Me } from "@/lib/api/client";
import { OWN_NUMBERS_PATHS, type OwnNumbersStatus } from "@/lib/api/ownNumbers";

import { expectNoA11yViolations } from "./a11y";
import { KYC_NOT_STARTED } from "./fixtures/sharedReads";
import { problem, renderClientPage, type ApiCall, type Routes } from "./harness";

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

describe("the three steps, as the server names them", () => {
  it("says the calling account is being set up, and asks nothing of the client", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status({ step: "workspace", account_setup: "pending", business_status: null })),
    );
    expect(await screen.findByText("Your calling account is being set up")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Send business details/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Show numbers" })).toBeNull();
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
    expect(screen.getByText(/Fix and send again/)).toBeTruthy();
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
    expect(await screen.findByText("The approval has lapsed. Please send the details again.")).toBeTruthy();
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
    expect(await screen.findByText(/Approval was withdrawn, and it cannot be restored from here\. Please contact us/)).toBeTruthy();
    expect(screen.getByText("Approval withdrawn by the authority.")).toBeTruthy();
    expect(screen.queryByText(/send them again here/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Send/ })).toBeNull();
  });

  it("says numbers are not on sale yet while no price is set", async () => {
    await renderClientPage(<PhoneNumberPage />, routes(status({ step: "price", inr_per_month: null })));
    expect(await screen.findByText(/Numbers are not on sale yet/)).toBeTruthy();
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
    expect(within(dialog).getByText(/₹499(\.00)? every month/)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/The agent that answers it/), {
      target: { value: "agent-1" },
    });
    expect(within(dialog).getByText("Calls to it reach Reception.")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Buy this number" }));
    expect(await within(dialog).findByText(/Press Buy again/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Buy this number" }));

    expect(
      await screen.findByText(/₹499(\.00)? charged now for the first month, then monthly\./),
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
    expect(await screen.findByText(/somebody else may have taken it, or your business details are still being checked/)).toBeTruthy();
    expect(screen.getByText(/Nothing was charged/)).toBeTruthy();
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
    expect(await screen.findByText(/not enough calling credit/)).toBeTruthy();
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
    expect(screen.getByText("Your earlier request already bought this number.")).toBeTruthy();
    expect(screen.queryByText(/charged now/)).toBeNull();
  });

  it("says the agent must be published again when the number cannot reach it", async () => {
    await buyAnswering({ attachment: "other_workspace", replayed: false, first_period: "charged" });
    expect(screen.getByText(/the agent has to be published again before it can answer this number/)).toBeTruthy();
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
    ["charged", /^₹499(\.00)? charged now for the first month, then monthly\.$/],
    ["invoiced", /^₹499(\.00)? a month — the first month is added to your next invoice\.$/],
    ["trial", /^₹499(\.00)? a month — free during your trial; charging starts at the first renewal after it\.$/],
    ["closed", /^₹499(\.00)? a month\.$/],
    ["before_first_period", /^₹499(\.00)? a month\.$/],
    [null, /^₹499(\.00)? a month\.$/],
  ] as const)("words %s", (period, wording) => {
    expect(firstPeriodSentence(period, "499.00")).toMatch(wording);
  });

  it("claims no charge for a replayed purchase", () => {
    const sentence = firstPeriodSentence("replayed", "499.00");
    expect(sentence).not.toMatch(/charged/);
    expect(sentence).toBe("Your earlier request already bought this number.");
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

  const attestation = {
    [`/v1/numbers/${NUMBER_ID}/sender-attestation`]: {
      attested: false,
      applicable: true,
      statement: "I confirm that my business is the sender of these calls.",
      statement_version: "2026-09-20",
    },
  };

  it("offers no Release on a number the server will not let this account release", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes(status(), {
        "/v1/campaigns/numbers": [{ ...held[0], releasable: false }],
        ...attestation,
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
        [`/v1/numbers/${NUMBER_ID}/sender-attestation`]: {
          attested: false,
          applicable: true,
          statement: "I confirm that my business is the sender of these calls.",
          statement_version: "2026-09-20",
        },
        [`POST ${OWN_NUMBERS_PATHS.release(NUMBER_ID)}`]: { number_id: NUMBER_ID, released: true },
      }),
    );
    fireEvent.click(await enabledButton("Release this number"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Releasing is permanent/)).toBeTruthy();
    expect(within(dialog).getByText(/anybody may take it next/)).toBeTruthy();
    expect(within(dialog).getByText(/This month is not refunded\. The monthly charge stops\./)).toBeTruthy();
    expect(bodies(calls, OWN_NUMBERS_PATHS.release(NUMBER_ID))).toHaveLength(0);

    fireEvent.click(within(dialog).getByRole("button", { name: "Release it for good" }));
    expect(await screen.findByText(/is released\. Its monthly charge has stopped\./)).toBeTruthy();
    expect(bodies(calls, OWN_NUMBERS_PATHS.release(NUMBER_ID))).toEqual([{ confirm: true }]);
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
      "/v1/compliance/kyc": KYC_NOT_STARTED,
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
    expect(screen.getByText(/Next, your business details are approved/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to phone numbers" }).getAttribute("href")).toContain(
      "/c/acme/phone-number",
    );
    expect(document.body.textContent ?? "").not.toMatch(/thinnest/i);
  });
});
