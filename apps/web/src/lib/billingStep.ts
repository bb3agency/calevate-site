/**
 * How a call is counted, from the served billing step (`CreditPacksOut.billing_step_seconds`,
 * `rates.CLIENT_PULSE_SECONDS`), so a page states the step the debit uses rather than a copy
 * of it (G8-3). Without the card there is no figure we can stand behind, so none is printed.
 */
export function stepPhrase(step: number | null): string {
  return step === null ? "in short steps" : `in ${step}-second steps`;
}

/** The rounding, worked through two calls, in words a reader checks; null without the card. */
export function stepExample(step: number | null): string | null {
  if (step === null || step <= 10) return null;
  const said = (seconds: number) =>
    seconds === 60 ? "one minute" : seconds === 30 ? "half a minute" : `${seconds} seconds`;
  return `a ${step + 10}-second call is ${said(2 * step)}, a 10-second call is ${said(step)}`;
}
