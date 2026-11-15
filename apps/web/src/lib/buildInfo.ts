/**
 * The build this page was loaded from (global rule 8), inlined by `next.config.ts`.
 * `/version.json` serves the build the server runs now; `UpdateWatcher` compares the two.
 */
export interface BuildInfo {
  version: string;
  commit: string;
  builtAt: string;
}

export const BUILD: BuildInfo = {
  version: process.env.NEXT_PUBLIC_APP_VERSION ?? "0.0.0",
  commit: process.env.NEXT_PUBLIC_APP_COMMIT ?? "unknown",
  builtAt: process.env.NEXT_PUBLIC_APP_BUILT_AT ?? "",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** dd-mmm-yyyy in IST (global rule 1; D-709). */
export function buildDay(iso: string): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "numeric",
    year: "numeric",
  }).formatToParts(at);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("day")}-${MONTHS[Number(get("month")) - 1] ?? ""}-${get("year")}`;
}

/** "v0.2.0 · 1397d2711 · 15-Nov-2026". */
export function buildLabel(build: BuildInfo = BUILD): string {
  return [`v${build.version}`, build.commit, buildDay(build.builtAt)].filter(Boolean).join(" · ");
}

/** True when `server` is a different, known build from the one running here. */
export function isNewerBuild(server: Partial<BuildInfo> | null | undefined, running: BuildInfo = BUILD): boolean {
  if (!server?.commit || server.commit === "unknown" || running.commit === "unknown") return false;
  return server.commit !== running.commit;
}
