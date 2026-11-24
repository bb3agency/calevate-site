import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WhatsAppFollowUp } from "@/app/c/[slug]/campaigns/CampaignBoosters";
import { ToastProvider } from "@/components/arc/toast";
import type { Me } from "@/lib/api/client";
import type { CampaignWhatsApp, CampaignWhatsAppMade } from "@/lib/api/followUps";

import { expectNoA11yViolations } from "./a11y";
import { renderClientPage, stillLoading } from "./harness";

/**
 * D-1041 (founder, 24 Nov 2026: "make the whatsapp card set it up directly"). The campaign's
 * WhatsApp card in each state: not connected (one line, one link that fixes it), ready (one
 * button), Pip writing, a try that made nothing, and a made follow-up with its message,
 * outcomes, the review state and an On switch that waits for WhatsApp's approval.
 */

const CAMPAIGN = "0192f0aa-1111-7000-8000-000000000001";
const PATH = `/v1/campaigns/${CAMPAIGN}/whatsapp-follow-up`;
const FOLLOW_UP = "0192f0aa-2222-7000-8000-000000000002";

const OWNER: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["leads:read", "leads:dispatch", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Rytu Khata", slug: "acme", status: "active" },
};
/** Runs campaigns but may not send WhatsApp templates. */
const DISPATCHER: Me = { ...OWNER, role: "staff", permissions: ["leads:read", "leads:dispatch"] };

function made(overrides: Partial<CampaignWhatsAppMade> = {}): CampaignWhatsAppMade {
  return {
    follow_up_id: FOLLOW_UP,
    status: "draft",
    message: "Thank you for the call. Install the app from Play Store to keep your accounts.",
    message_status: "approved",
    message_language: "en",
    outcomes: [
      { key: "hung_up_early", label: "Hung up early" },
      { key: "wants_details", label: "Wants details" },
    ],
    wait_minutes: 10,
    sent: 0,
    replied: 0,
    has_unpublished_changes: true,
    ...overrides,
  };
}

function card(overrides: Partial<CampaignWhatsApp> = {}): CampaignWhatsApp {
  return { phase: "none", connected: true, failure: null, made: null, ...overrides };
}

async function show(routes: Record<string, unknown>, canWrite = true, me: Me = OWNER) {
  return renderClientPage(
    <ToastProvider>
      <WhatsAppFollowUp
        slug="acme"
        campaignId={CAMPAIGN}
        canWrite={canWrite}
        refusal="Only the owner can change this."
      />
    </ToastProvider>,
    { "/v1/me": me, ...routes },
  );
}

describe("the campaign's WhatsApp follow-up card", () => {
  it("without WhatsApp says so in one line with the one link that fixes it", async () => {
    const { container } = await show({ [PATH]: card({ phase: "not_connected", connected: false }) });
    expect(await screen.findByText("Connect WhatsApp to send messages after calls.")).toBeTruthy();
    const link = screen.getByRole("link", { name: "Connect WhatsApp" });
    expect(link.getAttribute("href")).toContain("/c/acme/integrations/whatsapp");
    expect(screen.queryByRole("button", { name: "Set up WhatsApp follow-up" })).toBeNull();
    await expectNoA11yViolations(container, "WhatsApp card, not connected");
  });

  it("sets it up with one press, then shows Pip writing", async () => {
    const { calls, container } = await show({
      [`GET ${PATH}`]: card(),
      [`POST ${PATH}`]: card({ phase: "writing" }),
    });
    const button = await screen.findByRole("button", { name: "Set up WhatsApp follow-up" });
    await expectNoA11yViolations(container, "WhatsApp card, ready");
    await act(async () => {
      fireEvent.click(button);
    });
    expect((await screen.findByText("Pip is writing the message.")).getAttribute("role")).toBe("status");
    expect(calls.filter((c) => c.method === "POST" && c.path === PATH)).toHaveLength(1);
  });

  it("holds the button in its pending face while the press is answered", async () => {
    await show({ [`GET ${PATH}`]: card(), [`POST ${PATH}`]: stillLoading() });
    const button = await screen.findByRole("button", { name: "Set up WhatsApp follow-up" });
    await act(async () => {
      fireEvent.click(button);
    });
    await waitFor(() =>
      expect(button.getAttribute("data-status")).toBe("pending"),
    );
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByText("Asking Pip…")).toBeTruthy();
  });

  it("after a try that made nothing, says why and offers to try again", async () => {
    await show({
      [PATH]: card({ phase: "failed", failure: "Write this campaign's main task first, so Pip knows what to say." }),
    });
    expect(await screen.findByText("Write this campaign's main task first, so Pip knows what to say.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("shows the message, its outcomes and an On switch that is off until WhatsApp approves", async () => {
    const { container } = await show({
      [PATH]: card({ phase: "made", made: made({ message_status: "pending" }) }),
    });
    const message = await screen.findByText(/Install the app from Play Store/);
    expect(message.getAttribute("lang")).toBe("en");
    expect(screen.getByText(/For calls that ended as: Hung up early, Wants details\./)).toBeTruthy();
    expect(screen.getByText(/10 minutes after the call/)).toBeTruthy();
    expect(screen.getByText("WhatsApp is checking the message. This can take up to a day.")).toBeTruthy();
    const toggle = screen.getByRole("switch", { name: /On/ }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect(toggle.disabled).toBe(true);
    expect(screen.getByRole("link", { name: "Edit" }).getAttribute("href")).toContain(
      `/c/acme/follow-ups/${FOLLOW_UP}`,
    );
    await expectNoA11yViolations(container, "WhatsApp card, in review");
  });

  it("turns on with one press once approved, and shows what it sent", async () => {
    const { calls } = await show({
      [`GET ${PATH}`]: card({ phase: "made", made: made() }),
      [`POST ${PATH}/switch`]: card({
        phase: "made",
        made: made({ status: "live", has_unpublished_changes: false, sent: 4, replied: 1 }),
      }),
    });
    const toggle = (await screen.findByRole("switch", { name: /On/ })) as HTMLInputElement;
    expect(toggle.disabled).toBe(false);
    await act(async () => {
      fireEvent.click(toggle);
    });
    const sent = calls.filter((c) => c.method === "POST" && c.path === `${PATH}/switch`);
    expect(sent).toHaveLength(1);
    expect(JSON.parse(sent[0].body ?? "{}")).toEqual({ on: true });
    expect((await screen.findByRole("switch", { name: /On/ }) as HTMLInputElement).checked).toBe(true);
    expect(await screen.findByText("4 sent · 1 replied")).toBeTruthy();
  });

  it("asks before turning off, because people waiting stop getting theirs", async () => {
    const { calls } = await show({
      [`GET ${PATH}`]: card({ phase: "made", made: made({ status: "live", has_unpublished_changes: false }) }),
      [`POST ${PATH}/switch`]: card({ phase: "made", made: made({ status: "off" }) }),
    });
    const toggle = await screen.findByRole("switch", { name: /On/ });
    await act(async () => {
      fireEvent.click(toggle);
    });
    const dialog = await screen.findByRole("dialog", { name: "Turn off the WhatsApp follow-up?" });
    expect(calls.filter((c) => c.path === `${PATH}/switch`)).toHaveLength(0);
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Turn it off" }));
    });
    const sent = calls.filter((c) => c.path === `${PATH}/switch`);
    expect(sent).toHaveLength(1);
    expect(JSON.parse(sent[0].body ?? "{}")).toEqual({ on: false });
  });

  it("offers Pip's rewrite when WhatsApp turned the message down", async () => {
    await show({ [PATH]: card({ phase: "made", made: made({ message_status: "rejected" }) }) });
    expect(await screen.findByText("WhatsApp turned this message down.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Write it again" })).toBeTruthy();
  });

  it("holds every control for someone who cannot change it", async () => {
    await show({ [PATH]: card() }, false, DISPATCHER);
    const button = (await screen.findByRole("button", { name: "Set up WhatsApp follow-up" })) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(true));
  });

  it("keeps setting up to the owner and says why, while the switch stays with campaign runners", async () => {
    const { container } = await show(
      { [PATH]: card({ phase: "made", made: made({ message_status: "rejected" }) }) },
      true,
      DISPATCHER,
    );
    const again = (await screen.findByRole("button", { name: "Write it again" })) as HTMLButtonElement;
    await waitFor(() => expect(again.disabled).toBe(true));
    expect(screen.getByText("Only an account owner can set up a WhatsApp follow-up.")).toBeTruthy();
    await expectNoA11yViolations(container, "WhatsApp card, not the owner");
  });

  it("refuses the first set-up to someone who runs campaigns but is not the owner", async () => {
    await show({ [PATH]: card() }, true, DISPATCHER);
    const button = (await screen.findByRole("button", { name: "Set up WhatsApp follow-up" })) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(screen.getByText("Only an account owner can set up a WhatsApp follow-up.")).toBeTruthy();
  });
});
