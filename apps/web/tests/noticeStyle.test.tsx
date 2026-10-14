import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChecklistRows } from "@/components/console/checklist";
import { NoticeBox, ProblemNotice, type NoticeTone } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";

/**
 * NOTICES ARE QUIET (founder, 11 Oct 2026).
 *
 * The old notice was a cream or rose card with a border, an icon medallion, a bold coloured
 * title and every line in the tone colour, so everything looked equally urgent and read as
 * generated. A notice is now a 2px tone rule on the page's own white, with ink text; several
 * blockers are checklist rows. These cases fail if the tinted card comes back, through the
 * shared components or hand-rolled in a screen.
 */

/** A soft tint behind a block: the card the founder rejected. Pills keep theirs. */
const TINT =
  /\bbg-(?:warn-soft|danger-soft|brand-soft|amber-50|rose-50|yellow-50|red-50|orange-50|emerald-50|sky-50|blue-50|green-50)\b/;
/** Text in a tone colour. */
const TONE_TEXT = /\btext-(?:warn|danger|brand-deep|amber-\d+|rose-\d+|red-\d+|emerald-\d+)\b/;

function classesUnder(root: Element): string[] {
  return [root, ...Array.from(root.querySelectorAll("*"))].map((el) => el.getAttribute("class") ?? "");
}

describe("NoticeBox", () => {
  const tones: NoticeTone[] = ["ok", "warn", "stop", "neutral"];

  it.each(tones)("is a tone rule on white with ink text, never a tinted card (%s)", (tone) => {
    const { container } = render(
      <NoticeBox tone={tone} title="Business type not confirmed" icon={<svg data-testid="icon" />}>
        Calls collect standard details until you choose one.
      </NoticeBox>,
    );
    const box = container.querySelector("[data-notice]");
    expect(box).not.toBeNull();
    const own = box!.getAttribute("class") ?? "";
    expect(own).toContain("border-l-2");
    expect(own).toContain("bg-surface");
    expect(own).not.toMatch(/\brounded/);
    for (const cls of classesUnder(box!)) {
      expect(cls).not.toMatch(TINT);
      expect(cls).not.toMatch(TONE_TEXT);
    }
    // The medallion was the slop: an `icon` is accepted and not drawn.
    expect(screen.queryByTestId("icon")).toBeNull();
  });

  it("puts the action inline, inside the bar", () => {
    const { container } = render(
      <NoticeBox tone="warn" title="Not connected" action={<button type="button">Connect</button>} />,
    );
    const box = container.querySelector("[data-notice]")!;
    expect(box.contains(screen.getByRole("button", { name: "Connect" }))).toBe(true);
  });

  it("keeps the explanation behind an ⓘ rather than on the page", () => {
    render(
      <NoticeBox tone="neutral" title="Pay by bank transfer" info="Three working days to clear.">
        Use the reference on your invoice.
      </NoticeBox>,
    );
    expect(screen.getByRole("button", { name: "About Pay by bank transfer" })).toBeTruthy();
    expect(screen.queryByText("Three working days to clear.")).toBeNull();
  });
});

describe("ProblemNotice", () => {
  it("is one quiet alert: a rule, ink text, retry as a text action", () => {
    const problem = new ApiProblem(503, {
      type: "https://calevate.tech/problems/upstream_unavailable",
      title: "Service unavailable",
      detail: "We could not load your calls.",
      remediation: "Try again in a minute.",
      retryable: true,
      kind: "transient",
      trace_id: "abc123",
    });
    const { container } = render(<ProblemNotice error={problem} onRetry={() => undefined} />);
    const alert = screen.getByRole("alert");
    expect(alert.getAttribute("class")).toContain("border-l-2");
    for (const cls of classesUnder(alert)) {
      expect(cls).not.toMatch(TINT);
      expect(cls).not.toMatch(/\b(?:bg|text|border)-rose-/);
    }
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(container.textContent).toContain("Try again in a minute.");
  });
});

describe("ChecklistRows", () => {
  it("says each status in words, one action per row, the reason behind ⓘ", () => {
    render(
      <ChecklistRows
        heading="Waiting on us"
        rows={[
          {
            id: "kyc",
            label: "Identity (KYC)",
            status: "not_started",
            statusText: "Not filed",
            info: "Blocks all outbound calling.",
            link: { href: "/admin/tenants/t1/kyc", label: "Open" },
          },
          { id: "first", label: "First campaign", status: "waiting", statusText: "Waiting for review" },
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Waiting on us" })).toBeTruthy();
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("Not filed");
    expect(rows[1].textContent).toContain("Waiting for review");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.queryByText("Blocks all outbound calling.")).toBeNull();
  });
});

/* ── Hand-rolled tinted notices ─────────────────────────────────────────────────────── */

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");

/**
 * Files still allowed a tinted block, each with why. Marketing mockups draw the product as
 * an illustration and the legal renderer is not console chrome. Everything else uses
 * `NoticeBox`, `ChecklistRows` or `NOTICE_BASE`.
 */
const ALLOWED: Record<string, string> = {
  "app/industries/page.tsx": "marketing page",
  "app/roi/page.tsx": "marketing page",
  "components/marketing/home/languageAndTrade.tsx": "marketing illustration",
  "components/marketing/home/mockups/featureMockups.tsx": "marketing illustration",
  "components/marketing/pageShell.tsx": "marketing page",
  "components/marketing/pricing/billingMockups.tsx": "marketing illustration",
  "components/marketing/roiCalculator.tsx": "marketing page",
  "components/marketing/solutions/solutionMockups.tsx": "marketing illustration",
  "lib/legal/document.tsx": "the legal document renderer, hashed content beside it",
  // A SELECTED option in a picker, not a notice: the tint marks the choice.
  "components/voicePicker.tsx": "selected option",
  "components/copilot/workspace/Routines.tsx": "selected day toggle",
  "app/c/[slug]/lead-sources/CallingPlan.tsx": "selected day and retry toggles",
};

/** Other lanes are editing these right now; they move with the rest in the next pass. */
const PENDING: ReadonlySet<string> = new Set([]);

function tsxFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return tsxFiles(path);
    return entry.name.endsWith(".tsx") ? [path] : [];
  });
}

/** A class string that paints a tinted, bordered, padded block: a hand-rolled notice card. */
function tintedBlocks(text: string): string[] {
  const strings = text.match(/"[^"\n]*"|`[^`]*`/g) ?? [];
  return strings.filter(
    (s) =>
      TINT.test(s) &&
      !/rounded-full/.test(s) &&
      /\bborder\b|\bborder-/.test(s) &&
      /\b(?:p|px|py)-\d/.test(s),
  );
}

describe("no hand-rolled tinted notice cards", () => {
  it("finds none outside the allowed files", () => {
    const found: string[] = [];
    for (const file of tsxFiles(SRC)) {
      const rel = relative(SRC, file).split("\\").join("/");
      if (Object.hasOwn(ALLOWED, rel) || PENDING.has(rel)) continue;
      for (const hit of tintedBlocks(readFileSync(file, "utf8"))) found.push(`${rel}: ${hit.slice(0, 90)}`);
    }
    expect(found).toEqual([]);
  });
});
