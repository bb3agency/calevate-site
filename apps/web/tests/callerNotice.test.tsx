import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallerNoticePage from "@/app/c/[slug]/caller-notice/page";
import type { CallerNotice } from "@/lib/api/callerNotice";
import type { Me } from "@/lib/api/client";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderClientPage } from "./harness";

/**
 * The client's own privacy-notice draft (LEGAL-SURFACE F-8, D-179) — the screen for an
 * endpoint that shipped mounted, permissioned and response-modelled with zero callers.
 *
 * What is at stake, and therefore what is asserted here:
 *
 * - **The draft warning must survive the copy.** The disclaimer is rendered above the
 *   document AND is inside the markdown the client pastes into their website. A warning
 *   that lives only in the envelope stops travelling the moment the text leaves the page,
 *   which on a legal surface is the difference between a draft and a published claim.
 * - **§52: a failed read renders a refusal and nothing that resembles an answer.** "You
 *   collect nothing" and "we could not ask what you collect" are one branch apart in code
 *   and worlds apart in front of a regulator, and this screen is the one a client reads
 *   before publishing a legal notice.
 * - **The announcement lists are named, not counted, and are never presented as the whole
 *   obligation.** With an opening announcement off (D-163) the duty moves onto this
 *   notice, so the client needs the agent's name. But the truthful answer to a direct
 *   question is enforced server-side and cannot be withdrawn by any setting — a screen
 *   that said only "AI disclosure off" would describe a product that conceals, which this
 *   one is incapable of being.
 * - **`org:read`, so the read-only support session (D-22) can open it.** The endpoint
 *   chose the weaker permission precisely for that case; a screen that gated on write
 *   access would close it again, so `staff` must see the whole draft.
 */

const OWNER: Me = {
  impersonating: false,
  permissions: ["calls:read", "leads:read", "org:read", "org:manage"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

/** The read-only session support is in when a client rings about their notice. */
const STAFF: Me = {
  ...OWNER,
  permissions: ["calls:read", "leads:read", "org:read"],
  role: "staff",
};

const DISCLAIMER =
  "This is a draft and not legal advice. Have your advocate review it.";

const NOTICE: CallerNotice = {
  disclaimer: DISCLAIMER,
  collected: [
    {
      what: "Your name",
      why: "So we can address you and match you to your enquiry.",
    },
    {
      what: "Your phone number",
      why: "So we can call you back about your enquiry.",
    },
  ],
  retention: [
    { what: "Call recordings", days: 90 },
    { what: "Lead records", days: 365 },
  ],
  ai_disclosure_off: ["Reception agent"],
  recording_notice_off: ["Reception agent", "Follow-up agent"],
  open_questions: [
    "Who is your grievance officer, and how does a caller reach them?",
  ],
  // The disclaimer is inside the document as well as beside it — that is the property the
  // first test below exists to pin, so the fixture has to carry it in both places.
  notice_markdown: `# Privacy notice\n\n${DISCLAIMER}\n\nWhen you call us, an AI assistant answers.\n`,
};

const ROUTES = { "/v1/me": OWNER, "/v1/compliance/caller-notice": NOTICE };

describe("the caller-notice draft", () => {
  it("itemises what is collected and how long it is kept", async () => {
    await renderClientPage(<CallerNoticePage />, ROUTES);

    expect(await screen.findByText("Your phone number")).toBeTruthy();
    expect(
      screen.getByText("So we can call you back about your enquiry."),
    ).toBeTruthy();
    expect(screen.getByText("Call recordings")).toBeTruthy();
    expect(screen.getByText("365 days")).toBeTruthy();
  });

  it("keeps the draft warning both beside the document and inside it", async () => {
    await renderClientPage(<CallerNoticePage />, ROUTES);
    await screen.findByText("Your name");

    // TWICE, and that is the assertion rather than an accident of the fixture: once in the
    // notice box the client reads, once in the text they copy out. A single occurrence
    // would mean one of the two is missing, and the one that matters is the copy.
    expect(screen.getAllByText(new RegExp(DISCLAIMER))).toHaveLength(2);
  });

  it("names the agents whose announcements are off, and says what is still guaranteed", async () => {
    await renderClientPage(<CallerNoticePage />, ROUTES);
    await screen.findByText("Your name");

    expect(
      screen.getByText("These agents do not announce that they are AI"),
    ).toBeTruthy();
    // NAMED, not counted — with the announcement off the obligation lands on the written
    // notice, and "one agent" does not tell the client which one to describe.
    expect(screen.getAllByText("Reception agent")).toHaveLength(2);
    expect(screen.getByText("Follow-up agent")).toBeTruthy();
    expect(
      screen.getByText(/answers truthfully whenever a caller asks/i),
    ).toBeTruthy();
  });

  it("shows the whole draft to a read-only staff session", async () => {
    // The endpoint asks for `org:read` so a "view as client" support session can open this
    // while the client is on the phone. Nothing here is gated on write access, and this
    // test is what stops somebody adding a gate later out of habit.
    await renderClientPage(<CallerNoticePage />, {
      ...ROUTES,
      "/v1/me": STAFF,
    });

    expect(await screen.findByText("Your name")).toBeTruthy();
    expect(screen.getByRole("button", { name: /copy/i })).toBeTruthy();
  });

  it("renders an empty account as a prompt rather than as an answer", async () => {
    // A 200 on an account with no published agent is deliberate on the server: "you have
    // not launched yet" is not an answer to "what will I be collecting?". The screen must
    // say there is nothing itemised YET, never imply the answer is nothing.
    await renderClientPage(<CallerNoticePage />, {
      ...ROUTES,
      "/v1/compliance/caller-notice": {
        ...NOTICE,
        collected: [],
        ai_disclosure_off: [],
        recording_notice_off: [],
      },
    });

    expect(await screen.findByText("Nothing itemised yet")).toBeTruthy();
    // The announcement card renders only when something is off. With both lists empty it
    // must be absent rather than present-and-empty, which would read as a finding.
    expect(
      screen.queryByText("Announcements your agents do not make"),
    ).toBeNull();
  });

  it("refuses rather than rendering an empty notice when the read fails (§52)", async () => {
    await renderClientPage(<CallerNoticePage />, {
      ...ROUTES,
      "/v1/compliance/caller-notice": problem(503, {
        title: "Service unavailable",
        detail: "We could not build your draft just now.",
      }),
    });

    expect(await screen.findByText(/could not build your draft/i)).toBeTruthy();
    // Nothing that could be mistaken for the answer: no empty state, no document card.
    expect(screen.queryByText("Nothing itemised yet")).toBeNull();
    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
  });

  it("has no accessibility violations", async () => {
    const { container } = await renderClientPage(<CallerNoticePage />, ROUTES);
    await screen.findByText("Your name");
    await expectNoA11yViolations(container, "c/[slug]/caller-notice/page.tsx");
  });
});
