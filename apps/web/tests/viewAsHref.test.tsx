/**
 * The view-as marker carried by `useClientRealm().href` must land in the QUERY, never in
 * the fragment: a link written as `…?section=handover#call-handling` came out as
 * `…#call-handling&view=admin`, the next page read no `view=admin`, built a CLIENT session
 * and sent the operator to the client sign-in.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useClientRealm } from "@/lib/api/session";

import { renderClientPage } from "./harness";

function Link({ path }: { path: string }) {
  const { href } = useClientRealm();
  return <a href={href(path)}>Open</a>;
}

async function hrefOf(path: string): Promise<URL> {
  window.history.replaceState(null, "", "/c/acme?view=admin");
  await renderClientPage(<Link path={path} />, {});
  const link = await screen.findByRole("link", { name: "Open" });
  return new URL(link.getAttribute("href") ?? "", "https://app.calevate.tech");
}

describe("view-as links", () => {
  it("keeps view=admin in the query when the path carries a fragment", async () => {
    const url = await hrefOf("/c/acme/agents/a1?section=settings#call-handling");
    expect(url.searchParams.get("view")).toBe("admin");
    expect(url.searchParams.get("section")).toBe("settings");
    expect(url.hash).toBe("#call-handling");
  });

  it("adds a query to a path with only a fragment", async () => {
    const url = await hrefOf("/c/acme/verify-business#calling-numbers");
    expect(url.pathname).toBe("/c/acme/verify-business");
    expect(url.searchParams.get("view")).toBe("admin");
    expect(url.hash).toBe("#calling-numbers");
  });
});
