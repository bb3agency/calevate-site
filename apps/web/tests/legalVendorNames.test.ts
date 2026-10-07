import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { LEGAL_DOCUMENTS, textOf } from "@/lib/legal";
import { resolvePlaceholders } from "@/lib/legal/placeholders";
import { PUBLICLY_NAMED_SUBPROCESSORS } from "@/lib/legal/subprocessors";

/**
 * NO PUBLISHED LEGAL DOCUMENT NAMES A SUB-PROCESSOR THE REGISTER KEEPS UNNAMED (D-679).
 *
 * The public pages list sub-processors by category; the named list is
 * `docs/legal/SUBPROCESSOR-REGISTER.md`, given on request. The banned words are DERIVED
 * from that register — every alias of every row marked "Named publicly: no", minus the
 * identities some other row may print — so a vendor added to the register is banned here
 * the day it is added, and nobody keeps a second list.
 *
 * Read over the RESOLVED text: a placeholder value renders on three documents, and the
 * hosting provider's name once reached all three through one.
 */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const REGISTER = resolve(REPO_ROOT, "docs/legal/SUBPROCESSOR-REGISTER.md");

interface Row {
  identity: string;
  publiclyNamed: boolean;
  aliases: string[];
}

function registerRows(): Row[] {
  const text = readFileSync(REGISTER, "utf8").replace(/\r\n/g, "\n");
  const start = text.indexOf("<!-- register:start -->");
  const end = text.indexOf("<!-- register:end -->");
  expect(start, "the register's table markers are gone").toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(start);
  return text
    .slice(start, end)
    .split("\n")
    .filter((line) => line.startsWith("|") && !line.startsWith("|---"))
    .map((line) => line.split("|").slice(1, -1).map((cell) => cell.trim()))
    .filter((cells) => cells[0] !== "Identity")
    .map((cells) => ({
      identity: cells[0] ?? "",
      publiclyNamed: (cells[3] ?? "").toLowerCase() === "yes",
      aliases: (cells[4] ?? "").split(",").map((a) => a.trim()).filter(Boolean),
    }));
}

/** Departed vendors are not in the register and must not come back by name either. */
const DEPARTED = ["Bolna", "Clerk", "Exotel"];

function bannedWords(rows: Row[]): string[] {
  const printable = new Set(rows.filter((r) => r.publiclyNamed).map((r) => r.identity));
  const banned = new Set<string>(DEPARTED);
  for (const row of rows) {
    if (row.publiclyNamed) continue;
    for (const word of [row.identity, ...row.aliases]) {
      if (!printable.has(word)) banned.add(word);
    }
  }
  return [...banned];
}

const escape = (word: string): string => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

describe("the published legal documents name only what they may", () => {
  it("is reading a register with rows in it", () => {
    // THE PREMISE, alone: a parse that silently stopped matching would ban nothing.
    const rows = registerRows();
    expect(rows.length).toBeGreaterThan(20);
    const identities = rows.map((r) => r.identity);
    for (const anchor of ["Sarvam", "Microsoft", "Vobiz", "Razorpay"]) {
      expect(identities).toContain(anchor);
    }
    expect(bannedWords(rows)).toEqual(
      expect.arrayContaining(["Sarvam", "Azure", "Vobiz", "Pipecat", "ThinnestAI"]),
    );
  });

  it("names no unnamed sub-processor anywhere in the set", () => {
    const banned = bannedWords(registerRows());
    const pattern = new RegExp(`\\b(?:${banned.map(escape).join("|")})\\b`, "i");
    for (const doc of LEGAL_DOCUMENTS) {
      const prose = resolvePlaceholders(textOf(doc));
      const found = pattern.exec(prose);
      expect(
        found?.[0] ?? null,
        `/legal/${doc.slug} names "${found?.[0]}". D-679: the legal pages describe ` +
          "sub-processors by category; the named list is given on request from " +
          "docs/legal/SUBPROCESSOR-REGISTER.md. Describe the role instead.",
      ).toBeNull();
    }
  });

  it("prints only names the register marks public", () => {
    const printable = new Set(
      registerRows().filter((r) => r.publiclyNamed).map((r) => r.identity),
    );
    for (const name of PUBLICLY_NAMED_SUBPROCESSORS) {
      expect(printable, `${name} is printed but not marked public`).toContain(name);
    }
  });
});
