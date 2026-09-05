import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProblemNotice, formatIST, istDateStamp } from "@/components/ui";
import { ApiProblem, problemFrom } from "@/lib/api/client";
import { currentISTMonth } from "@/lib/api/invoice";

/**
 * THE REFUSAL SURFACE, ON THE INPUTS NOBODY RENDERED WHILE BUILDING IT.
 *
 * `ProblemNotice` is the ONE failure channel these screens have — every §52 refusal on
 * every screen ends here — and every assertion below is a shape that reaches it in
 * production and did not reach it in any test.
 *
 * ## 1. The blank refusal (production only, and only over HTTP/2)
 *
 * `problemFrom` falls back to `response.statusText` when the body is not JSON — an nginx
 * 502, a proxy error page, a WAF block. **HTTP/2 carries no reason phrase**: RFC 9113
 * §8.3.2 states it "does not define a way to carry the version or reason phrase that is
 * included in an HTTP/1.1 status line", and the Fetch Standard therefore leaves
 * `statusText` empty — Chrome returns `""`, and Safari has historically returned the
 * whole status line `"HTTP/2.0 502"` (whatwg/fetch#599, WebKit bug 176479; read
 * 2 Sep 2026). `infra/nginx/calevate.conf.template` sets `http2 on` on every server
 * block, so this is what our clients get, not an edge case:
 *
 * - on Chrome, `detail: ""` — and `??` does not fall through an empty string, so the
 *   `Error` message is `""`, `ProblemNotice`'s `problem?.message ?? "…"` keeps it, and a
 *   client watching a 502 gets an EMPTY RED BOX. A refusal with no sentence is worse than
 *   no refusal: there is nothing to act on and nothing to quote to support.
 * - on Safari, the raw status line is printed as the user-facing sentence, which is the
 *   internal-detail leak the same rule forbids.
 *
 * The fix is to stop reading `statusText` at all — the STATUS is the only thing HTTP/2
 * guarantees us, so the sentence is derived from it.
 *
 * ## 2. A sentence with nowhere to wrap
 *
 * problem+json `detail` and `remediation` are the server's prose, and the server puts the
 * client's own strings in them — an endpoint URL they typed on `/integrations`, a slug, a
 * webhook host. One 300-character token with no space in it, in a card that is 320px wide
 * on a phone, pushes the whole panel sideways. Tailwind's default `overflow-wrap` does
 * not break inside a word.
 *
 * ## 3. A file named for a day that had not started here
 *
 * The CSV and the subject-access JSON were named from `new Date().toISOString()`, which is
 * UTC. Between 00:00 and 05:29 IST — the whole of an Indian small hours — that names
 * YESTERDAY, on the two files in this product a client is most likely to keep, forward and
 * later have to place in time. `campaigns/page.tsx::todayInputValue` already carries the
 * warning ("a day early for half of every IST evening") for a picker's `max`; the same
 * trap was live on the filenames.
 */

const ORIGINAL_TZ = process.env.TZ;

/** A response with a body nginx wrote, not the API — the case `problemFrom` falls back on. */
function nonJson(status: number, statusText: string): Response {
  return new Response("<html><body><h1>502 Bad Gateway</h1></body></html>", {
    status,
    statusText,
    headers: { "content-type": "text/html" },
  });
}

describe("a failure whose body was not ours", () => {
  it("still says something, when HTTP/2 leaves the reason phrase empty", async () => {
    const problem = await problemFrom(nonJson(502, ""));
    render(<ProblemNotice error={problem} />);
    const alert = screen.getByRole("alert");
    // The bug: an alert box with no words in it.
    expect(alert.textContent?.trim()).not.toBe("");
    expect(alert.textContent).toContain("Calevate");
    // A gateway failure is the most retryable thing there is, and a non-JSON body carries
    // no `retryable` for us to read — so it must not be inferred as false.
    expect(problem.retryable).toBe(true);
  });

  it("never prints the transport's own status line as the client's sentence", async () => {
    // Safari's spelling of the same response.
    const problem = await problemFrom(nonJson(502, "HTTP/2.0 502"));
    render(<ProblemNotice error={problem} />);
    expect(screen.getByRole("alert").textContent).not.toContain("HTTP/2.0");
  });

  it("separates a refusal we caused from one we did not", async () => {
    // 413 is nginx's `client_max_body_size`, answered before our app sees the request, so
    // there is no problem+json and no `retryable`. Telling someone to try again is wrong.
    const tooLarge = await problemFrom(nonJson(413, ""));
    expect(tooLarge.retryable).toBe(false);
    render(<ProblemNotice error={tooLarge} onRetry={() => {}} />);
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
  });

  it("keeps a machine code that reads as unknown when the body named none", async () => {
    // `String(body.type ?? "").split("/").pop()` is `""`, not `undefined`, so the `??
    // "unknown"` beside it never fired and callers comparing `code` met an empty string.
    expect((await problemFrom(nonJson(502, ""))).code).toBe("unknown");
  });
});

describe("the server's prose, at the widths it is read at", () => {
  it("breaks inside a long unbroken token instead of widening the panel", () => {
    const problem = new ApiProblem(422, {
      type: "urn:calevate:crm/endpoint_rejected",
      detail: `Your endpoint https://crm.example.co.in/${"a".repeat(240)}/inbound rejected the lead.`,
      remediation: `Check the address you gave us: https://crm.example.co.in/${"b".repeat(240)}`,
      fields: [{ field: `payload.${"c".repeat(120)}`, rule: "required", message: "Missing." }],
      trace_id: "0199c4f0-1c2e-7a55-9f8b-6d0a5e2b71c4",
    });
    render(<ProblemNotice error={problem} />);
    const alert = screen.getByRole("alert");
    // Every element that can hold server prose, not just the outer box: `break-words` does
    // not inherit past a child that sets its own `overflow-wrap`, and the field list and
    // the trace reference are the two that most often carry an unbreakable string.
    for (const node of alert.querySelectorAll("p, li, span")) {
      const text = node.textContent ?? "";
      if (text.length < 40) continue;
      expect(
        node.className.includes("break-words") || node.className.includes("break-all"),
        `"${text.slice(0, 40)}…" has nowhere to wrap`,
      ).toBe(true);
    }
  });
});

describe("a file is named for the day it was taken, in India", () => {
  it("names the IST day even while UTC is still on the one before", () => {
    // 00:30 IST on 4 Sep 2026 is 19:00 UTC on 3 Sep. The client took the file on the 4th.
    const midnightish = new Date("2026-09-03T19:00:00.000Z");
    expect(istDateStamp(midnightish)).toBe("2026-09-04");
    expect(currentISTMonth(midnightish)).toBe("2026-09");
  });

  it("is the same day whatever clock the browser is set to", () => {
    const instant = new Date("2026-09-03T19:00:00.000Z");
    for (const zone of ["UTC", "America/Los_Angeles", "Pacific/Auckland"]) {
      process.env.TZ = zone;
      expect(istDateStamp(instant)).toBe("2026-09-04");
    }
    if (ORIGINAL_TZ === undefined) delete process.env.TZ;
    else process.env.TZ = ORIGINAL_TZ;
  });
});

describe("a timestamp the server sent in a shape we could not read", () => {
  it("says we do not know, rather than printing 'Invalid Date' at a client", () => {
    // Every other date helper in `ui.tsx` guards this (`formatCallCap`, `istDateToInstant`,
    // `calendarDay` on the quality screen). `formatIST` — the one all 101 call sites use —
    // did not, and `new Date("…").toLocaleString()` renders the words "Invalid Date".
    expect(formatIST("not-a-timestamp")).toBe("—");
    expect(formatIST("2026-13-45T99:99:99Z")).toBe("—");
    // The honest cases are untouched.
    expect(formatIST(null)).toBe("—");
    expect(formatIST("2026-09-03T19:00:00.000Z")).toContain("04 Sep");
  });
});

/**
 * THE HIERARCHY OF A REFUSAL, which is the half of the founder's screenshot this app owns.
 *
 * The photographed sign-in refusal gave four things near-equal weight — a generic title, an
 * instruction written to an API client, a Pydantic validator's own words, and a 32-character
 * id — and the only one that helped ("use a longer password") was third. The server's half
 * of that is somebody else's fix. These are the properties of the RENDERER.
 */
describe("what a refusal puts first, and what it leaves out", () => {
  const fieldRefusal = new ApiProblem(422, {
    type: "https://calevate.tech/problems/invalid_fields",
    // `kind` is what decides whether a support reference is printed, so a fixture without
    // one tests a body the API does not send: every refusal it builds carries a kind
    // (`apps/api/core/errors.py`), and a 422 about the answers is `validation`.
    kind: "validation",
    detail: "We could not use one of your answers.",
    remediation: "Change the answer marked below and send it again.",
    fields: [
      {
        field: "body.password",
        rule: "min_length",
        // The NOUN is the server's, sent beside the wire path rather than derived from
        // it. The console prints `label` or nothing — deriving "Password" from
        // `body.password` here happened to read well and would have printed
        // "Consent source" for `items.0.consent_source`, which names nothing on screen.
        label: "Password",
        message: "Use at least 12 characters.",
      },
    ],
    trace_id: "9c83825c95f2495d87a4194ba0ef2849",
    retryable: false,
  });

  it("names the field the way a person would, not the way the code spells it", () => {
    render(<ProblemNotice error={fieldRefusal} />);
    expect(screen.getByRole("alert").textContent).toContain("Password: Use at least 12 characters.");
    // The wire path is what the founder photographed. It is a schema's spelling, not a noun.
    expect(screen.getByRole("alert").textContent).not.toContain("body.password");
  });

  it("prints the sentence alone when the server named no noun for the answer", () => {
    // A body from before the server carried `label` still parses, and the WIRE PATH is
    // never the fallback: `body.password` in front of a person is the defect, and
    // deriving a noun from it in the console is how the console came to own a naming
    // rule that belongs to the API.
    const unlabelled = new ApiProblem(422, {
      type: "https://calevate.tech/problems/invalid_fields",
      kind: "validation",
      detail: "We could not use one of your answers.",
      fields: [
        { field: "body.password", rule: "min_length", message: "Use at least 12 characters." },
      ],
    });
    render(<ProblemNotice error={unlabelled} />);
    const box = screen.getByRole("alert").textContent ?? "";
    expect(box).toContain("Use at least 12 characters.");
    expect(box).not.toContain("body.password");
    expect(box).not.toContain("password:");
  });

  it("still quotes the reference when the failure is a dependency of ours", () => {
    // The three kinds that get one are the ones whose answer is in a log line rather
    // than on the screen (`apps/api/core/errors.py`).
    const upstream = new ApiProblem(502, {
      type: "https://calevate.tech/problems/dependency",
      kind: "dependency",
      detail: "We could not reach the phone network just now.",
      trace_id: "9c83825c95f2495d87a4194ba0ef2849",
    });
    render(<ProblemNotice error={upstream} />);
    expect(screen.getByRole("alert").textContent).toContain("9c83825c95f2495d87a4194ba0ef2849");
  });

  it("keeps the support reference off a refusal the person can clear themselves", () => {
    render(<ProblemNotice error={fieldRefusal} />);
    expect(screen.getByRole("alert").textContent).not.toContain("9c83825c");
  });

  it("still quotes it when the failure is ours and there is nothing for them to do", () => {
    const ourFault = new ApiProblem(500, {
      type: "https://calevate.tech/problems/internal",
      kind: "internal",
      detail: "Something went wrong at our end.",
      trace_id: "9c83825c95f2495d87a4194ba0ef2849",
    });
    render(<ProblemNotice error={ourFault} />);
    expect(screen.getByRole("alert").textContent).toContain("9c83825c95f2495d87a4194ba0ef2849");
  });

  it("gives the sentence more weight than anything under it", () => {
    const { container } = render(<ProblemNotice error={fieldRefusal} />);
    const paragraphs = Array.from(container.querySelectorAll("p"));
    const headline = paragraphs[0];
    expect(headline?.textContent).toBe("We could not use one of your answers.");
    // Not a decorative assertion: "equal weight for four things" is the defect, so the
    // one line that says what happened has to be the loudest thing in the box.
    expect(headline?.className).toContain("font-semibold");
    for (const other of paragraphs.slice(1)) {
      expect(other.className).not.toContain("font-semibold");
    }
  });
});
