import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionGate } from "@/components/authn/sessionGate";
import {
  SIGNED_OUT_TOAST_MS,
  SignedOutToast,
} from "@/components/authn/signedOutToast";
import {
  markSignedOut,
  rememberSession,
  takeSignedOut,
} from "@/lib/authn/signedOutNotice";

/**
 * A dead session sends you to the door, and the door explains itself only if it should.
 *
 * WHAT THIS REPLACES. `SessionGate` rendered a terminal red panel — "You are signed out",
 * one Sign in link — on whatever console URL the person was on. Every part of that is a
 * dead end: the single control is a link, so clicking it is ceremony, and the URL left in
 * the address bar refuses them again the moment they navigate back to it.
 *
 * THE HARD PART IS NOT THE REDIRECT. It is knowing whether to say anything on arrival. A
 * restore answering `signed_out` means the same thing for somebody whose session just
 * expired and somebody who has never signed in — the server cannot tell an expired cookie
 * from an absent one, and the browser cannot read an `HttpOnly` cookie to check. Telling
 * a first-time visitor that their session ended invents an event, which is worse than
 * saying nothing. So the only evidence is a mark this TAB made while it held a session,
 * and these tests are mostly about that mark.
 */

const replace = vi.fn();
let pathname = "/admin";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => pathname,
  useRouter: () => ({
    push: vi.fn(),
    replace,
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

beforeEach(() => {
  replace.mockClear();
  pathname = "/admin";
  window.sessionStorage.clear();
});

function gate(realm = "admin", signInPath = "/auth/admin/sign-in") {
  return render(
    <SessionGate
      status="signed-out"
      realm={realm}
      realmLabel="operator console"
      signInPath={signInPath}
      onRetry={() => {}}
    />,
  );
}

describe("the signed-out gate", () => {
  it("redirects to the realm's sign-in page", () => {
    gate();
    expect(replace).toHaveBeenCalledWith("/auth/admin/sign-in");
  });

  it("uses replace, so Back does not bounce off the page that refused them", () => {
    const view = gate();
    // A `push` would leave the guarded URL in history; Back would land on this gate and
    // navigate forward again, which reads as a broken Back button.
    expect(replace).toHaveBeenCalledTimes(1);
    expect(view.container.textContent).toContain("Taking you to sign in");
  });

  it("does NOT redirect when it is already on the sign-in path", () => {
    // `SessionGate` is rendered by pages at and beside the door. Without this guard the
    // redirect targets the page it is already on, forever.
    pathname = "/auth/admin/sign-in";
    const view = gate();
    expect(replace).not.toHaveBeenCalled();
    expect(view.container.textContent).toContain("You are signed out");
  });

  it("announces the wait, so a screen reader is not silent through a navigation", () => {
    const view = gate();
    expect(view.container.querySelector('[role="status"]')).not.toBeNull();
  });

  it("keeps each realm's mark to itself", () => {
    // An operator session ending must not put a notice in front of a client on the same
    // machine — the two realms share nothing else, and must not start here.
    rememberSession("admin");
    gate("admin");
    expect(takeSignedOut("client")).toBe(false);
    expect(takeSignedOut("admin")).toBe(true);
  });
});

describe("whether the door says anything", () => {
  it("says nothing to a browser that never held a session", () => {
    // THE CASE THAT MATTERS MOST. A first-time visitor typing a console URL is not
    // "signed out" — they are not signed in, and there is no event to report.
    gate();
    render(<SignedOutToast realm="admin" realmLabel="operator console" />);
    expect(screen.queryByTestId("signed-out-toast")).toBeNull();
  });

  it("speaks when a session this tab held has ended", () => {
    rememberSession("admin");
    gate();
    render(<SignedOutToast realm="admin" realmLabel="operator console" />);
    expect(screen.getByTestId("signed-out-toast").textContent).toContain(
      "operator console session ended",
    );
  });

  it("says it once and not again on the next visit", () => {
    // A flag that survived being read would re-announce a sign-out on every visit to the
    // sign-in page — including the visit right after a successful one, where it would
    // read as the sign-in having failed.
    rememberSession("admin");
    gate();
    const first = render(
      <SignedOutToast realm="admin" realmLabel="operator console" />,
    );
    expect(screen.getByTestId("signed-out-toast")).toBeTruthy();
    first.unmount();

    render(<SignedOutToast realm="admin" realmLabel="operator console" />);
    expect(screen.queryByTestId("signed-out-toast")).toBeNull();
  });

  it("is forgotten again once a session is live", () => {
    // `useRealmSession` calls `rememberSession` on every `ready`, which is also what
    // clears a stale "ended" — so a mark cannot surface after the next sign-in works.
    rememberSession("admin");
    markSignedOut("admin");
    rememberSession("admin");
    expect(takeSignedOut("admin")).toBe(false);
  });

  it("leaves on its own", () => {
    vi.useFakeTimers();
    try {
      rememberSession("admin");
      markSignedOut("admin");
      render(<SignedOutToast realm="admin" realmLabel="operator console" />);
      expect(screen.getByTestId("signed-out-toast")).toBeTruthy();
      act(() => {
        vi.advanceTimersByTime(SIGNED_OUT_TOAST_MS + 10);
      });
      expect(screen.queryByTestId("signed-out-toast")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("survives a browser that refuses storage", () => {
    // Private modes throw on `sessionStorage` access outright. A cosmetic notice must
    // never be the thing that breaks a sign-in page.
    const original = Object.getOwnPropertyDescriptor(window, "sessionStorage");
    Object.defineProperty(window, "sessionStorage", {
      configurable: true,
      get() {
        throw new Error("refused");
      },
    });
    try {
      expect(() => rememberSession("admin")).not.toThrow();
      expect(markSignedOut("admin")).toBe(false);
      expect(takeSignedOut("admin")).toBe(false);
      expect(() => gate()).not.toThrow();
      expect(replace).toHaveBeenCalledWith("/auth/admin/sign-in");
    } finally {
      if (original) Object.defineProperty(window, "sessionStorage", original);
    }
  });
});
