import { readFileSync } from "node:fs";
import { join } from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { copyUnder, tsSources, WEB_ROOT } from "./copyScan";
import { blankComments } from "./sourceScan";

import { GLOSSARY, Term, type GlossaryId } from "@/lib/glossary";
import { TermGloss, glossPosition } from "@/components/ui";

/**
 * The two halves of "a term the reader does not know is explained where it is used":
 * the BOX works, and the term is in it.
 *
 * Both halves were broken when this file was written, and neither was visible from here —
 * the first because jsdom applies no CSS at all, the second because a screen that never
 * glosses a term looks exactly like one that has no term on it. So the box's geometry is
 * asserted as a pure function (the browser measured the rest — `components/ui.tsx`), and
 * the coverage is asserted over `copyScan`'s AST walk of what a person actually reads.
 */

describe("the gloss the reader gets", () => {
  it("prints the term and carries the map's words as its accessible name", () => {
    render(<Term id="dlt" />);
    const el = screen.getByText("DLT");
    expect(el.getAttribute("aria-label")).toBe(
      "DLT: India's telecom message registry",
    );
    // The gloss is drawn by CSS from `data-gloss`, so the rendered TEXT stays the term —
    // the property every `getByText` on every screen using a term depends on.
    expect(el.getAttribute("data-gloss")).toBe(
      "India's telecom message registry",
    );
    expect(el.textContent).toBe("DLT");
  });

  it("lets a screen spell the term its own way without re-writing the explanation", () => {
    render(<Term id="tm" term="telemarketer (TM)" />);
    const el = screen.getByText("telemarketer (TM)");
    expect(el.getAttribute("data-gloss")).toBe(GLOSSARY.tm.gloss);
  });

  it("gives an operator the precise wording of the same term", () => {
    render(<Term id="kyc" audience="operator" />);
    expect(screen.getByText("KYC").getAttribute("data-gloss")).toBe(
      GLOSSARY.kyc.operator,
    );
    expect(GLOSSARY.kyc.operator).not.toBe(GLOSSARY.kyc.gloss);
  });

  it("falls back to the one wording for a term that has no operator variant", () => {
    render(<Term id="dlt" audience="operator" />);
    expect(screen.getByText("DLT").getAttribute("data-gloss")).toBe(
      GLOSSARY.dlt.gloss,
    );
  });
});

describe("the box is placed where it can be read", () => {
  /**
   * Measured in Chromium before this existed: `after:absolute after:bottom-full` put the
   * box inside `<main class="overflow-y-auto">` and inside every `ScrollRegion`, and both
   * clip it — 106px of a 192px box cut off at the right-hand edge of `main`, 16.5px of a
   * 26.5px box cut off by a table's scroll region. These assert the arithmetic that
   * replaced it; the mechanism itself (that the box is `fixed`, which is what escapes an
   * ancestor's overflow) is pinned at the bottom of this file.
   */
  const VIEWPORT = { width: 1280, height: 800 };

  it("keeps a box beside a term at the right-hand edge inside the viewport", () => {
    // The exact case the browser measured: a term in a right-aligned row at x=1194.
    const at = glossPosition({ top: 300, bottom: 316, left: 1194 }, VIEWPORT);
    expect(Number.parseInt(at.left, 10) + 256).toBeLessThanOrEqual(
      VIEWPORT.width,
    );
  });

  it("does not drag a box off the LEFT edge to achieve that", () => {
    const at = glossPosition(
      { top: 300, bottom: 316, left: 4 },
      { width: 320, height: 640 },
    );
    expect(Number.parseInt(at.left, 10)).toBeGreaterThanOrEqual(0);
  });

  it("sits above the term when there is room", () => {
    const at = glossPosition({ top: 400, bottom: 416, left: 100 }, VIEWPORT);
    expect(at.top).toBe("auto");
    expect(Number.parseInt(at.bottom, 10)).toBe(VIEWPORT.height - 400 + 6);
  });

  it("flips below for a term in the first row of a panel, where above is off-screen", () => {
    const at = glossPosition({ top: 20, bottom: 36, left: 100 }, VIEWPORT);
    expect(at.bottom).toBe("auto");
    expect(Number.parseInt(at.top, 10)).toBe(36 + 6);
  });

  it("writes those coordinates onto the term when it is hovered, focused or tapped", () => {
    render(<Term id="dlt" />);
    const el = screen.getByText("DLT");
    expect(el.style.getPropertyValue("--gloss-left")).toBe("");
    fireEvent.focus(el);
    // jsdom lays nothing out, so every rect is zero — the VALUES are asserted above. What
    // this pins is that the handler runs at all: without it the box has no coordinates and
    // `fixed` puts it at its static position.
    expect(el.style.getPropertyValue("--gloss-left")).not.toBe("");
    expect(el.style.getPropertyValue("--gloss-top")).not.toBe("");
    expect(el.style.getPropertyValue("--gloss-bottom")).not.toBe("");
  });

  it("is a FIXED box drawn from data-gloss, which is what escapes the shell's overflow", () => {
    render(<TermGloss term="X">y</TermGloss>);
    const classes = screen.getByText("X").className;
    // `after:absolute` is the defect: its containing block is the term, which is inside
    // `<main class="overflow-y-auto">` and inside every ScrollRegion.
    expect(classes).not.toContain("after:absolute");
    expect(classes).toContain("after:fixed");
    // `after:content-[…]`, the UTILITY, sets `--tw-content`; the arbitrary PROPERTY form
    // was silently blanked by `hover:after:block`/`focus:after:block`, which re-emit
    // `content: var(--tw-content)` and sort later — the box showed empty in every browser.
    expect(classes).toContain("after:content-[attr(data-gloss)]");
    expect(classes).toContain("hover:after:block");
    expect(classes).toContain("focus:after:block");
    // The accessibility properties this box is not allowed to lose.
    const el = screen.getByText("X");
    expect(el.tagName).toBe("ABBR");
    expect(el.getAttribute("tabindex")).toBe("0");
    expect(el.getAttribute("aria-label")).toBe("X: y");
  });
});

/**
 * ONE DEFINITION PER TERM, ON EVERY SCREEN THAT SAYS IT.
 *
 * The defect this guards is not a missing tooltip; it is the SAME term explained one way
 * here and another way there — "Principal Entity" had four wordings across four screens
 * and a fifth screen printed it bare. A reader who meets a term twice must meet the same
 * sentence twice, so the words live in `lib/glossary` and a screen may not re-type them.
 */
describe("every screen that uses a term explains it", () => {
  /** How each glossary term shows up in copy, and how a file proves it explains it. */
  const PATTERNS: Record<GlossaryId, RegExp> = {
    dlt: /\bDLT\b/,
    pe: /\bPE\b|[Pp]rincipal [Ee]ntity/,
    tm: /\bTM\b|[Tt]elemarketer/,
    dpdp: /\bDPDP\b/,
    dnc: /\bDNC\b/,
    dnd: /\bDND\b/,
    kyc: /\bKYC\b/,
    series140: /\b140[- ]series\b/,
    series160: /\b160[- ]series\b/,
    dataFiduciary: /[Dd]ata [Ff]iduciary/,
  };

  /**
   * A file that says a term without explaining it, and why that is right.
   *
   * Every entry is a decision, not a backlog: an exemption says the reader of THAT screen
   * does not need the box, and gives the ground. A new bare term is not exempted by adding
   * a line here without one.
   */
  const NO_GLOSS_NEEDED: Record<string, string> = {
    "src/app/admin/ops/dnc/page.tsx:tm":
      "Operator realm, and the word appears inside an example a colleague types into a " +
      "suppression note — not our own prose about the role.",
    "src/app/admin/ops/opsLanguage.tsx:tm":
      "A copy table, not a screen. Its sentences render on /admin/ops, which glosses the " +
      "term itself; a second box on the same screen would be the noise this mechanism is " +
      "supposed to prevent.",
    "src/app/admin/ops/OpsSurface.tsx:tm":
      "Not screen copy: it is the LABEL of a fact this screen declares to the assistant, " +
      "and the screen itself glosses the term where a person reads it — " +
      "`TmRegistrationPanel.tsx`, the panel this fact is about.",
    "src/app/c/[slug]/verification/page.tsx:tm":
      "Not screen copy: it is the LABEL of a fact this screen declares to the assistant, " +
      "and the screen glosses the term where a person reads it — " +
      "`verification/DltRegistration.tsx`, the section this fact is about. Same case as " +
      "`admin/ops/OpsSurface.tsx:tm` above.",
    "src/app/c/[slug]/campaigns/campaignsCopilotSurface.ts:dlt":
      "Not screen copy: it is the LABEL of a control this screen declares to the " +
      "assistant, and the screen glosses the term where a person reads it — " +
      "`campaigns/NewCampaignForm.tsx` and `campaigns/blockerCopy.tsx`. Same case as " +
      "`admin/ops/OpsSurface.tsx:tm` above, and a `.ts` data module producing plain " +
      "strings for a model cannot hold an element anyway.",
    "src/app/c/[slug]/campaigns/campaignsCopilotSurface.ts:series140":
      "Same entry, same reason: the string is the assistant's `help` for the " +
      "classification control, and `campaigns/choices.tsx` glosses the series where the " +
      "client reads it.",
    "src/app/admin/tenants/[tenantId]/TenantNav.tsx:kyc":
      "Operator realm, and the string is the section label `Identity (KYC)` — the " +
      "parenthesis IS the gloss, and a label is not prose a box can sit in.",
    "src/app/admin/tenants/[tenantId]/CampaignSetup.tsx:series140":
      "The option label is `140 — promotional`: it explains itself in the two words " +
      "beside it, and an <option> cannot hold an element.",
    "src/app/admin/tenants/[tenantId]/CampaignSetup.tsx:series160":
      "The option label is `160 — service`, for the reason above.",
    "src/app/resources/page.tsx:dlt":
      "This page IS a glossary — `Registration (DLT)` is a term whose own `detail` " +
      "explains it in full. A tooltip inside a definition list of definitions is a loop.",
    "src/app/resources/page.tsx:tm": "Same entry, same reason.",
    "src/app/security/page.tsx:tm":
      "Public marketing prose that already explains the role in the same sentence — " +
      "'the business whose calls they are, and the telemarketer placing them'. Plain " +
      "language beats a tooltip; the box is for terms a sentence cannot absorb.",
    "src/components/marketing/faq.tsx:dlt":
      "The FAQ answer under it is the gloss, at length. A prospect reading a question " +
      "gets the explanation by reading on, which is what an FAQ is.",
    "src/components/marketing/faq.tsx:tm": "Same answer, same reason.",
  };

  const ROOTS = ["src/app", "src/components"];

  it("has a glossed use of every term it prints, or a stated reason not to", () => {
    const copy = copyUnder(ROOTS);
    const files = new Set(copy.map((c) => c.file));
    const bare: string[] = [];
    for (const file of [...files].sort()) {
      const source = readFileSync(join(WEB_ROOT, file), "utf8");
      const strings = copy.filter((c) => c.file === file);
      for (const [id, pattern] of Object.entries(PATTERNS) as [
        GlossaryId,
        RegExp,
      ][]) {
        const hits = strings.filter((s) => pattern.test(s.text));
        if (hits.length === 0) continue;
        // The screen explains it if it glosses it anywhere — once per screen is the rule,
        // not once per sentence.
        if (new RegExp(`<Term\\s+id="${id}"`).test(source)) continue;
        if (Object.hasOwn(NO_GLOSS_NEEDED, `${file}:${id}`)) continue;
        bare.push(
          `${file}:${hits[0].line} — "${id}" in: ${hits[0].text.trim().slice(0, 70)}`,
        );
      }
    }
    expect(
      bare,
      `these screens put a term in front of a person and never explain it:\n  ` +
        `${bare.join("\n  ")}\n` +
        `Use <Term id="…" /> (src/lib/glossary) at its first mention on that screen, or — ` +
        `if the reader of that screen genuinely does not need it — add the file to ` +
        `NO_GLOSS_NEEDED in this test WITH the reason.`,
    ).toEqual([]);
  });

  it("nobody re-types a gloss the map already owns", () => {
    // `TermGloss` stays public — it is the mechanism, and a one-off term that belongs to a
    // single screen may still use it. What it may NOT do is give a glossary term a second
    // wording, which is the drift `lib/glossary` was written to end.
    const owned = new Set(
      Object.values(GLOSSARY).map((e) => e.term.toLowerCase()),
    );
    const rogue: string[] = [];
    for (const root of ROOTS) {
      for (const file of tsSources(join(WEB_ROOT, root))) {
        // Over the BLANKED source: `components/ui.tsx`'s own docstring shows
        // `<TermGloss term="DLT">…` as the example of the mechanism, and a guard that
        // reads its own documentation as the defect is the failure `sourceScan` exists for.
        const source = blankComments(
          readFileSync(file, "utf8").split("\n"),
        ).join("\n");
        for (const m of source.matchAll(/<TermGloss\s+term="([^"]+)"/g)) {
          const printed = m[1].toLowerCase();
          if ([...owned].some((t) => printed.includes(t))) {
            rogue.push(
              `${file.slice(WEB_ROOT.length + 1)} — <TermGloss term="${m[1]}">`,
            );
          }
        }
      }
    }
    expect(
      rogue,
      `these spell out a gloss for a term lib/glossary already defines:\n  ` +
        `${rogue.join("\n  ")}\n` +
        `Use <Term id="…" term="${"…"}" /> so the words come from the map.`,
    ).toEqual([]);
  });
});
