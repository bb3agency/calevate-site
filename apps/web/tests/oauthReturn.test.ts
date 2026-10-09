/**
 * The OAuth hand-off between the Integrations screen and `/oauth/callback/<provider>`.
 *
 * Whether the callback page is the popup comes from the screen's record, never from
 * `window.opener`: Google's Cross-Origin-Opener-Policy cuts the popup off from its opener,
 * which used to leave the popup open with the console loaded inside it.
 */

import { beforeEach, describe, expect, it } from "vitest";

import {
  beginOAuthReturn,
  noteOAuthReturn,
  takeOAuthReturn,
} from "@/app/c/[slug]/integrations/oauthReturn";

const RESULT = { code: "code-1", state: "state-1", accountsServer: null };

describe("the OAuth return route", () => {
  beforeEach(() => window.localStorage.clear());

  it("tells the callback page it is the popup when the screen opened one", () => {
    beginOAuthReturn("sunrise", "google_calendar", true);
    expect(noteOAuthReturn("google", RESULT)).toEqual({
      back: "/c/sunrise/integrations",
      popup: true,
    });
  });

  it("sends a full-tab return back to Integrations", () => {
    beginOAuthReturn("sunrise", "google_calendar", false);
    expect(noteOAuthReturn("google", RESULT)).toEqual({
      back: "/c/sunrise/integrations",
      popup: false,
    });
  });

  it("leaves the result for the screen to finish, once", () => {
    beginOAuthReturn("sunrise", "google_sheets", true);
    noteOAuthReturn("google", RESULT);
    expect(takeOAuthReturn("sunrise")).toEqual({ kind: "google_sheets", ...RESULT });
    expect(takeOAuthReturn("sunrise")).toBeNull();
  });

  it("refuses a return nobody started in this browser", () => {
    expect(noteOAuthReturn("google", RESULT)).toBeNull();
  });
});
