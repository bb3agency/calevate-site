import { useEffect, useState, type CSSProperties } from "react";

/**
 * Keeps a full-height fixed sheet inside the part of the screen the on-screen keyboard
 * leaves visible, so the ask box stays above the keys.
 *
 * The root viewport's `interactive-widget=resizes-content` (app/layout.tsx) already does
 * this where it is honoured (Chrome on Android): the layout viewport shrinks, `innerHeight`
 * shrinks with it, and this hook stays a no-op. iOS Safari does not honour that key; it
 * shrinks only the VISUAL viewport and leaves `position: fixed` where it was, under the
 * keyboard (WebKit bug 230225, still open; workaround described at
 * https://dev.to/0x2e_tech/ios-safari-viewport-bug-fix-a-practical-guide-14hp, read
 * 5 Nov 2026). So when the visual viewport is shorter than the layout one, the sheet takes
 * the visual viewport's height and offset instead of `inset-y-0`/`h-dvh`.
 */
export function useKeyboardFit(active: boolean): CSSProperties | undefined {
  const [fit, setFit] = useState<{ top: number; height: number } | null>(null);

  useEffect(() => {
    const vv = typeof window === "undefined" ? undefined : window.visualViewport;
    if (!active || vv == null) return undefined;
    const update = (): void => {
      // A pinch-zoom also shrinks the visual viewport; following it would shrink the sheet
      // while the person is zooming to read, which is not what they asked for.
      const covered = window.innerHeight - vv.height;
      setFit(vv.scale <= 1.01 && covered > 1 ? { top: vv.offsetTop, height: vv.height } : null);
    };
    update();
    vv.addEventListener("resize", update);
    vv.addEventListener("scroll", update);
    return () => {
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
    };
  }, [active]);

  return fit === null ? undefined : { top: fit.top, bottom: "auto", height: fit.height };
}
