import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import CallWordsPage from "@/app/admin/ops/call-words/page";
import { entryName } from "@/app/admin/ops/call-words/CallWordsScreen";
import { CALL_WORDS_PATH, textToValue, valueToText } from "@/lib/api/callWords";

import { CALL_WORDS, PRICING_DETAIL } from "./fixtures/callWords";
import { renderAdminPage } from "./harness";

/**
 * Ops > Call words (G-C2). What the screen must get right, worst failure first:
 *
 * 1. A save sends the whole list in its shipped shape with the server's own confirmation.
 * 2. "Use the shipped words" sends null, and only an edited list offers it.
 * 3. The lists waiting for the founder's words are what the screen opens on.
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

const PRICING = `${CALL_WORDS_PATH}/detection.topic.pricing`;
const STALLS = `${CALL_WORDS_PATH}/detection.stalls`;

function routes(extra: Record<string, unknown> = {}) {
  return {
    [ADMIN_ME_PATH]: SUPERADMIN,
    [CALL_WORDS_PATH]: CALL_WORDS,
    [PRICING]: PRICING_DETAIL,
    [STALLS]: { ...CALL_WORDS.entries[0], history: [] },
    [`${CALL_WORDS_PATH}/optout.not_now`]: { ...CALL_WORDS.entries[2], history: [] },
    [`PUT ${PRICING}`]: PRICING_DETAIL,
    [`PUT ${STALLS}`]: { ...CALL_WORDS.entries[0], history: [] },
    ...extra,
  };
}

function confirmHeader(call: { headers?: Record<string, string> } | undefined): string | undefined {
  return Object.entries(call?.headers ?? {}).find(([name]) => name.toLowerCase() === "x-confirm-action")?.[1];
}

describe("Ops > Call words", () => {
  it("opens on the lists that need the founder's words, grouped by what reads them", async () => {
    renderAdminPage(<CallWordsPage />, routes());
    expect(await screen.findByText("2 lists need your words")).toBeTruthy();
    expect(screen.getByText("Questions to answer")).toBeTruthy();
    expect(screen.getByText("stalls")).toBeTruthy();
    expect(screen.getByText("topic pricing")).toBeTruthy();
    // Not waiting for words, so hidden until "All lists".
    expect(screen.queryByText("not now")).toBeNull();
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "all" } });
    expect(screen.getByText("not now")).toBeTruthy();
    expect(screen.getByText("Do not call me again")).toBeTruthy();
  });

  it("saves a list as one word per line with the server's confirmation string", async () => {
    const page = renderAdminPage(<CallWordsPage />, routes());
    fireEvent.click(await screen.findByRole("button", { name: "Edit: topic pricing" }));
    fireEvent.change(screen.getByLabelText(/^Words/), { target: { value: "price\ncost\n\nrate\n\n" } });
    fireEvent.change(screen.getByLabelText(/^Why/), { target: { value: " asked often " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(page.calls.some((c) => c.method === "PUT")).toBe(true));
    const put = page.calls.find((c) => c.method === "PUT");
    expect(put?.path).toBe(PRICING);
    // A blank line inside keeps its place; the ones at the end are dropped.
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ value: ["price", "cost", "", "rate"], note: "asked often" });
    expect(confirmHeader(put)).toBe("change_call_words:detection.topic.pricing");
  });

  it("puts the shipped words back with null, offered only on an edited list", async () => {
    const page = renderAdminPage(<CallWordsPage />, routes());
    fireEvent.click(await screen.findByRole("button", { name: "Edit: stalls" }));
    expect(screen.queryByRole("button", { name: "Use the shipped words" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit: topic pricing" }));
    expect(await screen.findByText(/rate is asked often/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Use the shipped words" }));
    await waitFor(() => expect(page.calls.some((c) => c.method === "PUT")).toBe(true));
    const put = page.calls.find((c) => c.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ value: null, note: null });
  });

  it("refuses to send a table that is not JSON, and says why", async () => {
    const page = renderAdminPage(<CallWordsPage />, routes());
    await screen.findByText("2 lists need your words");
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "all" } });
    fireEvent.click(screen.getByRole("button", { name: "Edit: not now" }));
    fireEvent.change(screen.getByLabelText(/^Words/), { target: { value: "{ te: " } });
    expect(screen.getByText(/not valid JSON/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    expect(page.calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("tells a session without ops:manage that it may not change the words", async () => {
    renderAdminPage(<CallWordsPage />, routes({ [ADMIN_ME_PATH]: OPERATOR }));
    expect(await screen.findByText(/change the words the call checks listen for/)).toBeTruthy();
    expect(screen.queryByLabelText("Show")).toBeNull();
  });

  it("round-trips each shape through the editor's text box", () => {
    expect(entryName("turn_checks._TE_WH_STEMS")).toBe("te wh stems");
    expect(textToValue("pattern", " a|b ")).toEqual({ ok: true, value: "a|b" });
    const table = { te: { latin: "x", native: "y" } };
    expect(textToValue("table", valueToText("table", table))).toEqual({ ok: true, value: table });
    expect(textToValue("table", "[]").ok).toBe(false);
  });
});
