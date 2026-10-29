import { describe, expect, it } from "vitest";

import { consoleHref } from "@/app/c/[slug]/ClientAnnouncements";

/**
 * Where an announcement's console link lands. D-941's announcement links to a card on a
 * page ("/verify-business#calling-numbers"), so the fragment must survive a view-as session,
 * whose realm appends its own query to the path.
 */
const viewAs = (path: string) => `${path}${path.includes("?") ? "&" : "?"}as=admin`;

describe("an announcement's console link", () => {
  it("keeps the fragment after the realm's query", () => {
    expect(consoleHref("/verify-business#calling-numbers", "acme", viewAs)).toBe(
      "/c/acme/verify-business?as=admin#calling-numbers",
    );
    expect(consoleHref("/verify-business#calling-numbers", "acme", (path) => path)).toBe(
      "/c/acme/verify-business#calling-numbers",
    );
  });

  it("leaves an https address and a plain path as they were", () => {
    expect(consoleHref("https://calevate.tech/news", "acme", viewAs)).toBe("https://calevate.tech/news");
    expect(consoleHref("/billing", "acme", viewAs)).toBe("/c/acme/billing?as=admin");
  });
});
