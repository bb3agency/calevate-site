import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AutodialerNoticePanel } from "@/app/c/[slug]/agreements/AutodialerNoticePanel";
import { parseDeclaredNumbers, type AutodialerNotice } from "@/lib/api/autodialerNotice";
import type { Me } from "@/lib/api/client";

import { renderClientPage } from "./harness";

/**
 * The notice names the numbers the calls come from (TCCCPR Third Amendment, 18 Sep 2026).
 *
 * The dial gate refuses a call from a number the notice does not name, so the panel has to
 * say which of the account's numbers are missing, make adding them one press, and refuse
 * to submit a notice that names none.
 */

const OWNER: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const MISSING_ONE: AutodialerNotice = {
  recorded: true,
  state: "notified",
  access_provider: "Airtel",
  objective: "Appointment reminders",
  notified_on: "2026-09-01",
  notice_reference: null,
  effective: true,
  declared_clis: ["+919848022338"],
  undeclared_clis: ["+911409876543"],
};

function routes() {
  return { "/v1/me": OWNER, "/v1/compliance/autodialer-notice": MISSING_ONE };
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("the numbers on the autodialer notice", () => {
  it("names the agent numbers the notice leaves out", async () => {
    await renderClientPage(<AutodialerNoticePanel />, routes());

    expect(await screen.findByText("+911409876543")).toBeTruthy();
    expect(
      screen.getByText(/does not name every number your agents call from/),
    ).toBeTruthy();
  });

  it("will not record a notice that names no number", async () => {
    await renderClientPage(<AutodialerNoticePanel />, routes());
    await screen.findByText("+911409876543");

    fill("Which operator did you tell?", "Airtel");
    fill("What is the date on your letter?", "2026-09-20");
    fill("What did you tell them the calls are for?", "Appointment reminders");

    const submit = screen.getByRole("button", { name: "Record this notice" });
    expect(submit.matches(":disabled")).toBe(true);
  });

  it("adds the missing numbers in one press and sends them", async () => {
    const { calls } = await renderClientPage(<AutodialerNoticePanel />, routes());
    await screen.findByText("+911409876543");

    fill("Which operator did you tell?", "Airtel");
    fill("What is the date on your letter?", "2026-09-20");
    fill("What did you tell them the calls are for?", "Appointment reminders");
    fill("Which numbers did your letter say the calls come from?", "+91 98480 22338");
    fireEvent.click(screen.getByRole("button", { name: "Add my agents' numbers" }));

    const submit = screen.getByRole("button", { name: "Record this notice" });
    await waitFor(() => expect(submit.matches(":disabled")).toBe(false));
    fireEvent.click(submit);

    await waitFor(() =>
      expect(calls.some((call) => call.method === "POST")).toBe(true),
    );
    const posted = calls.find((call) => call.method === "POST");
    expect(JSON.parse(posted?.body ?? "{}").declared_clis).toEqual([
      "+91 98480 22338",
      "+911409876543",
    ]);
  });
});

describe("parseDeclaredNumbers", () => {
  it("splits on lines and commas and drops blanks", () => {
    expect(parseDeclaredNumbers(" +91 98480 22338 ,\n\n1409876543\n")).toEqual([
      "+91 98480 22338",
      "1409876543",
    ]);
  });
});
