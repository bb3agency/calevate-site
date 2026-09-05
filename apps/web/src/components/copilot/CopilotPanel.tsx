"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Eraser, Undo2, X } from "lucide-react";

import { AcceptChargeDialog, extraUnavailableSentence } from "@/components/aiExtraDialog";
import { ConfirmDialog } from "@/components/confirmDialog";
import { FIELD, PRIMARY_BUTTON, ProblemNotice, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
import { useAiQuota, useBuyAiExtra } from "@/lib/api/aiQuota";
import type { Session } from "@/lib/api/client";
import type { SurfaceHolder } from "@/lib/copilot/registry";
import { unsavedWork } from "@/lib/copilot/unsaved";
import { useCopilotConversation } from "@/lib/copilot/useCopilotConversation";

import { AnswerText } from "./answerText";
import { ActionReceipt } from "./ActionReceipt";
import { NavigationReceipt } from "./NavigationReceipt";
import { ProposalCard } from "./ProposalCard";
import { StepList } from "./StepList";

/**
 * The assistant's panel: the transcript, the ask box, what it filled in, and the one Undo.
 *
 * ## Why this is NOT a focus trap, and why that is the whole design
 *
 * `components/confirmDialog.tsx` and `AcceptChargeDialog` trap focus, because each of
 * them is a decision that must be answered before the page continues. This is the
 * opposite: the entire point is that it sits open BESIDE the form a person is filling in,
 * so they can read an answer, Tab back into the form, change a value and ask again.
 * `useFocusTrap` would make that impossible — the first Tab out of the panel would be
 * pulled back in — so it is deliberately not used here, and this paragraph is why the
 * next reader should not "fix" the omission.
 *
 * What is kept from the modal contract is the part that costs nothing: Escape closes, and
 * closing returns focus to the launcher that opened it. What is given up is Tab
 * containment, knowingly, and `aria-modal` is therefore ABSENT rather than `false` — a
 * dialog that claims modality while the page behind it is live is a lie told to a screen
 * reader, and `aria-modal="false"` is the spelling that says the same thing twice.
 *
 * ## The ceiling
 *
 * The AI allowance ceiling is answered through `AcceptChargeDialog` — the ONE wallet
 * dialog, whose own header explains why a second would be wrong. This is its third
 * caller, and it follows the second (`calls/[callId]/AssistCard.tsx`) exactly: recognise
 * `ai_quota_exceeded` on the refusal, re-read `GET /v1/billing/ai-quota` only THEN, and
 * render the amount from that read rather than from anything carried in the refusal.
 *
 * That branch is client-realm only, because the allowance is a tenant's. An operator
 * console has no wallet to debit, so the query stays disabled there and the refusal — if
 * the server ever sent one — renders as an ordinary `ProblemNotice`.
 */
export function CopilotPanel({
  session,
  holder,
  realm,
  onClose,
  onNavigate,
  labelledBy,
}: {
  session: Session;
  holder: SurfaceHolder;
  realm: "client" | "admin";
  onClose: () => void;
  /**
   * OPEN THIS SCREEN (D-524). Passed up to the dock rather than done here, and the split is
   * the same one the server made: this component decides WHETHER — it is the half that can
   * see the surface and the unsaved fill — and the dock, which outlives the route change,
   * performs the move and announces it. A `router.push` from here would unmount this
   * component mid-call, taking the live region that has to say where the person went.
   *
   * `undefined` on the admin realm, which has no screen inventory to navigate.
   */
  onNavigate?: (destination: { route: string; screen: string; where: string }) => void;
  labelledBy: string;
}) {
  const [question, setQuestion] = useState("");
  // Whether the wallet dialog is on screen. Separate from `atCeiling`: meeting the
  // ceiling is a fact about the month, opening the dialog is a decision to spend.
  const [buying, setBuying] = useState(false);
  const conversation = useCopilotConversation(session, holder);
  const panel = useRef<HTMLDivElement>(null);
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const inputId = useId();

  const wantsQuota = realm === "client" && conversation.atCeiling;
  const quota = useAiQuota(session, { enabled: wantsQuota });
  const buy = useBuyAiExtra(session);

  // Escape, on `document` rather than on this subtree: a person reaching for Escape has
  // very often just been typing in the FORM, not in the panel, and a React `onKeyDown`
  // only fires for keys pressed inside its own tree. Same reason `useFocusTrap` puts its
  // listener there; this file cannot borrow the hook itself (see the header).
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  // Focus the ask box when the panel opens — it is the only thing anybody opens this for.
  useEffect(() => {
    panel.current?.querySelector("textarea")?.focus();
  }, []);

  useEffect(() => {
    // Guarded, not because it can be absent in a browser but because it IS absent in
    // jsdom — `scrollIntoView` is one of the layout APIs jsdom does not implement, and an
    // unguarded call turns every test that renders this panel into a crash about
    // scrolling rather than an assertion about the assistant.
    const end = transcriptEnd.current;
    if (typeof end?.scrollIntoView === "function") end.scrollIntoView({ block: "end" });
  }, [conversation.turns, conversation.streaming]);

  const surface = holder.read();
  const batch = conversation.batch;
  const { navigation, clearNavigation, asking } = conversation;

  // THE ASK, when leaving this screen might throw work away. `null` while there is nothing
  // to ask about; `unsaved.ts` decides which it is and writes the sentence.
  const [leaving, setLeaving] = useState<{ reason: string } | null>(null);
  // WHICH DESTINATION HAS ALREADY BEEN DECIDED ABOUT. A ref rather than state because it
  // must not cause a render: the effect below runs on every render while a destination is
  // held (the receipt stays on screen until the move happens), and without this it would
  // navigate again on each one.
  const decided = useRef<unknown>(null);

  /*
   * OPEN THE SCREEN THE ANSWER ASKED FOR — after the answer has finished arriving.
   *
   * WAITING FOR `asking` TO FALL IS NOT A POLISH DETAIL. The dock closes this panel when
   * the surface under it changes, which unmounts this component and aborts the in-flight
   * request; moving the instant the frame arrived would therefore cut off the sentence
   * that tells the person where they are being taken, and charge them for it. The frame
   * arrives before the model's closing line, so the wait is one turn and no more.
   *
   * THE SURFACE IS READ AGAIN HERE rather than trusted from render: "is this form dirty"
   * is a question about the moment of the move, and the answer may have changed while the
   * answer was streaming — a person can keep typing beside this panel, which is exactly
   * what it is designed for (see the header on why it does not trap focus).
   */
  useEffect(() => {
    if (navigation === null || asking || onNavigate === undefined) return;
    if (decided.current === navigation) return;
    decided.current = navigation;
    const verdict = unsavedWork(holder.read(), batch?.ids.length ?? 0);
    if (verdict.ask) {
      setLeaving({ reason: verdict.reason });
      return;
    }
    onNavigate(navigation);
  }, [navigation, asking, onNavigate, holder, batch]);
  // THE ADMIN CONSOLE HAS NO ASSISTANT YET, AND THE HONEST PLACE TO SAY SO IS HERE (D-501).
  //
  // `POST /v1/copilot/ask` is client-realm: `core/auth.current_any` resolves the admin
  // realm only behind an impersonation header, so an operator's token is checked against
  // the client realm and refused 401 — which the console would otherwise render as
  // "Unauthorized · Authentication is required", i.e. "you are signed out" told to somebody
  // who is not. D-501 makes this launcher appear on every admin screen rather than only the
  // declared ones, so that misleading sentence is now in front of more operators, and the
  // fix is to not send a request whose only possible answer is that.
  //
  // NOT A DISABLED LAUNCHER, deliberately: the button opens, and what it opens says what
  // the assistant is and where it works. A person who reads this once knows something true;
  // a dead button teaches nothing and reads as a bug.
  //
  // WHAT REMOVES THIS BRANCH: `POST /v1/admin/copilot/ask`, the admin-realm route whose
  // payer is the platform rather than a client (D-499, in flight in another lane —
  // `billing/platform_ai.py`, `copilot/admin_tools.py`). When it lands, the admin realm
  // points at it and this paragraph goes with the branch. Nothing here should be built up
  // into a second assistant in the meantime.
  const adminUnserved = realm === "admin";

  return (
    <div
      ref={panel}
      role="dialog"
      aria-labelledby={labelledBy}
      className="fixed bottom-20 right-4 z-[70] flex max-h-[min(34rem,calc(100vh-7rem))] w-[min(24rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-card border border-line bg-surface shadow-lg"
    >
      <div className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h2 id={labelledBy} className="text-sm font-semibold text-ink">
            Ask about this screen
          </h2>
          <p className="truncate text-xs text-ink-faint">{surface.title}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {/* START AGAIN (D-540), and it exists BECAUSE the conversation is now durable.
              While the chat was React state, closing the panel was already a clear and a
              button for it would have been a second way to do the same thing. Now the
              thread follows a person across devices and outlives every refresh, so
              "forget this" is the only way to end one — and it is the thing somebody
              reaches for the moment they are about to hand their laptop to a colleague.

              Shown only when there is something to forget: a control that says it will
              do something and does nothing teaches people to distrust the ones beside
              it. */}
          {conversation.turns.length > 0 && (
            <button
              type="button"
              onClick={conversation.reset}
              disabled={conversation.asking}
              aria-label="Forget this conversation and start again"
              title="Start again"
              className="-mr-1 rounded-md p-1 text-ink-muted hover:bg-black/5 hover:text-ink disabled:opacity-40 dark:hover:bg-white/10"
            >
              <Eraser aria-hidden className="h-4 w-4" />
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close the assistant"
            className="-mr-1 rounded-md p-1 text-ink-muted hover:bg-black/5 hover:text-ink dark:hover:bg-white/10"
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
        {/* THE SECOND SENTENCE USED TO SAY "it never saves anything", AND THAT STOPPED
            BEING TRUE when the write tools shipped: it can now offer to change a lead's
            status, suppress a number or pause a campaign. It still cannot DO any of them
            on its own — every one arrives as a suggestion with a Confirm button — and
            that is the promise this copy has to make instead, because a person who was
            told nothing can ever be saved will not read the card before clicking. */}
        {adminUnserved && (
          <div className="rounded-lg border border-line bg-app px-3 py-2">
            <p className="text-xs font-medium text-ink">
              The assistant isn&apos;t available in the admin console yet.
            </p>
            <p className="mt-1 text-xs text-ink-muted">
              It answers about one client account — their screens, calls, leads and agents
              — and an operator session isn&apos;t inside an account. Open a client&apos;s
              own console to ask about them.
            </p>
          </div>
        )}

        {!adminUnserved &&
          conversation.turns.length === 0 &&
          conversation.streaming === null &&
          (surface.undeclared === true ? (
            /* THE FALLBACK SENTENCE (D-501), AND IT SAYS THE HONEST THING. This screen did
               not describe itself, so the assistant cannot see what is on it — which is not
               the same as the screen being empty, and this copy must never let a person
               (or the model, which is told the same thing in `prompt.py`) read it as "this
               screen shows nothing". What it CAN still do is the whole reason the launcher
               is here at all: the read tools answer from the account's own records. */
            <p className="text-xs text-ink-muted">
              This screen hasn&apos;t told the assistant what it shows, so it can&apos;t
              read or fill anything on it. It can still answer questions about your
              account — your calls, leads, campaigns and agents — by looking them up.
            </p>
          ) : (
            <p className="text-xs text-ink-muted">
              It can see the {surface.fields.length} fields on this screen and can fill them
              in for you — nothing is saved until you press the screen&apos;s own save
              button. If it suggests a change to your leads or campaigns, it asks you to
              confirm first and does nothing until you do.
            </p>
          ))}

        {/* `aria-live` on the region rather than on each bubble: a screen reader should
            hear the answer arrive without the transcript being re-read from the top. */}
        <div aria-live="polite" className="space-y-3">
          {/* THE STORED CONVERSATION ARRIVING (D-540). `aria-hidden` on it: this is not
              an answer and announcing "loading" into the same live region the answers
              come through would put a status message in the middle of a transcript a
              screen reader is reading back. */}
          {conversation.loading && conversation.turns.length === 0 && (
            <div aria-hidden>
              <Skeleton rows={2} label="Loading your conversation…" />
            </div>
          )}
          {conversation.turns.map((turn, index) =>
            // The PERSON'S turn stays literal `pre-wrap`: they typed what they typed, and
            // rendering their asterisks as emphasis would edit their own words back at
            // them. Only the model's answer is formatted (`answerText.tsx`).
            turn.role === "user" ? (
              <p
                key={index}
                className="ml-6 whitespace-pre-wrap rounded-lg bg-black/5 px-3 py-2 text-ink dark:bg-white/10"
              >
                {turn.content}
              </p>
            ) : (
              <AnswerText key={index} text={turn.content} />
            ),
          )}
          {conversation.streaming !== null &&
            (conversation.streaming === "" && conversation.steps.length === 0 ? (
              // THE SKELETON IS NOW THE FALLBACK RATHER THAN THE DEFAULT. Once a tool call
              // has started there is something real to show — which tool, with what, and how
              // long it has been going — and a spinner beside a live step list is two
              // answers to "is it still working".
              <Skeleton rows={2} label="Thinking…" />
            ) : (
              conversation.streaming !== "" && (
                // Through the SAME renderer as a finished answer, so a list does not
                // arrive as asterisks and then reflow into bullets when the stream ends.
                <AnswerText text={conversation.streaming} />
              )
            ))}
        </div>

        {/* WHAT IT IS DOING, WHILE IT DOES IT. Outside the `aria-live` region above on
            purpose: these frames change several times per second, and announcing each one
            would talk over the answer — which is the thing a screen-reader user is waiting
            for and which IS announced. Kept after the answer has arrived too, so a person
            can still see which of their data was read and what each lookup returned. */}
        <StepList steps={conversation.steps} />

        {/* A CHANGE THE ASSISTANT IS OFFERING TO MAKE — not one it has made.
            `aria-live="polite"` on the wrapper rather than focus management on the card:
            the card must announce itself when it arrives, and it must NOT pull the
            keyboard out of the ask box to do it. This panel is deliberately not a focus
            trap (see the header) precisely so a person can keep working beside it, and a
            suggestion that stole the caret would undo that. The card moves focus exactly
            once, after a confirm resolves, because the control the person was standing on
            is gone by then. */}
        <div aria-live="polite">
          {conversation.proposal !== null && (
            <ProposalCard
              // Keyed by the token so a SECOND proposal in the same conversation gets a
              // fresh card: the confirm mutation's own state lives inside, and a reused
              // component would show the previous change's outcome under the new offer.
              key={conversation.proposal.token}
              session={session}
              proposal={conversation.proposal}
              onDismiss={conversation.dismissProposal}
            />
          )}
        </div>

        {/* WHAT IT HAS ALREADY DONE. Announced, because a change to the person's account
            that happened without a click is exactly the thing they must not have to
            discover. Rendered ABOVE the fill batch and BELOW the proposal: a receipt is
            settled, an offer is not, and the unsettled thing belongs nearest the input. */}
        <div aria-live="polite" className="space-y-2">
          {/* WHERE IT IS TAKING THEM (D-524). In the same announced region as the receipts
              and for the same reason: a screen change the person did not read about is one
              they cannot connect to what they asked. It stays on screen until the move
              happens — or disappears if they answer "stay", because then it is no longer
              true. */}
          {navigation !== null && <NavigationReceipt navigation={navigation} />}
          {conversation.actions.map((performed, index) => (
            // Keyed by position because an action list only ever grows within an exchange
            // and is emptied by the next question — there is no reorder for a key to
            // survive, and `object_id` is empty on an action whose object did not exist
            // when it was described.
            <ActionReceipt key={index} action={performed} />
          ))}
        </div>

        {batch !== null && (
          <div className="rounded-lg border border-line bg-app px-3 py-2">
            <p className="text-xs font-medium text-ink">
              Filled {batch.labels.length} {batch.labels.length === 1 ? "field" : "fields"}
            </p>
            <p className="mt-0.5 text-xs text-ink-muted">{batch.labels.join(", ")}</p>
            <p className="mt-1 text-xs text-ink-faint">
              Nothing has been saved. Check the values, then use this screen&apos;s own
              save button.
            </p>
            <button
              type="button"
              onClick={conversation.undo}
              className={`${SECONDARY_BUTTON} mt-2`}
            >
              <Undo2 aria-hidden className="h-4 w-4" />
              Undo
            </button>
          </div>
        )}

        {/* VERBATIM, and never summarised or truncated: this is the server's own
            disclosure sentence (D-127 G-6), and a console that paraphrases it is a
            console making its own claim about what happened to the data. */}
        {conversation.disclosure !== null && (
          <p className="text-xs text-ink-faint">{conversation.disclosure}</p>
        )}

        {conversation.error != null && !wantsQuota && (
          <ProblemNotice error={conversation.error} />
        )}

        {wantsQuota && (
          <div className="space-y-2">
            {quota.error != null && (
              <ProblemNotice error={quota.error} onRetry={() => void quota.refetch()} />
            )}
            {quota.error == null && quota.data === undefined && <Skeleton rows={2} />}
            {quota.data !== undefined && (
              <div className="rounded-lg border border-line bg-app px-3 py-2">
                <p className="text-xs font-medium text-ink">
                  You have used this month&apos;s included AI help.
                </p>
                {quota.data.extra_available ? (
                  <button
                    type="button"
                    onClick={() => setBuying(true)}
                    className={`${SECONDARY_BUTTON} mt-2`}
                  >
                    Add more AI help
                  </button>
                ) : (
                  <p className="mt-1 text-xs text-ink-muted">
                    {extraUnavailableSentence(quota.data)}
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        <div ref={transcriptEnd} />
      </div>

      {!adminUnserved && (
      <form
        className="border-t border-line px-4 py-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          conversation.ask(question);
          setQuestion("");
        }}
      >
        <label htmlFor={inputId} className="sr-only">
          Your question about this screen
        </label>
        <textarea
          id={inputId}
          rows={2}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends, Shift+Enter is a newline — the convention every chat surface
            // uses, and the reason the control is a textarea rather than an input.
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              conversation.ask(question);
              setQuestion("");
            }
          }}
          placeholder="e.g. fill in the opening hours for a clinic that shuts on Sunday"
          className={FIELD}
        />
        <div className="mt-2 flex justify-end">
          <button
            type="submit"
            disabled={conversation.asking || question.trim() === ""}
            className={PRIMARY_BUTTON}
          >
            {conversation.asking ? "Asking…" : "Ask"}
          </button>
        </div>
      </form>
      )}
      {/* "YOU WILL LOSE WHAT YOU TYPED" — the one question the server could not answer.
          THROUGH `ConfirmDialog` AND NOT `window.confirm`: one way per problem, and this is
          the console's dialog for a consequence with two answers. It is not `beforeunload`
          either, which does not fire for a client-side route change and so cannot see this
          move at all.

          CANCEL IS THE SAFE ANSWER AND COMES FIRST in that component's DOM order, which is
          the property that matters here: staying loses nothing, leaving loses the work. */}
      {leaving !== null && navigation !== null && (
        <ConfirmDialog
          title={`Open ${navigation.screen}?`}
          confirmLabel={`Open ${navigation.screen}`}
          pendingLabel={`Opening ${navigation.screen}…`}
          cancelLabel="Stay here"
          pending={false}
          error={null}
          onCancel={() => {
            setLeaving(null);
            // The receipt goes with it: "Opening Credits & billing" stops being true the
            // moment they say no, and a card left standing would be the assistant claiming
            // something it did not do.
            clearNavigation();
          }}
          onConfirm={() => {
            setLeaving(null);
            onNavigate?.(navigation);
          }}
        >
          {leaving.reason}
        </ConfirmDialog>
      )}
      {buying && quota.data !== undefined && (
        <AcceptChargeDialog
          quota={quota.data}
          pending={buy.isPending}
          error={buy.error}
          onCancel={() => setBuying(false)}
          onAccept={() =>
            buy.mutate(quota.data.extra_block_inr, { onSuccess: () => setBuying(false) })
          }
        />
      )}
    </div>
  );
}
