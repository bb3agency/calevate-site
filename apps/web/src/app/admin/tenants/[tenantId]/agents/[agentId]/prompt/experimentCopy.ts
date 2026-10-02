import type { ConcludeExperimentOut, ExperimentVariant } from "@/lib/api/publishing";

/*
 * The A/B section's sentences, kept free of React so a test can drive them without a
 * render (UX-DOCTRINE §6: pull the arithmetic out of the JSX).
 */

/**
 * What the Conclude button reports, including the ending it did not perform.
 *
 * Concluding is idempotent on the server: a second operator on the same screen, or a
 * retry of a request whose response was lost, gets 200 and a test that ended exactly
 * once — nothing is promoted or published a second time. That call's response carries
 * the arm the test ENDED on and a null `new_version`, because no version was minted by
 * it, and printing "as vnull" at an operator is how a correct server answer becomes a
 * broken screen.
 *
 * The server states it outright as `changed`, and that is now what this reads. It used
 * to derive the same fact from `promoted_label != null && new_version == null` because
 * the generated client predated the field; the two agree by construction, but the
 * derivation was a second way of knowing one thing and this is the first.
 *
 * "This test" is exact rather than loose: the request names an `experiment_id`, so the
 * response is about the test that was on screen — never about whichever one happens to
 * be running now. That is what makes "reload" honest advice; before the id, the reply
 * could be describing a test the operator had not looked at.
 */
export function concludeMessage(data: ConcludeExperimentOut): string {
  if (!data.promoted_label) {
    // True of an ending with no promotion whether or not this call made it: either way
    // the control is what callers keep hearing.
    return "Stopped. Callers keep hearing the control script.";
  }
  if (!data.changed) {
    return (
      `This test had already ended, promoting variant ${data.promoted_label}. ` +
      "Nothing was published again — reload to see the version it produced."
    );
  }
  return (
    `Promoted variant ${data.promoted_label} as v${data.new_version}.` +
    (data.applied
      ? data.engine_synced
        ? " The voice platform has it."
        : " The agent is not live, so nothing was sent to the voice platform."
      : " It is STAGED — press Apply to live calls, in Live, to put it on live calls.")
  );
}


/** A rate with its plausible range, or the reason there is no rate. Never "0%" for an
 *  arm with no completed calls — that is a claim, and the server sent null.
 *
 *  The mixed-population qualifier is built INTO this string rather than rendered beside
 *  it, and that is the point: the rate's denominator is `completed`, which can hold
 *  inbound calls the engine credited to this arm (D-60) and which nothing ever SPLIT
 *  between the arms. A caller who renders the number therefore cannot omit the fact that
 *  part of it was not randomised — the alternative, a separate element somebody may
 *  forget or a layout may drop, is how the "dialled" defect this replaced got shipped.
 */
export function rateReading(variant: ExperimentVariant): string {
  if (variant.rate === null || variant.rate_low === null || variant.rate_high === null) {
    return "no completed calls yet";
  }
  const pct = (value: number) => `${(value * 100).toFixed(1)}%`;
  const reading = `${pct(variant.rate)} (${pct(variant.rate_low)}–${pct(variant.rate_high)})`;
  if (variant.inbound_completed === 0) return reading;
  return (
    `${reading} · includes ${variant.inbound_completed} inbound call` +
    `${variant.inbound_completed === 1 ? "" : "s"} this arm's line answered, which were ` +
    `not split between the arms`
  );
}

/** Percentage POINTS, signed, because the gap can legitimately run either way. */
export function pointsReading(value: number): string {
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)} pts`;
}
