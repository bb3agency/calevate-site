import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { ImageResponse } from "next/og";

import { SITE_DESCRIPTION } from "@/lib/seo/structuredData";

/**
 * THE LINK PREVIEW CARD — `app/opengraph-image.tsx`, the Metadata Route file convention.
 *
 * Generated rather than committed as a PNG, for the reason CLAUDE.md's supply-chain and
 * "one way per problem" rules both point at: a binary in the tree is a copy of the brand
 * that no rebrand can reach, that nobody can diff, and that quietly goes stale the first
 * time the wordmark or the green moves. This renders from the SAME font files the site
 * ships (`src/fonts/PPMori-*.otf`), the same brand hexes `globals.css` declares, and the
 * same sentence the hero says — so the card cannot disagree with the page it previews.
 *
 * `size` and `contentType` are the file convention's own exports; Next reads them to write
 * `og:image:width`/`height` and `og:image:type`. 1200x630 is the size every consumer of
 * Open Graph documents (it is 1.91:1, which is also what `summary_large_image` wants), and
 * it is what `lib/seo/metadata.ts` sets `twitter.card` on the strength of.
 *
 * ## The fonts are READ FROM DISK, and `fetch(new URL(..., import.meta.url))` DOES NOT WORK
 *
 * That is the shape most examples of this route use, and it was written here first and
 * MEASURED FAILING — `GET /opengraph-image` returned 500 with
 * *"Failed to parse URL from /_next/static/media/PPMori-SemiBold.cb07cb68.otf"*
 * (next 15.5.21, `next dev`, 9 Sep 2026). The bundler rewrites the asset URL to a
 * ROOT-RELATIVE path, and `fetch` has no origin to resolve it against on the server.
 *
 * `readFile(join(process.cwd(), ...))` is the shape that works, and the working directory
 * it depends on is a fact this repository fixes rather than hopes for: `pnpm dev`,
 * `pnpm start` and the deployed pm2 process all run with `apps/web` as cwd
 * (`ecosystem.config.cjs` sets `cwd: __dirname`, which is this directory).
 *
 * OTF rather than the WOFF2 files this app also ships: satori (what `ImageResponse` renders
 * with) reads TTF, OTF and WOFF and does NOT read WOFF2. `PPMori-*.otf` is what
 * `app/layout.tsx` already loads through `next/font/local`.
 *
 * ## LIGHT ONLY (D-471)
 *
 * Painted with the light palette's own hexes, and there is no dark variant and no branch
 * on the OS theme preference — this file is under `src/`, where `tests/lightOnly.test.ts`
 * forbids reading that media query at all, and it scans COMMENTS as well as code, so the
 * query is not spelled here either. A link preview has no viewer preference to read in any
 * case: it is a PNG rendered once on our server, and every consumer gets the same bytes.
 */

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/** The card's own words. Deliberately the site's name and nothing a page could contradict. */
const HEADLINE = "AI phone agents for Indian businesses";

/** From `globals.css` `:root` — `--brand-strong`, `--brand-bright`, `--surface`, `--text`. */
const BRAND_STRONG = "#0f6b3d";
const BRAND_BRIGHT = "#22c55e";
const SURFACE = "#ffffff";
const INK = "#171a1c";
const INK_MUTED = "#475569";

export default async function OpengraphImage() {
  const fonts = join(process.cwd(), "src", "fonts");
  const [semibold, regular] = await Promise.all([
    readFile(join(fonts, "PPMori-SemiBold.otf")),
    readFile(join(fonts, "PPMori-Regular.otf")),
  ]);

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: SURFACE,
          padding: "72px 80px",
          // satori has no cascade: every text node inherits from here or states its own.
          fontFamily: "PP Mori",
          color: INK,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div
            style={{
              width: 24,
              height: 24,
              borderRadius: 12,
              background: BRAND_BRIGHT,
              display: "flex",
            }}
          />
          <div style={{ fontSize: 40, fontWeight: 600, color: BRAND_STRONG }}>Calevate</div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
          <div style={{ fontSize: 76, fontWeight: 600, lineHeight: 1.05, maxWidth: 980 }}>
            {HEADLINE}
          </div>
          <div style={{ fontSize: 30, lineHeight: 1.4, color: INK_MUTED, maxWidth: 940 }}>
            {SITE_DESCRIPTION}
          </div>
        </div>

        <div style={{ display: "flex", height: 10, background: BRAND_STRONG, borderRadius: 5 }} />
      </div>
    ),
    {
      ...size,
      fonts: [
        { name: "PP Mori", data: semibold, weight: 600, style: "normal" },
        { name: "PP Mori", data: regular, weight: 400, style: "normal" },
      ],
    },
  );
}
