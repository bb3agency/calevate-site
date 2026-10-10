import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SetupWizard } from "@/app/c/[slug]/setup/SetupWizard";
import { SetupChecklist } from "@/app/c/[slug]/SetupChecklist";
import { BusinessProfileScreen } from "@/app/c/[slug]/settings/business/BusinessProfileScreen";
import {
  draftFromProfile,
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
    },
    blockers: [],
    updated_at: null,
    agents_updated: null,
    ...over,
  };
}

describe("the wire mapping", () => {
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
    const link = screen.getByRole("link", { name: /Services and prices/ });
    expect(link.getAttribute("href")).toContain("/c/acme/setup?step=services");
    expect(container.textContent).toContain("Sunrise Dental");
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

describe("the setup checklist's two places (founder, REDESIGN-2)", () => {
  it("leaves the dashboard once hidden but stays under Settings, and can go back", async () => {
    const hidden = profile({ setup: { ...profile().setup, dismissed: true } });
    const { calls } = await renderClientPage(<SetupChecklist placement="settings" />, {
      "/v1/me": OWNER,
      "/v1/business-profile": hidden,
      "POST /v1/business-profile/setup": profile(),
    });
    expect(await screen.findByText("Your setup")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show it on the dashboard again" }));
    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST" && c.path.endsWith("/setup"));
      expect(JSON.parse(post?.body ?? "{}")).toEqual({ action: "reopen" });
    });
  });

  it("is not on the dashboard once hidden", async () => {
    const hidden = profile({ setup: { ...profile().setup, dismissed: true } });
    const { container } = await renderClientPage(<SetupChecklist />, {
      "/v1/me": OWNER,
      "/v1/business-profile": hidden,
    });
    await waitFor(() => expect(container.textContent).toBe(""));
  });
});
