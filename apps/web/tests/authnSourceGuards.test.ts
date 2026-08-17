import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { ApiProblem } from "@/lib/api/client";
import { MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS } from "@/lib/authn/password";
import { AUTHN_CODES, signInMessage } from "@/lib/authn/problems";

/**
 * Source-level guards over the first-party auth surface (D-174).
 *
 * Four of the nine defects in `docs/evidence/raghava-platform-teardown.md` §5.7 are
 * ABSENCES — a field that must not exist, a decode that must not happen, a comparison that
 * must not be written, a bound that must not drift. A behavioural test cannot prove an
 * absence: it can only fail to find the thing on the one path it happened to walk. So they
 * are asserted the way `tests/responsive.test.ts` asserts its rules, by reading the source
 * of the directories that own the surface.
 *
 * What that trade costs, stated rather than implied: a regex cannot understand code, so a
 * determined author can write any of these in a spelling this file does not match. It is
 * not a sandbox; it is a tripwire on the obvious spelling, which is the one a well-meaning
 * change actually takes.
 */

const SRC = join(process.cwd(), "src");

/** Every file that makes up the first-party auth surface. */
function authnSources(): string[] {
  const roots = [
    join(SRC, "lib", "authn"),
    join(SRC, "components", "authn"),
    join(SRC, "app", "(auth)", "auth"),
  ];
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.tsx?$/.test(entry.name)) out.push(full);
    }
  };
  for (const root of roots) walk(root);
  // The floor every guard in this repo asserts: a wrong path would otherwise report a
  // confident pass over nothing at all.
  if (out.length < 15) {
    throw new Error(`only ${out.length} authn source files found — this guard is looking in the wrong place`);
  }
  return out;
}

const FILES = authnSources();
const read = (f: string): string => readFileSync(f, "utf8");
const rel = (f: string): string => relative(process.cwd(), f);

/**
 * Strip comments so a rule cannot flag the paragraph that explains it.
 *
 * The same trade `tests/responsive.test.ts` makes and for the same reason: every one of
 * these guards is documented in prose that necessarily NAMES the forbidden thing, and a
 * check that reads its own documentation as a violation is a check people turn off.
 */
function code(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n");
}

describe("§5.7 defect 3 — no credential ever travels in a response or a bypass", () => {
  /**
   * Theirs puts the one-time code in the login response as `devOtp` and auto-fills it, and
   * separately writes the plaintext code to Redis for a CI script, both gated on
   * `NODE_ENV !== "production"` alone. **A credential in a response body is not made safe
   * by an environment variable** — it is a credential in a response body on every
   * non-production deployment, including every staging environment a real operator uses.
   */
  it("nothing in the auth surface names a development one-time-code field", () => {
    const offenders: string[] = [];
    for (const file of FILES) {
      for (const forbidden of [/\bdevOtp\b/, /\bdev_otp\b/, /\bdebugCode\b/, /\btestOtp\b/]) {
        if (forbidden.test(code(read(file)))) offenders.push(`${rel(file)} — ${forbidden}`);
      }
    }
    expect(
      offenders,
      `a one-time code must never appear in a response field or be auto-filled, whatever ` +
        `flag guards it (§5.7 defect 3):\n  ${offenders.join("\n  ")}`,
    ).toEqual([]);
  });

  it("no branch in the auth surface reads the environment to relax a credential path", () => {
    // `lib/auth/mode.ts` reads `NODE_ENV` legitimately — to make the DEV path impossible
    // in a production build, which is the opposite direction. Nothing in THIS surface has
    // a reason to read it at all: there is no dev credential here, because the credential
    // is a cookie the server sets and the browser cannot forge.
    const offenders = FILES.filter((f) => /process\.env|import\.meta\.env/.test(code(read(f))));
    expect(
      offenders.map(rel),
      `the first-party auth surface reads an environment variable. There is no ` +
        `configuration under which it should behave differently — a build that relaxes an ` +
        `authentication path by environment is §5.7 defect 3.`,
    ).toEqual([]);
  });
});

describe("§5.7 defect 4 — no hand-rolled countdown timers", () => {
  /**
   * The behavioural half is in `authnScreens.test.tsx`, against `useCountdown`. This is
   * the half that makes it MEAN something for the forms: a screen that grew its own
   * `setInterval` would pass that test and reintroduce the defect anyway, because the
   * defect is not "the hook is wrong", it is "the countdown was written per call site".
   *
   * `useCountdown.ts` itself is exempt by name — it is the one implementation.
   */
  it("only useCountdown owns an interval", () => {
    const offenders = FILES.filter(
      (f) => /setInterval\s*\(/.test(code(read(f))) && !f.endsWith("useCountdown.ts"),
    );
    expect(
      offenders.map(rel),
      `a second countdown implementation (§5.7 defect 4). Use \`useCountdown\`, which is ` +
        `keyed on an absolute deadline and cleaned up by its own effect.`,
    ).toEqual([]);
  });

  it("every setTimeout in the surface is cleared", () => {
    // §5.7 defect 1 generalised: the surface owns exactly three timers — the restore
    // deadline, the two realm watchdogs and the idle bound — and every file that starts
    // one must also stop one. A `setTimeout` with no matching `clearTimeout` in the same
    // file is the shape the reference's leaked deadline had.
    const offenders = FILES.filter((f) => {
      // `setTimeout(resolve, ms)` — the sleep in the 429 rung — is excluded, and the
      // exclusion is narrow on purpose: its whole body is resolving its own promise, so
      // there is no side effect to arrive late and nothing a cancel would prevent. Any
      // OTHER callback is a side effect scheduled into a future the caller cannot see.
      const body = code(read(f)).replace(/setTimeout\(resolve,[^)]*\)/g, "");
      return /setTimeout\s*\(/.test(body) && !/clearTimeout\s*\(/.test(body);
    });
    expect(
      offenders.map(rel),
      `a timer is started here and never cleared (§5.7 defect 1). A timer that outlives ` +
        `the state it was watching fires into a world that has moved on.`,
    ).toEqual([]);
  });
});

describe("§5.7 defect 6 — no credential is compared in the browser", () => {
  /**
   * Theirs compares a basic-auth username and password with `===` on the ops console.
   * Ours authenticates nothing client-side at all: every credential goes to the server and
   * the server answers. The only string comparison of this shape in the surface is the
   * password-confirmation field, which compares two values the same person just typed, in
   * their own browser, deciding nothing but whether a button is enabled — and it is
   * spelled `confirmation !== password`, which this rule allows by name.
   */
  it("no password or code is compared against a secret in the browser", () => {
    const offenders: string[] = [];
    // A credential identifier on the LEFT and a NON-EMPTY literal on the right is the
    // shape that would mean authentication happening here. `password === ""` is excluded
    // by the `[^"'\`]` after the quote: comparing against the empty string is an
    // emptiness check that decides whether a submit button is enabled, discloses nothing
    // and authenticates nobody.
    const suspicious =
      /\b(password|passcode|secret|otp|apiKey)\s*(===|!==|==|!=)\s*(["'`][^"'`]|process\.)/gi;
    for (const file of FILES) {
      const body = code(read(file));
      for (const match of body.matchAll(suspicious)) {
        offenders.push(`${rel(file)} — ${match[0].trim()}`);
      }
    }
    expect(
      offenders,
      `a credential is being compared in the browser (§5.7 defect 6). Authentication is ` +
        `the server's answer; nothing here may decide it:\n  ${offenders.join("\n  ")}`,
    ).toEqual([]);
  });
});

describe("§5.7 defect 7 — the client decodes no token and trusts no claim", () => {
  /**
   * Theirs base64-decodes a JWT payload with no signature check (correct and unavoidable in
   * a browser), then sets `isVerified: true` unconditionally from it and grants every
   * permission on a `"*"` entry. Rendering from unverified claims is fine; DECIDING from
   * them is not.
   *
   * We hold no token at all — the session is an `HttpOnly` cookie JavaScript cannot read —
   * so the defect is structurally out of reach, and this guard is what keeps it that way
   * if anybody ever reaches for a token again. Everything shown is the server's own
   * `SessionOut`, re-read from the subject row on every call.
   */
  it("nothing in the auth surface decodes a token or reads a claim", () => {
    const offenders: string[] = [];
    for (const file of FILES) {
      const body = code(read(file));
      for (const forbidden of [/\batob\s*\(/, /jwtDecode|parseJwt|decodeToken/, /\.split\(["']\.["']\)\[1\]/]) {
        if (forbidden.test(body)) offenders.push(`${rel(file)} — ${forbidden}`);
      }
    }
    expect(
      offenders,
      `the auth surface is decoding a token (§5.7 defect 7). The session is an HttpOnly ` +
        `cookie and there is nothing to decode; authorization is the server's answer:\n  ` +
        `${offenders.join("\n  ")}`,
    ).toEqual([]);
  });

  it('no permission check grants everything on a "*" entry', () => {
    const offenders = FILES.filter((f) => /=== *["']\*["']|includes\(["']\*["']\)/.test(code(read(f))));
    expect(
      offenders.map(rel),
      `a wildcard permission grant in the browser (§5.7 defect 7) — client claims decide ` +
        `what is SHOWN, never what is ALLOWED.`,
    ).toEqual([]);
  });
});

describe("hard rule 6 in the browser", () => {
  it("nothing in the auth surface logs", () => {
    const offenders: string[] = [];
    for (const file of FILES) {
      const body = code(read(file));
      for (const match of body.matchAll(/console\.(log|info|warn|error|debug)\s*\(/g)) {
        offenders.push(`${rel(file)} — ${match[0]}`);
      }
    }
    expect(
      offenders,
      `every argument this surface handles is an address, a password, a one-time code or ` +
        `a single-use token. There is no log line here that is safe to write:\n  ` +
        `${offenders.join("\n  ")}`,
    ).toEqual([]);
  });

  it("no credential is ever put into a query string", () => {
    const offenders: string[] = [];
    for (const file of FILES) {
      const body = code(read(file));
      // `searchParams.set` / `?token=` construction. Reading one (`searchParams.get`) is
      // required — that is how an emailed link delivers its token — and `useLinkToken`
      // removes it from the URL immediately afterwards.
      for (const match of body.matchAll(/searchParams\.(set|append)\s*\(|\?token=|&token=/g)) {
        offenders.push(`${rel(file)} — ${match[0]}`);
      }
    }
    expect(
      offenders,
      `a credential is being written into a URL:\n  ${offenders.join("\n  ")}`,
    ).toEqual([]);
  });
});

describe("§5.7 defect 8 — the client's password bounds are the hasher's", () => {
  /**
   * Theirs accepts 128 characters against a bcrypt that truncates at 72, so the validator
   * advertises a strength the store does not hold. Ours is Argon2id and does not truncate;
   * what makes this test worth having is not the current numbers but the PINNING — the
   * reference's 128 was true when it was written, too.
   *
   * Read out of `apps/api/authn/hashing.py`, which is the module that enforces them. A
   * read-only cross-app assertion is the point: a comment claiming the numbers match is
   * exactly what the defect looks like from the inside.
   */
  const hashing = readFileSync(
    join(process.cwd(), "..", "..", "apps", "api", "authn", "hashing.py"),
    "utf8",
  );

  const constant = (name: string): number => {
    const found = new RegExp(`^${name}\\s*=\\s*(\\d+)`, "m").exec(hashing);
    expect(found, `${name} not found in apps/api/authn/hashing.py`).not.toBeNull();
    return Number(found![1]);
  };

  it("MIN_PASSWORD_CHARS matches the API's floor", () => {
    expect(MIN_PASSWORD_CHARS).toBe(constant("MIN_PASSWORD_CHARS"));
  });

  it("MAX_PASSWORD_CHARS matches the API's ceiling", () => {
    expect(MAX_PASSWORD_CHARS).toBe(constant("MAX_PASSWORD_CHARS"));
  });

  it("the hasher is Argon2id, so there is no truncation the client would be hiding", () => {
    // Asserted on the IMPORTS, not on the prose: `hashing.py`'s own docstring discusses
    // bcrypt at length (it is arguing against it), so a text search for the word finds the
    // argument rather than the algorithm. What decides is what the module imports.
    expect(hashing, "the API no longer imports argon2").toMatch(/^from argon2/m);
    expect(
      hashing,
      "a bcrypt/passlib hasher would reintroduce the 72-byte truncation §5.7 defect 8 is " +
        "about, and MAX_PASSWORD_CHARS would become a claim the store does not keep",
    ).not.toMatch(/^(from|import)\s+(bcrypt|passlib)/m);
  });
});

describe("the refusal vocabulary is pinned to the API that raises it", () => {
  /**
   * `lib/authn/problems.ts` claims its code list is "read off the source … rather than
   * pinned to somebody's memory of it", and until this ran, nothing held it there.
   *
   * The failure it guards is quiet, which is what makes it worth an assertion: the server
   * adds or renames a code, `signInMessage` stops recognising it, and the sign-in screen
   * falls through to the generic `ProblemNotice` — no error, no test failure, just a person
   * told "something went wrong" where a sentence they could act on used to be. Nobody
   * reports that as a bug against this file.
   *
   * Read-only across the app boundary, the same way the password-bounds block above reads
   * `hashing.py`: what decides is the API's own source, not a comment claiming it matches.
   */
  const AUTHN_API = join(process.cwd(), "..", "..", "apps", "api", "authn");

  /** Every `code="…"` the auth module raises. Its own spelling, `ProblemError`'s keyword. */
  function serverCodes(): Set<string> {
    const found = new Set<string>();
    for (const entry of readdirSync(AUTHN_API)) {
      if (!entry.endsWith(".py")) continue;
      const body = readFileSync(join(AUTHN_API, entry), "utf8");
      for (const match of body.matchAll(/\bcode="([a-z_]+)"/g)) found.add(match[1]);
    }
    if (found.size === 0) {
      throw new Error(`no problem codes found under ${AUTHN_API} — this guard is looking in the wrong place`);
    }
    return found;
  }

  /**
   * The two codes the browser must handle that `apps/api/authn/` does not spell itself.
   *
   * Named here rather than allowed by a loose rule, because "the frontend may know codes
   * the auth module does not raise" is the hole this test exists to close. Each is asserted
   * against the module that DOES raise it, so neither is a claim.
   */
  const RAISED_ELSEWHERE: ReadonlyArray<readonly [code: string, source: string]> = [
    // `ProblemError.unauthorized()` — the shared 401, raised by the session dependency
    // rather than by a handler in `authn/`.
    [AUTHN_CODES.unauthorized, join("apps", "api", "core", "errors.py")],
    // The rate-limit middleware's own 429, which any route can meet.
    [AUTHN_CODES.rateLimited, join("apps", "api", "core", "middleware.py")],
  ];

  it("every code the API raises has a browser spelling", () => {
    const browser = new Set<string>(Object.values(AUTHN_CODES));
    const missing = [...serverCodes()].filter((c) => !browser.has(c)).sort();
    expect(
      missing,
      `these codes are raised by apps/api/authn/ and unknown to src/lib/authn/problems.ts:\n` +
        `  ${missing.join("\n  ")}\n` +
        `A code with no entry falls through to the generic notice, which is the one screen ` +
        `that cannot tell a person what to do about it.`,
    ).toEqual([]);
  });

  it("every browser spelling is a code something actually raises", () => {
    const server = serverCodes();
    const declared = new Map(RAISED_ELSEWHERE.map(([code, source]) => [code, source]));
    const orphans = Object.values(AUTHN_CODES)
      .filter((c) => !server.has(c) && !declared.has(c))
      .sort();
    expect(
      orphans,
      `these codes are handled in the browser and raised nowhere:\n  ${orphans.join("\n  ")}\n` +
        `Dead copy is worse than none — it reads as coverage. Delete it, or add it to ` +
        `RAISED_ELSEWHERE naming the module that raises it.`,
    ).toEqual([]);

    for (const [code, source] of RAISED_ELSEWHERE) {
      const body = readFileSync(join(process.cwd(), "..", "..", source), "utf8");
      expect(body, `${code} is declared as raised by ${source}, and is not there`).toContain(code);
    }
  });

  it("every code in the vocabulary has a sentence a person can act on", () => {
    for (const code of Object.values(AUTHN_CODES)) {
      const message = signInMessage(
        new ApiProblem(400, { kind: "auth", type: `urn:calevate:auth/${code}`, title: "t" }),
      );
      expect(message, `${code} has no sign-in copy`).not.toBeNull();
      // Never the server's `detail`: §5.7 defect 2 is a UI that renders what the server
      // said and so re-leaks a distinction the server was careful to equalise.
      expect(message).not.toBe("t");
    }
  });
});

describe("realm separation", () => {
  /**
   * CLAUDE.md: the two realms "must never share session logic". `createRealmAuthn` is
   * allowed to be written once — see `lib/authn/realm.ts` for the argument, which is the
   * one `apps/api/authn/routes.py::_realm_router` makes on the server side — but it must
   * be CONSTRUCTED exactly twice, each time with a literal, and each realm's provider must
   * name exactly one instance.
   */
  it("createRealmAuthn is called exactly twice, once per realm, with a literal", () => {
    // `realm.ts` DECLARES it (`export function createRealmAuthn(`) and is excluded by
    // matching a call rather than a declaration — a factory that could not name itself
    // would be an odd rule to write.
    const callers = FILES.filter((f) => /[^n] createRealmAuthn\(|= createRealmAuthn\(/.test(code(read(f))));
    expect(callers.map(rel).sort()).toEqual([
      "src/lib/authn/adminAuthn.ts",
      "src/lib/authn/clientAuthn.ts",
    ]);
    expect(code(read(join(SRC, "lib", "authn", "adminAuthn.ts")))).toContain(
      'createRealmAuthn("admin")',
    );
    expect(code(read(join(SRC, "lib", "authn", "clientAuthn.ts")))).toContain(
      'createRealmAuthn("client")',
    );
  });

  it("neither realm's session module imports the other's", () => {
    const admin = code(read(join(SRC, "lib", "authn", "adminSession.tsx")));
    const client = code(read(join(SRC, "lib", "authn", "clientSession.tsx")));
    expect(admin, "the admin realm reaches into the client realm").not.toMatch(/clientAuthn|clientSession/);
    expect(client, "the client realm reaches into the admin realm").not.toMatch(/adminAuthn|adminSession/);
  });

  it("each realm's session module names exactly one realm instance", () => {
    for (const [file, mine, theirs] of [
      ["adminSession.tsx", "adminAuthn", "clientAuthn"],
      ["clientSession.tsx", "clientAuthn", "adminAuthn"],
    ] as const) {
      const body = code(read(join(SRC, "lib", "authn", file)));
      expect(body).toContain(mine);
      expect(body).not.toContain(theirs);
    }
  });
});
