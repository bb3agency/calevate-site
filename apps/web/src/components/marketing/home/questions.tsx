import { Faq } from "@/components/marketing/faq";

import { Band, Chapter } from "./band";

/**
 * CHAPTER 8 — the questions people ask first.
 *
 * `quiet` weight, for the reason the trust chapter is: this is the last objection-handling
 * stop before the closing offer, read closely by someone already interested. It is also the
 * one band that legitimately changes the page's height on interaction, which is why `Faq`
 * is NOT wrapped in a `Reveal` — animating the container that contains the thing doing the
 * resizing is how a reveal ends up half-played.
 */
export function Questions() {
  return (
    <Chapter tone="app">
      <Band id="faq" eyebrow="Questions" weight="quiet" title="Questions people ask us first">
        <Faq />
      </Band>
    </Chapter>
  );
}
