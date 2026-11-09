import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ClientAccountPage from "@/app/(auth)/auth/account/page";
import { clientAuthn } from "@/lib/authn/clientAuthn";
import { normaliseMobileNumber } from "@/lib/authn/mobileNumber";

import { problem, stubApi, type Routes } from "./harness";

/**
 * The Mobile number row on Your account (D-976). No code is sent to the number yet, so the
 * one guard against a typo is the second look: what is typed is shown back, formatted, and
 * only "Save" on that screen writes it.
 */

const SET_PATH = "POST /v1/auth/client/mobile-number";

const ME = {
  user_id: "0192f0aa-0000-7000-8000-0000000000c1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage"],
  impersonating: false,
  email: "lakshmi@example.com",
  name: "Lakshmi Rao",
  phone: null as string | null,
  organization: {
    id: "0192f0aa-0000-7000-8000-0000000000d1",
    name: "Sri Lakshmi Dental",
    slug: "sri-lakshmi-dental",
    status: "active",
  },
};

async function renderPage(routes: Routes) {
  const calls = stubApi(routes);
  await act(async () => {
    render(<ClientAccountPage />);
  });
  return calls;
}

function bodyOf(calls: ReturnType<typeof stubApi>, suffix: string): unknown[] {
  return calls
    .filter((c) => c.method === "POST" && c.path.endsWith(suffix))
    .map((c) => (c.body === null ? null : JSON.parse(c.body)));
}

afterEach(() => {
  vi.unstubAllGlobals();
  clientAuthn.reset();
  window.location.hash = "";
});

describe("the number a person types becomes one E.164 value", () => {
  it.each([
    ["98765 43210", "+919876543210"],
    ["09876543210", "+919876543210"],
    ["+91 98765-43210", "+919876543210"],
    ["919876543210", "+919876543210"],
    ["+44 7700 900123", "+447700900123"],
  ])("%s -> %s", (typed, e164) => {
    expect(normaliseMobileNumber(typed)).toBe(e164);
  });

  it.each(["12345", "5876543210", "++919876543210", "98765+43210", ""])(
    "refuses %j rather than guessing",
    (typed) => {
      expect(normaliseMobileNumber(typed)).toBeNull();
    },
  );
});

describe("adding a mobile number", () => {
  it("says what it is for and offers Add when there is none", async () => {
    await renderPage({ "/v1/me": ME });

    expect(await screen.findByText("Not added")).toBeTruthy();
    expect(screen.getByText("For WhatsApp alerts and automatic top-ups.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add your mobile number" })).toBeTruthy();
  });

  it("shows the number back and saves only from that screen", async () => {
    let me = ME;
    const calls = await renderPage({
      "/v1/me": () => me,
      [SET_PATH]: () => {
        me = { ...ME, phone: "+919876543210" };
        return { change: "added" };
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Add your mobile number" }));
    fireEvent.change(screen.getByLabelText("Mobile number"), { target: { value: "98765 43210" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
    });

    expect(screen.getByText("Is this right?")).toBeTruthy();
    expect(screen.getByText("+91 98765 43210")).toBeTruthy();
    expect(bodyOf(calls, "/mobile-number")).toEqual([]);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });

    expect(bodyOf(calls, "/mobile-number")).toEqual([{ phone: "+919876543210" }]);
    expect(await screen.findByText("Mobile number saved.")).toBeTruthy();
    expect(await screen.findByText("+91 98765 43210")).toBeTruthy();
  });

  it("goes back to the field with the typing kept when the number is wrong", async () => {
    const calls = await renderPage({ "/v1/me": ME, [SET_PATH]: { change: "added" } });

    fireEvent.click(await screen.findByRole("button", { name: "Add your mobile number" }));
    fireEvent.change(screen.getByLabelText("Mobile number"), { target: { value: "98765 43201" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
    });
    fireEvent.click(screen.getByRole("button", { name: "Change" }));

    expect((screen.getByLabelText("Mobile number") as HTMLInputElement).value).toBe("98765 43201");
    expect(bodyOf(calls, "/mobile-number")).toEqual([]);
  });

  it("says plainly what to type when the number cannot be read", async () => {
    const calls = await renderPage({ "/v1/me": ME });

    fireEvent.click(await screen.findByRole("button", { name: "Add your mobile number" }));
    fireEvent.change(screen.getByLabelText("Mobile number"), { target: { value: "12345" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
    });

    expect(
      screen.getByText("Enter a 10-digit mobile number, or the full number starting with +."),
    ).toBeTruthy();
    expect(screen.queryByText("Is this right?")).toBeNull();
    expect(bodyOf(calls, "/mobile-number")).toEqual([]);
  });

  it("shows the server's refusal on the check screen", async () => {
    await renderPage({
      "/v1/me": ME,
      [SET_PATH]: problem(422, {
        type: "urn:calevate:error/mobile_number_invalid",
        title: "Check your mobile number",
        detail: "Enter a 10-digit mobile number, or the full number starting with +.",
        kind: "validation",
      }),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Add your mobile number" }));
    fireEvent.change(screen.getByLabelText("Mobile number"), { target: { value: "9876543210" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("Is this right?")).toBeTruthy();
  });

  it("opens the field straight away when the owner arrives from an Add button", async () => {
    window.location.hash = "#mobile-number";
    await renderPage({ "/v1/me": ME });

    expect(await screen.findByLabelText("Mobile number")).toBeTruthy();
  });
});

describe("a number already on the login", () => {
  const WITH_PHONE = { ...ME, phone: "+919876543210" };

  it("shows it formatted and offers Change", async () => {
    await renderPage({ "/v1/me": WITH_PHONE });

    expect(await screen.findByText("+91 98765 43210")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Change your mobile number" })).toBeTruthy();
  });

  it("asks before removing it, then sends null", async () => {
    const calls = await renderPage({
      "/v1/me": WITH_PHONE,
      [SET_PATH]: { change: "removed" },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Change your mobile number" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove number" }));
    const dialog = screen.getByRole("dialog", { name: "Remove your mobile number?" });
    expect(bodyOf(calls, "/mobile-number")).toEqual([]);

    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Remove number" }));
    });

    expect(bodyOf(calls, "/mobile-number")).toEqual([{ phone: null }]);
    expect(await screen.findByText("Mobile number removed.")).toBeTruthy();
  });

  it("tells the owner a new number needs the WhatsApp agreement again", async () => {
    await renderPage({ "/v1/me": WITH_PHONE, [SET_PATH]: { change: "changed" } });

    fireEvent.click(await screen.findByRole("button", { name: "Change your mobile number" }));
    fireEvent.change(screen.getByLabelText("Mobile number"), { target: { value: "98765 00011" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Next" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });

    expect(
      await screen.findByText("Saved. Turn WhatsApp alerts on again for the new number."),
    ).toBeTruthy();
  });
});
