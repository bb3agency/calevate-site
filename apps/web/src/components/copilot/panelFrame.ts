/*
 * The panel's frame, apart from the panel, so the view-as notice can use it without
 * pulling the whole conversation into its chunk (`CopilotDock` loads the panel lazily).
 */

export type PanelPlacement = "floating" | "header" | "side" | "page";

/** Beside the launcher: above a floating one, under a header one. */
function panelPlacement(placement: "floating" | "header"): string {
  return placement === "header"
    ? "fixed right-4 top-[80px] z-assistant max-h-[min(34rem,calc(100dvh-6.5rem))]"
    : "fixed bottom-20 right-4 z-assistant max-h-[min(34rem,calc(100dvh-7rem))]";
}

/**
 * The panel's frame per placement. `side` is full height on the right and full WIDTH below
 * `sm`, where a 24rem sheet would leave a sliver of page nobody can use; `dvh` and the safe
 * area keep the ask box above a phone's keyboard and home bar.
 */
export function panelFrame(placement: PanelPlacement): string {
  const card = "flex flex-col overflow-hidden bg-surface";
  switch (placement) {
    case "side":
      return `${card} fixed inset-y-0 right-0 z-assistant h-dvh w-full border-l border-line pb-[env(safe-area-inset-bottom)] shadow-overlay sm:w-[min(26rem,100vw)]`;
    case "page":
      return `${card} h-[min(44rem,calc(100dvh-12rem))] min-h-[24rem] w-full rounded-card border border-line`;
    default:
      return `${card} ${panelPlacement(placement)} w-[min(24rem,calc(100vw-2rem))] rounded-card border border-line shadow-overlay`;
  }
}
