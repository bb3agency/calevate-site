"use client";

import { ShieldAlert } from "lucide-react";

import { StepUpPrompt } from "@/app/admin/stepUpPrompt";
import { NoticeBox, ProblemNotice } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import { AUTHN_CODES } from "@/lib/authn/problems";

/**
 * A failed CONFIRMED WRITE anywhere in the admin console — and the two failures that must
 * not be rendered as a generic red box.
 *
 * Every write that sends `X-Confirm-Action` renders its failure through here: the ops
 * console's halt / load-shed / TM registration / outbox replay / spend-cap recompute, the
 * platform-wide do-not-call list, the platform config and secrets panels, a credit
 * adjustment, a top-up restatement, a spend ceiling and a tenant erasure. It moved up out
 * of `ops/` when the second of those two failures made it every confirmed write's
 * business rather than the ops screens' (D-340); the import path is the only thing that
 * changed.
 *
 * `step_up_required` is a 4xx, so `ProblemNotice` would print it in the same rose panel
 * as "the database is unreachable", under a title the operator answers by clicking the
 * button again. But every write on these screens SENDS its confirmation header —
 * `platformConfirmation` for the halt and the load-shed mode, the direction string in
 * `useSetTmRegistration`, `OUTBOX_REPLAY_CONFIRMATION` for the replay,
 * `SUPPRESS_GLOBALLY_CONFIRMATION` / `RELEASE_GLOBALLY_CONFIRMATION` for the
 * platform-wide do-not-call list — so a step-up refusal cannot mean "you forgot to
 * confirm" here. It can only mean this console and the API disagree about the string.
 * That is a version skew, and clicking again with the same build sends the same header
 * and is refused again. An operator mid-incident needs to be told that, not to be handed
 * a retry that cannot work.
 *
 * Two things it says that a generic error cannot. **Nothing happened**: `require_step_up`
 * runs before the work in every handler that asks for one, and the request's transaction
 * rolls back regardless, so a refused confirmation never half-applies — the operator does
 * not have to go and check. And **what to do instead**: reload for the current build, then
 * the runbook's request by hand, with the header the API itself names in `remediation`
 * printed verbatim rather than paraphrased.
 *
 * Everything else falls through to `ProblemNotice` deliberately. A 503 or a 500 here IS
 * "try again", and a second bespoke error panel per failure mode is how a screen ends up
 * with an explanation for the case its author imagined and a blank for the rest.
 *
 * `reauthentication_required` is the second, and it is routed to `StepUpPrompt` rather
 * than explained here — see that module for why a curl-shaped `remediation` is the right
 * answer in a log and the wrong one on a screen.
 *
 * IT LIVES IN ITS OWN MODULE rather than inside `ops/page.tsx`, where it was written,
 * because the global do-not-call screen sends step-up headers on both of its writes and
 * would otherwise have needed a second copy of this exact paragraph and this exact panel.
 * A Next.js page module may only export the default and the framework's own named
 * exports, so the choice was a shared module or a duplicate — and two consoles disagreeing
 * about what a refused confirmation means is the drift "one way per problem" is about.
 */
export function WriteFailure({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const problem = error instanceof ApiProblem ? error : null;
  // The OTHER half of the same control (D-340). `X-Confirm-Action` answers "this screen
  // meant to send this action"; step-up answers "the person at the keyboard is still
  // them", and `apps/api/core/stepup.py` keeps them deliberately separate because neither
  // substitutes for the other. They therefore need separate renderings: the panel below
  // says "reload, this build is skewed", which is exactly the wrong instruction for a
  // refusal an operator clears by proving a factor. Routed FIRST so the skew panel cannot
  // claim a refusal it does not describe.
  if (problem?.code === AUTHN_CODES.reauthenticationRequired) {
    return <StepUpPrompt error={error} onRetry={onRetry} />;
  }
  if (problem?.code !== "step_up_required") return <ProblemNotice error={error} onRetry={onRetry} />;
  return (
    // `NoticeBox` carries no ARIA role of its own, and this one interrupts an operator
    // mid-task — the same announcement `ProblemNotice` makes for the failures it renders.
    <div role="alert">
      <NoticeBox
        tone="stop"
        icon={<ShieldAlert aria-hidden className="h-5 w-5" />}
        title="Refused: this console's confirmation is not the one the API expects"
      >
        <p className="mt-1">
          Nothing was changed. The request was refused before it reached the work, and its
          transaction rolled back — you do not need to check whether it half-applied.
        </p>
        <p className="mt-2">
          You did type the confirmation, and the console did send it. A refusal at this
          point means this page is running a different build from the API, so pressing the
          button again will send the same header and be refused again.{" "}
          <span className="font-semibold">Reload this page first.</span> If it survives a
          reload, the API and the console have genuinely diverged: use the request in the
          runbook by hand, with the header below, and say so in the deploy channel.
        </p>
        {problem.remediation && <p className="mt-2 font-mono text-xs">{problem.remediation}</p>}
      </NoticeBox>
    </div>
  );
}
