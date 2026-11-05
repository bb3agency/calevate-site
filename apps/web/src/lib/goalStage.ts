/**
 * The `hot` stage's name on every screen. `hot` is the platform's key and a sales word that a
 * business selling nothing does not have (founder, 5 Nov 2026: an app calling its registered
 * users has no "hot lead"); the stage is where a call ending on an outcome the owner marked
 * as a goal puts a lead. The server spells the same name (`crm/lead_definition.
 * GOAL_STAGE_NAME`) in emails and the bell. Its own module, with no imports, because the
 * shared UI kit reads it too.
 */
export const GOAL_STAGE = "Goal reached";

/** A lead stage as a reader sees it: `hot` by its goal name, any other capitalised. */
export function stageLabel(stage: string): string {
  if (stage === "hot") return GOAL_STAGE;
  const words = stage.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
