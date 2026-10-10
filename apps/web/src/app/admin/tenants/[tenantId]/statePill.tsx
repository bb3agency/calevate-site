import type { NoticeTone } from "@/components/ui";

/** An agent's lifecycle status in the operator's palette: live is the healthy case. */
export const AGENT_STATUS_TONE: Record<string, NoticeTone> = {
  live: "ok",
  draft: "neutral",
  paused: "warn",
  archived: "neutral",
};
