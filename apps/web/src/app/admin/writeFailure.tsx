"use client";

import { useState } from "react";

import { ShieldAlert, ShieldCheck } from "lucide-react";

import { NoticeBox, PRIMARY_BUTTON_SM, ProblemNotice } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import { AUTHN_CODES } from "@/lib/authn/problems";
import { requireStepUp } from "@/lib/authn/stepUpPrompt";

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
/**
 * "Confirm it is still you", asked through the ONE asker this console has (D-210, D-340).
 *
 * This renders a button rather than a prompt, and that is the whole integration: the
 * prompt itself is `components/authn/stepUpPrompt`, mounted once in `admin/layout.tsx`
 * and driven by the module-level store in `lib/authn/stepUpPrompt`. `requireStepUp` is
 * single-flight, so six queries refused together produce ONE modal and ONE emailed code
 * — which matters because `service.request_step_up` retires the previous challenge on
 * issue, so a second prompt would be an operator typing a code that is already dead.
 *
 * A component that mounted its own prompt would be a second asker and would reintroduce
 * exactly that. The store already exists precisely because its first caller
 * (`lib/api/admin.ts::mint`) is a plain async function with no component in scope; a
 * confirmed write is simply the second caller, not a second mechanism.
 *
 * `requireStepUp` resolves `false` on dismissal rather than rejecting, so a prompt nobody
 * answers leaves the screen showing the server's own refusal — which is still true — and
 * can never become an unhandled rejection.
 */
function ReauthenticationRefusal({
  onRetry,
  actionLabel,
}: {
  onRetry?: () => void;
  actionLabel: string;
}) {
  /**
   * PROVING A FACTOR HAD NO VISIBLE OUTCOME, AND THAT WAS THE BUG.
   *
   * The button called `requireStepUp(...).then(proved => proved && onRetry?.())`, and NOT
   * ONE of the six call sites passed `onRetry` — so an operator typed the emailed code,
   * watched the same red panel sit there unchanged, and had to work out for themselves
   * that pressing the original button again would now work. The plumbing existed; nothing
   * was connected to it.
   *
   * The fix is NOT to replay the write. That decision is deliberate and stays: proving a
   * factor says who is at the keyboard, and a button that re-fired a platform halt off the
   * back of an emailed code would turn an identity check into a confirmation. What was
   * missing is the acknowledgement — so the panel changes state, says the check passed and
   * says what to press. `onRetry` is still called for any caller that wants more.
   */
  const [proved, setProved] = useState(false);

  if (proved) {
    return (
      // `status`, not `alert`: this interrupts nothing and announces a success.
      <div role="status">
        <NoticeBox
          tone="ok"
          icon={<ShieldCheck aria-hidden className="h-5 w-5" />}
          title="Confirmed — it is still you"
        >
          <p className="mt-1">
            Your second factor is proved for the next few minutes. Press{" "}
            <span className="font-semibold">{actionLabel}</span> again to apply the change.
            Nothing has been applied yet — the earlier attempt rolled back, and proving who
            you are does not re-send it.
          </p>
        </NoticeBox>
      </div>
    );
  }

  return (
    <div role="alert">
      <NoticeBox
        tone="stop"
        icon={<ShieldAlert aria-hidden className="h-5 w-5" />}
        title="Confirm it is still you"
      >
        <p className="mt-1">
          Nothing was changed. This action needs a second factor proved in the last few
          minutes, and the check runs before the work — so the request rolled back and you
          do not have to check whether it half-applied.
        </p>
        <button
          type="button"
          // `PRIMARY_BUTTON_SM`, not a hand-written fill. `bg-brand` under white text is
          // 3.38:1 and `tests/contrast.test.ts` refuses it; the shared constant already
          // rests on `bg-brand-strong` (6.58:1) and carries the touch target with it.
          className={`mt-3 ${PRIMARY_BUTTON_SM}`}
          onClick={() => {
            // Deliberately NOT replaying the write. Proving a factor says who is at the
            // keyboard; it does not restate the intent to halt a platform or adjust a
            // client's credits, and a button that silently re-fired one of those on the
            // back of an emailed code would turn an identity check into a confirmation.
            void requireStepUp("A confirmed change on this screen.").then((ok) => {
              if (!ok) return;
              setProved(true);
              onRetry?.();
            });
          }}
        >
          Send me a code
        </button>
      </NoticeBox>
    </div>
  );
}

export function WriteFailure({
  error,
  onRetry,
  actionLabel,
}: {
  error: unknown;
  onRetry?: () => void;
  /**
   * The button an operator pressed, named so the confirmation can say which one to press
   * again — "Press Install again" beats "press the button again" on a screen with four.
   *
   * REQUIRED, and that is the durable half of this fix. The bug was not that the label was
   * wrong; it was that an optional prop nobody passed left the whole acknowledgement dead
   * at all seventeen call sites, silently, for as long as it existed. A required prop makes
   * the eighteenth a compile error instead of a screen that does nothing.
   */
  actionLabel: string;
}) {
  const problem = error instanceof ApiProblem ? error : null;
  // The OTHER half of the same control (D-340). `X-Confirm-Action` answers "this screen
  // meant to send this action"; step-up answers "the person at the keyboard is still
  // them", and `apps/api/core/stepup.py` keeps them deliberately separate because neither
  // substitutes for the other. They therefore need separate renderings: the panel below
  // says "reload, this build is skewed", which is exactly the wrong instruction for a
  // refusal an operator clears by proving a factor. Routed FIRST so the skew panel cannot
  // claim a refusal it does not describe.
  if (problem?.code === AUTHN_CODES.reauthenticationRequired) {
    return <ReauthenticationRefusal onRetry={onRetry} actionLabel={actionLabel} />;
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
