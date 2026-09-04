"use client";

/**
 * THE NUMBER TO POINT YOUR EXISTING PHONE AT (D-537).
 *
 * The founder's decision on the inbound leg is that a clinic KEEPS its own published
 * number and conditionally forwards it to one of ours. That is a one-sentence instruction
 * and a number to copy — and until this screen existed there was nowhere the client could
 * read either. A number sitting in an operator's console is not a product.
 *
 * ## Two kinds of number, and telling them apart is the whole screen
 *
 * `supplied_by_us` is the server's own answer and is never re-derived here. A number WE
 * supplied is one to forward TO; a connection the client brought is one they already
 * publish and must not touch. Those are opposite instructions, and giving the wrong one to
 * somebody about to reconfigure their clinic's phone is the failure this screen exists to
 * avoid — so the two are separate sections with separate copy, not one list with a badge.
 *
 * ## `answerable` is stated, and it is not a technical detail
 *
 * It is False while the voice platform has no handle for the number, which means an agent
 * set to answer it WILL NOT — a state every number on this platform was in before D-537.
 * A client who forwarded their line to a number in that state would send every patient
 * into silence. So it is said plainly, in their words, with the action named as ours.
 *
 * ## No price, and no forwarding instructions for a specific operator
 *
 * What a number costs Calevate is not a client-facing figure (the pricing decision has not
 * been taken — OPERATIONS §2 gate 26), and the exact steps to set conditional forwarding
 * differ per operator and per handset. Inventing either would be this screen asserting
 * something nobody verified; what it does instead is say what to ASK for, in the words an
 * Indian operator uses.
 */

import { Card, EmptyState, MonoValue, ProblemNotice, Skeleton } from "@/components/ui";
import { useCampaignNumbers } from "@/lib/api/campaigns";
import { useClientSession } from "@/lib/api/session";

export default function PhoneNumberPage() {
  const session = useClientSession();
  const numbers = useCampaignNumbers(session);

  const rows = numbers.data;
  const ours = rows?.filter((number) => number.supplied_by_us) ?? [];
  const theirs = rows?.filter((number) => !number.supplied_by_us) ?? [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-ink">Your phone number</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Your customers go on calling the number they already know. What changes is where
          that number sends a call when nobody picks it up.
        </p>
      </div>

      {numbers.error && <ProblemNotice error={numbers.error} onRetry={() => numbers.refetch()} />}

      {numbers.isLoading || !rows ? (
        <Card title="Your numbers">
          <div className="p-4">
            <Skeleton rows={3} />
          </div>
        </Card>
      ) : rows.length === 0 ? (
        <Card title="Your numbers">
          <EmptyState
            title="No number set up yet"
            hint="Your account manager arranges this when your agent is being set up. Nothing is needed from you until then."
          />
        </Card>
      ) : (
        <>
          {ours.length > 0 && (
            <Card title="Point your existing phone at this number">
              <div className="space-y-4 p-4">
                <p className="text-sm text-ink-muted">
                  Ask your telephone operator to set up{" "}
                  <span className="font-medium text-ink">conditional call forwarding</span>{" "}
                  on your business line — forward a call when it is busy, unanswered, or
                  out of reach — and give them this number as the destination. Keep
                  advertising your own number; nobody needs to know this one.
                </p>
                <ul className="space-y-2">
                  {ours.map((number) => (
                    <li
                      key={number.id}
                      className="flex flex-wrap items-center gap-3 rounded-card border border-line p-3"
                    >
                      {/* The client's OWN destination number. Not a called party's, which
                          is the number hard rule 6 is about. */}
                      <span className="text-xs uppercase tracking-wide text-ink-muted">
                        Forward to
                      </span>
                      <MonoValue className="text-ink">{number.e164}</MonoValue>
                      <span
                        className={
                          number.answerable
                            ? "rounded bg-brand-soft px-1.5 py-0.5 text-xs font-medium text-brand-strong"
                            : "rounded border border-line px-1.5 py-0.5 text-xs font-medium text-ink-muted"
                        }
                      >
                        {number.answerable ? "Ready to answer" : "Not ready yet"}
                      </span>
                    </li>
                  ))}
                </ul>
                {ours.some((number) => !number.answerable) && (
                  <p className="text-sm text-ink-muted">
                    One of these is not ready to take calls yet — we are still connecting
                    it. Please wait until it says <em>Ready to answer</em> before you set
                    the forwarding up, or callers will reach silence. There is nothing for
                    you to do; we will tell you when it is done.
                  </p>
                )}
              </div>
            </Card>
          )}

          {theirs.length > 0 && (
            <Card title="Numbers you hold yourself">
              <div className="space-y-3 p-4">
                <p className="text-sm text-ink-muted">
                  These are connections in your own name with your own operator. You stay
                  the account holder and can withdraw our access at any time. Do not
                  forward these anywhere — they are what your agents call out from.
                </p>
                <ul className="space-y-2">
                  {theirs.map((number) => (
                    <li
                      key={number.id}
                      className="flex flex-wrap items-center gap-3 rounded-card border border-line p-3"
                    >
                      <MonoValue className="text-ink">{number.e164}</MonoValue>
                      <span className="text-xs text-ink-muted">
                        {number.dlt_status === "registered"
                          ? "Registered for calling out"
                          : "Registration still in progress"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
