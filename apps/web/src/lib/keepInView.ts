/**
 * Keep an element where it is on screen while the page around it changes height: a section
 * folding, a row opening for review (founder, 16 Nov 2026: the view jumped elsewhere after a
 * collapse). Measured before the change and corrected on the next frame, by scrolling the
 * nearest scrolling box (the app's main column) or the window.
 *
 * Only an element on screen is held: one the reader has scrolled away from is left alone.
 */
export function keepInView(element: HTMLElement | null): void {
  if (!element || typeof window === "undefined") return;
  const before = element.getBoundingClientRect().top;
  if (before < 0 || before > window.innerHeight) return;
  window.requestAnimationFrame(() => {
    const moved = element.getBoundingClientRect().top - before;
    if (Math.abs(moved) < 1) return;
    const box = scrollingAncestor(element);
    if (box) box.scrollTop += moved;
    else window.scrollBy(0, moved);
  });
}

function scrollingAncestor(element: HTMLElement): HTMLElement | null {
  for (let node = element.parentElement; node; node = node.parentElement) {
    const overflow = window.getComputedStyle(node).overflowY;
    if ((overflow === "auto" || overflow === "scroll") && node.scrollHeight > node.clientHeight) return node;
  }
  return null;
}
