/**
 * A dialog opened from a menu item keeps focus.
 *
 * The menu (`arc/menu`, Radix) hands focus back to its trigger when it closes, and it
 * closes in the same press that opens the dialog — so the hand-back landed AFTER the
 * dialog had moved focus in, and a keyboard or screen-reader user was left on the ⋯ button
 * behind an open modal. "Remove", "Stop campaign", "Revoke access" and "Mark" all open
 * their confirmation this way.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { RowMenu } from "@/components/arc/menu";
import { ConfirmDialog } from "@/components/confirmDialog";

function Row() {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <RowMenu
        label="Price list"
        items={[{ id: "remove", label: "Remove", tone: "danger", onSelect: () => setAsking(true) }]}
      />
      {asking && (
        <ConfirmDialog
          title="Remove Price list?"
          confirmLabel="Remove"
          pendingLabel="Removing"
          error={null}
          onCancel={() => setAsking(false)}
          onConfirm={() => setAsking(false)}
        >
          Your agents stop using it.
        </ConfirmDialog>
      )}
    </>
  );
}

async function settle() {
  // Radix returns focus on a timer after the menu's content unmounts.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

describe("a dialog opened from a menu", () => {
  it("keeps focus inside the dialog after the menu closes", async () => {
    render(<Row />);
    const trigger = screen.getByRole("button", { name: "More actions for Price list" });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Enter" });
    const item = await screen.findByRole("menuitem", { name: "Remove" });
    fireEvent.click(item);
    const dialog = await screen.findByRole("dialog", { name: "Remove Price list?" });
    await settle();
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("gives focus back to the menu's button when the dialog closes", async () => {
    render(<Row />);
    const trigger = screen.getByRole("button", { name: "More actions for Price list" });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Remove" }));
    await screen.findByRole("dialog", { name: "Remove Price list?" });
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await settle();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
