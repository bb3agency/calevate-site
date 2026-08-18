import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Every client-realm query key carries the org slug — checked over the source, not
 * trusted to the next author.
 *
 * Three keys had drifted off the convention (`["callback-check", callId]`,
 * `["campaign-check", campaignId]`, `["campaign", campaignId]`). Nothing was broken by
 * it TODAY, because the ids are uuid_v7 and two tenants cannot mint the same one — which
 * is precisely the problem: it made hard-rule-1 isolation, in the cache, a property of
 * the id generator instead of a property of the key. `app/providers.tsx` creates ONE
 * `QueryClient` per shell mount, and a D-22 operator following "View as client" into
 * tenant A, back out, and into tenant B stays inside it the whole time. The server is
 * correct throughout; what a slug-less key risks is the browser answering from a cache
 * entry another tenant filled.
 *
 * WHY THIS IS A SOURCE SCAN rather than a rendered assertion. The defect is the ABSENCE
 * of a discriminator in a key nobody looks at, on a path that only misbehaves when two
 * tenants are read in one session — a render test would have to stage the whole
 * impersonation round trip per hook and would still only cover the hooks somebody
 * remembered to stage. The scan covers all of them and fails on the next one added, which
 * is what the finding actually asks for. Same shape as `wireFixtureGuard.test.ts`.
 *
 * THE REALM DISCRIMINATOR IS THE SESSION THE `queryFn` USES, and it is exact rather than
 * a heuristic over file names: `adminSession()` is minted inside `lib/api/admin.ts` for
 * cross-tenant reads and belongs to no org, so a key built on it must NOT be org-scoped —
 * `["admin","tenants"]`, `OPS_*`, `voiceKeys.catalogue` and `QA_SAMPLES_QUERY_KEY` are
 * correctly global. A `queryFn` that closes over a `session` PARAMETER is reading one
 * tenant's data with that tenant's credential, and its key must say which tenant.
 */

/**
 * `process.cwd()`, not `import.meta.url` — under jsdom the latter is not a file URL, and
 * a wrong root here is the vacuous pass this whole file exists to avoid. The floor
 * assertion below is the second half of that guard. Same reasoning as
 * `tests/a11y.routePagesOnDisk`.
 */
const SRC = join(process.cwd(), "src") + "/";

/** Every `.ts`/`.tsx` file under `src/`, so a hook cannot hide by moving. */
function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...sourceFiles(full));
    } else if (/\.tsx?$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

/**
 * The text of every `useQuery({ … })` call in one file.
 *
 * Brace-balanced rather than regexed to a line: these option objects contain nested
 * objects, arrow bodies and template literals, and a line-wise match would truncate the
 * `queryFn` this test's whole classification depends on — silently turning a
 * client-realm hook into an unclassifiable one.
 */
function queryOptionBlocks(source: string): string[] {
  const blocks: string[] = [];
  const needle = "useQuery({";
  let from = 0;
  for (;;) {
    const start = source.indexOf(needle, from);
    if (start === -1) return blocks;
    let depth = 0;
    let i = start + needle.length - 1;
    for (; i < source.length; i += 1) {
      if (source[i] === "{") depth += 1;
      else if (source[i] === "}") {
        depth -= 1;
        if (depth === 0) break;
      }
    }
    blocks.push(source.slice(start, i + 1));
    from = i + 1;
  }
}

/** The `queryKey:` expression inside one block, brace/bracket balanced. */
function queryKeyOf(block: string): string | null {
  const at = block.indexOf("queryKey:");
  if (at === -1) return null;
  let i = at + "queryKey:".length;
  while (block[i] === " ") i += 1;
  let depth = 0;
  const start = i;
  for (; i < block.length; i += 1) {
    const c = block[i];
    if (c === "[" || c === "(" || c === "{") depth += 1;
    else if (c === "]" || c === ")" || c === "}") depth -= 1;
    else if (c === "," && depth === 0) break;
    if (depth < 0) break;
  }
  return block.slice(start, i).replace(/\s+/g, " ").trim();
}

/**
 * Reads one tenant's data with that tenant's credential?
 *
 * `adminSession(` and `signupSession(` mint their own; anything else in `lib/api` and
 * `app/` closes over the `session` the hook was handed, which is a client-realm session.
 */
function isClientRealm(block: string): boolean {
  if (/adminSession\(|signupSession\(/.test(block)) return false;
  return /\bsession\b/.test(block);
}

/**
 * The key says WHICH tenant it holds.
 *
 * Not "contains `session.orgSlug`", because the console has two honest spellings of the
 * same discriminator and the narrower rule would have flagged five correct hooks: a
 * client-realm hook keys on the session's own slug, while an admin-realm hook reading ONE
 * client's data (`useCredits`, `useCommercialTerms`, `useEngineState`) is handed the
 * tenant explicitly and keys on that. Both name a tenant, which is the property that
 * matters; a key-builder handed the whole session (`activityKey(session)`) does too.
 */
function namesATenant(key: string): boolean {
  return /session\.orgSlug|tenantId|\bslug\b|\(\s*session\s*[),]/.test(key);
}

/**
 * Keys that name no tenant because the thing they hold belongs to no tenant.
 *
 * Compound `file — key`, never by file alone, for the reason `tests/a11y.ts` gives for
 * its own compound exemptions: an exemption at the coarser grain silently covers the NEXT
 * key somebody adds to the same module. Each entry states WHAT IT IS.
 */
const NOT_TENANT_DATA: Record<string, string> = {
  'lib/api/billing.ts — ["billing", "topup-capability"]':
    "What THIS DEPLOYMENT can do about money — whether a payment provider is configured " +
    "in the environment at all. It is the same answer for every tenant and changes only " +
    "when someone edits the environment, which is why the hook also sets " +
    "`staleTime: Infinity`. Keying it per org would mint one cache entry per tenant for " +
    "one platform fact. NOT CLOSEABLE: it is correct as it stands.",
};

describe("client-realm query keys", () => {
  const files = sourceFiles(SRC);

  it("scans a source tree it actually found", () => {
    // A scan that silently matched nothing is a green tick on a check that never ran —
    // the failure mode `tests/a11y.ts` names for its own disabled rules.
    expect(files.length).toBeGreaterThan(50);
    const blocks = files.flatMap((f) => queryOptionBlocks(readFileSync(f, "utf8")));
    expect(blocks.length).toBeGreaterThan(60);
    expect(blocks.filter(isClientRealm).length).toBeGreaterThan(20);
  });

  it("every one of them carries the org slug", () => {
    const offenders: string[] = [];
    for (const file of files) {
      for (const block of queryOptionBlocks(readFileSync(file, "utf8"))) {
        if (!isClientRealm(block)) continue;
        const key = queryKeyOf(block);
        // A `useQuery` with no `queryKey` does not compile, so this is a parse failure
        // rather than a real state — report it instead of skipping it.
        if (key === null) {
          offenders.push(`${file.slice(SRC.length)} — could not read its queryKey`);
          continue;
        }
        const site = `${file.slice(SRC.length)} — ${key}`;
        if (!namesATenant(key) && !Object.hasOwn(NOT_TENANT_DATA, site)) {
          offenders.push(site);
        }
      }
    }

    expect(
      offenders,
      "client-realm query keys without a tenant discriminator — one QueryClient holds " +
        "more than one tenant's data (D-22 'View as client'), so the key is what keeps " +
        "them apart",
    ).toEqual([]);
  });

  it("carries no exemption for a hook that no longer exists", () => {
    // An exemption whose site has been renamed or deleted stops describing anything and
    // starts being a licence somebody inherits by accident.
    const live = new Set<string>();
    for (const file of files) {
      for (const block of queryOptionBlocks(readFileSync(file, "utf8"))) {
        if (!isClientRealm(block)) continue;
        const key = queryKeyOf(block);
        if (key !== null) live.add(`${file.slice(SRC.length)} — ${key}`);
      }
    }
    expect(Object.keys(NOT_TENANT_DATA).filter((site) => !live.has(site))).toEqual([]);
  });
});
