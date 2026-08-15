import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NewClientPage from "@/app/admin/new/page";
import { previewSlug, slugIsDerivable } from "@/lib/api/signup";

import { renderAdminPage } from "./harness";

/**
 * A business name we cannot build a web address from — the Telugu-first case.
 *
 * THE DEFECT. `slugify` folds anything outside `[a-z0-9]` away, so every character of
 * `మా క్లినిక్` and `नमस्ते क्लिनिक` disappeared and the server substituted the constant
 * `client`. The FIRST business named in an Indic script silently took `/c/client` —
 * immutable, in every URL their staff types — and the SECOND was refused `slug_taken`, a
 * 409 naming a slug nobody had typed. On a product whose default language is Telugu
 * (D-36) that is the ordinary path, not an edge case.
 *
 * The server now refuses (`slug_not_derivable`) rather than guessing. This file is the
 * console's half: the operator is told BEFORE the POST, because `lib/api/signup.ts`'s own
 * rule is that a form which cannot succeed is a worse answer than a form that says what
 * it needs.
 *
 * Both screens share ONE preview (`previewSlug`) — the wizard used to carry an inline
 * copy of the regex — so the unit cases below cover both surfaces at once.
 */

const TENANTS = "/v1/admin/tenants";
const UNFINISHED = "/v1/admin/onboarding/unfinished";

const TELUGU = "మా క్లినిక్";
const HINDI = "नमस्ते क्लिनिक";

function fillName(value: string) {
  fireEvent.change(screen.getByPlaceholderText("Sunrise Clinic"), { target: { value } });
}

function slugInput(): HTMLInputElement {
  return screen.getByPlaceholderText("sunrise-clinic") as HTMLInputElement;
}

describe("the preview both signup surfaces share", () => {
  it("derives nothing at all from a name in an Indic script", () => {
    expect(previewSlug(TELUGU)).toBe("");
    expect(previewSlug(HINDI)).toBe("");
    expect(slugIsDerivable(TELUGU)).toBe(false);
  });

  it("refuses a name too short to be a slug, which is a legal business name", () => {
    // `SLUG_RE`'s floor is 3. "Om" is a real clinic name and an illegal URL.
    expect(previewSlug("Om")).toBe("om");
    expect(slugIsDerivable("Om")).toBe(false);
  });

  it("still derives the ordinary case", () => {
    expect(previewSlug("Sri Sai Dental Care")).toBe("sri-sai-dental-care");
    expect(slugIsDerivable("Sri Sai Dental Care")).toBe(true);
  });

  it("never previews a trailing hyphen a truncation created", () => {
    // Truncation happens BEFORE the strip, server-side and here. The input is chosen so
    // the 40-character cut lands EXACTLY on the separator — strip-then-slice would leave
    // `aaa…a-`, which `SLUG_RE` accepts and nobody wants in a URL.
    const cut = previewSlug("a".repeat(39) + " clinic");
    expect(cut.endsWith("-")).toBe(false);
    expect(cut).toBe("a".repeat(39));
  });
});

describe("the new-client wizard", () => {
  it("asks for the web address when the business name cannot supply one", async () => {
    const { container } = renderAdminPage(<NewClientPage />, {
      [TENANTS]: { detail: "never reached" },
      [UNFINISHED]: [],
    });

    fillName(TELUGU);

    expect(container.textContent).toContain(
      "We cannot build a web address out of that business name",
    );
    // Required, so the browser stops the submit that the server would refuse anyway.
    expect(slugInput().required).toBe(true);
    expect(slugInput().minLength).toBe(3);
  });

  it("goes back to previewing once the operator answers", async () => {
    const { container } = renderAdminPage(<NewClientPage />, {
      [TENANTS]: { detail: "never reached" },
      [UNFINISHED]: [],
    });

    fillName(TELUGU);
    fireEvent.change(slugInput(), { target: { value: "ma-clinic" } });

    expect(container.textContent).not.toContain("We cannot build a web address");
    expect(container.textContent).toContain("ma-clinic");
    expect(slugInput().required).toBe(false);
  });

  it("says nothing about the slug before a name has been typed", () => {
    const { container } = renderAdminPage(<NewClientPage />, {
      [TENANTS]: { detail: "never reached" },
      [UNFINISHED]: [],
    });

    // An empty form is not a form with a problem — the sentence appears when the operator
    // has typed a name we cannot use, not on arrival.
    expect(container.textContent).not.toContain("We cannot build a web address");
    expect(slugInput().required).toBe(false);
  });
});
