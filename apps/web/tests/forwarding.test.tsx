import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PhoneNumbersSettingsPage from "@/app/c/[slug]/settings/phone-numbers/page";
import ExistingNumberPage from "@/app/c/[slug]/setup/existing-number/page";
import { ForwardingCard } from "@/app/admin/tenants/[tenantId]/numbers/ForwardingCard";
import { dialledForm, renderCode } from "@/lib/api/forwarding";

import { ADMIN_FORWARDING, CODES, LINE, READY_TO_FORWARD, SETTLED_TEST, WITH_LINE } from "./fixtures/forwarding";
import { renderAdminPage, renderClientPage, type Routes } from "./harness";

const ME = {
  user_id: "u1",
  tenant_id: "t1",
  role: "owner",
  permissions: ["org:read", "org:manage"],
  impersonating: false,
};

function settingsRoutes(over: Routes = {}): Routes {
  return {
    "/v1/me": ME,
    "/v1/forwarding": WITH_LINE,
    "/v1/forwarding/codes": CODES,
    "/v1/forwarding/lines/l1/tests?limit=5": [SETTLED_TEST],
    "/v1/forwarding/save-number": { enabled: false },
    "/v1/call-lines": { call_lines: 2, in_progress: 0, on_trial: false },
    ...over,
  };
}

describe("dialled form of the Calevate number", () => {
  it("is 0 and the ten digits, whatever the series", () => {
    expect(dialledForm("+918012345678")).toBe("08012345678");
    expect(dialledForm("+919812345678")).toBe("09812345678");
    expect(renderCode("**61*{number}**{seconds}#", "+919812345678", 25)).toBe("**61*09812345678**25#");
  });
});

describe("Settings > Phone numbers", () => {
  it("shows the line, its findings and the quiet notice", async () => {
    await renderClientPage(<PhoneNumbersSettingsPage />, settingsRoutes());
    expect(await screen.findByText("+91 98123 45678")).toBeTruthy();
    expect(screen.getByText("Rings 20 seconds first, then your agent answers")).toBeTruthy();
    // The line's finding, and the settled test's when its history has loaded: one or both.
    expect(screen.getAllByText(/shows your number instead of the caller's/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Only one of two calls at the same time/).length).toBeGreaterThan(0);
    expect(screen.getByText("No calls from this number for three days.")).toBeTruthy();
  });

  it("reopens Change on the saved setting, not on an edit that was cancelled", async () => {
    await renderClientPage(<PhoneNumbersSettingsPage />, settingsRoutes());
    const change = async () => {
      const button = await screen.findByRole("button", { name: "Change" });
      await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
      fireEvent.click(button);
      return screen.getByLabelText("How long your phone rings first") as HTMLSelectElement;
    };
    fireEvent.change(await change(), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect((await change()).value).toBe("20");
  });

  it("fills the Calevate number and ring time into the codes, with no tel: links", async () => {
    const { container } = await renderClientPage(<PhoneNumbersSettingsPage />, settingsRoutes());
    expect(await screen.findByText("**61*08012345678**20#")).toBeTruthy();
    expect(screen.getByText("**67*08012345678#")).toBeTruthy();
    expect(screen.getByText("**62*08012345678#")).toBeTruthy();
    // The all-calls code is not part of the set-once guide.
    expect(screen.queryByText("**21*08012345678#")).toBeNull();
    expect(container.querySelector('a[href^="tel:"]')).toBeNull();
  });

  it("switches to the all-calls code when 0 seconds is chosen", async () => {
    const all = { ...LINE, mode: "all_calls", ring_seconds: 0 } as const;
    await renderClientPage(
      <PhoneNumbersSettingsPage />,
      settingsRoutes({ "/v1/forwarding": { ...WITH_LINE, lines: [all] } }),
    );
    expect(await screen.findByText("**21*08012345678#")).toBeTruthy();
    expect(screen.getByText("Every call goes straight to your agent")).toBeTruthy();
  });

  it("tells a Jio user to use the app and marks other codes as unconfirmed", async () => {
    const jio = { ...LINE, carrier: "jio" } as const;
    await renderClientPage(
      <PhoneNumbersSettingsPage />,
      settingsRoutes({ "/v1/forwarding": { ...WITH_LINE, lines: [jio] } }),
    );
    expect(await screen.findByText(/MyJio app: Profile/)).toBeTruthy();
    expect(screen.getByText("Codes other sites give")).toBeTruthy();
  });

  it("asks a landline to have its provider enable call divert", async () => {
    const landline = { ...LINE, line_kind: "landline" } as const;
    await renderClientPage(
      <PhoneNumbersSettingsPage />,
      settingsRoutes({ "/v1/forwarding": { ...WITH_LINE, lines: [landline] } }),
    );
    expect(await screen.findByText(/Ask your phone provider to enable call divert/)).toBeTruthy();
  });

  it("runs the test with the account confirmation", async () => {
    const { calls } = await renderClientPage(
      <PhoneNumbersSettingsPage />,
      settingsRoutes({ "POST /v1/forwarding/lines/l1/tests": { ...SETTLED_TEST, status: "ringing", outcome: null } }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Test again" }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const post = calls.find((call) => call.method === "POST");
    expect(post?.path).toBe("/v1/forwarding/lines/l1/tests");
    expect(post?.headers["x-confirm-action"] ?? post?.headers["X-Confirm-Action"]).toBe("forwarding_test:acme");
  });

  it("offers the save-our-number switch, off by default", async () => {
    await renderClientPage(<PhoneNumbersSettingsPage />, settingsRoutes());
    const toggle = await screen.findByRole("switch", { name: /Send one message after a booking/ });
    expect((toggle as HTMLInputElement).checked).toBe(false);
  });
});

describe("Use your existing number (onboarding)", () => {
  it("starts with the number question and refuses a short number", async () => {
    await renderClientPage(<ExistingNumberPage />, { "/v1/me": ME, "/v1/forwarding": READY_TO_FORWARD });
    expect(await screen.findByText("Which number do your callers know?")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Your business number"), { target: { value: "12345" } });
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(await screen.findByText(/Enter your Indian business number/)).toBeTruthy();
  });

  it("sends the client to get a Calevate number first", async () => {
    await renderClientPage(<ExistingNumberPage />, {
      "/v1/me": ME,
      "/v1/forwarding": { ...READY_TO_FORWARD, calevate_numbers: [] },
    });
    expect(await screen.findByText("Get your Calevate number first")).toBeTruthy();
  });
});

describe("admin card", () => {
  it("shows the published number, findings and the message switch", async () => {
    renderAdminPage(<ForwardingCard tenantId="t1" />, {
      "/v1/admin/forwarding/tenants/t1?limit=5": ADMIN_FORWARDING,
    });
    const card = await screen.findByText("+91 98123 45678");
    expect(card).toBeTruthy();
    expect(screen.getByText("On · 4 sent")).toBeTruthy();
    expect(screen.getByText(/Only one of two calls/)).toBeTruthy();
  });
});
