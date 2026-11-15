import { NextResponse } from "next/server";

import { BUILD } from "@/lib/buildInfo";

/**
 * The build the server runs NOW (global rule 8). Read on every page load and every few
 * minutes by `UpdateWatcher`; never cached, so a deploy is seen at once.
 */
export const dynamic = "force-dynamic";

export function GET(): NextResponse {
  return NextResponse.json(BUILD, { headers: { "Cache-Control": "no-store, max-age=0" } });
}
