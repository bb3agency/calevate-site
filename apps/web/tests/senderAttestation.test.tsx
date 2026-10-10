import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PhoneNumberPage from "@/app/c/[slug]/phone-number/page";
import type { Me } from "@/lib/api/client";
import type { SenderAttestation } from "@/lib/api/senderAttestation";

import { expectNoA11yViolations } from "./a11y";
import { readInfoTip } from "./infoTip";
import { problem, renderClientPage, type Routes } from "./harness";
import {
  KYC_NOT_STARTED,
  OWN_NUMBERS_OFF,
  OWN_NUMBERS_STATUS_PATH,
  agentRow,
  prepaidWallet,
} from "./fixtures/sharedReads";

/**
 * THE OUTBOUND-SENDER CONFIRMATION, ON THE SCREEN WHERE A CLIENT ACCEPTS IT.
 *
 * TRAI direction RG-25/(18)/2023-QoS (E-10291), 18 Jun 2024 forbids a sender from calling
 * customers from an ordinary 10-digit number and names the delegation chain, so under
 * Model B (D-474) the obligation is the client's and the exception has to be theirs too
 * (`docs/evidence/primary-legal-findings-2026-09-20.md` §1). Four properties of that make
 * this panel wrong in ways nothing else would catch:
 *
 * - **It must not be OFFERED on a registered 140 or 160 header.** The API refuses a row
 *   against one (`sender_attestation_not_applicable`), so a control there is a control
 *   whose only outcome is a refusal — and, worse, it asks a business to accept an
 *   obligation it has not incurred.
 * - **The version the page was SERVED is what travels back.** It is half the evidence:
 *   the row records which wording was accepted, and a version invented by the browser
 *   would make the record evidence of words nobody showed.
 * - **A stale version is a RELOAD, not an error.** Nothing is wrong with the account; the
 *   sentence on screen is simply not the current one.
 * - **A withdrawal reads as not-confirmed, and the panel asks again.** The row is not
 *   deleted (hard rule 4), and the screen must not imply either that it was or that the
 *   number still carries campaigns.
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["calls:read", "leads:read", "org:read", "org:manage"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

/** An operator inside D-22 "view as client": `org:manage`, and this act withheld. */
const VIEW_AS: Me = {
  ...OWNER,
  impersonating: true,
  withheld_acts: ["compliance.outbound_sender_attestation"],
};

const VERSION = "2026-09-20";

/** `campaigns/sender_attestation.SENDER_STATEMENT` — rendered verbatim by the panel. */
const STATEMENT =
  "I confirm that my business is the sender of these calls, that I have been told TRAI " +
  "requires promotional, service and transactional voice calls to be made only from a " +
  "registered 140 or 160 series voice header, that this number is not one, and that my " +
  "business accepts responsibility for calls made from it.";

function state(over: Partial<SenderAttestation> = {}): SenderAttestation {
  return {
    attested: false,
    applicable: true,
    statement: STATEMENT,
    statement_version: VERSION,
    ...over,
  };
}

/** One number the client holds themselves, which is what `series` decides the rest of. */
function numbers(series: string): unknown {
  return [
    {
      id: "num-1",
      e164: "+918041234567",
      series,
      dlt_status: "registered",
      supplied_by_us: false,
      answerable: true,
    },
  ];
}

function routes(series: string, attestation: unknown, extra: Routes = {}): Routes {
  return {
    "/v1/me": OWNER,
    "/v1/campaigns/numbers": numbers(series),
    "/v1/numbers/num-1/sender-attestation": attestation,
    // The rest of the phone-number screen, in this deployment's ordinary state: buying a
    // number is operator-led, so the offer read answers with that refusal.
    "/v1/agents": [agentRow()],
    "/v1/compliance/kyc": KYC_NOT_STARTED,
    "/v1/billing/wallet": prepaidWallet(),
    [OWN_NUMBERS_STATUS_PATH]: OWN_NUMBERS_OFF,
    "/v1/numbers/available": problem(422, {
      kind: "business_rule",
      type: "https://calevate.tech/problems/number_purchase_is_operator_led",
      title: "A phone number cannot be bought from this screen.",
      detail:
        "A phone number cannot be bought from this screen. Numbers are arranged with us as part of setting your agent up.",
      // A mirror of `self_serve_purchase_refused()`'s remediation: the number is Calevate's,
      // and no provider is named (white label, founder 6 Oct 2026).
      remediation:
        "Talk to us and we will arrange the number. Calevate provides it on our own telephony account, so there is no operator account for you to open.",
    }),
    ...extra,
  };
}

describe("where a recorded number comes from", () => {
  it("says Calevate provides it, names no provider, and never says the client holds it", async () => {
    // Was "Numbers you hold yourself … connections in your own name with your own
    // operator", which the founder's decision of 2 Oct 2026 made untrue.
    await renderClientPage(<PhoneNumberPage />, routes("standard", state()));

    expect(await screen.findByRole("heading", { name: /numbers your agents call out from/i })).toBeTruthy();
    const tip = await readInfoTip("Where these numbers come from");
    expect(tip).toMatch(/our own telephony account/);
    expect(tip).not.toMatch(/Vobiz|Plivo|Thinnest|Pipecat/i);
    expect(tip).not.toMatch(/your own operator|account holder/i);
  });
});

describe("the confirmation is only asked where TRAI's exception is open", () => {
  it("is not offered on a registered 160-series header", async () => {
    const { container } = await renderClientPage(
      <PhoneNumberPage />,
      routes("160", state({ applicable: false })),
    );

    // Displayed grouped for reading (`formatPhone`) since the round-2 redesign.
    await screen.findByText("+91 80412 34567");
    expect(screen.queryByText(STATEMENT)).toBeNull();
    expect(
      screen.queryByRole("button", { name: /confirm and accept/i }),
    ).toBeNull();
    await expectNoA11yViolations(container, "phone-number: sender confirmation");
  });

  it("renders the server's statement, unchanged, on an ordinary number", async () => {
    await renderClientPage(<PhoneNumberPage />, routes("standard", state()));

    expect(await screen.findByText(STATEMENT)).toBeTruthy();
  });

  it("refuses to state what confirming is worth on a read that failed", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes("standard", problem(503, { detail: "Upstream is down." })),
    );

    expect(await screen.findByText("Upstream is down.")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /confirm and accept/i }),
    ).toBeNull();
  });
});

describe("accepting", () => {
  it("sends the statement version the page was served", async () => {
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes("standard", state(), {
        "POST /v1/numbers/num-1/sender-attestation": state({ attested: true }),
      }),
    );

    await screen.findByText(STATEMENT);
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /confirm and accept/i }));

    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.path.endsWith("/sender-attestation"),
      );
      expect(post).toBeTruthy();
      expect(JSON.parse(post!.body ?? "{}")).toEqual({
        statement_version: VERSION,
      });
    });
  });

  it("stays unavailable until the statement has been read", async () => {
    await renderClientPage(<PhoneNumberPage />, routes("standard", state()));

    await screen.findByText(STATEMENT);
    expect(
      screen
        .getByRole("button", { name: /confirm and accept/i })
        .hasAttribute("disabled"),
    ).toBe(true);
  });

  it("names the act an operator may not do on the client's behalf", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes("standard", state(), { "/v1/me": VIEW_AS }),
    );

    await screen.findByText(STATEMENT);
    expect(
      screen.getByText(
        /This stays with the client, so you cannot confirm that this business is the sender/i,
      ),
    ).toBeTruthy();
    expect(screen.getByRole("checkbox").hasAttribute("disabled")).toBe(true);
  });

  it("asks for a reload rather than reporting a fault when the wording moved", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes("standard", state(), {
        "POST /v1/numbers/num-1/sender-attestation": problem(409, {
          type: "https://calevate.tech/problems/sender_statement_not_current",
          detail: "The confirmation on your screen is out of date.",
        }),
      }),
    );

    await screen.findByText(STATEMENT);
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /confirm and accept/i }));

    expect(
      await screen.findByRole("button", { name: /reload the confirmation/i }),
    ).toBeTruthy();
    // The tick is cleared with it: what was read is no longer what is on screen.
    fireEvent.click(
      screen.getByRole("button", { name: /reload the confirmation/i }),
    );
    await waitFor(() =>
      expect(
        (screen.getByRole("checkbox") as HTMLInputElement).checked,
      ).toBe(false),
    );
  });
});

describe("withdrawing", () => {
  it("says the earlier record survives, and asks again once it is done", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes("standard", state({ attested: true }), {
        "DELETE /v1/numbers/num-1/sender-attestation": state({ attested: false }),
      }),
    );

    fireEvent.click(
      await screen.findByRole("button", { name: /withdraw this confirmation/i }),
    );
    expect(
      screen.getByText(/Your earlier confirmation is not removed/i),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /withdraw it/i }));

    // Back to the ask: the number no longer carries campaigns, and the panel says so by
    // offering the confirmation again rather than by reporting a success and stopping.
    expect(
      await screen.findByRole("button", { name: /confirm and accept/i }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /withdraw this confirmation/i }),
    ).toBeNull();
  });
});
