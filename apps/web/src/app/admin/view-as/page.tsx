"use client";

/**
 * `/admin/view-as?slug=<slug>&path=<path>` — where every "View as client" link starts (D-730).
 *
 * Starting a view-as session is accepted from the operator console's origin only: an
 * injected script on the client console could otherwise turn the operator's cookie into a
 * grant for any tenant. So this page, on the operator console, mints the grant (no code is
 * asked for, D-791) and hands it to the client console in the URL FRAGMENT, which no
 * server sees. The client console strips it on arrival and may only renew it.
 */

import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { NoticeBox, PRIMARY_BUTTON_SM, ProblemNotice } from "@/components/ui";
import { HANDOFF_EXPIRES_KEY, HANDOFF_GRANT_KEY, startViewAs } from "@/lib/api/admin";
import { clientConsoleUrl, VIEW_AS_ADMIN, VIEW_AS_PARAM } from "@/lib/api/session";

/** The slug shape `tenancy/signup` mints: lower-case letters, digits and inner hyphens. */
const SLUG = /^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$/;

/** A path inside one client's console: plain segments only, never a second origin. */
const PATH = /^(?:\/[A-Za-z0-9_-]+)*$/;

function destination(slug: string, path: string, grant: string, expiresAtMs: number): string {
  const fragment = new URLSearchParams({
    [HANDOFF_GRANT_KEY]: grant,
    [HANDOFF_EXPIRES_KEY]: String(expiresAtMs),
  });
  return `${clientConsoleUrl(`/c/${slug}${path}?${VIEW_AS_PARAM}=${VIEW_AS_ADMIN}`)}#${fragment}`;
}

function ViewAsStart() {
  const params = useSearchParams();
  const slug = params.get("slug") ?? "";
  const path = params.get("path") ?? "";
  const valid = SLUG.test(slug) && PATH.test(path);
  const [error, setError] = useState<unknown>(null);
  const started = useRef(false);

  const start = useCallback(() => {
    setError(null);
    void startViewAs(slug)
      .then((minted) => {
        window.location.assign(destination(slug, path, minted.grant, minted.expiresAtMs));
      })
      .catch(setError);
  }, [slug, path]);

  useEffect(() => {
    if (!valid || started.current) return;
    started.current = true;
    start();
  }, [valid, start]);

  if (!valid) {
    return (
      <NoticeBox tone="warn" title="This link does not name a client">
        Open the client from the <Link href="/admin">accounts list</Link> instead.
      </NoticeBox>
    );
  }
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold text-ink">Opening {slug}</h1>
      {error === null ? (
        <p className="text-sm text-ink-muted">
          The client&apos;s console opens in this tab.
        </p>
      ) : (
        <>
          <ProblemNotice error={error} />
          <button type="button" className={PRIMARY_BUTTON_SM} onClick={start}>
            Try again
          </button>
        </>
      )}
    </div>
  );
}

export default function ViewAsStartPage() {
  return (
    <Suspense fallback={null}>
      <ViewAsStart />
    </Suspense>
  );
}
