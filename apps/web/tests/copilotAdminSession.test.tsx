import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * THE ADMIN DOCK'S SESSION IS HELD, and this file exists because the alternative is
 * invisible from a diff.
 *
 * `adminSession()` BUILDS A NEW OBJECT every call
 * (`lib/authn/realmSessions.ts::adminRealmSession` returns an object literal), so calling
 * it inline in the component body gave the panel a `session` with a new identity on every
 * render. `session` is a dependency of `ask`, of `reset` and of the confirm mutation
 * inside the panel, so all three were rebuilt on every render — nothing broke, which is
 * the problem: any future memoisation on those would have been silently defeated, and the
 * defeat would look exactly like working code.
 *
 * The credential itself is still read lazily through `session.token()`, so holding the
 * wrapper holds nothing stale.
 */
const built = vi.hoisted(() => ({ count: 0 }));

vi.mock("@/lib/api/admin", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api/admin")>();
  return {
    ...real,
    adminSession: (orgSlug?: string) => {
      built.count += 1;
      return real.adminSession(orgSlug);
    },
  };
});

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/tenants",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const { AdminCopilotDock } = await import("@/components/copilot/CopilotDock");

function Parent() {
  const [n, setN] = useState(0);
  return (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <button type="button" onClick={() => setN((v) => v + 1)}>
        re-render {n}
      </button>
      <AdminCopilotDock />
    </QueryClientProvider>
  );
}

describe("the admin dock's session", () => {
  it("IS BUILT ONCE, however many times its parent re-renders", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 200 })),
    );
    built.count = 0;
    render(<Parent />);
    expect(built.count).toBe(1);

    for (let i = 0; i < 5; i += 1) {
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /^re-render/ }));
      });
    }

    // FAILS IF: `adminSession()` is called inline in the component body again — this
    // becomes 6, and every callback inside the panel is rebuilt on every render with it.
    expect(built.count).toBe(1);
  });
});
