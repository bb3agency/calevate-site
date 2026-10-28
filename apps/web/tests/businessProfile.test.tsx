import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SetupWizard } from "@/app/c/[slug]/setup/SetupWizard";
import { SetupChecklist } from "@/app/c/[slug]/SetupChecklist";
import { BusinessProfileScreen } from "@/app/c/[slug]/settings/business/BusinessProfileScreen";
import {
  draftFromProfile,
  rebaseDraft,
  stepCopy,
  toPatch,
  type BusinessProfile,
} from "@/lib/api/businessProfile";

import { renderClientPage } from "./harness";

/**
 * The client's business profile (D-695): the setup wizard, the Business profile screen
 * and the wire mapping between them. What matters is that a step saves only its own topic,
 * that "closed" and "not answered" stay different answers, that prices stay the digits
 * typed, and that every step can be skipped.
 */

const OWNER = {
  realm: "client",
  user_id: "u1",
  tenant_id: "t1",
  org_slug: "acme",
  role: "owner",
  permissions: ["org:read", "org:manage", "agents:read"],
  impersonating: false,
  withheld_acts: [],
};

const STEPS = ["hours", "branches", "services", "faqs", "staff", "booking", "contacts", "languages"] as const;

function profile(over: Partial<BusinessProfile> = {}): BusinessProfile {
  return {
    business_name: "Sunrise Dental",
    legal_name: null,
    vertical_template: "clinic",
    hours: [
      { day: "mon", opens: "09:30", closes: "18:00", closed: false },
      { day: "sun", opens: null, closes: null, closed: true },
    ],
    branches: [{ label: "Main", address: "12 MG Road, Hyderabad" }],
    services: [{ name: "Root canal", price_inr: "8000", notes: null }],
    faqs: [],
    staff: [],
    booking_rules: null,
    contacts: [{ id: "c1", label: "Reception", phone_e164: "+919000000123", note: null }],
    languages: ["te-IN"],
    setup: {
      steps: STEPS.map((id) => ({ id, state: "todo" as const })),
      started: true,
      dismissed: false,
      complete: false,
      on_dashboard: true,
      nudges: [],
    },
    blockers: [],
    required_steps: ["hours", "branches", "services", "contacts"],
    updated_at: null,
    agents_updated: null,
    ...over,
  };
}

describe("the wire mapping", () => {
  it("brings untouched steps up to a newer profile and keeps the edited ones", () => {
    // The wizard left open while a contact is added elsewhere: saving the untouched Contacts
    // step from the first copy deleted that contact.
    const first = draftFromProfile(profile());
    const typing = { ...first, booking_rules: "Call to book." };
    const newer = draftFromProfile(
      profile({
        booking_rules: "Book on WhatsApp.",
        contacts: [
          { id: "c1", label: "Reception", phone_e164: "+919000000123", note: null },
          { id: "c2", label: "Owner", phone_e164: "+919000000124", note: null },
        ],
      }),
    );
    const rebased = rebaseDraft(typing, first, newer);
    expect(toPatch(rebased, "contacts").contacts?.map((c) => c.id)).toEqual(["c1", "c2"]);
    expect(rebased.booking_rules).toBe("Call to book.");
  });

  it("keeps closed apart from not answered", () => {
    const draft = draftFromProfile(profile());
    const tue = draft.business_hours.find((day) => day.day === "tue");
    const sun = draft.business_hours.find((day) => day.day === "sun");
    expect(tue).toMatchObject({ opens: "", closes: "", closed: false });
    expect(sun?.closed).toBe(true);
    const patch = toPatch(draft, "hours");
    expect(patch.hours?.map((day) => day.day)).toEqual(["mon", "sun"]);
  });

  it("sends only the topic of the step being saved", () => {
    const draft = draftFromProfile(profile());
    expect(Object.keys(toPatch(draft, "services"))).toEqual(["services"]);
    expect(Object.keys(toPatch(draft, "contacts"))).toEqual(["contacts"]);
  });

  it("sends a price as the digits typed and keeps a contact's identity", () => {
    const draft = draftFromProfile(profile());
    draft.services[0].price_inr = "1500.50";
    expect(toPatch(draft, "services").services?.[0].price_inr).toBe("1500.50");
    expect(toPatch(draft, "contacts").contacts?.[0].id).toBe("c1");
  });

  it("drops rows nobody typed in", () => {
    const draft = draftFromProfile(profile());
    draft.faqs.push({ question: "", answer: "" });
    expect(toPatch(draft, "faqs").faqs).toEqual([]);
  });

  it("says the languages are where new agents start, not a change to existing ones (D-815)", () => {
    const hint = stepCopy("languages").hint;
    expect(hint).toContain("New agents start out replying in these");
    expect(hint).toContain("agents you create from now on");
  });
});

describe("the setup wizard", () => {
  it("asks one topic at a time and lets a step be skipped", async () => {
    const { calls } = await renderClientPage(<SetupWizard />, {
      "/v1/me": OWNER,
      "/v1/business-profile": profile(),
      "/v1/business-profile/setup": profile(),
    });
    await screen.findByRole("heading", { name: "When are you open?" });
    fireEvent.click(await screen.findByRole("button", { name: /Skip/ }));
    await waitFor(() => {
      const skip = calls.find((call) => call.method === "POST" && call.path === "/v1/business-profile/setup");
      expect(skip).toBeTruthy();
      expect(JSON.parse(skip?.body ?? "{}")).toEqual({ action: "skip", step: "hours" });
    });
    await screen.findByRole("heading", { name: "Where are you?" });
  });

  it("saves only the step's own topic and moves on", async () => {
    const { calls } = await renderClientPage(<SetupWizard />, {
      "/v1/me": OWNER,
      "/v1/business-profile": profile(),
      "PATCH /v1/business-profile": profile(),
    });
    await screen.findByRole("heading", { name: "When are you open?" });
    const save = screen.getByRole("button", { name: "Save and continue" });
    await waitFor(() => expect((save as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(save);
    await waitFor(() => {
      const patch = calls.find((call) => call.method === "PATCH");
      expect(patch).toBeTruthy();
      expect(Object.keys(JSON.parse(patch?.body ?? "{}"))).toEqual(["hours"]);
    });
    await screen.findByRole("heading", { name: "Where are you?" });
  });

  it("refuses a day with only one time before anything is sent", async () => {
    const { calls } = await renderClientPage(<SetupWizard />, {
      "/v1/me": OWNER,
      "/v1/business-profile": profile({ hours: [] }),
    });
    await screen.findByRole("heading", { name: "When are you open?" });
    const opens = document.getElementById("profile-business_hours-tue-opens") as HTMLInputElement;
    fireEvent.change(opens, { target: { value: "09:00" } });
    expect(await screen.findAllByText(/Give both times, or tick Closed/)).not.toHaveLength(0);
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);
  });

  it("marks the steps the server says an agent needs before it takes calls (D-838)", async () => {
    await renderClientPage(<SetupWizard />, {
      "/v1/me": OWNER,
      // No agent answers calls or hands them over, so people who take calls are not needed.
      "/v1/business-profile": profile({ required_steps: ["hours", "branches", "services"] }),
    });
    await screen.findByRole("heading", { name: "When are you open?" });
    expect(screen.getByText("Needed for calls")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /People who take calls/ }));
    await screen.findByRole("heading", { name: "Who can take a call?" });
    expect(screen.queryByText("Needed for calls")).toBeNull();
  });
});

describe("the business profile screen", () => {
  it("links each missing fact to the step that fixes it", async () => {
    const { container } = await renderClientPage(<BusinessProfileScreen />, {
      "/v1/me": OWNER,
      "/v1/business-profile": profile({
        blockers: [
          { code: "service_missing", step: "services", message: "Add at least one service." },
        ],
      }),
    });
    await screen.findByText("Finish your business profile");
    const blockers = screen.getByRole("region", { name: "Finish your business profile" });
    const row = within(blockers).getByText("Services and prices").closest("li") as HTMLElement;
    const link = within(row).getByRole("link", { name: /Open/ });
    expect(link.getAttribute("href")).toContain("/c/acme/setup?step=services");
    expect(container.textContent).toContain("Sunrise Dental");
  });

  it("keeps what is being typed in one section while another section's save lands", async () => {
    const { container } = await renderClientPage(<BusinessProfileScreen />, {
      "/v1/me": OWNER,
      "/v1/business-profile": profile(),
      "PATCH /v1/business-profile": profile({
        branches: [{ label: "Main", address: "14 MG Road, Hyderabad" }],
      }),
    });
    await screen.findAllByRole("button", { name: "Save" });
    const textboxesOf = (index: number) =>
      within(container.querySelectorAll("form")[index] as HTMLElement).getAllByRole("textbox");
    const address = textboxesOf(1).find(
      (box) => (box as HTMLInputElement).value === "12 MG Road, Hyderabad",
    ) as HTMLInputElement;
    fireEvent.change(address, { target: { value: "14 MG Road, Hyderabad" } });
    fireEvent.submit(container.querySelectorAll("form")[1] as HTMLFormElement);
    // Before the save answers, the owner is already typing in another section.
    const other = textboxesOf(5)[0] as HTMLInputElement | HTMLTextAreaElement;
    fireEvent.change(other, { target: { value: "Walk-ins before noon only" } });
    await screen.findByText("Your agents use this now.");
    expect((textboxesOf(5)[0] as HTMLInputElement).value).toBe("Walk-ins before noon only");
  });

  it("is read-only for staff, with the reason on screen", async () => {
    await renderClientPage(<BusinessProfileScreen />, {
      "/v1/me": { ...OWNER, role: "staff", permissions: ["org:read", "agents:read"] },
      "/v1/business-profile": profile(),
    });
    await screen.findByText(/Only an account owner can change the business profile/);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });
});

describe("the setup checklist's two places (founder, 22 Oct 2026)", () => {
  it("is always under Settings, even when the dashboard does not show it", async () => {
    const off = profile({ setup: { ...profile().setup, dismissed: true, on_dashboard: false } });
    await renderClientPage(<SetupChecklist placement="settings" />, {
      "/v1/me": OWNER,
      "/v1/business-profile": off,
    });
    expect(await screen.findByText("Your setup")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Hide this list" })).toBeNull();
  });

  it("is not on the dashboard when the server says it is not due", async () => {
    // After the first day, with no call showing a missing step.
    const off = profile({ setup: { ...profile().setup, on_dashboard: false } });
    const { container } = await renderClientPage(<SetupChecklist />, {
      "/v1/me": OWNER,
      "/v1/business-profile": off,
    });
    await waitFor(() => expect(container.textContent).toBe(""));
  });

  it("comes back saying why, on the step the calls show is missing", async () => {
    const back = profile({
      setup: {
        ...profile().setup,
        on_dashboard: true,
        nudges: [
          {
            step: "contacts",
            message: "3 calls in the last 14 days needed a person, and nobody is set up to take calls.",
          },
        ],
      },
    });
    await renderClientPage(<SetupChecklist />, {
      "/v1/me": OWNER,
      "/v1/business-profile": back,
    });
    expect(await screen.findByText("Your calls show something is missing")).toBeTruthy();
    expect(
      screen.getByText("3 calls in the last 14 days needed a person, and nobody is set up to take calls."),
    ).toBeTruthy();
  });
});
