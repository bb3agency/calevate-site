import type { AdminBusinessProfile, BusinessProfile } from "@/lib/api/businessProfile";
import type { UnfinishedOnboarding } from "@/lib/api/onboarding";

/**
 * A business profile as `GET /v1/business-profile` answers it (D-695): every setup step
 * answered and nothing blocking, so a screen that shows the setup checklist or the go-live
 * blockers renders neither unless the test is about them.
 */
export function businessProfileFixture(over: Partial<BusinessProfile> = {}): BusinessProfile {
  return {
    business_name: "Sri Clinic",
    legal_name: null,
    vertical_template: "clinic",
    hours: [{ day: "mon", opens: "09:00", closes: "18:00", closed: false }],
    branches: [{ label: "Main", address: "1 Test Road, Hyderabad" }],
    services: [{ name: "Consultation", price_inr: "500", notes: null }],
    faqs: [],
    staff: [],
    booking_rules: null,
    contacts: [{ id: "c1", label: "Front desk", phone_e164: "+919000000999", note: null }],
    languages: ["te-IN"],
    setup: {
      steps: (["hours", "branches", "services", "faqs", "staff", "booking", "contacts", "languages"] as const).map(
        (id) => ({ id, state: "done" as const }),
      ),
      started: true,
      dismissed: false,
      complete: true,
    },
    blockers: [],
    updated_at: null,
    agents_updated: null,
    ...over,
  };
}

/** The unfinished-onboardings list, empty: no account is waiting on an owner. */
export const NO_UNFINISHED: UnfinishedOnboarding[] = [];

/** `GET /v1/admin/tenants/{id}/owner-status` for an account its owner has joined. */
export const OWNER_JOINED = { owner_present: true, invite_pending: false };

/** The operator console's read of the same profile. */
export function adminBusinessProfileFixture(): AdminBusinessProfile {
  return { ...businessProfileFixture(), merge_notes: [] };
}
