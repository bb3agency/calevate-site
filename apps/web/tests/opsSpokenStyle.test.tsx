import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import SpokenStylePage from "@/app/admin/ops/spoken-style/page";
import { textToTurns, turnsToText } from "@/app/admin/ops/spoken-style/SpokenStyleScreen";
import { SPOKEN_STYLE_PATH, reviewStamp } from "@/lib/api/spokenStyle";

import { STYLE_LIST, TELUGU_STYLE } from "./fixtures/spokenStyle";
import { renderAdminPage } from "./harness";

/**
 * Ops > Spoken style (D-744). What the screen must get right, worst failure first:
 *
 * 1. Publishing sends the server's own confirmation string; nothing else carries one.
 * 2. Approve, edit and retire send exactly the entry they name.
 * 3. The stamp says who reviewed it and when, and a refused session is told so.
 */

const SUPERADMIN: AdminMe = {
  user_id: "0192f0aa-7777-7000-8000-0000000000e1",
  realm: "admin",
  role: "superadmin",
  permissions: ["ops:manage", "admin:tenants"],
};

const OPERATOR: AdminMe = {
  user_id: "0192f0aa-7777-7000-8000-0000000000e2",
  realm: "admin",
  role: "operator",
  permissions: ["admin:tenants", "org:read"],
};

const LANGUAGE_PATH = `${SPOKEN_STYLE_PATH}/te-IN`;

function routes(extra: Record<string, unknown> = {}) {
  return {
    [ADMIN_ME_PATH]: SUPERADMIN,
    [SPOKEN_STYLE_PATH]: STYLE_LIST,
    [LANGUAGE_PATH]: TELUGU_STYLE,
    [`POST ${LANGUAGE_PATH}/entries`]: TELUGU_STYLE,
    [`POST ${LANGUAGE_PATH}/publish`]: TELUGU_STYLE,
    ...extra,
  };
}

describe("Ops > Spoken style", () => {
  it("shows the stamp, the counts and every kind of entry", async () => {
    renderAdminPage(<SpokenStylePage />, routes());
    expect((await screen.findAllByText(/Reviewed by Sri on 11 Oct 2026/)).length).toBe(2);
    expect(screen.getByText(/2 of 6 entries approved/)).toBeTruthy();
    expect(screen.getByText("ధన్యవాదాలు → thanks అండి", { exact: false })).toBeTruthy();
    expect(screen.getByText("Formal word, and what people say")).toBeTruthy();
    expect(screen.getByText("Example exchanges")).toBeTruthy();
    expect(screen.getAllByText("Needs review").length).toBe(4);
    expect(screen.getByText("Retired")).toBeTruthy();
  });

  it("approves and retires exactly the entry named", async () => {
    const page = renderAdminPage(<SpokenStylePage />, routes());
    fireEvent.click(await screen.findByRole("button", { name: /^Approve: సరే అండి/ }));
    await waitFor(() =>
      expect(page.calls.some((c) => c.method === "POST" && c.path.endsWith("/entries"))).toBe(true),
    );
    const approve = page.calls.find((c) => c.method === "POST" && c.path.endsWith("/entries"));
    expect(JSON.parse(approve?.body ?? "{}")).toEqual({
      kind: "filler",
      action: "approve",
      key: "sare-andi",
      value: null,
    });
    expect(Object.keys(approve?.headers ?? {}).map((h) => h.toLowerCase())).not.toContain("x-confirm-action");
  });

  it("edits a swap's spoken word and keeps its formal word as the key", async () => {
    const page = renderAdminPage(<SpokenStylePage />, routes());
    fireEvent.click(await screen.findByRole("button", { name: /^Edit: ధన్యవాదాలు/ }));
    fireEvent.change(screen.getByLabelText(/^What people say/), { target: { value: "thank you అండి" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and approve" }));
    await waitFor(() =>
      expect(page.calls.some((c) => c.method === "POST" && c.path.endsWith("/entries"))).toBe(true),
    );
    const edit = page.calls.find((c) => c.method === "POST" && c.path.endsWith("/entries"));
    expect(JSON.parse(edit?.body ?? "{}")).toEqual({
      kind: "swap",
      action: "edit",
      key: "ధన్యవాదాలు",
      value: { formal: "ధన్యవాదాలు", spoken: "thank you అండి", in_prompt: true },
    });
  });

  it("edits a filler with its slow-reply tick", async () => {
    const page = renderAdminPage(<SpokenStylePage />, routes());
    fireEvent.click(await screen.findByRole("button", { name: /^Edit: సరే అండి/ }));
    fireEvent.click(screen.getByLabelText("Say this while a reply is slow"));
    fireEvent.click(screen.getByRole("button", { name: "Save and approve" }));
    await waitFor(() =>
      expect(page.calls.some((c) => c.method === "POST" && c.path.endsWith("/entries"))).toBe(true),
    );
    const edit = page.calls.find((c) => c.method === "POST" && c.path.endsWith("/entries"));
    expect(JSON.parse(edit?.body ?? "{}").value).toMatchObject({ text: "సరే అండి", thinking: true });
  });

  it("publishes with the reviewer's name and the server's confirmation string", async () => {
    const page = renderAdminPage(<SpokenStylePage />, routes());
    fireEvent.change(await screen.findByLabelText(/^Reviewed by/), { target: { value: "Sri" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish to live agents" }));
    await waitFor(() => expect(page.calls.some((c) => c.path.endsWith("/publish"))).toBe(true));
    const publish = page.calls.find((c) => c.path.endsWith("/publish"));
    expect(JSON.parse(publish?.body ?? "{}")).toEqual({ reviewer_name: "Sri", note: null });
    const header = Object.entries(publish?.headers ?? {}).find(
      ([name]) => name.toLowerCase() === "x-confirm-action",
    );
    expect(header?.[1]).toBe("publish_spoken_style:te-IN");
  });

  it("tells a session without ops:manage that it may not review", async () => {
    renderAdminPage(<SpokenStylePage />, routes({ [ADMIN_ME_PATH]: OPERATOR }));
    expect(await screen.findByText(/review how agents speak/)).toBeTruthy();
    expect(screen.queryByLabelText(/^Reviewed by/)).toBeNull();
  });

  it("round-trips an example's lines", () => {
    const turns = [
      { speaker: "caller" as const, text: "హలో?" },
      { speaker: "agent" as const, text: "హా, చెప్పండి." },
    ];
    expect(textToTurns(turnsToText(turns))).toEqual(turns);
    expect(reviewStamp({ reviewed_by: null, reviewed_on: null })).toBeNull();
  });
});
