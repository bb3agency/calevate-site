import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BusinessCopySection, REFRESH_REQUEST, lastRefreshed } from "@/app/c/[slug]/settings/business/BusinessCopySection";
import { costLine, writtenLine } from "@/app/admin/tenants/[tenantId]/BusinessCopyPanel";
import type { AdminBusinessCopy, BusinessCopy, GeneratedPlaceholders } from "@/lib/api/businessCopy";
import { useClientSession } from "@/lib/api/session";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";
import { sameLanguage, useBusinessSuggestions, useVerticalExamples } from "@/lib/useVerticalExamples";
import { examplesFor, withGeneratedCopy } from "@/lib/verticalExamples";

import { OWNER_ME } from "./fixtures/sharedReads";
import { NO_BUSINESS_COPY, renderClientPage } from "./harness";

/**
 * D-827: the account's own AI-written examples are laid over the per-trade table, which
 * stays the fallback until the first copy lands; the Business profile screen says when they
 * were last written and asks Pip for a refresh.
 */

const PLACEHOLDERS: GeneratedPlaceholders = {
  branch_label: "Kukatpally shop",
  service_name: "Cold-pressed groundnut oil (1 litre)",
  service_price: "320",
  service_note: "Fresh batch every Monday",
  ask_on_arrival: "depends on the day's stock",
  faq_question: "Do you deliver to Miyapur?",
  staff_name: "Ramesh Rao",
  staff_spoken: "RAA-mesh RAO",
  staff_role: "Owner",
  staff_why_it_matters: "regular customers ask for the owner by name",
  booking_rules: "Orders before 6 pm are packed the same day.",
  contact_name: "Shop counter",
  knowledge_title: "This week's oil prices",
  knowledge_answer: "Free home delivery above 500 rupees.",
  extraction_reason: "so we can pack the order before the customer arrives",
  script_brief: "We sell cold-pressed oils in Hyderabad.",
  extraction_label: "Oil wanted",
  extraction_options: "Pickup, Home delivery",
  end_call_rules: "Never promise stock.\nAlways offer a call back.",
  lead_search: "groundnut oil for Saturday",
  booking_job_title: "Take orders",
  booking_job_line: "Your agent can check your calendar and book pickup times.",
};

const LANDED: BusinessCopy = {
  ...NO_BUSINESS_COPY,
  placeholders: PLACEHOLDERS,
  steps: [{ name: "Take the order", example_line: "Enni litres kavali andi?" }],
  caller_details: ["Oil wanted", "Delivery area", "Quantity"],
  example_questions: ["Is the oil cold-pressed?", "Do you deliver on Sundays?", "Can I pay on delivery?"],
  language: "te-IN",
  generated_at: "2026-10-19T04:30:00Z",
};

describe("the generated copy is laid over the per-trade table", () => {
  it("keeps the table when nothing has landed", () => {
    expect(withGeneratedCopy(examplesFor("clinic"), null)).toEqual(examplesFor("clinic"));
  });

  it("replaces every generated key and keeps the two shown before an account exists", () => {
    const merged = withGeneratedCopy(examplesFor("clinic"), PLACEHOLDERS);
    expect(merged.serviceName).toBe("Cold-pressed groundnut oil (1 litre)");
    expect(merged.bookingJobTitle).toBe("Take orders");
    expect(merged.endCallRules).toBe("Never promise stock.\nAlways offer a call back.");
    expect(merged.orgName).toBe(examplesFor("clinic").orgName);
  });

  it("falls back key by key on a blank value", () => {
    const merged = withGeneratedCopy(examplesFor("retail"), { ...PLACEHOLDERS, lead_search: "  " });
    expect(merged.leadSearch).toBe(examplesFor("retail").leadSearch);
  });

  it("matches a language whatever the region", () => {
    expect(sameLanguage("te-IN", "te")).toBe(true);
    expect(sameLanguage("te-IN", "hi-IN")).toBe(false);
    expect(sameLanguage(null, null)).toBe(false);
  });
});

function Probe() {
  const eg = useVerticalExamples();
  const ideas = useBusinessSuggestions();
  useClientSession();
  return (
    <p>
      <span data-testid="service">{eg.serviceName}</span>
      <span data-testid="question">{ideas.exampleQuestions[0] ?? "none"}</span>
    </p>
  );
}

describe("useVerticalExamples reads the stored copy", () => {
  it("shows the account's business type until the first copy lands", async () => {
    await renderClientPage(<Probe />, {
      "/v1/me": { ...OWNER_ME, organization: { ...OWNER_ME.organization, vertical_template: "retail" } },
    });
    expect((await screen.findByTestId("service")).textContent).toBe(examplesFor("retail").serviceName);
    expect(screen.getByTestId("question").textContent).toBe("none");
  });

  it("shows the account's own examples once they land", async () => {
    await renderClientPage(<Probe />, { "/v1/me": OWNER_ME, "/v1/business-copy": LANDED });
    expect((await screen.findByText("Cold-pressed groundnut oil (1 litre)")).textContent).toBeTruthy();
    expect(screen.getByTestId("question").textContent).toBe("Is the oil cold-pressed?");
  });
});

function listenToPip(): AssistantRequest[] {
  const asked: AssistantRequest[] = [];
  function Listener() {
    useAssistantRequests((request) => asked.push(request));
    return null;
  }
  render(<Listener />);
  return asked;
}

function Section({ canWrite = true }: { canWrite?: boolean }) {
  return <BusinessCopySection session={useClientSession()} canWrite={canWrite} />;
}

describe("the Business profile's examples row", () => {
  it("says when they were written and asks Pip for a refresh", async () => {
    const asked = listenToPip();
    const { calls } = await renderClientPage(<Section />, { "/v1/business-copy": LANDED });
    expect(await screen.findByText(lastRefreshed(LANDED, false, false))).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Refresh now: / }));
    });
    expect(asked.map((a) => a.prompt)).toEqual([REFRESH_REQUEST]);
    // The page asks Pip; it writes nothing itself.
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("says the examples come from the business type before the first copy", async () => {
    await renderClientPage(<Section />, {});
    expect(await screen.findByText(/Not yet/)).toBeTruthy();
  });

  it("cannot be refreshed while a run is in progress or by someone who cannot change the profile", async () => {
    await renderClientPage(<Section />, { "/v1/business-copy": { ...LANDED, refreshing: true } });
    expect(await screen.findByText(/is writing them now/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /^Refresh now: / }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("is disabled for a reader", async () => {
    await renderClientPage(<Section canWrite={false} />, { "/v1/business-copy": LANDED });
    expect((await screen.findByRole("button", { name: /^Refresh now: / }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("says plainly why the last run wrote nothing", async () => {
    const stopped = {
      ...LANDED,
      stop_reason: "allowance_used_up" as const,
      stop_message: "Not refreshed: this month's AI help allowance is used up. Your examples stay as they are.",
    };
    await renderClientPage(<Section />, { "/v1/business-copy": stopped });
    expect(await screen.findByText(/allowance is used up/)).toBeTruthy();
  });
});

describe("the operator's lines", () => {
  const admin: AdminBusinessCopy = {
    ...LANDED,
    model: "gemini-3.1-flash-lite",
    cost_inr: "0.26626",
    absorbed: true,
    last_trigger: "signup",
    last_attempt_at: "2026-10-19T04:30:00Z",
  };

  it("names who paid and why it ran", () => {
    expect(costLine(admin)).toContain("paid by us");
    expect(costLine({ ...admin, absorbed: false })).toContain("from the client's AI allowance");
    expect(writtenLine(admin)).toContain("account created");
    expect(writtenLine({ ...admin, generated_at: null })).toMatch(/^Not yet/);
  });
});
