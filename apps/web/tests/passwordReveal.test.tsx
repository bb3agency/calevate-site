import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthField } from "@/components/authn/fields";
import { PasswordInput } from "@/components/passwordInput";

/**
 * The show/hide control on every password field in the product.
 *
 * `components/passwordInput.tsx` is the only `type="password"` in `src/`, so this file is
 * the whole behavioural surface of the reveal: the sign-in forms, the three set-password
 * flows, the saved integration secret and the two Meta app-secret fields all render it.
 * `tests/authnScreens.test.tsx` drives the forms; this drives the control.
 *
 * The four properties, and why each is worth an assertion rather than a look:
 *
 * 1. **It flips the type and back.** The one thing a reader can check by eye — and the
 *    one thing that silently stops working if the toggle is ever given a `type` prop by
 *    a caller (the reason `AuthField` strips it before the branch).
 * 2. **The state is announced.** `aria-pressed` toggles and the accessible NAME does not.
 *    A test that only asserted the name would pass on the pattern this component
 *    deliberately rejects; asserting the name is CONSTANT is what pins the decision.
 * 3. **Focus and caret survive.** The failure this control exists to avoid is a person
 *    losing their place in a fifteen-character password, and it is invisible in jsdom
 *    unless it is asserted.
 * 4. **Hidden is the default, on every mount.** Including the remount a navigation or a
 *    re-rendered refusal produces.
 *
 * …plus the wiring `setPasswordForm` depends on: `aria-invalid`, `aria-describedby` and
 * the `role="alert"` message must still land on the INPUT after it moved inside a
 * wrapper with a button in it.
 */

/** A controlled password field, the shape every real caller uses. */
function Field(props: { reveals?: string } = {}) {
  return (
    <PasswordInput
      aria-label="Password"
      reveals={props.reveals}
      defaultValue="correct-horse-battery"
      autoComplete="current-password"
    />
  );
}

const input = (): HTMLInputElement => screen.getByLabelText("Password") as HTMLInputElement;
const toggle = (name = "Show password"): HTMLButtonElement =>
  screen.getByRole("button", { name }) as HTMLButtonElement;

describe("the reveal control flips the field and says so", () => {
  it("starts hidden", () => {
    render(<Field />);
    expect(input().type).toBe("password");
    expect(toggle().getAttribute("aria-pressed")).toBe("false");
  });

  it("flips to text and back", () => {
    render(<Field />);
    fireEvent.click(toggle());
    expect(input().type).toBe("text");
    fireEvent.click(toggle());
    expect(input().type).toBe("password");
  });

  it("toggles aria-pressed and keeps ONE accessible name in both states", () => {
    render(<Field />);
    const button = toggle();
    expect(button.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(button);
    expect(button.getAttribute("aria-pressed")).toBe("true");
    // The decision, pinned: a static name plus a dynamic state, never a dynamic name.
    // `getByRole` with the same name still finds it, which is the property a screen
    // reader's button list depends on.
    expect(toggle()).toBe(button);
    fireEvent.click(button);
    expect(button.getAttribute("aria-pressed")).toBe("false");
  });

  it("names itself after the field, so two on one form are distinguishable", () => {
    render(<Field reveals="new password" />);
    expect(screen.getByRole("button", { name: "Show new password" })).toBeTruthy();
  });

  it("hides the icon from assistive technology", () => {
    const { container } = render(<Field />);
    // The icon repeats a state `aria-pressed` already carries; announcing it says the
    // same thing twice.
    for (const svg of container.querySelectorAll("svg")) {
      expect(svg.getAttribute("aria-hidden")).toBe("true");
    }
  });
});

describe("revealing costs the field none of its protections", () => {
  /**
   * The half of this task that is not about eyes. `type="text"` moves the value into the
   * class of text browsers will spell-check, autocorrect and capitalise — the September
   * 2022 "spell-jacking" finding was that Chrome's Enhanced Spellcheck sends the value
   * once a page's own "show password" control is used. The component sets all three
   * unconditionally so there is no render in which they are momentarily absent, and this
   * asserts BOTH states rather than only the revealed one.
   */
  it("keeps spellcheck, autocorrect and autocapitalise off in both states", () => {
    render(<Field />);
    for (const state of ["hidden", "revealed"] as const) {
      if (state === "revealed") fireEvent.click(toggle());
      const field = input();
      expect(field.getAttribute("spellcheck"), state).toBe("false");
      expect(field.getAttribute("autocorrect"), state).toBe("off");
      expect(field.getAttribute("autocapitalize"), state).toBe("off");
    }
  });

  it("keeps the autocomplete token, which is what marks it a credential", () => {
    render(<Field />);
    expect(input().getAttribute("autocomplete")).toBe("current-password");
    fireEvent.click(toggle());
    // Unchanged: a password manager classifies on this token, not on the type, so
    // dropping or rewriting it on reveal is what would break autofill.
    expect(input().getAttribute("autocomplete")).toBe("current-password");
  });

  it("does not carry the value in an attribute a revealed field would expose", () => {
    render(<Field />);
    fireEvent.click(toggle());
    // React does not reflect `value` to the attribute for a controlled input, and a
    // `defaultValue` writes it once. What matters is that reveal adds nothing new: the
    // string lives in the DOM property, as it did while hidden.
    expect(input().value).toBe("correct-horse-battery");
  });
});

/**
 * WHAT THIS BLOCK DOES AND DOES NOT PROVE, measured rather than assumed.
 *
 * Deleting the `setSelectionRange` restore in `passwordInput.tsx` leaves all fourteen
 * tests here GREEN: jsdom preserves an input's selection across a `type` mutation, so the
 * caret assertions pin the OUTCOME a reader cares about and do not exercise the restore.
 * That is stated here rather than dressed up — the restore stays because this component
 * does not depend on every real engine behaving the way jsdom does, and because a browser
 * run cannot be a gate in this suite (`tests/contrast.test.ts` makes the same argument).
 * The two assertions in this block that ARE load-bearing in jsdom are that focus is not
 * moved off the input, and that focus is not STOLEN onto it.
 */
describe("focus and the caret survive the toggle", () => {
  it("leaves focus on the input and the caret where it was", () => {
    render(<Field />);
    const field = input();
    field.focus();
    field.setSelectionRange(4, 4);
    // A real pointer fires mousedown first, and its default action is what moves focus
    // off the input. The component refuses that default; this asserts the outcome.
    fireEvent.mouseDown(toggle());
    fireEvent.click(toggle());

    expect(document.activeElement).toBe(input());
    expect(input().selectionStart).toBe(4);
    expect(input().selectionEnd).toBe(4);
    expect(input().type).toBe("text");
  });

  it("preserves a selection range, not just a collapsed caret", () => {
    render(<Field />);
    const field = input();
    field.focus();
    field.setSelectionRange(2, 9);
    fireEvent.click(toggle());
    expect(input().selectionStart).toBe(2);
    expect(input().selectionEnd).toBe(9);
  });

  it("does not steal focus when the input never had it", () => {
    render(
      <>
        <button type="button">Elsewhere</button>
        <Field />
      </>,
    );
    const elsewhere = screen.getByRole("button", { name: "Elsewhere" });
    elsewhere.focus();
    fireEvent.click(toggle());
    // The restore is conditional on the input having HAD focus. A toggle that focused
    // the field unconditionally would drag a keyboard user out of wherever they were.
    expect(document.activeElement).toBe(elsewhere);
  });
});

describe("hidden is the default, and reveal does not survive a remount", () => {
  it("comes back hidden after the form is re-rendered from scratch", () => {
    const view = render(<Field />);
    fireEvent.click(toggle());
    expect(input().type).toBe("text");
    // A navigation, or a failed submit that re-renders the form: nothing durable holds
    // the reveal, so the field cannot come back showing a credential.
    view.unmount();
    render(<Field />);
    expect(input().type).toBe("password");
    expect(toggle().getAttribute("aria-pressed")).toBe("false");
  });
});

describe("the field-level refusal wiring is untouched by the toggle", () => {
  /**
   * `setPasswordForm` renders the server's specific rejection AT THE FIELD — `aria-invalid`
   * on the input, `aria-describedby` pointing at a `role="alert"` paragraph. Moving the
   * input inside a positioning wrapper with a button in it is exactly the change that
   * quietly relocates those attributes onto the wrapper, so this asserts them on the
   * input itself.
   */
  it("puts aria-invalid and aria-describedby on the input, not the wrapper", async () => {
    await act(async () => {
      render(
        <AuthField
          label="New password"
          type="password"
          reveals="new password"
          autoComplete="new-password"
          hint="At least 15 characters."
          error="That password is on a list of common passwords."
          value=""
          onChange={() => {}}
        />,
      );
    });
    const field = screen.getByLabelText("New password") as HTMLInputElement;
    expect(field.tagName).toBe("INPUT");
    expect(field.getAttribute("aria-invalid")).toBe("true");

    const describedBy = (field.getAttribute("aria-describedby") ?? "").split(" ");
    expect(describedBy.length).toBe(2);
    const alert = screen.getByRole("alert");
    expect(describedBy).toContain(alert.id);
    expect(alert.textContent).toBe("That password is on a list of common passwords.");

    // …and the reveal still works on a field that is currently refusing.
    fireEvent.click(screen.getByRole("button", { name: "Show new password" }));
    expect((screen.getByLabelText("New password") as HTMLInputElement).type).toBe("text");
    expect(screen.getByLabelText("New password").getAttribute("aria-invalid")).toBe("true");
  });

  it("leaves a non-password field with no toggle at all", async () => {
    await act(async () => {
      render(
        <AuthField label="Email address" type="email" value="" onChange={() => {}} />,
      );
    });
    expect(screen.queryByRole("button")).toBeNull();
  });
});
