import { fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { createPortal } from "react-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useFocusTrap } from "@/lib/focusTrap";

function Panel({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, true, () => {});
  return (
    <div ref={ref} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}>
      {children}
    </div>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  delete (HTMLElement.prototype as Partial<HTMLElement>).checkVisibility;
});

describe("useFocusTrap", () => {
  it("skips a control the stylesheet hides when it picks where focus lands and where Tab wraps", () => {
    // A browser answers checkVisibility from layout; jsdom has none, so the hidden
    // control is named here the way `hidden lg:flex` hides it below `lg`.
    HTMLElement.prototype.checkVisibility = function (this: HTMLElement) {
      return this.dataset.cssHidden === undefined;
    };
    render(
      <Panel label="Navigation">
        <button type="button" data-css-hidden="">
          Collapse sidebar
        </button>
        <button type="button">Close navigation</button>
        <a href="/c/acme/leads">Leads</a>
      </Panel>,
    );
    const close = screen.getByRole("button", { name: "Close navigation" });
    expect(document.activeElement).toBe(close);

    const leads = screen.getByRole("link", { name: "Leads" });
    leads.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(close);
  });

  it("lets only the newest trap handle Tab, so a dialog opened from a drawer keeps its own cycle", () => {
    function Nested({ dialog }: { dialog: boolean }) {
      return (
        <Panel label="History">
          <button type="button">Close history</button>
          {dialog
            ? createPortal(
                <Panel label="Restore this version?">
                  <button type="button">Keep my draft</button>
                  <button type="button">Restore to draft</button>
                </Panel>,
                document.body,
              )
            : null}
        </Panel>
      );
    }
    // The drawer is open first and the confirmation is opened from it, as on the screen.
    const { rerender } = render(<Nested dialog={false} />);
    rerender(<Nested dialog />);
    const keep = screen.getByRole("button", { name: "Keep my draft" });
    const restore = screen.getByRole("button", { name: "Restore to draft" });

    keep.focus();
    // Not at the dialog's last control: no trap may intervene, so the browser's own Tab
    // moves to "Restore to draft". Before, the drawer's trap saw focus outside ITS panel
    // and pulled it back, and the dialog then sent it to "Keep my draft" again.
    const notPrevented = fireEvent.keyDown(document, { key: "Tab" });
    expect(notPrevented).toBe(true);
    expect(document.activeElement).toBe(keep);

    restore.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(keep);
  });

  it("hands Tab back to the drawer once the dialog on top of it closes", () => {
    function Host({ dialog }: { dialog: boolean }) {
      return (
        <Panel label="History">
          <button type="button">Close history</button>
          <button type="button">Restore</button>
          {dialog
            ? createPortal(
                <Panel label="Restore this version?">
                  <button type="button">Keep my draft</button>
                </Panel>,
                document.body,
              )
            : null}
        </Panel>
      );
    }
    const { rerender } = render(<Host dialog={false} />);
    rerender(<Host dialog />);
    rerender(<Host dialog={false} />);
    const restore = screen.getByRole("button", { name: "Restore" });
    restore.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close history" }));
  });
});
