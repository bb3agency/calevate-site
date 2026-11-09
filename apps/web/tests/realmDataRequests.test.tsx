import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE, apiRequest, apiUpload, type Session } from "@/lib/api/client";
import { ROTATION_DRAIN_CAP_MS, createRealmAuthn } from "@/lib/authn/realm";
import { useRealmSession } from "@/lib/authn/useRealmSession";

/**
 * The `/v1/**` data requests and the realm whose cookie they carry.
 *
 * The rotation barrier in `realm.ts` used to cover only `/v1/auth/**`, so a dashboard poll
 * could leave with the cookie a step-up was superseding; and a session that ended under an
 * open console left every panel answering 401 with no way to the sign-in page.
 */

const SESSION = {
  realm: "admin",
  subject_id: "0192f0aa-0000-7000-8000-000000000001",
  mfa_complete: true,
  email_verified: true,
};

interface Pending {
  path: string;
  resolve: (body: unknown, init?: ResponseInit) => void;
}

function deferredFetch(): Pending[] {
  const pending: Pending[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      return new Promise<Response>((resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason), { once: true });
        pending.push({
          path: url.startsWith(API_BASE) ? url.slice(API_BASE.length) : url,
          resolve: (body, responseInit) =>
            resolve(
              new Response(JSON.stringify(body), {
                status: 200,
                headers: { "content-type": "application/json" },
                ...responseInit,
              }),
            ),
        });
      });
    }),
  );
  return pending;
}

const UNAUTHORIZED = {
  type: "https://calevate.tech/problems/unauthorized",
  kind: "auth",
  title: "Please sign in",
  detail: "Your session is not valid. Sign in again.",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("data requests and the rotation barrier", () => {
  it("a data request waits while a step-up rotates the cookie", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");
    const session: Session = { orgSlug: "", realm: authn.transport };

    const rotating = authn.rotatingRequest("/step-up/verify", { method: "POST", body: { code: "1" } });
    expect(pending).toHaveLength(1);

    const read = apiRequest(session, "/v1/admin/tenants");
    await Promise.resolve();
    await Promise.resolve();
    expect(pending, "a poll must not carry the cookie the rotation is superseding").toHaveLength(1);

    pending[0].resolve(SESSION);
    await rotating;
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[1].path).toBe("/v1/admin/tenants");
    pending[1].resolve({ ok: true });
    await expect(read).resolves.toEqual({ ok: true });
  });

  it("a data request with no rotation in flight goes out in the same tick", () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");
    void apiRequest({ orgSlug: "", realm: authn.transport }, "/v1/me");
    expect(pending).toHaveLength(1);
  });

  it("a rotation waits for data requests already on the wire", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");
    const read = apiRequest({ orgSlug: "", realm: authn.transport }, "/v1/admin/tenants");
    expect(pending).toHaveLength(1);

    const rotating = authn.rotatingRequest("/step-up/verify", { method: "POST", body: { code: "1" } });
    await Promise.resolve();
    expect(pending, "the rotation must not supersede a cookie still being verified").toHaveLength(1);

    pending[0].resolve({ ok: true });
    await read;
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[1].path).toBe("/v1/auth/admin/step-up/verify");
    pending[1].resolve(SESSION);
    await expect(rotating).resolves.toEqual(SESSION);
  });

  it("a request that never settles holds a rotation back only for the cap", async () => {
    vi.useFakeTimers();
    const pending = deferredFetch();
    const authn = createRealmAuthn("admin");
    void apiRequest({ orgSlug: "", realm: authn.transport }, "/v1/admin/tenants").catch(() => {});

    void authn.rotatingRequest("/step-up/verify", { method: "POST" }).catch(() => {});
    await vi.advanceTimersByTimeAsync(ROTATION_DRAIN_CAP_MS - 1);
    expect(pending).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(pending).toHaveLength(2);
  });
});

/** An `XMLHttpRequest` that records each send and answers when the test says. */
function deferredXhr(): { sent: string[]; answer: () => void } {
  const sent: string[] = [];
  const loads: (() => void)[] = [];
  class StubXhr {
    upload = { addEventListener: vi.fn() };
    withCredentials = false;
    status = 200;
    responseText = "{}";
    url = "";
    private listeners: Record<string, () => void> = {};
    open(_method: string, url: string) {
      this.url = url;
    }
    setRequestHeader() {}
    getResponseHeader() {
      return "application/json";
    }
    addEventListener(type: string, listener: () => void) {
      this.listeners[type] = listener;
    }
    abort() {}
    send() {
      sent.push(this.url.slice(API_BASE.length));
      loads.push(() => this.listeners.load?.());
    }
  }
  vi.stubGlobal("XMLHttpRequest", StubXhr);
  return { sent, answer: () => loads.shift()?.() };
}

describe("uploads and the rotation barrier", () => {
  it("an upload waits while a rotation supersedes the cookie", async () => {
    const pending = deferredFetch();
    const xhr = deferredXhr();
    const authn = createRealmAuthn("client");
    const session: Session = { orgSlug: "acme", realm: authn.transport };

    const rotating = authn.rotatingRequest("/step-up/verify", { method: "POST", body: { code: "1" } });
    const upload = apiUpload(session, "/v1/kb/uploads", new FormData());
    await Promise.resolve();
    await Promise.resolve();
    expect(xhr.sent, "an upload must not carry the cookie the rotation is superseding").toEqual([]);

    pending[0].resolve(SESSION);
    await rotating;
    await vi.waitFor(() => expect(xhr.sent).toEqual(["/v1/kb/uploads"]));
    xhr.answer();
    await expect(upload).resolves.toEqual({});
  });

  it("a rotation waits for an upload already on the wire", async () => {
    const pending = deferredFetch();
    const xhr = deferredXhr();
    const authn = createRealmAuthn("client");
    const upload = apiUpload({ orgSlug: "acme", realm: authn.transport }, "/v1/kb/uploads", new FormData());
    await vi.waitFor(() => expect(xhr.sent).toHaveLength(1));

    const rotating = authn.rotatingRequest("/step-up/verify", { method: "POST" });
    await Promise.resolve();
    expect(pending, "the rotation must not supersede the cookie the upload is carrying").toHaveLength(0);

    xhr.answer();
    await upload;
    await vi.waitFor(() => expect(pending).toHaveLength(1));
    pending[0].resolve(SESSION);
    await expect(rotating).resolves.toEqual(SESSION);
  });
});

function Probe({ authn }: { authn: ReturnType<typeof createRealmAuthn> }) {
  const { status } = useRealmSession(authn, "session");
  return <p>status:{status}</p>;
}

describe("a session that ends under an open console", () => {
  it("a data request's 401 reads the session again and moves the realm to signed-out", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("client");
    render(<Probe authn={authn} />);
    await waitFor(() => expect(pending).toHaveLength(1));
    await act(async () => pending[0].resolve(SESSION));
    await screen.findByText("status:ready");

    const read = apiRequest({ orgSlug: "acme", realm: authn.transport }, "/v1/leads").catch((e: unknown) => e);
    await act(async () => pending[1].resolve(UNAUTHORIZED, { status: 401 }));
    expect(await read).toMatchObject({ status: 401, code: "unauthorized" });

    // Not trusted on its own word: the session is asked once more.
    await waitFor(() => expect(pending).toHaveLength(3));
    expect(pending[2].path).toBe("/v1/auth/client/session");
    expect(screen.getByText("status:ready"), "nothing unmounts while it asks").toBeTruthy();
    await act(async () => pending[2].resolve(UNAUTHORIZED, { status: 401 }));
    await screen.findByText("status:signed-out");
  });

  it("stays ready when the session read says the session is fine", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("client");
    render(<Probe authn={authn} />);
    await waitFor(() => expect(pending).toHaveLength(1));
    await act(async () => pending[0].resolve(SESSION));
    await screen.findByText("status:ready");

    const read = apiRequest({ orgSlug: "acme", realm: authn.transport }, "/v1/leads").catch((e: unknown) => e);
    await act(async () => pending[1].resolve(UNAUTHORIZED, { status: 401 }));
    expect(await read).toBeTruthy();
    await waitFor(() => expect(pending).toHaveLength(3));
    await act(async () => pending[2].resolve(SESSION));
    await Promise.resolve();
    expect(screen.getByText("status:ready")).toBeTruthy();
  });

  it("a 403 is not a session that ended", async () => {
    const pending = deferredFetch();
    const authn = createRealmAuthn("client");
    render(<Probe authn={authn} />);
    await waitFor(() => expect(pending).toHaveLength(1));
    await act(async () => pending[0].resolve(SESSION));
    await screen.findByText("status:ready");

    const read = apiRequest({ orgSlug: "acme", realm: authn.transport }, "/v1/leads").catch((e: unknown) => e);
    await act(async () =>
      pending[1].resolve({ ...UNAUTHORIZED, type: "x/forbidden" }, { status: 403 }),
    );
    expect(await read).toBeTruthy();
    await new Promise((r) => setTimeout(r, 20));
    expect(pending).toHaveLength(2);
  });
});
